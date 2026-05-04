"""動画解析パイプライン本体。

Phase A が提供する `backend/cv/factory.py` の `get_tracknet()` / `get_pose()` 経由で
モデルを取得する。factory 未配置なら mock にフォールバックする（CUDA/torch を直接
import しない）。i5-1235U / CUDA 無しでも動作すること。
"""
from __future__ import annotations

import json
import logging
import os
import socket
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.db.models import (
    AnalysisJob,
    CenterOfGravity,
    GameSet,
    Match,
    PoseFrame,
    Rally,
    ShotInference,
    ShuttleTrack,
    Stroke,
)
from backend.cv.gravity import compute_cog
from backend.cv.shot_classifier import classify_stroke
from backend.pipeline.pose_storage import encode_landmarks

logger = logging.getLogger(__name__)


# ─── Factory フォールバック ──────────────────────────────────────────────────

class _InlineMockTrackNet:
    """factory 未配置時のフォールバック mock（base 未 import）。"""

    def run(self, video_path: str):
        out = []
        for i in range(30):
            out.append(type("S", (), {
                "frame": i, "ts_sec": i / 30.0,
                "x": 640.0, "y": 360.0, "confidence": 0.7,
            })())
        return out


class _InlineMockPose:
    def run(self, video_path: str):
        out = []
        for i in range(30):
            for side in ("a", "b"):
                lm = [
                    [0.50, 0.30, 1.0],
                    [0.50, 0.55, 1.0],
                    [0.45, 0.90, 1.0],
                    [0.55, 0.90, 1.0],
                ]
                out.append(type("P", (), {
                    "frame": i, "ts_sec": i / 30.0, "side": side, "landmarks": lm,
                })())
        return out


def _get_tracknet():
    # SS_CV_MOCK=1 のときは必ず mock（factory 経由で mock 返却される設計）
    if os.environ.get("SS_CV_MOCK") == "1":
        try:
            from backend.cv.tracknet_mock import MockTrackNet
            return MockTrackNet()
        except Exception:
            return _InlineMockTrackNet()
    try:
        from backend.cv import factory  # type: ignore
        if hasattr(factory, "get_tracknet"):
            return factory.get_tracknet()
    except Exception as exc:
        logger.debug("factory.get_tracknet 未利用 (%s) — inline mock を使用", exc)
    return _InlineMockTrackNet()


def _get_pose():
    if os.environ.get("SS_CV_MOCK") == "1":
        try:
            from backend.cv.pose_mock import MockPose
            return MockPose()
        except Exception:
            return _InlineMockPose()
    try:
        from backend.cv import factory  # type: ignore
        if hasattr(factory, "get_pose"):
            return factory.get_pose()
    except Exception as exc:
        logger.debug("factory.get_pose 未利用 (%s) — inline mock を使用", exc)
    return _InlineMockPose()


def _side_to_role(side: str) -> str:
    """base.PoseSample.side ("a"/"b") を DB の player_a/player_b に正規化。"""
    if side in ("a", "player_a"):
        return "player_a"
    if side in ("b", "player_b"):
        return "player_b"
    return side or "player_a"


# ─── パイプライン本体 ───────────────────────────────────────────────────────

def run_pipeline(db: Session, match_id: int, *, use_gpu: bool = False) -> dict:
    """単一試合に対してフル解析パイプラインを実行し、DB に結果を書き込む。

    Returns: 書き込み行数の集計。
    """
    match = db.get(Match, match_id)
    if match is None:
        raise ValueError(f"match_id={match_id} が見つかりません")

    is_mock = os.environ.get("SS_CV_MOCK") == "1"
    logger.info("run_pipeline start match_id=%d use_gpu=%s mock=%s", match_id, use_gpu, is_mock)

    tracknet = _get_tracknet()
    pose = _get_pose()

    video_path = match.video_local_path or match.video_url or f"match-{match.id}"

    # 既存行を除去（冪等）
    db.query(ShuttleTrack).filter(ShuttleTrack.match_id == match_id).delete()
    db.query(PoseFrame).filter(PoseFrame.match_id == match_id).delete()
    db.query(CenterOfGravity).filter(CenterOfGravity.match_id == match_id).delete()

    # 1) TrackNet: シャトル軌跡
    track_rows = list(tracknet.run(video_path))
    for t in track_rows:
        db.add(ShuttleTrack(
            match_id=match_id,
            frame_index=int(getattr(t, "frame", 0)),
            ts_sec=float(getattr(t, "ts_sec", 0.0)),
            x=getattr(t, "x", None),
            y=getattr(t, "y", None),
            confidence=float(getattr(t, "confidence", 0.0)),
        ))

    # 2) Pose: 骨格 + 重心
    pose_rows = list(pose.run(video_path))
    for p in pose_rows:
        lm = getattr(p, "landmarks", []) or []
        side = _side_to_role(getattr(p, "side", "a"))
        frame_idx = int(getattr(p, "frame", 0))
        ts = float(getattr(p, "ts_sec", 0.0))
        db.add(PoseFrame(
            match_id=match_id,
            frame_index=frame_idx,
            ts_sec=ts,
            side=side,
            # gzip 圧縮した JSON バイト列を格納 (helper 経由、後方互換の decode あり)
            landmarks_json=encode_landmarks(lm),
        ))
        cog = compute_cog(lm)
        db.add(CenterOfGravity(
            match_id=match_id,
            frame_index=frame_idx,
            side=side,
            left_pct=cog["left_pct"],
            right_pct=cog["right_pct"],
            forward_lean=cog["forward_lean"],
            stability_score=cog["stability_score"],
        ))

    # 3) ShotInference: ストロークを分類
    strokes = (
        db.query(Stroke)
        .join(Rally, Rally.id == Stroke.rally_id)
        .join(GameSet, GameSet.id == Rally.set_id)
        .filter(GameSet.match_id == match_id)
        .all()
    )
    # 既存推論を置換（冪等）
    if strokes:
        stroke_ids = [s.id for s in strokes]
        db.query(ShotInference).filter(ShotInference.stroke_id.in_(stroke_ids)).delete(
            synchronize_session=False
        )
    for s in strokes:
        res = classify_stroke(s)
        db.add(ShotInference(
            stroke_id=s.id,
            shot_type=res["shot_type"],
            confidence=res["confidence"],
            model_version=res["model_version"],
        ))

    # 4) miss_detector は読み取り専用（expert.py / pipeline レスポンスで参照）
    # ここでは DB には書かない（source="auto" として list_clips 側で合流させる）

    db.flush()
    counts = {
        "shuttle_tracks": len(track_rows),
        "pose_frames": len(pose_rows),
        "center_of_gravity": len(pose_rows),
        "shot_inferences": len(strokes),
    }
    logger.info("run_pipeline done match_id=%d counts=%s", match_id, counts)
    return counts


def execute_job(db: Session, job: AnalysisJob) -> None:
    """AnalysisJob を実行し、ステータスを更新する。"""
    job.status = "running"
    job.started_at = datetime.utcnow()
    job.worker_host = socket.gethostname()
    db.flush()
    try:
        counts = run_pipeline(db, job.match_id, use_gpu=False)
        job.progress = 1.0
        job.status = "done"
        job.finished_at = datetime.utcnow()
        # エラーをクリア
        job.error = None
        logger.info("job done id=%d counts=%s", job.id, counts)
    except Exception as exc:  # pragma: no cover - 防御的
        logger.exception("job failed id=%d: %s", job.id, exc)
        job.status = "failed"
        job.error = str(exc)[:1000]
        job.finished_at = datetime.utcnow()
    db.flush()
