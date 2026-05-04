"""統計量算出モジュール（K10 CPU ワーカー向け）。

cluster/tasks.py から呼ばれる薄いエントリポイント。
実ロジックは backend/analysis/ 以下の既存エンドポイントを再利用する。
"""
from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def run_statistics(video_id: int, **kwargs: Any) -> Dict[str, Any]:
    """match_id に対して統計量を算出する。

    Args:
        video_id: 解析対象の match_id（video_id と同義）

    Returns:
        {
            "status": "ok" | "skipped" | "error",
            "match_id": int,
            "stroke_count": int,
            "summary": dict,
        }
    """
    try:
        from backend.db.database import SessionLocal
        from backend.db.models import Match, Rally, Stroke

        db = SessionLocal()
        try:
            match = db.query(Match).filter(Match.id == video_id).first()
            if match is None:
                return {"status": "skipped", "reason": f"match_id={video_id} が見つかりません"}

            stroke_count = (
                db.query(Stroke)
                .join(Rally, Rally.id == Stroke.rally_id)
                .join(Match, Match.id == Rally.match_id if hasattr(Rally, "match_id") else Rally.set_id)
                .count()
            )

            logger.info("[statistics] match_id=%d stroke_count=%d", video_id, stroke_count)
            return {
                "status": "ok",
                "match_id": video_id,
                "stroke_count": stroke_count,
                "summary": {},  # 詳細集計は analysis ルーターに委ねる
            }
        finally:
            db.close()
    except Exception as exc:
        logger.exception("[statistics] 算出失敗: %s", exc)
        return {"status": "error", "error": str(exc)}
