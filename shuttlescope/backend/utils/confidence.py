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


# 勝ち負けの「判定」「方向」「注意」「提案」など、言い切りに近い表示を出してよい最低試合数。
# 1〜4 試合では Laplace 平滑化した率が 0.33〜0.83 の間を飛ぶだけで、方向を読む根拠にならない
# (n=1 の 1 勝で直近 1.0 / 全体 0.667 となり「上向き」と出た)。
# 数値そのものは出してよいが、n と共に「参考値」として格下げする。
# 勝率・方向ラベル・注意フラグ・成長傾向・ペア予想・ラインナップのレンジがすべてこの 1 つを参照する。
VERDICT_MIN_SAMPLE = 5


def wilson_ci_from_rate(p_hat: float, n: int, z: float = 1.96) -> tuple[float, float]:
    """率 p_hat と標本数 n から Wilson スコア区間を返す (n=0 は区間を定義できず (0, 1))。

    勝数が整数で分からない率 (混合後の勝率など) にも使える。
    """
    if n == 0:
        return (0.0, 1.0)
    denominator = 1 + z * z / n
    center = (p_hat + z * z / (2 * n)) / denominator
    margin = (z * math.sqrt(p_hat * (1 - p_hat) / n + z * z / (4 * n * n))) / denominator
    return (round(max(0.0, center - margin), 4), round(min(1.0, center + margin), 4))


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
    return wilson_ci_from_rate(successes / n, n, z)


# 両側 95% の t 値 (自由度 1..30)。30 を超えたら 1.96 を使う。
_T975 = (
    12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228,
    2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086,
    2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042,
)


def cluster_rate_ci(per_cluster: list[tuple[int, int]]) -> Optional[tuple[float, float]]:
    """試合などのまとまり (クラスタ) ごとの (成功数, 件数) から、全体の比率の 95% 区間を返す。

    防ぐ事象 (監査 #302): 同じ試合のラリーは互いに独立ではないのに、全ラリー数を n として
    Wilson 区間を当てると、区間が実際より狭くなる。ここでは試合を単位とする比推定量の
    クラスタ頑健な標準誤差 (残差の平方和 / (件数合計^2) * m/(m-1)) と t 分布で区間を作る。

    点推定は呼び出し側の「全体の比率 = 成功数合計 / 件数合計」と一致する。
    クラスタが 2 未満、または件数合計が 0 のときは区間を作れないので None。
    """
    clusters = [(w, n) for w, n in per_cluster if n > 0]
    m = len(clusters)
    total_n = sum(n for _, n in clusters)
    if m < 2 or total_n == 0:
        return None
    p_hat = sum(w for w, _ in clusters) / total_n
    ss = sum((w - p_hat * n) ** 2 for w, n in clusters)
    se = math.sqrt(ss * m / (m - 1)) / total_n
    t = _T975[m - 2] if m - 1 <= len(_T975) else 1.96
    return (
        round(max(0.0, p_hat - t * se), 4),
        round(min(1.0, p_hat + t * se), 4),
    )


# 解析種別ごとの最小標本数。「中程度」はこの件数から、「高信頼」は 5 倍から。
_MINIMUMS: dict[str, int] = {
    "descriptive_basic": 10,
    "heatmap": 50,
    "shot_transition": 100,
    "win_loss_comparison": 5,
    "opponent_analysis": 30,
    "pressure_performance": 15,
    "rally_vs_winrate": 20,
    "temporal": 30,
    # 打球数ベース (SPEC.md §6.3 / フロントの ConfidenceBadge strokes 閾値 500 / 2000)。
    # 旧 backend/analysis/confidence.py:calc_confidence の基準をここへ統合した。
    "stroke_count": 500,
}
_DEFAULT_MINIMUM = 20
_HIGH_MULTIPLIER = 5
# 「高信頼」の開始件数を倍率でなく固定値で持つ解析種別 (stroke_count は 2000)
_HIGH_AT: dict[str, int] = {"stroke_count": 2000}

# 実用レベルの解析ではない tier / evidence_level。ここに該当する解析は
# 標本数がいくら多くても「高信頼（実用レベル）」「中程度」を名乗らない。
# 防ぐ事象: registry で research / exploratory (昇格条件が未達) の解析が、
# 標本数だけで「高信頼（実用レベル）」と表示された
# (pair_synergy は全 53 試合で高信頼、ペア個別は 16 試合。監査 B4 / C5)。
CAPPED_TIERS = frozenset({"research"})
CAPPED_EVIDENCE_LEVELS = frozenset({"exploratory"})

# 対象の推定区間の幅 (確率 0..1) がこれを超えたら「参考値」止まり。
# フロント MatchupForecastCard の「疎データ」警告 (CI 幅 > 30pp) と同じ値。
# 防ぐ事象: 行は「疎データ」と警告しているのにカード全体の信頼度は高い、という矛盾。
WIDE_INTERVAL_WIDTH = 0.30

REFERENCE_LABEL = "参考（研究段階）"
REFERENCE_WARNING = "研究段階の解析のため、標本数にかかわらず参考値として扱ってください"
_LOW_LABEL = "参考値（データ蓄積中）"
_MEDIUM_LABEL = "中程度（解釈に注意）"
_HIGH_LABEL = "高信頼（実用レベル）"


def check_confidence(
    analysis_type: str,
    sample_size: int,
    *,
    tier: Optional[str] = None,
    evidence_level: Optional[str] = None,
    unit_n: Optional[int] = None,
    interval_width: Optional[float] = None,
) -> dict:
    """標本数から信頼度を返す。判定は常にこの 1 関数。

    Parameters:
        analysis_type:  _MINIMUMS のキー (未知は最小 20 件)。
        sample_size:    セクション全体の標本数。
        tier / evidence_level:
            解析の成熟度。research / exploratory なら最高でも「参考（研究段階）」。
        unit_n:
            ラベルを付ける表示単位 (ペア・対戦相手・セル) 自身の n。
            与えると sample_size との小さい方で判定する。全体 53 試合でも
            そのペアが 16 試合なら 16 で判定される。
        interval_width:
            対象の推定区間の幅 (確率 0..1)。WIDE_INTERVAL_WIDTH を超えると
            「参考値」止まり。
    """
    n = sample_size if unit_n is None else min(sample_size, unit_n)
    n = max(0, n)
    minimum = _MINIMUMS.get(analysis_type, _DEFAULT_MINIMUM)
    high_at = _HIGH_AT.get(analysis_type, minimum * _HIGH_MULTIPLIER)
    if n < minimum // 2:
        level, stars = "low", "★☆☆"
        label = _LOW_LABEL
        warning = f"解析には{minimum}件以上推奨（現在{n}件）"
    elif n < minimum:
        level, stars = "low", "★☆☆"
        label = _LOW_LABEL
        warning = f"サンプルが少ない可能性（推奨{minimum}件）"
    elif n < high_at:
        level, stars = "medium", "★★☆"
        label = _MEDIUM_LABEL
        warning = None
    else:
        level, stars = "high", "★★★"
        label = _HIGH_LABEL
        warning = None

    capped_by: Optional[str] = None
    if level != "low":
        if tier in CAPPED_TIERS or evidence_level in CAPPED_EVIDENCE_LEVELS:
            level, stars, label, warning = "low", "★☆☆", REFERENCE_LABEL, REFERENCE_WARNING
            capped_by = "tier"
        elif interval_width is not None and interval_width > WIDE_INTERVAL_WIDTH:
            level, stars, label = "low", "★☆☆", _LOW_LABEL
            warning = f"推定区間が広い（幅{interval_width * 100:.0f}ポイント）"
            capped_by = "interval"

    result = {
        "level": level,
        "stars": stars,
        "label": label,
        "warning": warning,
    }
    if unit_n is not None:
        result["n_used"] = n
    if capped_by is not None:
        result["capped_by"] = capped_by
    return result


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
