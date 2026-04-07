"""
analysis_tiers.py — 解析種別の stable / advanced / research 分類

目的:
  - 「現場で毎回見る層」と「深掘りする層」を分ける
  - フロントエンドがこの分類を使い、デフォルト表示範囲を制御できるようにする
  - confidence が不足している場合に research 層を非表示にするなどのゲーティングに使う

各 tier の意味:
  stable:   試合のたびに見るべき基礎統計
  advanced: 傾向把握・戦術改善に使う深掘り指標
  research: 研究・仮説検証用（データ量不足でも表示するが警告を出す）
"""
from __future__ import annotations
from typing import Literal

AnalysisTier = Literal["stable", "advanced", "research"]

# ── 分類定義 ────────────────────────────────────────────────────────────────
# key: analysis_type（/api/analysis/{type} のスラグに対応）

ANALYSIS_TIERS: dict[str, AnalysisTier] = {
    # ── stable ──────────────────────────────────────────────────────────────
    "descriptive":          "stable",
    "heatmap":              "stable",
    "score_progression":    "stable",
    "pre_win_pre_loss":     "stable",
    "first_return":         "stable",
    "set_summary":          "stable",

    # ── advanced ─────────────────────────────────────────────────────────────
    "pressure":             "advanced",
    "transition":           "advanced",
    "temporal":             "advanced",
    "post_long_rally":      "advanced",
    "growth":               "advanced",
    "doubles_tactical":     "advanced",
    "markov":               "advanced",
    "shot_quality":         "advanced",
    "movement":             "advanced",

    # ── research ─────────────────────────────────────────────────────────────
    "counterfactual":       "research",
    "recommendation":       "research",
    "opponent_affinity":    "research",
    "pair_synergy":         "research",
    "epv":                  "research",
    "shot_influence":       "research",
    "spatial_density":      "research",
    "bayesian_rt":          "research",
}

# ── tier 別の信頼度要件（最低サンプル数）───────────────────────────────────

TIER_MIN_SAMPLES: dict[AnalysisTier, int] = {
    "stable":   10,
    "advanced": 30,
    "research": 50,
}

# ── tier 別の出力制御方針 ───────────────────────────────────────────────────

TIER_OUTPUT_POLICY: dict[AnalysisTier, dict[str, bool]] = {
    "stable": {
        "show_conclusion":  True,
        "show_comparison":  True,
        "show_suggestion":  True,
    },
    "advanced": {
        "show_conclusion":  True,
        "show_comparison":  True,
        "show_suggestion":  True,  # データが十分な場合のみ
    },
    "research": {
        "show_conclusion":  False,  # 結論ではなく傾向のみ
        "show_comparison":  True,
        "show_suggestion":  False,
    },
}


def get_tier(analysis_type: str) -> AnalysisTier:
    """analysis_type の tier を返す。未知の場合は 'research'"""
    return ANALYSIS_TIERS.get(analysis_type, "research")


def get_min_samples(analysis_type: str) -> int:
    """analysis_type の推奨最低サンプル数を返す"""
    tier = get_tier(analysis_type)
    return TIER_MIN_SAMPLES[tier]


def get_output_policy(analysis_type: str) -> dict[str, bool]:
    """analysis_type の出力制御方針を返す"""
    tier = get_tier(analysis_type)
    return TIER_OUTPUT_POLICY[tier]


def all_tiers_meta() -> dict:
    """全 tier 分類をまとめて返す（API レスポンス用）"""
    grouped: dict[str, list[str]] = {"stable": [], "advanced": [], "research": []}
    for analysis_type, tier in ANALYSIS_TIERS.items():
        grouped[tier].append(analysis_type)
    return {
        "tiers": grouped,
        "min_samples": TIER_MIN_SAMPLES,
        "output_policy": TIER_OUTPUT_POLICY,
    }
