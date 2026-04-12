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
DEFAULT_SAMPLE_EVERY_N_FRAMES: int = 30  # 30fps なら 1fps 相当


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
    roi_rect: Optional[RoiRectModel] = None   # 解析対象エリア（未指定なら全体）
    resume: bool = False                       # True: 既存フレームをスキップして途中再開
    prev_roi: Optional[RoiRectModel] = None   # 直前の ROI（ROI 拡張時の差分処理用）


@router.post("/yolo/batch/{match_id}")
def start_yolo_batch(
    match_id: int,
    body: YoloBatchRequest,
    background_tasks: BackgroundTasks,
    sample_every_n: int = DEFAULT_SAMPLE_EVERY_N_FRAMES,
    db: Session = Depends(get_db),
):
    """試合動画全体を YOLO でバッチ検出開始（非同期）。

    sample_every_n: 何フレームごとに検出するか（デフォルト30 = 1fps@30fps）
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

    roi = body.roi_rect.model_dump() if body.roi_rect else None
    prev_roi = body.prev_roi.model_dump() if body.prev_roi else None
    background_tasks.add_task(
        _run_batch, job_id, match_id, video_path, sample_every_n, roi, body.resume, prev_roi
    )
    return {"success": True, "data": {"job_id": job_id}}


@router.get("/yolo/batch/{job_id}/status")
def yolo_batch_status(job_id: str):
    """バッチジョブの進捗確認"""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")
    return {"success": True, "data": job}


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
        existing_by_idx: dict[int, dict] = {}
        if resume or prev_roi:
            art = (
                db.query(MatchCVArtifact)
                .filter(
                    MatchCVArtifact.match_id == match_id,
                    MatchCVArtifact.artifact_type == "yolo_player_detections",
                )
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

        frames_data: list[dict] = []
        detected_total = 0
        processed = 0
        frame_idx = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % sample_every_n == 0:
                ts_sec = frame_idx / fps

                if frame_idx in existing_by_idx:
                    if delta_rois:
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
                    else:
                        # resume=True: 既存データをそのまま再利用（再処理なし）
                        frames_data.append(existing_by_idx[frame_idx])
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

                detected_total += len([p for p in frames_data[-1]["players"] if "player" in p.get("label", "")])
                processed += 1
                _jobs[job_id]["processed_frames"] = processed
                _jobs[job_id]["progress"] = round(processed / max(sample_count, 1), 3)
                _jobs[job_id]["detected_players"] = detected_total

            frame_idx += 1

        cap.release()

        # コート位置サマリー計算
        summary = summarize_frame_positions(frames_data)

        # DB に保存
        frames_json = json.dumps(frames_data, ensure_ascii=False)
        summary_json = json.dumps(summary, ensure_ascii=False)

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
            existing.summary = summary_json
            existing.frame_count = len(frames_data)
            existing.backend_used = inf.backend_name()
            existing.updated_at = __import__("datetime").datetime.utcnow()
        else:
            db.add(MatchCVArtifact(
                match_id=match_id,
                artifact_type="yolo_player_detections",
                frame_count=len(frames_data),
                backend_used=inf.backend_name(),
                summary=summary_json,
                data=frames_json,
            ))
        db.commit()

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


# ─── ダブルス CV 解析 ─────────────────────────────────────────────────────────

@router.get("/yolo/doubles_analysis/{match_id}")
def yolo_doubles_analysis(match_id: int, db: Session = Depends(get_db)):
    """YOLO 検出を使ったダブルス・ポジション解析を返す。

    YOLO バッチ検出（/api/yolo/batch/{match_id}）が完了している必要がある。
    アライメント（/api/yolo/align/{match_id}）が完了していると更に詳細なヒッター情報が得られる。
    """
    result = compute_doubles_cv_analytics(match_id, db)
    return {"success": True, "data": result}
