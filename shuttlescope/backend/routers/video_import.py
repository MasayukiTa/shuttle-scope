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


def _new_job(video_path: str, match_id: Optional[int] = None) -> dict:
    return {
        "job_id": None,           # 後で設定
        "video_path": video_path,
        "match_id": match_id,
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
    job = _new_job(str(path), body.match_id)
    job["job_id"] = job_id
    _jobs[job_id] = job

    background_tasks.add_task(_run_pipeline, job_id)
    return {"success": True, "data": {"job_id": job_id}}


@router.get("/video_import/list")
def list_jobs(request: Request):
    """全ジョブ一覧（最新順）"""
    ctx = get_auth(request)
    if ctx.is_player:
        raise HTTPException(status_code=403, detail="この操作を行う権限がありません")
    jobs = sorted(_jobs.values(), key=lambda j: j.get("started_at") or 0, reverse=True)
    return {"success": True, "data": jobs}


@router.get("/video_import/{job_id}")
def get_job(job_id: str, request: Request):
    """ジョブ進捗取得"""
    ctx = get_auth(request)
    if ctx.is_player:
        raise HTTPException(status_code=403, detail="この操作を行う権限がありません")
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")
    return {"success": True, "data": job}


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

    inf = get_inference("openvino")   # GPU優先バックエンドを明示
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

    # 1fps サンプリングでシャトル軌跡構築
    step_frames = max(1, int(fps))
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
            for pt in track:
                xn = pt.get("x_norm")
                yn = pt.get("y_norm")
                if xn is not None and yn is not None:
                    zone_info = pixel_to_court_zone(xn, yn, H)
                    pt["zone"]      = zone_info["zone_name"]   # 既存 zone を上書き
                    pt["court_x"]   = zone_info["court_x"]
                    pt["court_y"]   = zone_info["court_y"]
                    pt["zone_id"]   = zone_info["zone_id"]
                    refined += 1
            if refined:
                logger.info("TrackNet zone refined by homography: match=%d points=%d", match_id, refined)

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
