"""自動ミス検出（proxy 実装）。

Rally.end_type が unforced_error / forced_error のとき、ラリー末尾のストロークを
ミスとみなし、候補を返す。シャトル軌跡（ShuttleTrack）が利用可能であれば
軌跡終端座標でミス位置を補強する。
"""
from __future__ import annotations

from typing import Iterator

from sqlalchemy.orm import Session

from backend.db.models import Rally, Stroke, GameSet, ShuttleTrack


MISS_END_TYPES = {"unforced_error", "forced_error"}


def iter_auto_miss_candidates(db: Session, match_id: int) -> Iterator[dict]:
    """自動ミス検出の候補を列挙する。

    既存の手動アノテーション（end_type）を起点とする proxy 実装のため、
    ShuttleTrack が空でも動作する。
    """
    rows = (
        db.query(Rally, Stroke)
        .join(GameSet, GameSet.id == Rally.set_id)
        .join(Stroke, Stroke.rally_id == Rally.id)
        .filter(GameSet.match_id == match_id)
        .filter(Rally.end_type.in_(tuple(MISS_END_TYPES)))
        .all()
    )
    # ラリー末尾ストロークのみ採用
    last_by_rally: dict[int, tuple[Rally, Stroke]] = {}
    for rally, stroke in rows:
        cur = last_by_rally.get(rally.id)
        if cur is None or stroke.stroke_num > cur[1].stroke_num:
            last_by_rally[rally.id] = (rally, stroke)

    for rally, stroke in last_by_rally.values():
        # 軌跡終端座標（任意）
        endpoint = None
        if stroke.timestamp_sec is not None:
            track = (
                db.query(ShuttleTrack)
                .filter(ShuttleTrack.match_id == match_id)
                .order_by(ShuttleTrack.frame_index.desc())
                .first()
            )
            if track is not None:
                endpoint = {"x": track.x, "y": track.y, "frame": track.frame_index}

        yield {
            "rally_id": rally.id,
            "stroke_id": stroke.id,
            "end_type": rally.end_type,
            "endpoint": endpoint,
            "source": "auto",
        }
