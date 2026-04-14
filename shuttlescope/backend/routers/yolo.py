"""YOLO プレイヤー検出 API（/api/yolo）

エンドポイント:
  GET  /api/yolo/status                   — モデル状態確認
  POST /api/yolo/batch/{match_id}         — バッチ検出開始
  GET  /api/yolo/batch/{job_id}/status    — ジョブ進捗確認
  GET  /api/yolo/results/{match_id}       — 検出結果サマリー取得
  POST /api/yolo/align/{match_id}         — TrackNet との統合アライメント
"""
import json
import logging
import uuid
from typing import Optional

import cv2

from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.database import get_db, SessionLocal
from backend.db.models import Match, GameSet, Rally, MatchCVArtifact
from backend.yolo.inference import get_yolo_inference
from backend.yolo.court_mapper import summarize_frame_positions, summarize_rally_positions
from backend.yolo.cv_aligner import align_match
from backend.analysis.doubles_cv_engine import compute_doubles_cv_analytics

logger = logging.getLogger(__name__)
router = APIRouter()

# ─── インメモリジョブ管理 ────────────────────────────────────────────────────

_jobs: dict[str, dict] = {}

# バッチ処理サンプリングレート: N フレームごとに 1 フレームを検出
# デフォルト: 60fps 動画で 30fps 相当（SettingsPage の cv_batch_fps=30 に対応）
DEFAULT_SAMPLE_EVERY_N_FRAMES: int = 2  # 60fps 動画 → 30fps 相当


class JobStatus:
    PENDING  = "pending"
    RUNNING  = "running"
    COMPLETE = "complete"
    ERROR    = "error"


# ─── ステータス確認 ──────────────────────────────────────────────────────────

@router.get("/yolo/status")
def yolo_status():
    """YOLO モデルの導入状況・バックエンドを返す"""
    inf = get_yolo_inference()
    detail = inf.get_status_detail()
    return {
        "success": True,
        "data": {
            "available": inf.is_available(),
            "backend": inf.backend_name(),
            "loaded": inf._loaded,
            "status_code": detail["status_code"],
            "status_message": detail["message"],
            # 後方互換
            "install_hint": (
                None if inf.is_available()
                else detail["message"] or "pip install ultralytics を実行してモデルを導入してください"
            ),
        },
    }


# ─── バッチ検出 ──────────────────────────────────────────────────────────────

class RoiRectModel(BaseModel):
    """正規化座標 (0-1) の解析対象矩形"""
    x: float = 0.0
    y: float = 0.0
    w: float = 1.0
    h: float = 1.0


class YoloBatchRequest(BaseModel):
    roi_rect: Optional[RoiRectModel] = None       # 解析対象エリア（未指定なら全体）
    resume: bool = False                           # True: 既存フレームをスキップして途中再開
    prev_roi: Optional[RoiRectModel] = None       # 直前の ROI（ROI 拡張時の差分処理用）
    mode: str = "batch"                            # "batch" | "realtime"（解析レート選択）


def _load_setting_int(db: Session, key: str, default: int) -> int:
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


@router.post("/yolo/batch/{match_id}")
def start_yolo_batch(
    match_id: int,
    body: YoloBatchRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """試合動画全体を YOLO でバッチ検出開始（非同期）。

    body.mode: "batch" → yolo_batch_fps 設定を使用
              "realtime" → yolo_realtime_fps 設定を使用
    """
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")

    video_path = match.video_local_path or match.video_url
    if not video_path:
        raise HTTPException(status_code=400, detail="動画ファイルが設定されていません")

    inf = get_yolo_inference()
    if not inf.is_available():
        raise HTTPException(
            status_code=503,
            detail=(
                "YOLO モデルが見つかりません。"
                "pip install ultralytics を実行するか、"
                "backend/yolo/weights/yolo_badminton.onnx を配置してください。"
            ),
        )

    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {
        "status": JobStatus.PENDING,
        "match_id": match_id,
        "progress": 0.0,
        "processed_frames": 0,
        "total_frames": 0,
        "detected_players": 0,
        "error": None,
    }

    # mode に応じた設定値からサンプリングレートを計算（60fps 動画想定）
    if body.mode == "realtime":
        fps_setting = _load_setting_int(db, "yolo_realtime_fps", 10)
    else:
        fps_setting = _load_setting_int(db, "yolo_batch_fps", 30)
    sample_every_n = max(1, 60 // fps_setting)

    roi = body.roi_rect.model_dump() if body.roi_rect else None
    prev_roi = body.prev_roi.model_dump() if body.prev_roi else None
    background_tasks.add_task(
        _run_batch, job_id, match_id, video_path, sample_every_n, roi, body.resume, prev_roi
    )
    return {"success": True, "data": {"job_id": job_id, "sample_every_n": sample_every_n}}


@router.get("/yolo/batch/{job_id}/status")
def yolo_batch_status(job_id: str):
    """バッチジョブの進捗確認"""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")
    return {"success": True, "data": job}


@router.post("/yolo/batch/{job_id}/stop")
def yolo_batch_stop(job_id: str):
    """実行中のバッチジョブに停止リクエストを送る。現在のフレームを保存して停止する。"""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")
    if job.get("status") not in (JobStatus.RUNNING, JobStatus.PENDING):
        return {"success": True, "data": {"message": "already stopped"}}
    _jobs[job_id]["stop_requested"] = True
    return {"success": True, "data": {"job_id": job_id}}


# ─── 結果取得 ────────────────────────────────────────────────────────────────

@router.get("/yolo/results/{match_id}")
def get_yolo_results(match_id: int, include_raw: bool = False, db: Session = Depends(get_db)):
    """試合の YOLO 検出結果を返す。

    include_raw=True の場合、フレーム別生データも返す（大容量）。
    """
    artifact = (
        db.query(MatchCVArtifact)
        .filter(
            MatchCVArtifact.match_id == match_id,
            MatchCVArtifact.artifact_type == "yolo_player_detections",
        )
        .order_by(MatchCVArtifact.created_at.desc())
        .first()
    )
    if not artifact:
        return {"success": True, "data": None}

    summary = json.loads(artifact.summary) if artifact.summary else None
    result: dict = {
        "match_id": match_id,
        "artifact_id": artifact.id,
        "frame_count": artifact.frame_count,
        "backend_used": artifact.backend_used,
        "created_at": artifact.created_at.isoformat(),
        "summary": summary,
    }
    if include_raw and artifact.data:
        result["frames"] = json.loads(artifact.data)

    return {"success": True, "data": result}


@router.get("/yolo/results/{match_id}/frames")
def get_yolo_frames(match_id: int, db: Session = Depends(get_db)):
    """フレーム別生データのみを返す（オーバーレイ表示用）"""
    artifact = (
        db.query(MatchCVArtifact)
        .filter(
            MatchCVArtifact.match_id == match_id,
            MatchCVArtifact.artifact_type == "yolo_player_detections",
        )
        .order_by(MatchCVArtifact.created_at.desc())
        .first()
    )
    if not artifact or not artifact.data:
        return {"success": True, "data": []}

    return {"success": True, "data": json.loads(artifact.data)}


# ─── TrackNet 統合アライメント ───────────────────────────────────────────────

@router.post("/yolo/align/{match_id}")
def align_yolo_tracknet(match_id: int, db: Session = Depends(get_db)):
    """YOLO 検出と TrackNet シャトル軌跡をラリー単位でアライメントする。

    先に /api/yolo/batch/{match_id} と /api/tracknet/batch/{match_id} が
    実行済みである必要はない（利用可能な artifact を使う）。
    """
    # YOLO artifact
    yolo_artifact = (
        db.query(MatchCVArtifact)
        .filter(
            MatchCVArtifact.match_id == match_id,
            MatchCVArtifact.artifact_type == "yolo_player_detections",
        )
        .order_by(MatchCVArtifact.created_at.desc())
        .first()
    )
    if not yolo_artifact or not yolo_artifact.data:
        raise HTTPException(status_code=404, detail="YOLO 検出結果がありません。先にバッチ検出を実行してください。")

    yolo_frames: list[dict] = json.loads(yolo_artifact.data)

    # TrackNet artifact（あれば使用、なければ空）
    tracknet_artifact = (
        db.query(MatchCVArtifact)
        .filter(
            MatchCVArtifact.match_id == match_id,
            MatchCVArtifact.artifact_type == "tracknet_shuttle_track",
        )
        .order_by(MatchCVArtifact.created_at.desc())
        .first()
    )
    tracknet_frames: list[dict] = (
        json.loads(tracknet_artifact.data) if tracknet_artifact and tracknet_artifact.data else []
    )

    # ラリー一覧取得
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")

    sets = db.query(GameSet).filter(GameSet.match_id == match_id).all()
    set_ids = [s.id for s in sets]
    rallies_db = (
        db.query(Rally)
        .filter(Rally.set_id.in_(set_ids))
        .order_by(Rally.set_id, Rally.rally_num)
        .all()
    ) if set_ids else []

    rally_dicts = [
        {
            "rally_id": r.id,
            "start_sec": r.video_timestamp_start or 0.0,
            "end_sec": r.video_timestamp_end or (r.video_timestamp_start + 10.0
                       if r.video_timestamp_start else 10.0),
        }
        for r in rallies_db
        if r.video_timestamp_start is not None
    ]

    alignment = align_match(yolo_frames, tracknet_frames, rally_dicts)

    # 結果を artifact に保存
    alignment_json = json.dumps(alignment, ensure_ascii=False)
    existing = (
        db.query(MatchCVArtifact)
        .filter(
            MatchCVArtifact.match_id == match_id,
            MatchCVArtifact.artifact_type == "cv_alignment",
        )
        .first()
    )
    if existing:
        existing.data = alignment_json
        existing.updated_at = __import__("datetime").datetime.utcnow()
    else:
        db.add(MatchCVArtifact(
            match_id=match_id,
            artifact_type="cv_alignment",
            frame_count=len(alignment),
            data=alignment_json,
        ))
    db.commit()

    return {
        "success": True,
        "data": {
            "aligned_rallies": len(alignment),
            "alignment": alignment,
        },
    }


# ─── アライメント結果取得 ─────────────────────────────────────────────────────

@router.get("/yolo/alignment/{match_id}")
def get_alignment(match_id: int, db: Session = Depends(get_db)):
    artifact = (
        db.query(MatchCVArtifact)
        .filter(
            MatchCVArtifact.match_id == match_id,
            MatchCVArtifact.artifact_type == "cv_alignment",
        )
        .order_by(MatchCVArtifact.created_at.desc())
        .first()
    )
    if not artifact or not artifact.data:
        return {"success": True, "data": None}

    return {"success": True, "data": json.loads(artifact.data)}


# ─── バックグラウンドジョブ本体 ──────────────────────────────────────────────

def _compute_delta_rois(old_roi: dict, new_roi: dict) -> list[dict]:
    """旧ROIより新ROIが拡張した差分エリアを最大4ストリップで返す。
    新ROIが旧ROIより狭い方向がある場合は空リスト（差分処理なし）。"""
    ox = old_roi.get("x", 0); oy = old_roi.get("y", 0)
    ow = old_roi.get("w", 1); oh = old_roi.get("h", 1)
    nx = new_roi.get("x", 0); ny = new_roi.get("y", 0)
    nw = new_roi.get("w", 1); nh = new_roi.get("h", 1)
    ox2, oy2 = ox + ow, oy + oh
    nx2, ny2 = nx + nw, ny + nh
    eps = 1e-4
    # 新ROIが全方向で旧ROI以上でないと「純粋な拡張」とみなさない
    if nx > ox + eps or ny > oy + eps or nx2 < ox2 - eps or ny2 < oy2 - eps:
        return []
    strips: list[dict] = []
    if ny < oy - eps:  # 上方向拡張
        strips.append({"x": nx, "y": ny, "w": nw, "h": oy - ny})
    if ny2 > oy2 + eps:  # 下方向拡張
        strips.append({"x": nx, "y": oy2, "w": nw, "h": ny2 - oy2})
    mid_y = max(ny, oy); mid_y2 = min(ny2, oy2)
    if mid_y2 > mid_y + eps:
        if nx < ox - eps:  # 左方向拡張
            strips.append({"x": nx, "y": mid_y, "w": ox - nx, "h": mid_y2 - mid_y})
        if nx2 > ox2 + eps:  # 右方向拡張
            strips.append({"x": ox2, "y": mid_y, "w": nx2 - ox2, "h": mid_y2 - mid_y})
    return strips


def _bbox_iou(b1: list, b2: list) -> float:
    """正規化座標bboxのIoU"""
    if len(b1) != 4 or len(b2) != 4:
        return 0.0
    ix1, iy1 = max(b1[0], b2[0]), max(b1[1], b2[1])
    ix2, iy2 = min(b1[2], b2[2]), min(b1[3], b2[3])
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    a1 = (b1[2] - b1[0]) * (b1[3] - b1[1])
    a2 = (b2[2] - b2[0]) * (b2[3] - b2[1])
    union = a1 + a2 - inter
    return inter / union if union > 0 else 0.0


def _merge_players(existing: list[dict], new_players: list[dict], iou_thresh: float = 0.3) -> list[dict]:
    """既存と新規プレイヤー検出をマージ（IoU重複は既存を優先）。"""
    merged = list(existing)
    for p in new_players:
        if not any(_bbox_iou(p.get("bbox", []), e.get("bbox", [])) >= iou_thresh for e in merged):
            merged.append(p)
    return merged


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


def _remap_player_coords(players: list[dict], roi: dict | None) -> list[dict]:
    """YOLO 検出結果の正規化座標を ROI ローカル座標からフルフレーム座標に変換する。"""
    if not roi:
        return players
    rx, ry = roi.get("x", 0.0), roi.get("y", 0.0)
    rw, rh = roi.get("w", 1.0), roi.get("h", 1.0)
    out = []
    for p in players:
        p2 = dict(p)
        if p2.get("bbox") and len(p2["bbox"]) == 4:
            x1n, y1n, x2n, y2n = p2["bbox"]
            p2["bbox"] = [
                round(rx + x1n * rw, 4),
                round(ry + y1n * rh, 4),
                round(rx + x2n * rw, 4),
                round(ry + y2n * rh, 4),
            ]
        if p2.get("foot_point") and len(p2["foot_point"]) == 2:
            fx, fy = p2["foot_point"]
            p2["foot_point"] = [round(rx + fx * rw, 4), round(ry + fy * rh, 4)]
        if "cx_n" in p2:
            p2["cx_n"] = round(rx + p2["cx_n"] * rw, 4)
        if "cy_n" in p2:
            p2["cy_n"] = round(ry + p2["cy_n"] * rh, 4)
        out.append(p2)
    return out


# 中断耐性のため N フレーム処理するごとにアーティファクトを部分保存する
_YOLO_PARTIAL_SAVE_EVERY = 500


def _upsert_yolo_artifact(
    db,
    match_id: int,
    frames_data: list[dict],
    backend_name: str,
    summary_json: str | None = None,
) -> None:
    """frames_data を yolo_player_detections アーティファクトへ upsert する。"""
    import datetime as _dt
    frames_json = json.dumps(frames_data, ensure_ascii=False)
    existing = (
        db.query(MatchCVArtifact)
        .filter(
            MatchCVArtifact.match_id == match_id,
            MatchCVArtifact.artifact_type == "yolo_player_detections",
        )
        .first()
    )
    if existing:
        existing.data = frames_json
        existing.frame_count = len(frames_data)
        existing.backend_used = backend_name
        existing.updated_at = _dt.datetime.utcnow()
        if summary_json is not None:
            existing.summary = summary_json
    else:
        db.add(MatchCVArtifact(
            match_id=match_id,
            artifact_type="yolo_player_detections",
            frame_count=len(frames_data),
            backend_used=backend_name,
            summary=summary_json,
            data=frames_json,
        ))
    db.commit()


def _run_batch(
    job_id: str,
    match_id: int,
    video_path: str,
    sample_every_n: int,
    roi: dict | None = None,
    resume: bool = False,
    prev_roi: dict | None = None,
) -> None:
    _jobs[job_id]["status"] = JobStatus.RUNNING
    db = SessionLocal()

    try:
        inf = get_yolo_inference()
        if not inf.load():
            _jobs[job_id]["status"] = JobStatus.ERROR
            _jobs[job_id]["error"] = "モデルロードに失敗しました。pip install ultralytics を実行してください。"
            return

        # 既存アーティファクト読み込み（再開・差分処理用）
        # 最新アーティファクトを取得するため created_at 降順
        existing_by_idx: dict[int, dict] = {}
        if resume or prev_roi:
            art = (
                db.query(MatchCVArtifact)
                .filter(
                    MatchCVArtifact.match_id == match_id,
                    MatchCVArtifact.artifact_type == "yolo_player_detections",
                )
                .order_by(MatchCVArtifact.created_at.desc())
                .first()
            )
            if art and art.data:
                for f in json.loads(art.data):
                    existing_by_idx[f["frame_idx"]] = f

        # ROI拡張差分ストリップ計算
        delta_rois: list[dict] = []
        if prev_roi and roi:
            delta_rois = _compute_delta_rois(prev_roi, roi)

        if existing_by_idx:
            logger.info(
                "YOLO batch: resume=%s, delta_strips=%d, existing_frames=%d",
                resume, len(delta_rois), len(existing_by_idx),
            )

        # 動画オープン
        path = video_path
        if path.startswith("localfile:///"):
            path = path[len("localfile:///"):]

        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            _jobs[job_id]["status"] = JobStatus.ERROR
            _jobs[job_id]["error"] = f"動画を開けませんでした: {path}"
            return

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        sample_count = max(1, total_frames // sample_every_n)
        _jobs[job_id]["total_frames"] = sample_count

        # resume モードかつ差分処理なし: 既存フレームをコピーしてから未処理部分にシーク
        frames_data: list[dict] = []
        detected_total = 0
        new_frames_since_save = 0

        if existing_by_idx and not delta_rois:
            # 既存フレームをそのまま引き継ぐ
            frames_data = sorted(existing_by_idx.values(), key=lambda f: f["frame_idx"])
            detected_total = sum(
                len([p for p in f["players"] if "player" in p.get("label", "")])
                for f in frames_data
            )
            # 最大処理済みフレームの次の位置にシーク
            max_existing = max(existing_by_idx.keys())
            start_frame = max_existing + sample_every_n
            if start_frame < total_frames:
                cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
            else:
                # 全フレーム処理済み → そのまま完了
                cap.release()
                summary = summarize_frame_positions(frames_data)
                _upsert_yolo_artifact(db, match_id, frames_data, inf.backend_name(), json.dumps(summary, ensure_ascii=False))
                _jobs[job_id]["status"] = JobStatus.COMPLETE
                _jobs[job_id]["progress"] = 1.0
                _jobs[job_id]["processed_frames"] = len(frames_data)
                return
            frame_idx = start_frame
        else:
            start_frame = 0
            frame_idx = 0

        processed = len(frames_data)
        _jobs[job_id]["processed_frames"] = processed
        _jobs[job_id]["progress"] = round(processed / max(sample_count, 1), 3)

        while True:
            # 停止リクエスト確認（ユーザーが「停止」ボタンを押した場合）
            if _jobs[job_id].get("stop_requested"):
                cap.release()
                # 現在の全フレームを保存して "stopped" 状態にする
                if frames_data:
                    try:
                        _upsert_yolo_artifact(db, match_id, frames_data, inf.backend_name())
                    except Exception as save_err:
                        logger.warning("YOLO stop save failed: %s", save_err)
                _jobs[job_id]["status"] = "stopped"
                logger.info(
                    "YOLO batch stopped by user: match=%d, frames_saved=%d",
                    match_id, len(frames_data),
                )
                return

            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % sample_every_n == 0:
                ts_sec = frame_idx / fps

                if frame_idx in existing_by_idx and delta_rois:
                    # ROI拡張差分: 拡張エリアのみ追加検出してマージ
                    new_players: list[dict] = []
                    for droi in delta_rois:
                        cropped = _crop_roi(frame, droi)
                        detected = inf.predict_frame(cropped)
                        new_players.extend(_remap_player_coords(detected, droi))
                    merged = _merge_players(existing_by_idx[frame_idx]["players"], new_players)
                    frames_data.append({
                        "frame_idx": frame_idx,
                        "timestamp_sec": round(ts_sec, 3),
                        "players": merged,
                    })
                    new_frames_since_save += 1
                else:
                    # 未処理フレーム: 通常検出
                    cropped = _crop_roi(frame, roi)
                    players = inf.predict_frame(cropped)
                    if roi:
                        players = _remap_player_coords(players, roi)
                    frames_data.append({
                        "frame_idx": frame_idx,
                        "timestamp_sec": round(ts_sec, 3),
                        "players": players,
                    })
                    new_frames_since_save += 1

                detected_total += len([p for p in frames_data[-1]["players"] if "player" in p.get("label", "")])
                processed += 1
                _jobs[job_id]["processed_frames"] = processed
                _jobs[job_id]["progress"] = round(processed / max(sample_count, 1), 3)
                _jobs[job_id]["detected_players"] = detected_total

                # 中断耐性のため定期的に部分保存（新規処理フレームのみカウント）
                if new_frames_since_save >= _YOLO_PARTIAL_SAVE_EVERY:
                    try:
                        _upsert_yolo_artifact(db, match_id, frames_data, inf.backend_name())
                        new_frames_since_save = 0
                        logger.debug("YOLO partial save: match=%d, frames=%d", match_id, len(frames_data))
                    except Exception as save_err:
                        logger.warning("YOLO partial save failed: %s", save_err)

            frame_idx += 1

        cap.release()

        # コート位置サマリー計算
        summary = summarize_frame_positions(frames_data)
        summary_json = json.dumps(summary, ensure_ascii=False)

        # 最終保存
        _upsert_yolo_artifact(db, match_id, frames_data, inf.backend_name(), summary_json)

        # シード割り当てが保存済みなら識別トラックを全フレームで自動再適用する
        # （バッチ実行中に assign_and_track が呼ばれた場合、部分データしか処理されていない）
        try:
            seed_art = (
                db.query(MatchCVArtifact)
                .filter(
                    MatchCVArtifact.match_id == match_id,
                    MatchCVArtifact.artifact_type == "player_identity_seed",
                )
                .first()
            )
            if seed_art and seed_art.data:
                seed_data = json.loads(seed_art.data)
                re_tracked = _track_identities(
                    frames_data,
                    seed_data["seed_timestamp_sec"],
                    seed_data["assignments"],
                )
                if re_tracked:
                    import datetime as _dt2
                    re_track_json = json.dumps(re_tracked, ensure_ascii=False)
                    existing_track = (
                        db.query(MatchCVArtifact)
                        .filter(
                            MatchCVArtifact.match_id == match_id,
                            MatchCVArtifact.artifact_type == "player_identity_track",
                        )
                        .first()
                    )
                    if existing_track:
                        existing_track.data = re_track_json
                        existing_track.frame_count = len(re_tracked)
                        existing_track.updated_at = _dt2.datetime.utcnow()
                    else:
                        db.add(MatchCVArtifact(
                            match_id=match_id,
                            artifact_type="player_identity_track",
                            frame_count=len(re_tracked),
                            data=re_track_json,
                        ))
                    db.commit()
                    logger.info(
                        "YOLO batch: identity track auto re-applied, match=%d frames=%d",
                        match_id, len(re_tracked),
                    )
        except Exception as re_id_err:
            logger.warning("YOLO batch: identity track re-apply failed: %s", re_id_err)

        _jobs[job_id]["status"] = JobStatus.COMPLETE
        _jobs[job_id]["progress"] = 1.0
        _jobs[job_id]["processed_frames"] = processed

        logger.info(
            "YOLO batch complete: match=%d, frames=%d, detections=%d",
            match_id, processed, detected_total,
        )

    except Exception as exc:
        logger.exception("YOLO batch job %s failed: %s", job_id, exc)
        _jobs[job_id]["status"] = JobStatus.ERROR
        _jobs[job_id]["error"] = str(exc)
    finally:
        db.close()


# ─── 1フレーム即時検出（タグ付け用） ────────────────────────────────────────

class FrameDetectRequest(BaseModel):
    timestamp_sec: float
    roi_rect: Optional[RoiRectModel] = None


@router.post("/yolo/frame_detect/{match_id}")
def detect_single_frame(
    match_id: int,
    body: FrameDetectRequest,
    db: Session = Depends(get_db),
):
    """指定タイムスタンプの 1 フレームを YOLO 検出して即時返す（選手タグ付け用）。"""
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")

    path = match.video_local_path or match.video_url
    if not path:
        raise HTTPException(status_code=400, detail="動画ファイルが設定されていません")
    if path.startswith("localfile:///"):
        path = path[len("localfile:///"):]

    inf = get_yolo_inference()
    if not inf.is_available() or not inf.load():
        raise HTTPException(status_code=503, detail="YOLO モデルが利用できません")

    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise HTTPException(status_code=400, detail=f"動画を開けませんでした: {path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_idx = int(body.timestamp_sec * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ret, frame = cap.read()
    cap.release()

    if not ret:
        raise HTTPException(status_code=400, detail="フレームを読み込めませんでした")

    roi = body.roi_rect.model_dump() if body.roi_rect else None
    cropped = _crop_roi(frame, roi)
    h_crop, w_crop = cropped.shape[:2]
    players = inf.predict_frame(cropped)
    if roi:
        players = _remap_player_coords(players, roi)

    debug_info = inf.get_last_debug()

    logger.info(
        "frame_detect match=%d ts=%.2f frame_idx=%d fps=%.1f crop=%dx%d backend=%s players=%d debug=%s",
        match_id, body.timestamp_sec, frame_idx, fps, w_crop, h_crop,
        inf.backend_name(), len(players), debug_info,
    )

    return {
        "success": True,
        "data": {
            "frame_idx": frame_idx,
            "timestamp_sec": body.timestamp_sec,
            "players": players,
            "debug": debug_info,
        },
    }


# ─── モデルウォームアップ ───────────────────────────────────────────────────
import numpy as _np

@router.post("/yolo/warmup")
def yolo_warmup():
    """YOLO モデルを事前ロードして最初の検出遅延をなくす。
    アノテーターページロード時にバックグラウンドで呼び出す。
    """
    inf = get_yolo_inference()
    if not inf.is_available():
        return {"success": False, "data": {"message": "YOLO モデル未導入"}}
    try:
        # 64×64 の黒フレームでダミー推論（モデルをメモリにロードするだけ）
        dummy = _np.zeros((64, 64, 3), dtype=_np.uint8)
        inf.predict_frame(dummy)
        return {"success": True, "data": {"message": "warmup ok", "backend": inf.backend_name()}}
    except Exception as exc:
        logger.warning("YOLO warmup failed: %s", exc)
        return {"success": False, "data": {"message": str(exc)}}


# ─── 選手割り当て + IoU 追跡 ─────────────────────────────────────────────────

class PlayerIdentityAssignment(BaseModel):
    detection_index: int   # frame_detect の players[] インデックス
    player_key: str        # 'player_a' | 'partner_a' | 'player_b' | 'partner_b' | 'other'
    bbox: Optional[list[float]] = None  # frame_detect で表示された bbox（IoU マッチング用）


class AssignAndTrackRequest(BaseModel):
    seed_timestamp_sec: float
    assignments: list[PlayerIdentityAssignment]


@router.post("/yolo/assign_and_track/{match_id}")
def assign_and_track(
    match_id: int,
    body: AssignAndTrackRequest,
    db: Session = Depends(get_db),
):
    """シードフレームの選手割り当てを全バッチフレームに IoU 追跡で伝播し保存する。"""
    art = (
        db.query(MatchCVArtifact)
        .filter(
            MatchCVArtifact.match_id == match_id,
            MatchCVArtifact.artifact_type == "yolo_player_detections",
        )
        .first()
    )
    if not art or not art.data:
        raise HTTPException(
            status_code=400,
            detail="YOLO バッチ解析が完了していません。先にバッチ解析を実行してください。",
        )

    import datetime as _dt

    yolo_frames: list[dict] = json.loads(art.data)
    assignments = [a.model_dump() for a in body.assignments]

    # シード割り当てを保存（バッチ完了後に全フレームへ自動再適用するため）
    seed_payload = {
        "seed_timestamp_sec": body.seed_timestamp_sec,
        "assignments": assignments,
    }
    seed_json = json.dumps(seed_payload, ensure_ascii=False)
    existing_seed = (
        db.query(MatchCVArtifact)
        .filter(
            MatchCVArtifact.match_id == match_id,
            MatchCVArtifact.artifact_type == "player_identity_seed",
        )
        .first()
    )
    if existing_seed:
        existing_seed.data = seed_json
        existing_seed.updated_at = _dt.datetime.utcnow()
    else:
        db.add(MatchCVArtifact(
            match_id=match_id,
            artifact_type="player_identity_seed",
            data=seed_json,
        ))
    db.commit()

    tracked = _track_identities(yolo_frames, body.seed_timestamp_sec, assignments)
    logger.info(
        "assign_and_track: match=%d seed=%.2fs yolo_frames=%d tracked=%d",
        match_id, body.seed_timestamp_sec, len(yolo_frames), len(tracked),
    )

    track_json = json.dumps(tracked, ensure_ascii=False)
    existing = (
        db.query(MatchCVArtifact)
        .filter(
            MatchCVArtifact.match_id == match_id,
            MatchCVArtifact.artifact_type == "player_identity_track",
        )
        .first()
    )
    if existing:
        existing.data = track_json
        existing.frame_count = len(tracked)
        existing.updated_at = _dt.datetime.utcnow()
    else:
        db.add(MatchCVArtifact(
            match_id=match_id,
            artifact_type="player_identity_track",
            frame_count=len(tracked),
            data=track_json,
        ))
    db.commit()

    return {"success": True, "data": {"tracked_frames": len(tracked)}}


@router.get("/yolo/identity_track/{match_id}")
def get_identity_track(match_id: int, db: Session = Depends(get_db)):
    """保存済み選手識別トラックを返す。"""
    art = (
        db.query(MatchCVArtifact)
        .filter(
            MatchCVArtifact.match_id == match_id,
            MatchCVArtifact.artifact_type == "player_identity_track",
        )
        .order_by(MatchCVArtifact.created_at.desc())
        .first()
    )
    if not art or not art.data:
        return {"success": True, "data": []}
    return {"success": True, "data": json.loads(art.data)}


# ─── 選手移動距離統計 ────────────────────────────────────────────────────────

@router.get("/yolo/movement_stats/{match_id}")
def get_movement_stats(match_id: int, db: Session = Depends(get_db)):
    """
    選手識別トラックから各選手のコート上移動距離・方向・速度を計算する。

    コートキャリブレーションが設定済みの場合は実メートル換算、
    未設定の場合は画像正規化座標での相対値として返す。
    """
    import math
    from backend.routers.court_calibration import load_calibration_from_db, apply_homography

    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")

    # ── identity_track artifact ──────────────────────────────────────────────
    track_art = (
        db.query(MatchCVArtifact)
        .filter(
            MatchCVArtifact.match_id == match_id,
            MatchCVArtifact.artifact_type == "player_identity_track",
        )
        .order_by(MatchCVArtifact.created_at.desc())
        .first()
    )
    if not track_art or not track_art.data:
        return {"success": True, "data": {"available": False, "reason": "選手識別トラックがありません。先に「+ 識別」でトラッキングを実行してください。"}}

    frames: list[dict] = json.loads(track_art.data)

    # ── コートキャリブレーション ─────────────────────────────────────────────
    calib = load_calibration_from_db(match_id, db)
    has_calibration = calib is not None
    H = calib["homography"] if calib else None

    # ── コート寸法 ───────────────────────────────────────────────────────────
    is_doubles = match.format in ("doubles", "mixed_doubles")
    court_width_m  = 6.7 if is_doubles else 6.1   # 横幅
    court_length_m = 13.4                          # 縦（両コート合計）

    # ── プレイヤーごとに時系列ポイントを収集 ─────────────────────────────────
    # player_frames: {player_key: [{ts, cx_img, cy_img}, ...]}
    player_frames: dict[str, list[dict]] = {}
    for frame in frames:
        ts = frame.get("timestamp_sec", 0.0)
        for p in frame.get("players", []):
            key = p.get("player_key", "other")
            if key == "other":
                continue
            if p.get("lost", False):
                continue
            bbox = p.get("bbox", [])
            if len(bbox) != 4:
                continue
            cx_img = (bbox[0] + bbox[2]) / 2
            cy_img = (bbox[1] + bbox[3]) / 2
            if key not in player_frames:
                player_frames[key] = []
            player_frames[key].append({"ts": ts, "cx": cx_img, "cy": cy_img})

    for key in player_frames:
        player_frames[key].sort(key=lambda x: x["ts"])

    # ── フレーム間ギャップの上限（ラリー間を跨がない） ───────────────────────
    MAX_GAP_SEC = 3.0
    # トラッキングエラー由来の非現実的な速度を除外するキャップ（12m/s = 43.2km/h）
    # バドミントン選手のトップスピードは約 7-8m/s。12m/s は十分な余裕を持つ上限
    MAX_STEP_SPEED_MPS = 12.0

    # ── 各選手の統計計算 ─────────────────────────────────────────────────────
    results: dict[str, dict] = {}
    for player_key, pts in player_frames.items():
        if len(pts) < 2:
            continue

        total_dist_m     = 0.0
        total_lateral_m  = 0.0   # 横方向（ネット平行）
        total_depth_m    = 0.0   # 奥行き方向（ネット垂直）
        total_diagonal_m = 0.0   # 斜め方向
        step_speeds: list[float] = []
        zone_visits: dict[str, int] = {}
        time_series: list[dict]    = []  # 5秒ごとに累積距離を記録
        last_ts_recorded = -999.0

        prev: dict | None = None
        for p_pt in pts:
            ts = p_pt["ts"]
            cx_img, cy_img = p_pt["cx"], p_pt["cy"]

            # 画像座標 → コート正規化座標
            if H:
                cx_c, cy_c = apply_homography(H, cx_img, cy_img)
                cx_c = max(0.0, min(1.0, cx_c))
                cy_c = max(0.0, min(1.0, cy_c))
            else:
                cx_c, cy_c = cx_img, cy_img   # キャリブなし: 画像座標をそのまま使用

            # ゾーン集計（3列 × 6行 → 18ゾーン）
            col_i  = min(int(cx_c * 3), 2)
            row_i  = min(int(cy_c * 6), 5)
            side   = "A" if row_i < 3 else "B"
            depth  = ["front", "mid", "back"][row_i % 3]
            col    = ["left", "center", "right"][col_i]
            zone_name = f"{side}_{depth}_{col}"
            zone_visits[zone_name] = zone_visits.get(zone_name, 0) + 1

            if prev is not None:
                dt = ts - prev["ts"]
                if 0 < dt <= MAX_GAP_SEC:
                    dx_m = (cx_c - prev["cx_c"]) * court_width_m
                    dy_m = (cy_c - prev["cy_c"]) * court_length_m
                    dist_m = math.sqrt(dx_m ** 2 + dy_m ** 2)

                    step_speed = dist_m / dt
                    if dist_m > 0.001 and step_speed <= MAX_STEP_SPEED_MPS:
                        # ノイズカット（1mm 以下）＆ トラッキングエラー除外（12m/s 超）
                        total_dist_m += dist_m

                        # 方向分類（角度で判定）
                        angle_deg = math.degrees(math.atan2(abs(dy_m), abs(dx_m)))
                        if angle_deg < 22.5:
                            total_lateral_m += dist_m    # ほぼ横
                        elif angle_deg > 67.5:
                            total_depth_m += dist_m      # ほぼ前後
                        else:
                            total_diagonal_m += dist_m   # 斜め

                        # 速度
                        step_speeds.append(step_speed)

                # 5秒ごとに時系列ポイントを記録
                if ts - last_ts_recorded >= 5.0:
                    time_series.append({"t": round(ts, 1), "dist_m": round(total_dist_m, 2)})
                    last_ts_recorded = ts

            prev = {"ts": ts, "cx_c": cx_c, "cy_c": cy_c}

        # 末尾ポイントを追加
        if pts:
            time_series.append({"t": round(pts[-1]["ts"], 1), "dist_m": round(total_dist_m, 2)})

        avg_speed_mps = sum(step_speeds) / len(step_speeds) if step_speeds else 0.0
        max_speed_mps = max(step_speeds) if step_speeds else 0.0
        duration_sec  = pts[-1]["ts"] - pts[0]["ts"] if len(pts) > 1 else 0.0

        results[player_key] = {
            "total_distance_m":  round(total_dist_m, 2),
            "frames_tracked":    len(pts),
            "duration_sec":      round(duration_sec, 1),
            "avg_speed_m_per_s": round(avg_speed_mps, 3),
            "max_speed_m_per_s": round(max_speed_mps, 3),
            "direction_breakdown": {
                "lateral_m":    round(total_lateral_m, 2),
                "depth_m":      round(total_depth_m, 2),
                "diagonal_m":   round(total_diagonal_m, 2),
                "lateral_pct":  round(total_lateral_m  / total_dist_m * 100, 1) if total_dist_m > 0 else 0.0,
                "depth_pct":    round(total_depth_m    / total_dist_m * 100, 1) if total_dist_m > 0 else 0.0,
                "diagonal_pct": round(total_diagonal_m / total_dist_m * 100, 1) if total_dist_m > 0 else 0.0,
            },
            "zone_visits": zone_visits,
            "time_series": time_series,
        }

    # ── 信頼度メタデータ ─────────────────────────────────────────────────────
    max_frames = max((v["frames_tracked"] for v in results.values()), default=0)
    if not has_calibration:
        conf_level  = "low"
        conf_reason = "コートキャリブレーション未設定のため距離精度が低下しています。グリッド線ではなく「コートキャリブレーション」（6点指定）が必要です。"
    elif max_frames < 100:
        conf_level  = "low"
        conf_reason = f"トラックフレーム数が少なめです（{max_frames}フレーム）。"
    elif max_frames < 300:
        conf_level  = "medium"
        conf_reason = f"トラックフレーム数: {max_frames}フレーム。"
    else:
        conf_level  = "high"
        conf_reason = f"トラックフレーム数: {max_frames}フレーム。"

    return {
        "success": True,
        "data": {
            "available":       len(results) > 0,
            "has_calibration": has_calibration,
            "court_width_m":   court_width_m,
            "court_length_m":  court_length_m,
            "players":         results,
            "confidence": {
                "level":           conf_level,
                "reason":          conf_reason,
                "has_calibration": has_calibration,
            },
        },
    }


# ─── IoU 追跡ヘルパー ────────────────────────────────────────────────────────

def _match_identities(
    curr_players: list[dict],
    prev_identities: list[dict],
    iou_thresh: float = 0.05,
    max_cent_dist: float = 0.30,
) -> list[dict]:
    """前フレームの識別済み選手を現フレームに IoU → 重心距離フォールバックでマッチング伝播する。

    IoU が iou_thresh を超えない場合、重心距離が max_cent_dist 以内の最近傍を使う。
    これにより選手が大きく移動した場合でもトラッキングを維持できる。
    """
    import math as _math
    result: list[dict] = []
    used: set[int] = set()

    for prev in prev_identities:
        # ── IoU マッチング ────────────────────────────────────────────────────
        best_iou = iou_thresh
        best_i = -1
        for i, p in enumerate(curr_players):
            if i in used:
                continue
            iou = _bbox_iou(prev.get("bbox", []), p.get("bbox", []))
            if iou > best_iou:
                best_iou = iou
                best_i = i

        # ── IoU 失敗 → 重心距離フォールバック ─────────────────────────────────
        if best_i < 0:
            pb = prev.get("bbox", [])
            if len(pb) == 4:
                pcx = (pb[0] + pb[2]) / 2
                pcy = (pb[1] + pb[3]) / 2
            else:
                pcx = prev.get("cx_n", 0.5)
                pcy = prev.get("cy_n", 0.5)
            best_dist = max_cent_dist
            for i, p in enumerate(curr_players):
                if i in used:
                    continue
                pb2 = p.get("bbox", [])
                if len(pb2) == 4:
                    cx = (pb2[0] + pb2[2]) / 2
                    cy = (pb2[1] + pb2[3]) / 2
                else:
                    cx = p.get("cx_n", 0.5)
                    cy = p.get("cy_n", 0.5)
                dist = _math.sqrt((cx - pcx) ** 2 + (cy - pcy) ** 2)
                if dist < best_dist:
                    best_dist = dist
                    best_i = i

        if best_i >= 0:
            used.add(best_i)
            p = curr_players[best_i]
            result.append({
                "player_key": prev["player_key"],
                "bbox":  p.get("bbox", prev.get("bbox")),
                "cx_n":  p.get("cx_n",  prev.get("cx_n")),
                "cy_n":  p.get("cy_n",  prev.get("cy_n")),
                "lost":  False,
            })
        else:
            # トラッキングロスト — 前フレームの位置を保持
            result.append({**prev, "lost": True})

    return result


def _track_identities(
    yolo_frames: list[dict],
    seed_ts: float,
    assignments: list[dict],
) -> list[dict]:
    """シードフレームの割り当てをもとに全フレームへ前後双方向で IoU 伝播する。"""
    if not yolo_frames:
        return []

    # シードフレームのインデックスを特定
    seed_i = min(range(len(yolo_frames)), key=lambda i: abs(yolo_frames[i]["timestamp_sec"] - seed_ts))
    seed_players = yolo_frames[seed_i]["players"]

    # 初期識別リスト構築
    # bbox が渡された場合は IoU マッチングでシードプレイヤーを特定する。
    # frame_detect と batch の検出順序が異なる場合でも正確に対応できる。
    init: list[dict] = []
    for a in assignments:
        bbox_from_ui = a.get("bbox")
        matched_p: dict | None = None

        if bbox_from_ui and len(bbox_from_ui) == 4:
            # UIで選択した bbox に最も近いシードプレイヤーを IoU で探す
            best_iou = 0.05  # 最低 IoU 閾値
            for sp in seed_players:
                iou = _bbox_iou(bbox_from_ui, sp.get("bbox", []))
                if iou > best_iou:
                    best_iou = iou
                    matched_p = sp

        if matched_p is None:
            # フォールバック: インデックスベース（旧動作）
            idx = a["detection_index"]
            if idx < len(seed_players):
                matched_p = seed_players[idx]

        if matched_p is not None:
            init.append({
                "player_key": a["player_key"],
                "bbox":  matched_p.get("bbox", [0, 0, 0, 0]),
                "cx_n":  matched_p.get("cx_n"),
                "cy_n":  matched_p.get("cy_n"),
                "lost":  False,
            })

    # 前方伝播（シード → 末尾）
    forward: dict[int, dict] = {}
    prev = init
    for frame in yolo_frames[seed_i:]:
        matched = _match_identities(frame["players"], prev)
        forward[frame["frame_idx"]] = {
            "frame_idx":    frame["frame_idx"],
            "timestamp_sec": frame["timestamp_sec"],
            "players":      matched,
        }
        prev = matched

    # 後方伝播（シード → 先頭 / 逆順）
    backward: dict[int, dict] = {}
    prev = init
    for frame in reversed(yolo_frames[:seed_i]):
        matched = _match_identities(frame["players"], prev)
        backward[frame["frame_idx"]] = {
            "frame_idx":    frame["frame_idx"],
            "timestamp_sec": frame["timestamp_sec"],
            "players":      matched,
        }
        prev = matched

    merged = {**backward, **forward}  # forward が seed フレームを優先
    return sorted(merged.values(), key=lambda f: f["frame_idx"])


# ─── ダブルス CV 解析 ─────────────────────────────────────────────────────────

@router.get("/yolo/doubles_analysis/{match_id}")
def yolo_doubles_analysis(match_id: int, db: Session = Depends(get_db)):
    """YOLO 検出を使ったダブルス・ポジション解析を返す。

    YOLO バッチ検出（/api/yolo/batch/{match_id}）が完了している必要がある。
    アライメント（/api/yolo/align/{match_id}）が完了していると更に詳細なヒッター情報が得られる。
    """
    result = compute_doubles_cv_analytics(match_id, db)
    return {"success": True, "data": result}
