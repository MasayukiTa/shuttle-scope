"""問い合わせ通知 (_notify_inquiry) が Discord に受理される形で送られることの検査。

2026-10-21: 本文を "text" (Slack 形式) だけで送っていたため、Discord が 400 で拒否し、
問い合わせの通知が一度も届かなかった (大学の方からの連絡を6日間見落とした)。
Discord の webhook は "content" か "embeds" を要求する。
"""
from __future__ import annotations

import json
import types
import urllib.error

import pytest

from backend.routers import public_site


def _inquiry(**kw):
    base = dict(
        name="Test User",
        organization="Test University",
        role="analyst",
        contact_reference="user@example.com",
        message="hello " * 200,
        ip_address="203.0.113.7",
        user_agent="pytest",
    )
    base.update(kw)
    return types.SimpleNamespace(**base)


@pytest.fixture
def captured(monkeypatch):
    sent = []

    def fake_urlopen(req, timeout=None):
        url = req.full_url
        if "discord.com" in url:
            sent.append(json.loads(req.data.decode("utf-8")))

        class _Resp:
            def read(self):
                return b"{}"

        return _Resp()

    monkeypatch.setattr(public_site.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        public_site.settings, "ss_notify_webhook_url",
        "https://discord.com/api/webhooks/1/abc", raising=False,
    )
    monkeypatch.setattr(
        "backend.utils.safe_path.validate_external_url",
        lambda url, field_name="": None,
    )
    return sent


def test_payload_uses_the_content_key_discord_accepts(captured):
    public_site._notify_inquiry(_inquiry())
    assert len(captured) == 1
    body = captured[0]
    assert isinstance(body.get("content"), str) and body["content"].strip()
    assert "Test User" in body["content"]
    assert "user@example.com" in body["content"]


def test_content_stays_under_discord_limit(captured):
    public_site._notify_inquiry(_inquiry(message="あ" * 5000, name="n" * 120,
                                        organization="o" * 160, contact_reference="c" * 200))
    assert len(captured[0]["content"]) <= 2000


def test_rejection_is_logged_as_error(monkeypatch, caplog):
    def fake_urlopen(req, timeout=None):
        if "discord.com" in req.full_url:
            raise urllib.error.HTTPError(
                req.full_url, 400, "Bad Request", {}, None,
            )

        class _Resp:
            def read(self):
                return b"{}"

        return _Resp()

    monkeypatch.setattr(public_site.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        public_site.settings, "ss_notify_webhook_url",
        "https://discord.com/api/webhooks/1/abc", raising=False,
    )
    monkeypatch.setattr(
        "backend.utils.safe_path.validate_external_url",
        lambda url, field_name="": None,
    )
    with caplog.at_level("ERROR"):
        public_site._notify_inquiry(_inquiry())
    assert any("rejected" in r.getMessage() and r.levelname == "ERROR" for r in caplog.records)
