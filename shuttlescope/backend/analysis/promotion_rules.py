"""
promotion_rules.py — Tier 昇格基準の明文化

目的:
  - research → advanced、advanced → stable への昇格基準を定義する
  - 「役に立ちそう」という印象だけで昇格させないようにする
  - 降格条件も定義する（安定性が確認できなくなった場合）

昇格フロー:
  research → advanced: 実用候補水準に達した場合
  advanced → stable:   日常利用に耐える水準に達した場合
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PromotionCriteria:
    """昇格基準定義。"""
    analysis_type: str
    from_tier: str
    to_tier: str
    min_sample_size: int
    required_stability: str         # "single_season" / "cross_season" / "cross_tournament"
    ci_width_threshold: Optional[float]   # CI幅の上限（この値以下で安定と判定）
    brier_score_threshold: Optional[float]  # Brier score の上限（予測系のみ）
    calibration_required: bool
    coach_usefulness_test_required: bool
    additional_notes: str = ""


PROMOTION_CRITERIA: list[PromotionCriteria] = [
    # ── research → advanced ─────────────────────────────────────────────────
    PromotionCriteria(
        analysis_type="epv_state",
        from_tier="research",
        to_tier="advanced",
        min_sample_size=500,
        required_stability="cross_tournament",
        ci_width_threshold=0.20,
        brier_score_threshold=None,
        calibration_required=True,
        coach_usefulness_test_required=True,
        additional_notes="各状態ごとのサンプル数≥50が必要。",
    ),
    PromotionCriteria(
        analysis_type="state_action",
        from_tier="research",
        to_tier="advanced",
        min_sample_size=500,
        required_stability="cross_tournament",
        ci_width_threshold=0.30,
        brier_score_threshold=None,
        calibration_required=False,
        coach_usefulness_test_required=True,
        additional_notes="信頼できるQ値のある状態×行動ペアが≥20必要。",
    ),
    PromotionCriteria(
        analysis_type="hazard_fatigue",
        from_tier="research",
        to_tier="advanced",
        min_sample_size=500,
        required_stability="cross_tournament",
        ci_width_threshold=0.20,
        brier_score_threshold=0.25,
        calibration_required=True,
        coach_usefulness_test_required=True,
        additional_notes="ロングラリー後ハザードの再現性が2シーズン以上必要。",
    ),
    PromotionCriteria(
        analysis_type="counterfactual_v2",
        from_tier="research",
        to_tier="advanced",
        min_sample_size=500,
        required_stability="cross_tournament",
        ci_width_threshold=0.25,
        brier_score_threshold=None,
        calibration_required=False,
        coach_usefulness_test_required=True,
        additional_notes="CF-2（傾向スコア）実装後に評価すること。",
    ),
    PromotionCriteria(
        analysis_type="bayes_matchup",
        from_tier="research",
        to_tier="advanced",
        min_sample_size=50,
        required_stability="cross_season",
        ci_width_threshold=0.25,
        brier_score_threshold=0.22,
        calibration_required=True,
        coach_usefulness_test_required=True,
        additional_notes="対戦相手ごと≥3試合・全体≥50試合が必要。",
    ),
    PromotionCriteria(
        analysis_type="opponent_policy",
        from_tier="research",
        to_tier="advanced",
        min_sample_size=100,
        required_stability="cross_tournament",
        ci_width_threshold=None,
        brier_score_threshold=None,
        calibration_required=False,
        coach_usefulness_test_required=True,
        additional_notes="コンテキストごとのサポート数≥30・交差大会安定性が必要。",
    ),
    PromotionCriteria(
        analysis_type="doubles_role",
        from_tier="research",
        to_tier="advanced",
        min_sample_size=50,
        required_stability="single_season",
        ci_width_threshold=None,
        brier_score_threshold=None,
        calibration_required=False,
        coach_usefulness_test_required=True,
        additional_notes="DB-2（HMM）実装後に再評価すること。",
    ),

    # ── advanced → stable ───────────────────────────────────────────────────
    PromotionCriteria(
        analysis_type="pressure",
        from_tier="advanced",
        to_tier="stable",
        min_sample_size=1000,
        required_stability="cross_season",
        ci_width_threshold=0.10,
        brier_score_threshold=None,
        calibration_required=True,
        coach_usefulness_test_required=True,
        additional_notes="プレッシャー定義の校正完了が必要。",
    ),
    PromotionCriteria(
        analysis_type="growth",
        from_tier="advanced",
        to_tier="stable",
        min_sample_size=0,  # 試合数≥8 で判定
        required_stability="cross_season",
        ci_width_threshold=0.15,
        brier_score_threshold=None,
        calibration_required=False,
        coach_usefulness_test_required=True,
        additional_notes="選手ごとに≥8試合のデータが必要。",
    ),
]

# ── 降格条件 ────────────────────────────────────────────────────────────────

DEMOTION_CONDITIONS: dict[str, list[str]] = {
    "general": [
        "CI 幅が昇格時の閾値を2倍以上超えた場合",
        "Brier score が閾値を20%以上超えた場合",
        "クロス大会での再現性が確認できなくなった場合",
        "コーチから有用性の否定的フィードバックが複数回得られた場合",
    ],
    "epv_state": [
        "状態定義を変更した場合は全推定値を再計算して再評価すること",
    ],
    "bayes_matchup": [
        "事前分布の推定に使用したデータセットが大幅に変わった場合は再評価すること",
    ],
}


def get_criteria_for(analysis_type: str, from_tier: str) -> Optional[PromotionCriteria]:
    """analysis_type + from_tier に対応する昇格基準を返す。"""
    for crit in PROMOTION_CRITERIA:
        if crit.analysis_type == analysis_type and crit.from_tier == from_tier:
            return crit
    return None


def all_criteria_as_dict() -> list[dict]:
    """全昇格基準を辞書リストとして返す（API レスポンス用）。"""
    return [
        {
            "analysis_type": c.analysis_type,
            "from_tier": c.from_tier,
            "to_tier": c.to_tier,
            "min_sample_size": c.min_sample_size,
            "required_stability": c.required_stability,
            "ci_width_threshold": c.ci_width_threshold,
            "brier_score_threshold": c.brier_score_threshold,
            "calibration_required": c.calibration_required,
            "coach_usefulness_test_required": c.coach_usefulness_test_required,
            "additional_notes": c.additional_notes,
        }
        for c in PROMOTION_CRITERIA
    ]
