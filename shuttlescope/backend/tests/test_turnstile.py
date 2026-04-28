"""M-A5 Turnstile 検証のテスト。"""
from __future__ import annotations


def test_skipped_when_secret_not_configured(monkeypatch):
    monkeypatch.delenv("SS_TURNSTILE_SECRET_KEY", raising=False)
    import backend.config as cfg
    monkeypatch.setattr(cfg.settings, "ss_turnstile_secret_key", "")
    from backend.utils.turnstile import verify_turnstile
    ok, reason = verify_turnstile("any_token", "1.2.3.4")
    assert ok is True
    assert "skipped" in reason


def test_required_but_no_token(monkeypatch):
    import backend.config as cfg
    monkeypatch.setattr(cfg.settings, "ss_turnstile_secret_key", "test_secret")
    monkeypatch.setattr(cfg.settings, "ss_turnstile_required", 1)
    from backend.utils.turnstile import verify_turnstile
    ok, reason = verify_turnstile(None, "1.2.3.4")
    assert ok is False
    assert "提供されていません" in reason or "Turnstile" in reason


def test_not_required_no_token(monkeypatch):
    import backend.config as cfg
    monkeypatch.setattr(cfg.settings, "ss_turnstile_secret_key", "test_secret")
    monkeypatch.setattr(cfg.settings, "ss_turnstile_required", 0)
    from backend.utils.turnstile import verify_turnstile
    ok, _ = verify_turnstile(None, "1.2.3.4")
    assert ok is True
