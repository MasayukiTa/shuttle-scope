"""3rd-review #5 fix: analysis_registry の check_or_raise / evaluate_sample 検証

CLAUDE.md non-negotiable rule:
  「New analyses must declare evidence level, minimum sample size, and
   behavior when the threshold is unmet.」
  「Promotion ... is governed by promotion_rules.py (do not bypass)」

旧コードはサンプル閾値を register していたが、強制する仕組みがなく、
低 N の research/advanced 結果が ConfidenceBadge 任せで返っていた。
"""
import pytest

from backend.analysis.analysis_registry import (
    InsufficientSampleError,
    SampleDiagnostic,
    TIER_MIN_SAMPLES,
    check_or_raise,
    evaluate_sample,
    get_analysis_meta,
)


# ─── evaluate_sample (非例外) ────────────────────────────────────────────────


class TestEvaluateSample:
    def test_research_below_threshold_returns_insufficient(self):
        d: SampleDiagnostic = evaluate_sample("opponent_policy", 10)
        assert d["analysis_type"] == "opponent_policy"
        assert d["tier"] == "research"
        assert d["sample_size"] == 10
        assert d["min_recommended_sample"] == TIER_MIN_SAMPLES["research"]
        assert d["is_sufficient"] is False

    def test_research_at_threshold_is_sufficient(self):
        n = TIER_MIN_SAMPLES["research"]
        d = evaluate_sample("opponent_policy", n)
        assert d["is_sufficient"] is True

    def test_stable_low_sample_still_evaluated(self):
        d = evaluate_sample("descriptive", 1)
        assert d["tier"] == "stable"
        # min_recommended は stable 閾値が反映される
        assert d["min_recommended_sample"] == TIER_MIN_SAMPLES["stable"]
        assert d["is_sufficient"] is False

    def test_unknown_analysis_falls_back_to_research(self):
        d = evaluate_sample("__non_existent__", 0)
        assert d["tier"] == "research"
        assert d["min_recommended_sample"] == TIER_MIN_SAMPLES["research"]


# ─── check_or_raise (例外) ───────────────────────────────────────────────────


class TestCheckOrRaise:
    def test_raises_for_research_below_threshold(self):
        with pytest.raises(InsufficientSampleError) as exc_info:
            check_or_raise("opponent_policy", 5)
        err = exc_info.value
        assert err.analysis_type == "opponent_policy"
        assert err.tier == "research"
        assert err.sample_size == 5
        assert err.min_recommended_sample == TIER_MIN_SAMPLES["research"]
        # FastAPI HTTPException(detail=...) に渡せる形
        d = err.to_dict()
        assert d["code"] == "insufficient_sample"
        assert d["analysis_type"] == "opponent_policy"
        assert d["tier"] == "research"

    def test_does_not_raise_for_research_at_threshold(self):
        check_or_raise("opponent_policy", TIER_MIN_SAMPLES["research"])  # 例外なし

    def test_raises_for_advanced_below_threshold_by_default(self):
        # "pressure" は advanced tier として登録されている
        assert get_analysis_meta("pressure")["tier"] == "advanced"
        with pytest.raises(InsufficientSampleError) as exc_info:
            check_or_raise("pressure", 0)
        assert exc_info.value.tier == "advanced"
        assert exc_info.value.min_recommended_sample == TIER_MIN_SAMPLES["advanced"]

    def test_stable_tier_is_not_enforced_by_default(self):
        """stable は ConfidenceBadge 任せ。check_or_raise は raise しない"""
        check_or_raise("descriptive", 0)  # 例外なし

    def test_enforce_tiers_can_include_stable(self):
        """強制対象に stable を含めれば stable も raise する"""
        with pytest.raises(InsufficientSampleError):
            check_or_raise("descriptive", 0, enforce_tiers=("stable", "advanced", "research"))

    def test_enforce_tiers_can_exclude_advanced(self):
        """強制対象から advanced を外せば advanced は raise しない"""
        assert get_analysis_meta("pressure")["tier"] == "advanced"
        check_or_raise("pressure", 0, enforce_tiers=("research",))  # 例外なし

    def test_negative_sample_treated_as_zero(self):
        """defensive: 負の sample_size は 0 として扱う"""
        with pytest.raises(InsufficientSampleError) as exc_info:
            check_or_raise("opponent_policy", -5)
        assert exc_info.value.sample_size == 0

    def test_none_sample_treated_as_zero(self):
        """defensive: None でも 0 扱い"""
        with pytest.raises(InsufficientSampleError) as exc_info:
            check_or_raise("opponent_policy", None)  # type: ignore[arg-type]
        assert exc_info.value.sample_size == 0

    def test_unknown_analysis_uses_research_threshold(self):
        with pytest.raises(InsufficientSampleError) as exc_info:
            check_or_raise("__non_existent__", 0)
        assert exc_info.value.tier == "research"
