"""M-A1 Mailer 抽象化のテスト。"""
from __future__ import annotations

import os


def test_console_mailer_returns_true(caplog):
    import logging
    caplog.set_level(logging.INFO)
    from backend.services.mailer.console import ConsoleMailer
    from backend.services.mailer.base import MailMessage
    m = ConsoleMailer()
    ok = m.send(MailMessage(to=["test@example.com"], subject="hi", text_body="hello", tags=["test"]))
    assert ok is True
    # ログにメール内容が出力される
    joined = "\n".join(r.message for r in caplog.records)
    assert "test@example.com" in joined
    assert "hello" in joined


def test_noop_mailer_records_messages():
    from backend.services.mailer.noop import NoopMailer
    from backend.services.mailer.base import MailMessage
    m = NoopMailer()
    assert len(m.sent) == 0
    m.send(MailMessage(to=["a@x"], subject="s1", text_body="b1"))
    m.send(MailMessage(to=["b@y"], subject="s2", text_body="b2"))
    assert len(m.sent) == 2
    assert m.sent[0].subject == "s1"
    assert m.sent[1].to == ["b@y"]
    m.clear()
    assert len(m.sent) == 0


def test_factory_returns_console_by_default(monkeypatch):
    monkeypatch.delenv("SS_MAIL_BACKEND", raising=False)
    from backend.services.mailer import get_mailer, reset_mailer_for_test
    from backend.services.mailer.console import ConsoleMailer
    reset_mailer_for_test()
    # config の値を変更するため reload
    from importlib import reload
    import backend.config as cfg
    monkeypatch.setattr(cfg.settings, "ss_mail_backend", "")
    m = get_mailer()
    assert isinstance(m, ConsoleMailer)
    reset_mailer_for_test()


def test_factory_returns_noop(monkeypatch):
    from backend.services.mailer import get_mailer, reset_mailer_for_test
    from backend.services.mailer.noop import NoopMailer
    import backend.config as cfg
    reset_mailer_for_test()
    monkeypatch.setattr(cfg.settings, "ss_mail_backend", "noop")
    m = get_mailer()
    assert isinstance(m, NoopMailer)
    reset_mailer_for_test()
