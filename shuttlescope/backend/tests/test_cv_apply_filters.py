"""cv_candidates apply フィルタ (A1-2) のユニットテスト。

ルータ全体（FastAPI app）を立てずに、純粋なフィルタ判定関数
`_field_passes_filters` の振る舞いを検証する。ローカルでは FastAPI/Starlette
版数不整合で app 起動テストが落ちる既知問題があるため、関数レベルで担保する。
"""
import pytest

from backend.routers.cv_candidates import ApplyRequest, _field_passes_filters


APPLY_MODES = {"auto_filled", "suggested"}


def _cand(decision="auto_filled", conf=0.8, codes=None):
    return {
        "value": "BL",
        "confidence_score": conf,
        "decision_mode": decision,
        "reason_codes": codes or [],
    }


class TestDecisionMode:
    def test_passes_when_mode_in_set(self):
        assert _field_passes_filters(_cand("auto_filled"), ApplyRequest(), APPLY_MODES)

    def test_blocked_when_mode_not_in_set(self):
        assert not _field_passes_filters(_cand("review_required"), ApplyRequest(), APPLY_MODES)

    def test_none_candidate_blocked(self):
        assert not _field_passes_filters(None, ApplyRequest(), APPLY_MODES)


class TestConfidenceFilters:
    def test_min_confidence_excludes_low(self):
        body = ApplyRequest(min_confidence=0.75)
        assert _field_passes_filters(_cand(conf=0.8), body, APPLY_MODES)
        assert not _field_passes_filters(_cand(conf=0.5), body, APPLY_MODES)

    def test_max_confidence_excludes_high(self):
        body = ApplyRequest(max_confidence=0.7)
        assert _field_passes_filters(_cand(conf=0.6), body, APPLY_MODES)
        assert not _field_passes_filters(_cand(conf=0.95), body, APPLY_MODES)

    def test_confidence_range(self):
        body = ApplyRequest(min_confidence=0.5, max_confidence=0.9)
        assert _field_passes_filters(_cand(conf=0.7), body, APPLY_MODES)
        assert not _field_passes_filters(_cand(conf=0.95), body, APPLY_MODES)
        assert not _field_passes_filters(_cand(conf=0.3), body, APPLY_MODES)


class TestReasonCodeExclusion:
    def test_exclude_reason_code_blocks(self):
        body = ApplyRequest(exclude_reason_codes=["multiple_near_players"])
        clean = _cand(codes=["track_present_high_confidence"])
        flagged = _cand(codes=["multiple_near_players"])
        assert _field_passes_filters(clean, body, APPLY_MODES)
        assert not _field_passes_filters(flagged, body, APPLY_MODES)

    def test_no_exclusion_when_unset(self):
        body = ApplyRequest()
        flagged = _cand(codes=["multiple_near_players"])
        assert _field_passes_filters(flagged, body, APPLY_MODES)


class TestBackwardCompat:
    def test_default_request_behaves_like_legacy(self):
        """フィルタ未指定の ApplyRequest は decision_mode のみで判定（従来挙動）。"""
        body = ApplyRequest()
        assert body.min_confidence is None
        assert body.max_confidence is None
        assert body.exclude_reason_codes is None
        assert body.rally_ids is None
        # auto_filled は通り、review_required は通らない（mode 既定挙動のまま）
        assert _field_passes_filters(_cand("auto_filled", conf=0.0, codes=[]), body, APPLY_MODES)
