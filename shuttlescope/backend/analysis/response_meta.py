"""
response_meta.py — API レスポンス共通 meta フィールドビルダー

使い方:
    from backend.analysis.response_meta import build_response_meta

    @router.get("/analysis/foo")
    def get_foo(player_id: int, ...):
        data = compute_foo(...)
        sample_size = len(data)
        meta = build_response_meta("epv", sample_size)
        return {"success": True, "data": data, "meta": meta}
"""
from __future__ import annotations

from backend.analysis.analysis_tiers import get_tier, get_min_samples, get_output_policy
from backend.analysis.analysis_meta import get_evidence_meta


def build_response_meta(analysis_type: str, sample_size: int) -> dict:
    """
    analysis_type と実際のサンプルサイズから meta dict を構築する。

    Returns:
        {
          "tier": str,
          "evidence_level": str,
          "sample_size": int,
          "min_recommended_sample": int,
          "confidence_level": float,
          "conclusion_allowed": bool,
          "recommendation_allowed": bool,
          "caution": str | None,
          "assumptions": str | None,
          "promotion_criteria": str | None,
        }
    """
    tier = get_tier(analysis_type)
    min_samples = get_min_samples(analysis_type)
    policy = get_output_policy(analysis_type)
    evidence = get_evidence_meta(analysis_type)

    # 信頼度スコア (0〜1): min_samples に対する実サンプルの達成率
    if min_samples > 0:
        confidence_level = round(min(1.0, sample_size / min_samples), 3)
    else:
        confidence_level = 1.0

    sufficient = sample_size >= min_samples

    return {
        "tier": tier,
        "evidence_level": evidence.get("evidence_level", "exploratory"),
        "sample_size": sample_size,
        "min_recommended_sample": min_samples,
        "confidence_level": confidence_level,
        "conclusion_allowed": policy["show_conclusion"] and sufficient,
        "recommendation_allowed": policy["show_suggestion"] and sufficient,
        "caution": evidence.get("caution"),
        "assumptions": evidence.get("assumptions"),
        "promotion_criteria": evidence.get("promotion_criteria"),
    }


def build_empty_meta(analysis_type: str) -> dict:
    """サンプルサイズ 0 での meta を返す（データなし状態）。"""
    return build_response_meta(analysis_type, 0)
