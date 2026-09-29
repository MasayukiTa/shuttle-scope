"""動画ソースの置換に伴う recoverable CV 成果物のライフサイクル管理。"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from backend.db.models import MatchCVArtifact

logger = logging.getLogger(__name__)


def effective_video_source(
    video_local_path: Optional[str],
    video_url: Optional[str],
) -> tuple[str, str] | None:
    """解析コードと同じ優先順位で、現在の有効動画ソースを返す。"""
    local = (video_local_path or "").strip()
    if local:
        return ("local", local)
    url = (video_url or "").strip()
    if url:
        return ("url", url)
    return None


def invalidate_match_cv_artifacts_if_source_replaced(
    db: Session,
    match_id: int,
    *,
    old_video_local_path: Optional[str],
    old_video_url: Optional[str],
    new_video_local_path: Optional[str],
    new_video_url: Optional[str],
) -> int:
    """有効動画ソースが置換された場合だけ MatchCVArtifact を全削除する。

    MatchCVArtifact は court calibration / YOLO / TrackNet / alignment 等の
    動画座標に依存する recoverable 成果物だけを保持する。人手 annotation truth
    (Rally / Stroke) はここでは削除しない。

    commit は呼び出し側に任せ、動画参照の更新と同一トランザクションにする。
    """
    old_source = effective_video_source(old_video_local_path, old_video_url)
    new_source = effective_video_source(new_video_local_path, new_video_url)
    if old_source == new_source:
        return 0

    deleted = (
        db.query(MatchCVArtifact)
        .filter(MatchCVArtifact.match_id == match_id)
        .delete(synchronize_session=False)
    )
    if deleted:
        logger.info(
            "invalidated %d CV artifact(s) for match=%s after video source replacement (%s -> %s)",
            deleted,
            match_id,
            old_source[0] if old_source else "none",
            new_source[0] if new_source else "none",
        )
    return int(deleted or 0)
