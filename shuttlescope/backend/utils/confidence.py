"""
サンプルサイズに基づく信頼度チェックユーティリティ

confidence-aware output control:
  解析結果の出力内容を confidence レベルで制御する。
  insufficient: 結論を出さない
  low:          傾向のみ
  medium:       傾向 + 参考示唆
  high:         具体的比較・提案まで出す
"""
from __future__ import annotations
import math
from typing import Any, Optional


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson スコア法による比率の信頼区間。

    Returns (ci_low, ci_high) in [0, 1].

    既に `backend.analysis.epv_state_model.wilson_ci` に同じ実装があるが、
    700e3dd 以降 `markov.py` が `backend.utils.confidence` から import している
    ため、共通ユーティリティ層 (本ファイル) を canonical として一元化する。
    epv_state_model 側は import alias として残しても良い。
    """
    if n == 0:
        return (0.0, 1.0)
    p_hat = successes / n
    denominator = 1 + z * z / n
    center = (p_hat + z * z / (2 * n)) / denominator
    margin = (z * math.sqrt(p_hat * (1 - p_hat) / n + z * z / (4 * n * n))) / denominator
    return (round(max(0.0, center - margin), 4), round(min(1.0, center + margin), 4))


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


# ── confidence-aware output control ────────────────────────────────────────

# tier → 出力許可フラグ
_OUTPUT_FLAGS: dict[str, dict[str, bool]] = {
    "insufficient": {
        "show_conclusion":  False,
        "show_comparison":  False,
        "show_suggestion":  False,
        "show_trend":       False,
    },
    "low": {
        "show_conclusion":  False,
        "show_comparison":  False,
        "show_suggestion":  False,
        "show_trend":       True,   # 傾向のみ
    },
    "medium": {
        "show_conclusion":  True,
        "show_comparison":  True,
        "show_suggestion":  True,   # 参考示唆まで
        "show_trend":       True,
    },
    "high": {
        "show_conclusion":  True,
        "show_comparison":  True,
        "show_suggestion":  True,
        "show_trend":       True,
    },
}


def output_flags(confidence_level: str) -> dict[str, bool]:
    """
    confidence level に応じた出力制御フラグを返す。

    Parameters:
        confidence_level: 'insufficient' / 'low' / 'medium' / 'high'

    Returns:
        {
          'show_conclusion': bool,
          'show_comparison': bool,
          'show_suggestion': bool,
          'show_trend':      bool,
        }
    """
    return _OUTPUT_FLAGS.get(confidence_level, _OUTPUT_FLAGS["low"]).copy()


def gate_field(
    value: Any,
    confidence_level: str,
    flag: str,
    placeholder: Any = None,
) -> Any:
    """
    confidence フラグに応じて value または placeholder を返す。

    使用例:
        result['top_shot'] = gate_field(computed_top, conf_level, 'show_conclusion')
    """
    flags = output_flags(confidence_level)
    return value if flags.get(flag, False) else placeholder


def build_confidence_aware_response(
    data: dict,
    confidence_level: str,
    *,
    conclusion_keys: Optional[list[str]] = None,
    comparison_keys: Optional[list[str]] = None,
    suggestion_keys: Optional[list[str]] = None,
    trend_keys: Optional[list[str]] = None,
) -> dict:
    """
    data の各フィールドを confidence_level に応じてフィルタリングする。

    指定されたキーグループに属するフィールドは、
    対応する出力フラグが False の場合に None に置き換えられる。

    Parameters:
        data:             元のレスポンス dict
        confidence_level: 'insufficient'/'low'/'medium'/'high'
        conclusion_keys:  show_conclusion が False の場合に None にするキー
        comparison_keys:  show_comparison が False の場合に None にするキー
        suggestion_keys:  show_suggestion が False の場合に None にするキー
        trend_keys:       show_trend が False の場合に None にするキー

    Returns:
        フィルタリング後の dict（元の dict は変更しない）
    """
    flags = output_flags(confidence_level)
    result = dict(data)

    _apply_gate(result, conclusion_keys, flags["show_conclusion"])
    _apply_gate(result, comparison_keys, flags["show_comparison"])
    _apply_gate(result, suggestion_keys, flags["show_suggestion"])
    _apply_gate(result, trend_keys, flags["show_trend"])

    return result


def _apply_gate(d: dict, keys: Optional[list[str]], allowed: bool) -> None:
    if not allowed and keys:
        for k in keys:
            if k in d:
                d[k] = None


def insufficient_response(analysis_type: str, sample_size: int) -> dict:
    """
    サンプル不足時の標準レスポンスを返す。
    エンドポイントの早期リターン用。
    """
    return {
        "success": True,
        "data": None,
        "confidence": {
            "level": "insufficient",
            "stars": "—",
            "label": "データ不足",
            "warning": f"{analysis_type} には十分なデータがありません（現在{sample_size}件）",
        },
    }
