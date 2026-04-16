"""重心位置算出モジュール（K10 CPU ワーカー向け）。

cluster/tasks.py から呼ばれる薄いエントリポイント。
`backend/cv/gravity.py` の既存実装に委譲する。
"""
from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def calc_center_of_gravity(video_id: int, **kwargs: Any) -> Dict[str, Any]:
    """match_id に対して重心位置を算出する。

    Args:
        video_id: 解析対象の match_id

    Returns:
        {
            "status": "ok" | "skipped" | "error",
            "match_id": int,
            "frame_count": int,
        }
    """
    try:
        # gravity.py の公開 API を呼ぶ（実装が整っていれば）
        try:
            from backend.cv.gravity import calc_gravity  # type: ignore[import]

            result = calc_gravity(video_id)
            logger.info("[cog] match_id=%d 完了", video_id)
            return {"status": "ok", "match_id": video_id, **result}
        except (ImportError, AttributeError):
            # gravity.py の公開 API がまだ整備されていない場合
            logger.info("[cog] gravity.calc_gravity 未実装のためスキップ (match_id=%d)", video_id)
            return {"status": "skipped", "reason": "gravity.calc_gravity not implemented"}
    except Exception as exc:
        logger.exception("[cog] 算出失敗: %s", exc)
        return {"status": "error", "error": str(exc)}
