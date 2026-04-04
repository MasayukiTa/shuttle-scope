"""サンプルサイズに基づく信頼度チェックユーティリティ"""


def check_confidence(analysis_type: str, sample_size: int) -> dict:
    """サンプルサイズに応じた信頼度を返す"""
    minimums = {
        "descriptive_basic": 10,
        "heatmap": 50,
        "shot_transition": 100,
        "win_loss_comparison": 5,
        "opponent_analysis": 30,
        "pressure_performance": 15,
        "rally_vs_winrate": 20,
        "temporal": 30,
    }
    minimum = minimums.get(analysis_type, 20)
    if sample_size < minimum // 2:
        level, stars = "low", "★☆☆"
        label = "参考値（データ蓄積中）"
        warning = f"解析には{minimum}件以上推奨（現在{sample_size}件）"
    elif sample_size < minimum:
        level, stars = "low", "★☆☆"
        label = "参考値（データ蓄積中）"
        warning = f"サンプルが少ない可能性（推奨{minimum}件）"
    elif sample_size < minimum * 5:
        level, stars = "medium", "★★☆"
        label = "中程度（解釈に注意）"
        warning = None
    else:
        level, stars = "high", "★★★"
        label = "高信頼（実用レベル）"
        warning = None
    return {
        "level": level,
        "stars": stars,
        "label": label,
        "warning": warning,
    }
