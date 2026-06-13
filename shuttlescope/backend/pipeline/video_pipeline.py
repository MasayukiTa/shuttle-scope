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
from backend.utils.path_jail import assert_pipeline_video_source_safe

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
        # production: env switch (SS_SHUTTLE_IMPL=wasb|tracknet) を尊重する
        if hasattr(factory, "get_shuttle_detector"):
            return factory.get_shuttle_detector()
        if hasattr(factory, "get_tracknet"):
            return factory.get_tracknet()
    except Exception as exc:
        logger.debug("factory.get_shuttle_detector 未利用 (%s) — inline mock を使用", exc)
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

    # Round 258 R18 P0 fix (R18a-3 P0-1): worker pipeline が match.video_local_path
    # を **path_jail なしで** cv2.VideoCapture / TrackNet / MediaPipe に渡していた。
    # OpenCV は http(s)/rtsp/smb/file 等を解釈するため、analyst が Match を編集して
    # 任意 URL を仕込めば、worker プロセス特権で SSRF / file:// 任意ファイル読み /
    # SMB credential relay / RTSP NAT pivot が成立していた。
    # 修正: pipeline 入口で strict 版を通し、ローカルパス + localfile:/// + server://
    # 以外を ValueError で reject する。
    try:
        assert_pipeline_video_source_safe(match.video_local_path)
    except ValueError as exc:
        logger.error("run_pipeline reject unsafe video source: match_id=%d err=%s", match_id, exc)
        raise

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

    # 2.5) A5: ラリー境界の CV 自動検出（候補のみ。既存 Rally は不変）。
    # シャトル軌跡(gated_conf)とプレイヤー位置(YOLO)が揃った後・ストローク分類前に
    # 走らせる。SS_RALLY_BOUNDARY_DETECT=0 で完全に従来挙動（呼ばない）。
    # アーティファクトが無い環境（mock 等）では best-effort で no-op。
    try:
        detect_and_store_rally_boundaries(db, match_id)
    except Exception as exc:  # 候補生成失敗で本体パイプラインは止めない
        logger.warning("rally boundary detect/store skip match_id=%d: %s", match_id, exc)

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

    # A1-1 (rule-v1): 打点近傍 PoseFrame をストローク毎に渡す。
    # この試合の PoseFrame を一度だけ取得し ts_sec 昇順に並べておく。
    pose_all = (
        db.query(PoseFrame)
        .filter(PoseFrame.match_id == match_id)
        .order_by(PoseFrame.ts_sec)
        .all()
    )
    pose_ts = [pf.ts_sec for pf in pose_all]

    for s in strokes:
        nearby_pose = _pose_frames_near(pose_all, pose_ts, getattr(s, "timestamp_sec", None))
        res = classify_stroke(s, pose_frames=nearby_pose)
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


def detect_and_store_rally_boundaries(db: Session, match_id: int) -> dict:
    """A5: 保存済み TrackNet / YOLO アーティファクトからラリー境界候補を検出し、
    `rally_boundaries` アーティファクトとして保存する（候補のみ・既存 Rally 不変）。

    SS_RALLY_BOUNDARY_DETECT=0 のときは検出も保存も行わず空 dict を返す（後方互換）。
    アーティファクトが無い / シャトル軌跡が空なら no-op（境界 0 件）。

    Returns: detect_rally_boundaries_from_cv の戻り値（保存しなかった場合は空 dict）。
    """
    from backend.cv.candidate_builder import (
        detect_rally_boundaries_from_cv,
        rally_boundary_detect_enabled,
    )

    if not rally_boundary_detect_enabled():
        return {}

    from backend.db.models import MatchCVArtifact, Recording

    def _latest(atype: str):
        return (
            db.query(MatchCVArtifact)
            .filter(
                MatchCVArtifact.match_id == match_id,
                MatchCVArtifact.artifact_type == atype,
            )
            .order_by(MatchCVArtifact.created_at.desc())
            .first()
        )

    tracknet_art = _latest("tracknet_shuttle_track")
    yolo_art = _latest("yolo_player_detections")

    shuttle_frames: list = []
    player_frames: list = []
    if tracknet_art and tracknet_art.data:
        try:
            shuttle_frames = json.loads(tracknet_art.data)
        except Exception:
            logger.warning("rally boundary: TrackNet artifact JSON 解析失敗 match_id=%d", match_id)
    if yolo_art and yolo_art.data:
        try:
            player_frames = json.loads(yolo_art.data)
        except Exception:
            logger.warning("rally boundary: YOLO artifact JSON 解析失敗 match_id=%d", match_id)

    if not shuttle_frames:
        # シャトル軌跡が無ければ検出不能 → no-op
        return {}

    # FPS 解決（Recording.fps 優先・既定 60）
    fps = 60.0
    try:
        rec = (
            db.query(Recording)
            .filter(Recording.match_id == match_id, Recording.fps != None)  # noqa: E711
            .order_by(Recording.branch_no)
            .first()
        )
        if rec and rec.fps and rec.fps > 0:
            fps = float(rec.fps)
    except Exception:
        pass

    result = detect_rally_boundaries_from_cv(
        match_id=match_id,
        shuttle_frames=shuttle_frames,
        player_frames=player_frames,
        fps=fps,
    )

    boundaries = result.get("boundaries", [])
    data_json = json.dumps(result, ensure_ascii=False)
    summary_json = json.dumps({
        "boundary_count": result.get("boundary_count", len(boundaries)),
        "fps":            result.get("fps"),
    }, ensure_ascii=False)

    existing = _latest("rally_boundaries")
    if existing:
        existing.data = data_json
        existing.summary = summary_json
        existing.frame_count = len(boundaries)
        existing.updated_at = datetime.utcnow()
    else:
        db.add(MatchCVArtifact(
            match_id=match_id,
            artifact_type="rally_boundaries",
            frame_count=len(boundaries),
            summary=summary_json,
            data=data_json,
        ))
    db.flush()
    logger.info(
        "rally boundary detect match_id=%d boundaries=%d fps=%.1f",
        match_id, len(boundaries), fps,
    )
    return result


def _pose_frames_near(
    pose_all: list,
    pose_ts: list[float],
    stroke_ts: Optional[float],
    window_sec: float = 0.4,
) -> list:
    """打点タイムスタンプ ±window_sec 内の PoseFrame を返す（A1-1）。

    pose_ts は ts_sec 昇順前提。stroke_ts が無い / 近傍が無ければ空リスト
    （classify_stroke 側で rule-v0 にフォールバック）。
    """
    if stroke_ts is None or not pose_all:
        return []
    import bisect
    lo = bisect.bisect_left(pose_ts, stroke_ts - window_sec)
    hi = bisect.bisect_right(pose_ts, stroke_ts + window_sec)
    return pose_all[lo:hi]


def execute_job(db: Session, job: AnalysisJob) -> None:
    """AnalysisJob を実行し、ステータスを更新する。

    job_type による dispatch:
      - "video_variant": post-process で 1080p / 720p variant を生成
                         (不要 upscale は service 側で自動 skip)
      - "full_pipeline" / その他: 既定の解析パイプライン
    """
    job.status = "running"
    job.started_at = datetime.utcnow()
    job.worker_host = socket.gethostname()
    db.flush()
    try:
        if (job.job_type or "").strip() == "video_variant":
            counts = _run_video_variant_job(db, job.match_id)
        else:
            counts = run_pipeline(db, job.match_id, use_gpu=False)
        job.progress = 1.0
        job.status = "done"
        job.finished_at = datetime.utcnow()
        # エラーをクリア
        job.error = None
        logger.info("job done id=%d type=%s counts=%s", job.id, job.job_type, counts)
    except Exception as exc:  # pragma: no cover - 防御的
        logger.exception("job failed id=%d type=%s: %s", job.id, job.job_type, exc)
        job.status = "failed"
        job.error = str(exc)[:1000]
        job.finished_at = datetime.utcnow()
    db.flush()


def _run_video_variant_job(db: Session, match_id: int) -> dict:
    """video_variant ジョブの本体。

    Match.video_local_path が server:// の場合のみ処理 (= サーバ保管動画のみ)。
    localfile:/// やアーカイブ済みアクセス経路は対象外 (= 旧 / 外部動画は variant
    を作らない)。
    """
    from backend.db.models import Match
    from backend.services.video_variants import generate_all_for_source
    from backend.routers.uploads import UPLOAD_DIR
    from backend.utils.safe_path import safe_path

    m = db.get(Match, match_id)
    if m is None:
        raise RuntimeError(f"match {match_id} not found")
    vlp = m.video_local_path or ""
    if not vlp.startswith("server://"):
        return {"skipped": "video_local_path not server://"}
    rest = vlp[len("server://"):]
    src = safe_path(UPLOAD_DIR, rest)
    if src is None or not src.exists():
        raise RuntimeError(f"source file missing: {rest}")
    # upload_id は server://{upload_id}{ext} の {upload_id} 部分。拡張子を除いた basename。
    upload_id = rest.rsplit(".", 1)[0] if "." in rest else rest
    result = generate_all_for_source(src, UPLOAD_DIR, upload_id)
    return {"variants": result}
