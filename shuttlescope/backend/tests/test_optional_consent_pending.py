"""任意同意の「未回答」判定 (/api/auth/me の optional_consent_pending)。

同意画面は cross_border_transfer を提示も送信もしない (EU-Japan 十分性認定)。
それを判定対象に含めていたため、画面で全項目に回答しても永久に「未回答」のままで、
再読み込みのたびに同意画面が出直していた。
"""
from backend.routers.auth import (
    _OPTIONAL_CONSENT_TYPES,
    _PROMPTED_OPTIONAL_CONSENT_TYPES,
    _optional_consent_pending,
)

# OnboardingConsentPage.tsx の OPTIONAL と同じ集合 (UI が実際に送る型)
_UI_SENT = {"ai_training", "research_participation", "body_disclose_to_analyst", "body_disclose_to_coach"}


def test_answering_every_presented_consent_clears_pending():
    assert _optional_consent_pending(set(_UI_SENT)) is False


def test_nothing_recorded_is_pending_and_means_not_consented():
    assert _optional_consent_pending(set()) is True


def test_partially_answered_is_still_pending():
    assert _optional_consent_pending({"ai_training"}) is True


def test_prompted_set_matches_what_the_ui_sends():
    assert _PROMPTED_OPTIONAL_CONSENT_TYPES == _UI_SENT
    assert _PROMPTED_OPTIONAL_CONSENT_TYPES < _OPTIONAL_CONSENT_TYPES
