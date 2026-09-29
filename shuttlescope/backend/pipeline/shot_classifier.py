"""ショット分類モジュール（K10 CPU ワーカー向け）。

cluster/tasks.py から呼ばれる薄いエントリポイント。
`backend/cv/shot_classifier.py` の既存実装に委譲する。
"""
from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def classify_shots(video_id: int, **kwargs: Any) -> Dict[str, Any]:
    """match_id に対してショット分類を実行する。

    Args:
        video_id: 解析対象の match_id

    Returns:
        {
            "status": "ok" | "skipped" | "error",
            "match_id": int,
            "classified_count": int,
        }
    """
    try:
        try:
            from backend.cv.shot_classifier import classify_match_shots  # type: ignore[import]

            result = classify_match_shots(video_id)
            logger.info("[shot_classifier] match_id=%d 完了", video_id)
            return {"status": "ok", "match_id": video_id, **result}
        except (ImportError, AttributeError):
            logger.info(
                "[shot_classifier] shot_classifier.classify_match_shots 未実装のためスキップ"
                " (match_id=%d)", video_id
            )
            return {"status": "skipped", "reason": "shot_classifier.classify_match_shots not implemented"}
    except Exception as exc:
        logger.exception("[shot_classifier] 分類失敗: %s", exc)
        return {"status": "error", "error": str(exc)}
