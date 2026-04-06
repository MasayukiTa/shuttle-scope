"""TrackNet解析API（/api/tracknet）
バッチ処理（試合後一括解析）とシングルフレームヒントをサポート。
on/off は /api/settings で管理。モデル未導入時はエラーを返さず未導入状態を返す。
"""
import uuid
import threading
import logging
from typing import Optional
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Match, GameSet, Rally, Stroke
from backend.tracknet.inference import get_inference

logger = logging.getLogger(__name__)
router = APIRouter()

# バッチジョブ管理（インメモリ）
_jobs: dict[str, dict] = {}


class BatchJobStatus:
    PENDING  = "pending"
    RUNNING  = "running"
    COMPLETE = "complete"
    ERROR    = "error"


# ────────────────────────────────────────────────────────────────────
# /api/tracknet/status — モデルステータス確認
# ────────────────────────────────────────────────────────────────────

@router.get("/tracknet/status")
def tracknet_status():
    """TrackNetモデルの導入状況・バックエンドを返す"""
    inf = get_inference()
    return {
        "success": True,
        "data": {
            "available": inf.is_available(),
            "backend": inf.backend_name() if inf.is_available() else None,
            "loaded": inf._infer_fn is not None,
        },
    }


# ────────────────────────────────────────────────────────────────────
# /api/tracknet/batch/{match_id} — バッチ解析
# ────────────────────────────────────────────────────────────────────

class BatchRequest(BaseModel):
    backend: str = "auto"  # auto | openvino | onnx_cpu
    confidence_threshold: float = 0.5

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

    inf = get_inference(body.backend)
    if not inf.is_available():
        raise HTTPException(
            status_code=503,
            detail=(
                "TrackNetのウェイトが見つかりません。"
                "python -m backend.tracknet.setup all を実行してセットアップしてください。"
            ),
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

    background_tasks.add_task(
        _run_batch, job_id, match_id, video_path, body.confidence_threshold
    )
    return {"success": True, "data": {"job_id": job_id}}


@router.get("/tracknet/batch/{job_id}/status")
def batch_status(job_id: str):
    """バッチジョブの進捗確認"""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")
    return {"success": True, "data": job}


# ────────────────────────────────────────────────────────────────────
# /api/tracknet/frame_hint — シングルフレームヒント（P5向け実験的）
# ────────────────────────────────────────────────────────────────────

class FrameHintRequest(BaseModel):
    """Base64エンコードされた1フレーム（PNG/JPEG）を受け取る"""
    frame_b64: str          # 中央フレーム
    frame_prev_b64: str     # 1フレーム前
    frame_next_b64: str     # 1フレーム後
    confidence_threshold: float = 0.5

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

def _run_batch(job_id: str, match_id: int, video_path: str, threshold: float):
    """バッチ解析の本体。別スレッドで実行される。"""
    from backend.db.database import SessionLocal

    _jobs[job_id]["status"] = BatchJobStatus.RUNNING
    db = SessionLocal()

    try:
        inf = get_inference()
        if not inf.load():
            _jobs[job_id]["status"] = BatchJobStatus.ERROR
            _jobs[job_id]["error"] = "モデルロードに失敗しました"
            return

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

        for i, rally in enumerate(rallies):
            # タイムスタンプが設定されているラリーのみ解析
            if rally.video_timestamp_start is None:
                _jobs[job_id]["processed_rallies"] = i + 1
                _jobs[job_id]["progress"] = (i + 1) / max(len(rallies), 1)
                continue

            try:
                frames = _extract_frames(video_path, rally.video_timestamp_start, n_frames=5)
                if len(frames) < 3:
                    continue

                results = inf.predict_frames(frames)
                if not results:
                    continue

                # 最初の結果（ラリー開始付近）をhit_zoneとして使用
                first = results[0]
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
                        if not stroke.land_zone:  # 未入力のみ補完
                            stroke.land_zone = res["zone"]
                            updated += 1

                db.commit()
            except Exception as e:
                logger.warning("Rally %d analysis failed: %s", rally.id, e)

            _jobs[job_id]["processed_rallies"] = i + 1
            _jobs[job_id]["progress"] = (i + 1) / max(len(rallies), 1)
            _jobs[job_id]["updated_strokes"] = updated

        _jobs[job_id]["status"] = BatchJobStatus.COMPLETE
        _jobs[job_id]["updated_strokes"] = updated

    except Exception as e:
        logger.error("Batch job %s failed: %s", job_id, e)
        _jobs[job_id]["status"] = BatchJobStatus.ERROR
        _jobs[job_id]["error"] = str(e)
    finally:
        db.close()


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
