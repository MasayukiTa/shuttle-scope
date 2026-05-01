"""TrackNet解析API（/api/tracknet）
バッチ処理（試合後一括解析）とシングルフレームヒントをサポート。
on/off は /api/settings で管理。モデル未導入時はエラーを返さず未導入状態を返す。
"""
import uuid
import threading
import logging
from typing import Optional
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import json

from backend.db.database import get_db, SessionLocal
from backend.db.models import Match, GameSet, Rally, Stroke, MatchCVArtifact
from backend.tracknet.inference import get_inference

logger = logging.getLogger(__name__)
router = APIRouter()

# バッチジョブ管理（インメモリ）
_jobs: dict[str, dict] = {}


def _load_setting_int(db, key: str, default: int) -> int:
    """app_settings テーブルから整数設定値を読み込む"""
    import json as _json
    from sqlalchemy import text as _text
    try:
        row = db.execute(_text("SELECT value FROM app_settings WHERE key = :k"), {"k": key}).fetchone()
        if row:
            return int(_json.loads(row[0]))
    except Exception:
        pass
    return default


def _load_device_settings(db) -> tuple[int, str]:
    """DB から cuda_device_index / openvino_device を読み込む"""
    import json as _json
    from sqlalchemy import text as _text
    cuda_idx = 0
    ov_device = "GPU"
    try:
        rows = db.execute(
            _text("SELECT key, value FROM app_settings WHERE key IN ('cuda_device_index','openvino_device')")
        ).fetchall()
        for k, v in rows:
            val = _json.loads(v)
            if k == "cuda_device_index":
                cuda_idx = int(val)
            elif k == "openvino_device":
                ov_device = str(val)
    except Exception:
        pass
    return cuda_idx, ov_device


class BatchJobStatus:
    PENDING  = "pending"
    RUNNING  = "running"
    COMPLETE = "complete"
    ERROR    = "error"


# ────────────────────────────────────────────────────────────────────
# /api/tracknet/status — モデルステータス確認
# ────────────────────────────────────────────────────────────────────

@router.get("/tracknet/shuttle_track/{match_id}")
def get_shuttle_track(match_id: int, db: Session = Depends(get_db)):
    """TrackNet バッチで保存したシャトル軌跡アーティファクトを返す。
    フロントエンドの ShuttleTrackOverlay が参照する。
    """
    artifact = (
        db.query(MatchCVArtifact)
        .filter(
            MatchCVArtifact.match_id == match_id,
            MatchCVArtifact.artifact_type == "tracknet_shuttle_track",
        )
        .order_by(MatchCVArtifact.created_at.desc())
        .first()
    )
    if not artifact or not artifact.data:
        return {"success": True, "data": []}
    return {"success": True, "data": json.loads(artifact.data)}


@router.get("/tracknet/resume_check/{match_id}")
def tracknet_resume_check(match_id: int, db: Session = Depends(get_db)):
    """TrackNet 再開ボタン表示用: ストロークに land_zone が 1 件以上あるか確認する。
    shuttle_track アーティファクトが存在しない旧バージョンのデータに対してもフォールバックとして機能する。
    """
    sets = db.query(GameSet).filter(GameSet.match_id == match_id).all()
    if not sets:
        return {"success": True, "data": {"has_land_zone": False}}
    set_ids = [s.id for s in sets]
    has_land_zone = (
        db.query(Stroke)
        .join(Rally, Stroke.rally_id == Rally.id)
        .filter(Rally.set_id.in_(set_ids), Stroke.land_zone.isnot(None))
        .first()
    ) is not None
    return {"success": True, "data": {"has_land_zone": has_land_zone}}


@router.get("/tracknet/status")
def tracknet_status():
    """TrackNetモデルの導入状況・バックエンドを返す（ロード試行込み）"""
    inf = get_inference()
    available = inf.is_available()
    loaded = inf._infer_fn is not None
    # ロード未試行の場合はここで試みる（ステータス確認時に初期化）
    if available and not loaded:
        loaded = inf.load()
    # Stack-trace-exposure 防止: 例外テキストをそのまま返さず、汎用メッセージに置換
    _load_err_detail = inf.get_load_error() if not loaded else None
    if _load_err_detail:
        import logging as _lg
        _lg.getLogger(__name__).warning("tracknet load_error (sanitized): %s", _load_err_detail)
    return {
        "success": True,
        "data": {
            "available": available,
            "backend": inf.backend_name() if loaded else None,
            "loaded": loaded,
            "load_error": "モデルの読み込みに失敗しました" if _load_err_detail else None,
        },
    }


# ────────────────────────────────────────────────────────────────────
# /api/tracknet/batch/{match_id} — バッチ解析
# ────────────────────────────────────────────────────────────────────

class RoiRectModel(BaseModel):
    """正規化座標 (0-1) の解析対象矩形"""
    x: float = 0.0
    y: float = 0.0
    w: float = 1.0
    h: float = 1.0


class BatchRequest(BaseModel):
    backend: str = "auto"  # auto | openvino | onnx_cpu
    confidence_threshold: float = 0.5
    roi_rect: Optional[RoiRectModel] = None   # 解析対象エリア（未指定なら全体）
    resume: bool = False                       # True: 解析済みラリーをスキップして途中再開
    prev_roi: Optional[RoiRectModel] = None   # 直前の ROI（ROI 拡張時に再処理強制）

@router.post("/tracknet/batch/{match_id}")
def start_batch(
    match_id: int,
    body: BatchRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """試合動画全体を解析してhit_zone/land_zoneを自動補完（非同期）。
    完了確認は GET /api/tracknet/batch/{job_id}/status で行う。
    """
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")

    video_path = match.video_local_path or match.video_url
    if not video_path:
        raise HTTPException(status_code=400, detail="動画ファイルが設定されていません")
    # path_jail: ローカルパスは許可ルート内であることを確認（HDD ドローン映像等への CV 誤起動防止）
    from backend.utils.path_jail import assert_match_video_path_allowed
    try:
        assert_match_video_path_allowed(match.video_local_path)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    cuda_idx, ov_device = _load_device_settings(db)
    inf = get_inference(body.backend, cuda_device_index=cuda_idx, openvino_device=ov_device)
    if not inf.is_available():
        raise HTTPException(
            status_code=503,
            detail=(
                "TrackNetのウェイトが見つかりません。"
                "python -m backend.tracknet.setup all を実行してセットアップしてください。"
            ),
        )

    # F-4 防御 (round115): 同一 match_id に並列 batch 起動を禁止 (GPU 占有 DoS 防止)
    for jid, jinfo in _jobs.items():
        if jinfo.get("match_id") == match_id and jinfo.get("status") in (BatchJobStatus.PENDING, BatchJobStatus.RUNNING):
            raise HTTPException(
                status_code=409,
                detail=f"この試合は既に TrackNet バッチ処理中です (job_id={jid})。",
            )

    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {
        "status": BatchJobStatus.PENDING,
        "match_id": match_id,
        "progress": 0.0,
        "processed_rallies": 0,
        "total_rallies": 0,
        "updated_strokes": 0,
        "error": None,
    }

    roi = body.roi_rect.model_dump() if body.roi_rect else None
    prev_roi = body.prev_roi.model_dump() if body.prev_roi else None
    background_tasks.add_task(
        _run_batch, job_id, match_id, video_path, body.confidence_threshold, roi, body.resume, prev_roi,
        cuda_idx, ov_device,
    )
    return {"success": True, "data": {"job_id": job_id}}


@router.get("/tracknet/batch/{job_id}/status")
def batch_status(job_id: str):
    """バッチジョブの進捗確認"""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")
    return {"success": True, "data": job}


@router.post("/tracknet/batch/{job_id}/stop")
def stop_tracknet_batch(job_id: str):
    """実行中のTrackNetバッチに停止リクエストを送る。現在のラリーが終わり次第停止する。"""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")
    if job.get("status") not in (BatchJobStatus.RUNNING, BatchJobStatus.PENDING):
        return {"success": True, "data": {"message": "already stopped"}}
    _jobs[job_id]["stop_requested"] = True
    return {"success": True, "data": {"job_id": job_id}}


# ────────────────────────────────────────────────────────────────────
# /api/tracknet/live_frame_hint — ライブストリーム推論（LAN カメラ向け）
# ────────────────────────────────────────────────────────────────────

from collections import deque

# セッションコードをキーにした直近フレームバッファ（3フレーム保持）
_live_frame_buffers: dict[str, deque] = {}


class LiveFrameHintRequest(BaseModel):
    """ライブストリームから 1 フレームを受け取る。3 フレーム揃ったら推論。"""
    # F-7 (round115): float 系に Inf/NaN を入れると 500 を引くため明示拒否
    model_config = {"extra": "forbid"}
    session_code: str
    frame_b64: str = Field(..., max_length=2_000_000)  # base64 JPEG/PNG
    frame_width: int = Field(default=512, ge=1, le=4096)
    frame_height: int = Field(default=288, ge=1, le=4096)
    confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0, allow_inf_nan=False)


@router.post("/tracknet/live_frame_hint")
def live_frame_hint(body: LiveFrameHintRequest):
    """ライブカメラ映像の 1 フレームを受け取り、3 フレーム蓄積後に TrackNet 推論を実行。
    JS 側（DeviceManagerPanel / LiveInferenceOverlay）が 200ms 間隔で呼ぶ想定。
    """
    import base64
    import cv2
    import numpy as np

    inf = get_inference()
    if not inf.is_available() or not inf.load():
        return {"success": True, "data": {"zone": None, "confidence": 0.0, "available": False}}

    # フレームデコード
    # round147 N-1/N-2 fix: cv2.imdecode は巨大画像/zip-bomb で SIGABRT 級の
    # 例外/メモリ消費を起こす。decode 後に dimension/byte をチェックし上限を超えたら拒否。
    _MAX_FRAME_W = 4096
    _MAX_FRAME_H = 4096
    _MAX_FRAME_BYTES = 8 * 1024 * 1024  # decoded raw bytes 上限
    try:
        # data URI の場合はヘッダー除去
        b64 = body.frame_b64
        if "," in b64:
            b64 = b64.split(",", 1)[1]
        img_bytes = base64.b64decode(b64)
        if len(img_bytes) > 1_500_000:
            return {"success": False, "error": "画像サイズが大きすぎます (1.5MB 以下)"}
        arr = np.frombuffer(img_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("decode failed")
        h, w = frame.shape[:2]
        if w > _MAX_FRAME_W or h > _MAX_FRAME_H:
            return {"success": False, "error": f"画像解像度が上限超過 ({w}x{h} > {_MAX_FRAME_W}x{_MAX_FRAME_H})"}
        if frame.nbytes > _MAX_FRAME_BYTES:
            return {"success": False, "error": "decoded frame が大きすぎます"}
    except Exception:
        return {"success": False, "error": "フレームデコードに失敗しました"}

    # セッション別バッファに追加
    if body.session_code not in _live_frame_buffers:
        _live_frame_buffers[body.session_code] = deque(maxlen=3)
    buf = _live_frame_buffers[body.session_code]
    buf.append(frame)

    # 3 フレーム未満は候補なし
    if len(buf) < 3:
        return {"success": True, "data": {"zone": None, "confidence": 0.0, "buffering": True}}

    results = inf.predict_frames(list(buf))
    if not results:
        return {"success": True, "data": {"zone": None, "confidence": 0.0}}

    r = results[0]
    return {
        "success": True,
        "data": {
            "zone": r["zone"] if r["confidence"] >= body.confidence_threshold else None,
            "confidence": r["confidence"],
            "x_norm": r["x_norm"],
            "y_norm": r["y_norm"],
            "available": True,
        },
    }


# ────────────────────────────────────────────────────────────────────
# /api/tracknet/frame_hint — シングルフレームヒント（P5向け実験的）
# ────────────────────────────────────────────────────────────────────

class FrameHintRequest(BaseModel):
    """Base64エンコードされた1フレーム（PNG/JPEG）を受け取る"""
    model_config = {"extra": "forbid"}
    # round136 D-5: 5MB 入力で 500 → 各 base64 に max_length=2MB (decode 後 ~1.5MB)
    frame_b64: str = Field(..., max_length=2_000_000)
    frame_prev_b64: str = Field(..., max_length=2_000_000)
    frame_next_b64: str = Field(..., max_length=2_000_000)
    confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0, allow_inf_nan=False)

@router.post("/tracknet/frame_hint")
def frame_hint(body: FrameHintRequest):
    """[実験的 P5] 3フレームからシャトル位置を推定。
    WebViewキャプチャによるリアルタイム補助用。
    精度・遅延は環境依存。i5-1235UではCPU推論で200~500ms程度。
    """
    import base64
    import cv2
    import numpy as np

    inf = get_inference()
    if not inf.is_available() or not inf.load():
        return {"success": True, "data": {"zone": None, "confidence": 0.0, "available": False}}

    frames = []
    for b64 in [body.frame_prev_b64, body.frame_b64, body.frame_next_b64]:
        try:
            img_bytes = base64.b64decode(b64)
            arr = np.frombuffer(img_bytes, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            frames.append(frame)
        except Exception:
            return {"success": False, "error": "フレームデコードに失敗しました"}

    results = inf.predict_frames(frames)
    if not results:
        return {"success": True, "data": {"zone": None, "confidence": 0.0}}

    r = results[0]
    return {
        "success": True,
        "data": {
            "zone": r["zone"] if r["confidence"] >= body.confidence_threshold else None,
            "confidence": r["confidence"],
            "x_norm": r["x_norm"],
            "y_norm": r["y_norm"],
            "available": True,
        },
    }


# ────────────────────────────────────────────────────────────────────
# バックグラウンドジョブ実装
# ────────────────────────────────────────────────────────────────────

def _crop_roi(frame, roi: dict | None):
    """ROI 指定がある場合、正規化座標でフレームをクロップする。"""
    if not roi:
        return frame
    h, w = frame.shape[:2]
    x1 = max(0, int(roi.get("x", 0) * w))
    y1 = max(0, int(roi.get("y", 0) * h))
    x2 = min(w, int((roi.get("x", 0) + roi.get("w", 1)) * w))
    y2 = min(h, int((roi.get("y", 0) + roi.get("h", 1)) * h))
    if x2 <= x1 or y2 <= y1:
        return frame
    return frame[y1:y2, x1:x2]


def _remap_tracknet_result(result: dict, roi: dict | None) -> dict:
    """TrackNet の x_norm / y_norm を ROI ローカル座標からフルフレーム座標に変換する。"""
    if not roi or result.get("x_norm") is None:
        return result
    rx, ry = roi.get("x", 0.0), roi.get("y", 0.0)
    rw, rh = roi.get("w", 1.0), roi.get("h", 1.0)
    out = dict(result)
    if out.get("x_norm") is not None:
        out["x_norm"] = rx + out["x_norm"] * rw
    if out.get("y_norm") is not None:
        out["y_norm"] = ry + out["y_norm"] * rh
    return out


def _run_batch(
    job_id: str,
    match_id: int,
    video_path: str,
    threshold: float,
    roi: dict | None = None,
    resume: bool = False,
    prev_roi: dict | None = None,
    cuda_device_index: int = 0,
    openvino_device: str = "GPU",
):
    """バッチ解析の本体。別スレッドで実行される。"""
    from backend.db.database import SessionLocal
    from backend.routers.yolo import _compute_delta_rois

    _jobs[job_id]["status"] = BatchJobStatus.RUNNING
    db = SessionLocal()

    try:
        inf = get_inference("auto", cuda_device_index=cuda_device_index, openvino_device=openvino_device)
        if not inf.load():
            _jobs[job_id]["status"] = BatchJobStatus.ERROR
            _jobs[job_id]["error"] = inf.get_load_error() or "モデルロードに失敗しました"
            return

        # ROI拡張判定（拡張時は既存 land_zone を上書きして再解析）
        roi_widened = bool(prev_roi and roi and _compute_delta_rois(prev_roi, roi))

        # ラリー一覧取得（スキップラリーは除外）
        sets = db.query(GameSet).filter(GameSet.match_id == match_id).all()
        set_ids = [s.id for s in sets]
        rallies = (
            db.query(Rally)
            .filter(Rally.set_id.in_(set_ids), Rally.is_skipped == False)  # noqa: E712
            .order_by(Rally.set_id, Rally.rally_num)
            .all()
        ) if set_ids else []

        _jobs[job_id]["total_rallies"] = len(rallies)
        updated = 0

        # resume モード: 解析済みラリー数を事前にカウントして進捗の初期値を設定
        if resume and not roi_widened and rallies:
            pre_done = 0
            for rally in rallies:
                if rally.video_timestamp_start is None:
                    pre_done += 1
                    continue
                strokes_check = db.query(Stroke).filter(Stroke.rally_id == rally.id).all()
                if strokes_check and all(s.land_zone for s in strokes_check):
                    pre_done += 1
            _jobs[job_id]["processed_rallies"] = pre_done
            _jobs[job_id]["progress"] = pre_done / max(len(rallies), 1)

        for i, rally in enumerate(rallies):
            # 停止リクエスト確認（ユーザーが「停止」ボタンを押した場合）
            # TrackNet は各ラリー終了後に DB 保存済みなので、安全に停止できる
            if _jobs[job_id].get("stop_requested"):
                _jobs[job_id]["status"] = "stopped"
                logger.info(
                    "TrackNet batch stopped by user: match=%d, processed=%d/%d",
                    match_id, i, len(rallies),
                )
                return

            # タイムスタンプが設定されているラリーのみ解析
            if rally.video_timestamp_start is None:
                _jobs[job_id]["processed_rallies"] = i + 1
                _jobs[job_id]["progress"] = (i + 1) / max(len(rallies), 1)
                continue

            # resume かつ ROI 拡張なし: 全ストロークが解析済みならスキップ
            if resume and not roi_widened:
                strokes_check = (
                    db.query(Stroke)
                    .filter(Stroke.rally_id == rally.id)
                    .all()
                )
                if strokes_check and all(s.land_zone for s in strokes_check):
                    _jobs[job_id]["processed_rallies"] = i + 1
                    _jobs[job_id]["progress"] = (i + 1) / max(len(rallies), 1)
                    continue

            try:
                frames = _extract_frames(video_path, rally.video_timestamp_start, n_frames=5)
                if len(frames) < 3:
                    continue

                # ROI クロップを適用（指定がある場合）
                if roi:
                    frames = [_crop_roi(f, roi) for f in frames]

                results = inf.predict_frames(frames)
                if not results:
                    continue

                # ROI 座標をフルフレーム座標に変換
                if roi:
                    results = [_remap_tracknet_result(r, roi) for r in results]

                # 最後の結果をland_zoneとして使用
                last = results[-1]

                strokes = (
                    db.query(Stroke)
                    .filter(Stroke.rally_id == rally.id)
                    .order_by(Stroke.stroke_num)
                    .all()
                )
                for j, stroke in enumerate(strokes):
                    res = results[j] if j < len(results) else last
                    if res["confidence"] >= threshold and res["zone"]:
                        # ROI拡張時は既存 land_zone を上書き（より広い範囲で再解析）
                        if not stroke.land_zone or roi_widened:
                            stroke.land_zone = res["zone"]
                            updated += 1

                db.commit()
            except Exception as e:
                logger.warning("Rally %d analysis failed: %s", rally.id, e)

            _jobs[job_id]["processed_rallies"] = i + 1
            _jobs[job_id]["progress"] = (i + 1) / max(len(rallies), 1)
            _jobs[job_id]["updated_strokes"] = updated

        # メインループ完了: 進捗を 100% に設定（status はまだ running のまま）
        _jobs[job_id]["progress"] = 1.0
        _jobs[job_id]["updated_strokes"] = updated

        # MatchCVArtifact として tracknet_shuttle_track を保存
        # YOLO アライメント（/api/yolo/align）が参照するフレーム別シャトル軌跡
        # 再開時 (resume=True) かつ既存アーティファクトがある場合は rebuild をスキップ
        import datetime as _dt
        existing_shuttle_art = (
            db.query(MatchCVArtifact)
            .filter(
                MatchCVArtifact.match_id == match_id,
                MatchCVArtifact.artifact_type == "tracknet_shuttle_track",
            )
            .first()
        )
        skip_shuttle_build = resume and existing_shuttle_art and existing_shuttle_art.data
        if skip_shuttle_build:
            logger.info("TrackNet resume: shuttle_track rebuild skipped (existing artifact reused)")
        else:
            batch_fps = _load_setting_int(db, "tracknet_batch_fps", 10)
            shuttle_step = round(1.0 / max(1, batch_fps), 3)
            logger.info("TrackNet shuttle_track: step=%.3fs (%.1ffps)", shuttle_step, batch_fps)
            shuttle_track = _build_shuttle_track(rallies, db, inf, threshold, video_path, roi, step=shuttle_step)
            if shuttle_track:
                track_json = json.dumps(shuttle_track, ensure_ascii=False)
                if existing_shuttle_art:
                    existing_shuttle_art.data = track_json
                    existing_shuttle_art.frame_count = len(shuttle_track)
                    existing_shuttle_art.updated_at = _dt.datetime.utcnow()
                else:
                    db.add(MatchCVArtifact(
                        match_id=match_id,
                        artifact_type="tracknet_shuttle_track",
                        frame_count=len(shuttle_track),
                        backend_used=inf.backend_name(),
                        data=track_json,
                    ))
                db.commit()
                logger.info("TrackNet shuttle_track saved: match=%d, points=%d", match_id, len(shuttle_track))

        # shuttle_track 保存完了後に status を COMPLETE に設定
        # （フロントエンドが COMPLETE を見てから shuttle_track を取得するため、保存前に COMPLETE にしない）
        _jobs[job_id]["status"] = BatchJobStatus.COMPLETE

    except Exception as e:
        logger.error("Batch job %s failed: %s", job_id, e)
        _jobs[job_id]["status"] = BatchJobStatus.ERROR
        _jobs[job_id]["error"] = str(e)
    finally:
        db.close()


def _build_shuttle_track(
    rallies: list,
    db,
    inf,
    threshold: float,
    video_path: str,
    roi: dict | None = None,
    step: float = 1.0,
) -> list[dict]:
    """ラリー別の TrackNet 推論結果を時系列フラットリストにまとめ返す。

    Returns:
        [{"timestamp_sec": float, "zone": str|None, "confidence": float,
          "x_norm": float|None, "y_norm": float|None}, ...]
    """
    import cv2

    path = video_path
    if path.startswith("localfile:///"):
        path = path[len("localfile:///"):]

    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.release()

    track: list[dict] = []

    for rally in rallies:
        if rally.video_timestamp_start is None:
            continue
        start_sec: float = rally.video_timestamp_start
        end_sec: float = rally.video_timestamp_end or (start_sec + 15.0)

        # ラリー区間を 3 フレームスライド窓で走査（step 秒ごと）
        t = start_sec
        while t < end_sec:
            frames = _extract_frames(video_path, t, n_frames=3)
            if len(frames) >= 3:
                if roi:
                    frames = [_crop_roi(f, roi) for f in frames]
                results = inf.predict_frames(frames)
                if results:
                    r = _remap_tracknet_result(results[0], roi)
                    track.append({
                        "timestamp_sec": round(t, 3),
                        "zone": r["zone"] if r["confidence"] >= threshold else None,
                        "confidence": round(r["confidence"], 3),
                        "x_norm": r.get("x_norm"),
                        "y_norm": r.get("y_norm"),
                    })
            t += step

    return track


def _extract_frames(video_path: str, start_sec: float, n_frames: int = 5) -> list:
    """動画からフレームを抽出（cv2使用）。
    localfile:// プレフィックスがある場合は除去してファイルパスに変換。
    """
    import cv2

    path = video_path
    if path.startswith("localfile:///"):
        path = path[len("localfile:///"):]

    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        logger.warning("Cannot open video: %s", path)
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    start_frame = int(start_sec * fps)
    frames = []

    for i in range(n_frames):
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame + i)
        ret, frame = cap.read()
        if not ret:
            break
        frames.append(frame)

    cap.release()
    return frames
