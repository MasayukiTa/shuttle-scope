"""バックグラウンド解析パイプライン

試合終了後にローカル動画を TrackNet + YOLO で自動解析する。
動画は試合中に既にローカル保存済みのため、アップロード機能は不要。

エンドポイント:
  POST /api/video_import/path          — ローカルパス + match_id で解析ジョブ投入
  GET  /api/video_import/{job_id}      — ジョブ進捗（TrackNet + YOLO 合算）
  GET  /api/video_import/list          — 全ジョブ一覧

iGPU 優先設計:
  - TrackNet / YOLO ともに OpenVINO GPU デバイスで動作
  - CPU 負荷を抑えることでアノテーション操作への影響を最小化
  - ジョブは別スレッドで実行し FastAPI イベントループをブロックしない
"""
from __future__ import annotations

import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel
from backend.utils.auth import get_auth
from backend.utils.control_plane import allow_local_file_control

logger = logging.getLogger(__name__)
router = APIRouter()

TRACKNET_ARTIFACT_TYPE = "tracknet_shuttle_track"
LEGACY_TRACKNET_ARTIFACT_TYPES = ("tracknet_shuttle_track", "tracknet_track")

# 動画ファイルのサイズ上限（10 GB）— これを超えると解析を拒否
_MAX_VIDEO_BYTES = 10 * 1024 * 1024 * 1024

# ─── ジョブ管理 ──────────────────────────────────────────────────────────────

class Phase:
    QUEUED    = "queued"
    SAVING    = "saving"
    TRACKNET  = "tracknet"
    YOLO      = "yolo"
    DONE      = "done"
    ERROR     = "error"


_jobs: dict[str, dict] = {}   # job_id → job dict


def _new_job(video_path: str, match_id: Optional[int] = None,
             owner_user_id: Optional[int] = None,
             owner_team_name: Optional[str] = None) -> dict:
    return {
        "job_id": None,           # 後で設定
        "video_path": video_path,
        "match_id": match_id,
        # Round 258 P1: cross-team filesystem path leak 対策のため owner を記録
        "owner_user_id": owner_user_id,
        "owner_team_name": owner_team_name,
        "phase": Phase.QUEUED,
        "progress": 0.0,          # 0.0 - 1.0
        "tracknet": {
            "status": "pending",
            "progress": 0.0,
            "backend": None,
            "error": None,
        },
        "yolo": {
            "status": "pending",
            "progress": 0.0,
            "backend": None,
            "error": None,
        },
        "started_at": None,
        "finished_at": None,
        "error": None,
    }


def _can_view_job(ctx, job: dict) -> bool:
    """Round 258 P1: cross-team の video_path leak 防止.
    admin: 全件可視 / coach・analyst: 同チーム or owner=自分 / player: 不可."""
    if ctx is None or ctx.role is None:
        return False
    if ctx.is_admin:
        return True
    if ctx.is_player:
        return False
    if job.get("owner_user_id") == ctx.user_id:
        return True
    own_team = (ctx.team_name or "").strip()
    job_team = (job.get("owner_team_name") or "").strip()
    return bool(own_team and job_team and own_team == job_team)


def _redact_job(job: dict, ctx) -> dict:
    """非 admin には絶対パスを返さず basename のみ。"""
    if ctx is not None and ctx.is_admin:
        return job
    redacted = dict(job)
    vp = job.get("video_path") or ""
    if vp:
        try:
            redacted["video_path"] = Path(vp).name  # filesystem path 構造を伏せる
        except Exception:
            redacted["video_path"] = "<redacted>"
    return redacted


# ─── エンドポイント ───────────────────────────────────────────────────────────

class PathImportRequest(BaseModel):
    video_path: str
    match_id: Optional[int] = None


@router.post("/video_import/path")
def import_from_path(body: PathImportRequest, background_tasks: BackgroundTasks, request: Request):
    """試合動画のローカルパスと match_id を指定してバックグラウンド解析を開始。
    試合終了後に自動呼び出しされる想定。
    """
    if not allow_local_file_control(request):
        raise HTTPException(status_code=403, detail="ローカルファイル操作はローカルからのみ実行できます")
    # URLスキームを持つパスを拒否（SSRF防止 — OpenCV は rtsp:// / http:// を直接開けるため）
    raw_video_path = body.video_path.strip()
    if re.match(r'^[a-zA-Z][a-zA-Z0-9+\-.]*://', raw_video_path):
        raise HTTPException(status_code=400, detail="URLは指定できません。ローカルファイルパスのみ有効です")
    # NUL / 改行等の制御文字を拒否
    if any(ch in raw_video_path for ch in ("\x00", "\r", "\n")):
        raise HTTPException(status_code=400, detail="パスに不正な文字が含まれています")

    # Path-injection 防止: 拡張子チェックを resolve 前に行う
    ALLOWED_VIDEO_EXTS = {'.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.m4v', '.webm', '.ts', '.mts'}
    _pre_suffix = Path(raw_video_path).suffix.lower()
    if _pre_suffix not in ALLOWED_VIDEO_EXTS:
        raise HTTPException(status_code=400, detail=f"動画ファイル以外は処理できません: {_pre_suffix}")

    path = Path(raw_video_path).resolve()
    # 再度拡張子チェック（シンボリックリンク越し対策）
    if path.suffix.lower() not in ALLOWED_VIDEO_EXTS:
        raise HTTPException(status_code=400, detail="動画ファイル以外は処理できません")

    # ⚠️ path_jail を **存在/種別チェックより前に** 実行する (CodeQL py/path-injection 対策)。
    # exists() / is_file() を許可ルート外で呼ぶと、任意パスの存在情報を attacker が
    # プローブできる side-channel になる (response code 差異)。
    # backend/data, ss_video_root, ss_live_archive_root, ss_video_extra_roots 配下に
    # 限定してから filesystem を触る。
    from backend.utils.path_jail import is_allowed_video_path, allowed_video_roots
    if not is_allowed_video_path(path):
        roots = [str(r) for r in allowed_video_roots()]
        raise HTTPException(
            status_code=403,
            detail=(
                f"動画パスが許可ルート外です: {path}. "
                f"許可ルート: {roots}. "
                f"必要であれば SS_VIDEO_EXTRA_ROOTS に追加してください。"
            ),
        )

    # この時点で path は jail 内が保証されている → 安全に存在/種別チェック
    if not path.exists():
        raise HTTPException(status_code=404, detail="ファイルが存在しません")
    if not path.is_file():
        raise HTTPException(status_code=400, detail="ファイルパスを指定してください（ディレクトリ不可）")

    file_size = path.stat().st_size
    if file_size > _MAX_VIDEO_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"動画ファイルサイズが上限（{_MAX_VIDEO_BYTES // 1024 // 1024 // 1024} GB）を超えています: {file_size / 1024**3:.1f} GB",
        )

    job_id = uuid.uuid4().hex[:8]
    # Round 258 P1: owner を記録 (cross-team leak 防止)
    _ctx_imp = get_auth(request)
    job = _new_job(
        str(path),
        body.match_id,
        owner_user_id=_ctx_imp.user_id,
        owner_team_name=(_ctx_imp.team_name or None),
    )
    job["job_id"] = job_id
    _jobs[job_id] = job

    background_tasks.add_task(_run_pipeline, job_id)
    return {"success": True, "data": {"job_id": job_id}}


@router.get("/video_import/list")
def list_jobs(request: Request):
    """全ジョブ一覧（最新順）。Round 258 P1: cross-team 絞込 + path redact。"""
    ctx = get_auth(request)
    if ctx.is_player:
        raise HTTPException(status_code=403, detail="この操作を行う権限がありません")
    jobs = [j for j in _jobs.values() if _can_view_job(ctx, j)]
    jobs.sort(key=lambda j: j.get("started_at") or 0, reverse=True)
    return {"success": True, "data": [_redact_job(j, ctx) for j in jobs]}


@router.get("/video_import/{job_id}")
def get_job(job_id: str, request: Request):
    """ジョブ進捗取得。Round 258 P1: cross-team は 404、admin 以外は path redact。"""
    ctx = get_auth(request)
    if ctx.is_player:
        raise HTTPException(status_code=403, detail="この操作を行う権限がありません")
    job = _jobs.get(job_id)
    if not job or not _can_view_job(ctx, job):
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")
    return {"success": True, "data": _redact_job(job, ctx)}


# ─── パイプライン本体（別スレッド） ──────────────────────────────────────────

def _run_pipeline(job_id: str) -> None:
    """TrackNet → YOLO の順で解析（iGPU で実行）。"""
    job = _jobs[job_id]
    job["started_at"] = time.time()
    video_path = job["video_path"]

    try:
        # ── Phase 1: TrackNet ──────────────────────────────────────────────
        job["phase"] = Phase.TRACKNET
        job["tracknet"]["status"] = "running"
        _run_tracknet(job, video_path)

        if job["tracknet"]["status"] == "error":
            logger.warning("job %s: TrackNet failed, continuing to YOLO", job_id)

        # ── Phase 2: YOLO ─────────────────────────────────────────────────
        job["phase"] = Phase.YOLO
        job["yolo"]["status"] = "running"
        _run_yolo(job, video_path)

        job["phase"] = Phase.DONE
        job["progress"] = 1.0
        job["finished_at"] = time.time()
        logger.info("job %s done in %.1fs", job_id,
                    job["finished_at"] - job["started_at"])

    except Exception as exc:
        job["phase"] = Phase.ERROR
        job["error"] = str(exc)
        job["finished_at"] = time.time()
        logger.exception("job %s pipeline error: %s", job_id, exc)


def _run_tracknet(job: dict, video_path: str) -> None:
    """TrackNet でシャトル軌跡を解析（GPU優先）。コートキャリブレーションが設定済みなら homography でゾーンを精緻化する。"""
    import cv2
    from backend.tracknet.inference import get_inference
    from backend.routers.court_calibration import load_calibration_standalone, pixel_to_court_zone
    from backend.tracknet.zone_mapper import court_to_zone9

    # **"auto"**。以前は "openvino" を「GPU優先バックエンドを明示」として
    # 固定していたが、OpenVINO の "GPU" は **Intel の GPU** を指す。
    # 本番機 (MiniTakeuchi) は RTX 5060 Ti を積んでおり、この指定では
    # NVIDIA のカードを遊ばせたまま Intel iGPU で推論していた。
    #
    # 実測 (2026-09-20、本番機・実試合映像 1920x1080 29.97fps):
    #   openvino : 1557.9 ms / 推論   (0.6 推論/s)
    #   cuda     :   16.0 ms / 推論  (62.4 推論/s)   = **97 倍**
    #
    # `inference.py` の "auto" は ONNX CUDA を最優先に解決する
    # (docstring がこのカードを名指ししている)。CUDA が無い K10 ワーカーでは
    # 従来どおり OpenVINO へ落ちるので、固定する理由が無い。
    inf = get_inference("auto")
    if not inf.load():
        job["tracknet"]["status"] = "error"
        job["tracknet"]["error"] = inf.get_load_error() or "ロード失敗"
        return

    job["tracknet"]["backend"] = inf.backend_name()

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        job["tracknet"]["status"] = "error"
        job["tracknet"]["error"] = f"動画を開けません: {video_path}"
        return

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    fps   = cap.get(cv2.CAP_PROP_FPS) or 30.0

    # シャトル軌跡構築のサンプリング。
    #
    # C-10: 旧実装は 1fps 固定だった。シャトルの落下は 1 秒未満なので、
    # 着地窓に入るサンプルは 1 個しか無く、着地点候補が事実上すべて
    # review_required にしかならない (一貫性の下限が標本数を織り込むため)。
    #
    # 実測 (検出 0.9、LAND_SEARCH_WINDOW_SEC=3.0 の上限ケース):
    #   1fps  -> landing_window 2 個  -> 0.31  review_required
    #   5fps  -> 6 個                 -> 0.55  suggested
    #   10fps -> 12 個                -> 0.68  suggested
    #   15fps -> 18 個                -> 0.74  auto_filled
    #   30fps -> 36 個                -> 0.81  auto_filled
    # (実際の窓は次ストロークで切られるのでこれより短い = 上の値は上限)
    #
    # 既定は 15fps。**実測してから決めた** (2026-09-20、本番機・実試合映像)。
    #
    # 10fps だったのは「GPU 時間と相談して」という理由だったが、その GPU 時間は
    # 上記のとおり **Intel iGPU で推論していたせい**で、NVIDIA のカードでは
    # 話がまるで違う。60 分の試合 1 本あたりの実測投影:
    #
    #   サンプル   推論      デコード   合計      Wilson 下限 (検出 0.92)
    #   10 fps    9.6 min   6.0 min   15.6 min   0.68  suggested
    #   15 fps   14.4 min   6.0 min   20.4 min   0.74  auto_filled
    #   30 fps   28.8 min   6.0 min   34.8 min   0.81  auto_filled
    #
    # (デコードはサンプリング率によらず一定。ループは毎フレーム読むため)
    #
    # 15 を選ぶ理由: auto_filled の閾値に届く最小のサンプリング率。
    # 30 にすると GPU 時間が倍になって Wilson 下限は 0.07 しか上がらない。
    # 30 でも実時間を下回る (52 分の映像に 35 分) ので、証拠を厚くしたいなら
    # `CV_TRACKNET_SAMPLE_FPS=30` で足りる。
    _sample_fps = float(os.environ.get("CV_TRACKNET_SAMPLE_FPS", "15"))
    if _sample_fps <= 0:
        _sample_fps = 10.0
    # 元動画より速くはサンプルできない
    step_frames = max(1, int(round(fps / min(_sample_fps, fps))))
    logger.info(
        "[video_import] TrackNet サンプリング: %.1ffps 相当 (step_frames=%d, 動画 %.1ffps)",
        min(_sample_fps, fps), step_frames, fps,
    )
    track: list[dict] = []
    frame_buf: list = []
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame_buf.append(frame)
        if len(frame_buf) == 3:
            results = inf.predict_frames(frame_buf)
            if results:
                r = results[0]
                track.append({
                    "frame_idx": frame_idx,
                    "timestamp_sec": round(frame_idx / fps, 3),
                    "zone": r["zone"],
                    "confidence": r["confidence"],
                    "x_norm": r.get("x_norm"),
                    "y_norm": r.get("y_norm"),
                })
            frame_buf = frame_buf[step_frames:]   # step_frames ずつスライド
            frame_idx += step_frames

        # step_frames ごとにフレームを消費
        for _ in range(step_frames - 1):
            cap.read()
            frame_idx += 1

        job["tracknet"]["progress"] = min(frame_idx / total, 1.0)
        job["progress"] = job["tracknet"]["progress"] * 0.5  # 全体の 0-50%

    cap.release()

    # コートキャリブレーションが設定済みなら homography でゾーンを精緻化
    match_id = job.get("match_id")
    if match_id and track:
        calib = load_calibration_standalone(match_id)
        if calib and "homography" in calib:
            H = calib["homography"]
            refined = 0
            out_of_court = 0
            for pt in track:
                xn = pt.get("x_norm")
                yn = pt.get("y_norm")
                if xn is not None and yn is not None:
                    zone_info = pixel_to_court_zone(xn, yn, H)
                    # C-7: ここで `zone` を 18 ゾーン名 ("A_front_left" 等) で
                    # 上書きしていた。`zone` は zone_mapper が入れる Zone9
                    # ("BL" 等) の場所で、candidate_builder はこれを無検証で読んで
                    # `land_zone` 候補にする。`Stroke.land_zone` は VARCHAR(5) なので
                    # **PostgreSQL では 12 文字が入らず失敗し、SQLite では黙って入る**
                    # (開発では通り本番だけ落ちる、いつもの形)。
                    # Zone9 は保ったまま、コート座標系の呼称は別キーに置く。
                    # C-6: コートの外に落ちた点は 18 ゾーンに属さない。
                    # 旧実装は [0,1] にクランプしてから判定していたので、
                    # アウトや観客席の誤検出が端のゾーンとして確定していた。
                    # 外なら座標だけ残してゾーンは付けない。
                    pt["court_x"]   = zone_info["court_x"]
                    pt["court_y"]   = zone_info["court_y"]
                    pt["out_of_court"] = zone_info["out_of_court"]
                    if zone_info["out_of_court"]:
                        out_of_court += 1
                        continue
                    pt["court_zone_name"] = zone_info["zone_name"]
                    pt["zone_id"]   = zone_info["zone_id"]
                    # A-1b (2026-09-22): `zone` (Zone9) を入れられるのは
                    # **ここだけ**になった。`zone_mapper.coords_to_zone` は
                    # 画像の生座標から Zone9 を名乗るのをやめて None を返す
                    # (ネット位置も半面も遠近も画像座標には入っていない)。
                    # キャリブレーション済みのここではコート座標があるので
                    # Zone9 が決まる。未キャリブレーションの試合では
                    # `zone` は None のままで、`candidate_builder` は
                    # 着地点候補を出さない (C-11 と同じ方針)。
                    side_zone = court_to_zone9(zone_info["court_x"], zone_info["court_y"])
                    if side_zone:
                        pt["court_side"] = side_zone[0]
                        pt["zone"] = side_zone[1]
                    refined += 1
            if refined or out_of_court:
                logger.info(
                    "TrackNet zone refined by homography: match=%d points=%d out_of_court=%d",
                    match_id, refined, out_of_court,
                )

    job["tracknet"]["status"] = "done"
    job["tracknet"]["progress"] = 1.0
    job["tracknet"]["track_points"] = len(track)
    job["_tracknet_track"] = track   # YOLO 統合用に保持

    # DB 保存
    if match_id and track:
        _save_tracknet_artifact(match_id, track, inf.backend_name())


def _save_tracknet_artifact(match_id: int, track: list[dict], backend: str) -> None:
    """TrackNet シャトル軌跡を MatchCVArtifact に保存（再実行時は上書き）。

    Canonical artifact_type は tracknet_shuttle_track。
    旧実装で混在した tracknet_track も拾って上書きし、読み出し互換を保つ。
    """
    import json
    import datetime
    from backend.db.database import SessionLocal
    from backend.db.models import MatchCVArtifact

    db = SessionLocal()
    try:
        track_json   = json.dumps(track, ensure_ascii=False)
        summary_json = json.dumps({"point_count": len(track), "backend": backend}, ensure_ascii=False)

        existing = (
            db.query(MatchCVArtifact)
            .filter(
                MatchCVArtifact.match_id == match_id,
                MatchCVArtifact.artifact_type.in_(LEGACY_TRACKNET_ARTIFACT_TYPES),
            )
            .first()
        )
        if existing:
            existing.artifact_type = TRACKNET_ARTIFACT_TYPE
            existing.data         = track_json
            existing.summary      = summary_json
            existing.frame_count  = len(track)
            existing.backend_used = backend
            existing.updated_at   = datetime.datetime.utcnow()
        else:
            db.add(MatchCVArtifact(
                match_id=match_id,
                artifact_type=TRACKNET_ARTIFACT_TYPE,
                frame_count=len(track),
                backend_used=backend,
                summary=summary_json,
                data=track_json,
            ))
        db.commit()
        logger.info("TrackNet artifact saved: match=%d, points=%d", match_id, len(track))
    except Exception as exc:
        logger.warning("TrackNet artifact save failed: %s", exc)
    finally:
        db.close()


# ROI 拡張マージン（コート多角形を centroid から外側へ拡張する比率）
# 奥側・サービスライン際に立つプレイヤーがライン上・ライン外に見えることへの対策。
# 0.08 = コーナーと centroid の距離の 8% 外側まで許容。
_ROI_EXPAND_MARGIN = 0.08


def _expand_polygon(polygon: list[list[float]], margin: float = _ROI_EXPAND_MARGIN) -> list[list[float]]:
    """コート多角形を centroid から外側へ拡張する（凸多角形前提）。"""
    cx = sum(p[0] for p in polygon) / len(polygon)
    cy = sum(p[1] for p in polygon) / len(polygon)
    return [
        [cx + (px - cx) * (1 + margin), cy + (py - cy) * (1 + margin)]
        for px, py in polygon
    ]


def _run_yolo(job: dict, video_path: str) -> None:
    """YOLO でプレイヤー位置を解析（GPU優先）。コートキャリブレーションが設定済みなら ROI 外の検出を除外する。"""
    import cv2
    from backend.yolo.inference import get_yolo_inference
    from backend.routers.court_calibration import load_calibration_standalone, is_inside_court

    inf = get_yolo_inference()
    if not inf.load():
        job["yolo"]["status"] = "error"
        job["yolo"]["error"] = "モデルロード失敗"
        return

    job["yolo"]["backend"] = inf.backend_name()

    # コートキャリブレーション（ROI フィルタ用）— 未設定なら全検出を使用
    # ポリゴンは _ROI_EXPAND_MARGIN 分だけ外側に拡張する（奥側ベースライン際プレイヤー対策）
    match_id = job.get("match_id")
    roi_polygon: list[list[float]] | None = None
    if match_id:
        calib = load_calibration_standalone(match_id)
        if calib and "roi_polygon" in calib:
            roi_polygon = _expand_polygon(calib["roi_polygon"])
            logger.info(
                "YOLO ROI filter: match=%d margin=%.0f%% expanded_polygon=%s",
                match_id, _ROI_EXPAND_MARGIN * 100, roi_polygon,
            )

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        job["yolo"]["status"] = "error"
        job["yolo"]["error"] = f"動画を開けません: {video_path}"
        return

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    fps   = cap.get(cv2.CAP_PROP_FPS) or 30.0
    # 6フレームに1回 (= 10fps@60fps) でポジション解析
    sample_every = max(1, int(fps / 10))

    frames_data: list[dict] = []
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % sample_every == 0:
            players = inf.predict_frame(frame)
            # ROI フィルタ: foot_point（足元推定）がコート多角形の外側なら除外
            if roi_polygon:
                filtered = []
                for p in players:
                    fp = p.get("foot_point")
                    if fp:
                        fx, fy = fp[0], fp[1]
                    else:
                        # foot_point がなければ bbox 下辺中央を使用
                        b = p.get("bbox", [0, 0, 1, 1])
                        fx = (b[0] + b[2]) / 2
                        fy = b[3]
                    if is_inside_court(fx, fy, roi_polygon):
                        filtered.append(p)
                players = filtered
            frames_data.append({
                "frame_idx": frame_idx,
                "timestamp_sec": round(frame_idx / fps, 3),
                "players": players,
            })
        frame_idx += 1
        if frame_idx % 300 == 0:
            job["yolo"]["progress"] = min(frame_idx / total, 1.0)
            job["progress"] = 0.5 + job["yolo"]["progress"] * 0.5  # 全体の 50-100%

    cap.release()

    job["yolo"]["status"] = "done"
    job["yolo"]["progress"] = 1.0
    job["yolo"]["frame_count"] = len(frames_data)
    job["progress"] = 1.0

    # match_id が指定されていれば DB に保存
    if match_id and frames_data:
        _save_yolo_artifact(match_id, frames_data, inf.backend_name())


def _save_yolo_artifact(match_id: int, frames_data: list[dict], backend: str) -> None:
    """YOLO 検出結果を MatchCVArtifact に保存。"""
    import json
    import datetime
    from backend.db.database import SessionLocal
    from backend.db.models import MatchCVArtifact
    from backend.yolo.court_mapper import summarize_frame_positions

    db = SessionLocal()
    try:
        summary = summarize_frame_positions(frames_data)
        frames_json  = json.dumps(frames_data, ensure_ascii=False)
        summary_json = json.dumps(summary,     ensure_ascii=False)

        existing = (
            db.query(MatchCVArtifact)
            .filter(
                MatchCVArtifact.match_id == match_id,
                MatchCVArtifact.artifact_type == "yolo_player_detections",
            )
            .first()
        )
        if existing:
            existing.data        = frames_json
            existing.summary     = summary_json
            existing.frame_count = len(frames_data)
            existing.backend_used = backend
            existing.updated_at  = datetime.datetime.utcnow()
        else:
            db.add(MatchCVArtifact(
                match_id=match_id,
                artifact_type="yolo_player_detections",
                frame_count=len(frames_data),
                backend_used=backend,
                summary=summary_json,
                data=frames_json,
            ))
        db.commit()
        logger.info("YOLO artifact saved: match=%d, frames=%d", match_id, len(frames_data))
    except Exception as exc:
        logger.warning("YOLO artifact save failed: %s", exc)
    finally:
        db.close()
