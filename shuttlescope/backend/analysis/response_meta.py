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

from backend.analysis.analysis_registry import (
    get_analysis_meta,
    TIER_OUTPUT_POLICY,
)


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
    entry = get_analysis_meta(analysis_type)
    tier = entry["tier"]
    min_samples = entry["min_recommended_sample"]
    policy = TIER_OUTPUT_POLICY.get(tier, TIER_OUTPUT_POLICY["research"])

    # 信頼度スコア (0〜1): min_samples に対する実サンプルの達成率
    if min_samples > 0:
        confidence_level = round(min(1.0, sample_size / min_samples), 3)
    else:
        confidence_level = 1.0

    sufficient = sample_size >= min_samples

    return {
        "tier": tier,
        "evidence_level": entry["evidence_level"],
        "sample_size": sample_size,
        "min_recommended_sample": min_samples,
        "confidence_level": confidence_level,
        "conclusion_allowed": policy["show_conclusion"] and sufficient,
        "recommendation_allowed": policy["show_suggestion"] and sufficient,
        "caution": entry["caution"],
        "assumptions": entry["assumptions"],
        "promotion_criteria": entry["promotion_criteria"],
    }


def build_empty_meta(analysis_type: str) -> dict:
    """サンプルサイズ 0 での meta を返す（データなし状態）。"""
    return build_response_meta(analysis_type, 0)
