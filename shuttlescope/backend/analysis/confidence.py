"""信頼度スコアリング（SPEC.md §6.3）"""
from backend.config import CONFIDENCE_LEVELS


def calc_confidence(n_strokes: int) -> dict:
    """
    全解析で必ず呼び出す共通関数。
    ストローク数に基づいて信頼度を算出する。
    """
    if n_strokes < 500:
        return {
            "level": "low",
            "stars": "★☆☆",
            "label": "参考値（データ蓄積中）",
            "warning": "サンプルが少なく推定精度が低い。傾向参考程度に留めること。",
        }
    elif n_strokes < 2000:
        return {
            "level": "medium",
            "stars": "★★☆",
            "label": "中程度（解釈に注意）",
            "warning": "推定値には相当の不確実性がある。信頼区間を必ず確認すること。",
        }
    else:
        return {
            "level": "high",
            "stars": "★★★",
            "label": "高信頼（実用レベル）",
            "warning": None,
        }
