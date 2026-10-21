"""信頼度スコアリング（SPEC.md §6.3）

判定の実装は `backend.utils.confidence.check_confidence` の 1 つだけ。
ここは打球数を渡す呼び出し向けの薄い入口で、閾値は持たない。
"""
from backend.utils.confidence import check_confidence


def calc_confidence(n_strokes: int) -> dict:
    """打球数に基づく信頼度 (500 未満=参考値 / 2000 未満=中程度 / それ以上=高信頼)。"""
    return check_confidence("stroke_count", n_strokes)
