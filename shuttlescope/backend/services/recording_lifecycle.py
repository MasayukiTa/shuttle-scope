"""Recording branch lifecycle helpers.

A Match may own multiple camera recordings. Branch allocation must be serialized
per match in production so concurrent camera finalization cannot allocate the
same branch_no.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from backend.db.models import LiveSource, Match, Recording, SessionParticipant
from backend.utils.video_token import new_token


_DEVICE_SOURCE_FALLBACK = {
    "iphone": "iphone_webrtc",
    "ipad": "iphone_webrtc",
    "usb_camera": "usb_camera",
    "builtin_camera": "builtin_camera",
    "pc": "pc_local",
}


def lock_match_for_recording(db: Session, match_id: int) -> Optional[Match]:
    """Return the Match while taking a row lock where the DB supports it."""
    return (
        db.query(Match)
        .filter(Match.id == match_id)
        .with_for_update()
        .one_or_none()
    )


def next_recording_branch_no(db: Session, match_id: int) -> int:
    row = (
        db.query(Recording.branch_no)
        .filter(Recording.match_id == match_id)
        .order_by(desc(Recording.branch_no))
        .first()
    )
    return (int(row[0]) if row else 0) + 1


def participant_source_kind(
    db: Session,
    participant_id: int,
) -> tuple[Optional[str], Optional[str]]:
    """Resolve a camera source kind and human label for a participant."""
    participant = db.get(SessionParticipant, participant_id)
    if participant is None:
        return None, None

    live_source = (
        db.query(LiveSource)
        .filter(LiveSource.participant_id == participant_id)
        .order_by(desc(LiveSource.id))
        .first()
    )
    if live_source is not None and live_source.source_kind:
        source_kind = live_source.source_kind
    else:
        source_kind = _DEVICE_SOURCE_FALLBACK.get(participant.device_type or "")

    return source_kind, participant.device_name


def create_camera_recording(
    db: Session,
    *,
    match: Match,
    participant_id: int,
    video_local_path: str,
    started_at: Optional[datetime],
    ended_at: datetime,
    streaming: bool,
) -> Recording:
    """Create one branch entry for a finalized camera upload.

    The caller must obtain lock_match_for_recording before calling this helper.
    A flush assigns Recording.id but commit remains with the caller so upload
    state, recording branch, artifact, and optional primary-video update remain
    one transaction.
    """
    source_kind, label = participant_source_kind(db, participant_id)
    rec = Recording(
        match_id=match.id,
        branch_no=next_recording_branch_no(db, match.id),
        kind="live" if streaming else "upload",
        source_kind=source_kind,
        status="ready",
        video_local_path=video_local_path,
        video_token=new_token(),
        label=label,
        started_at=started_at,
        ended_at=ended_at,
    )
    db.add(rec)
    db.flush()
    return rec
