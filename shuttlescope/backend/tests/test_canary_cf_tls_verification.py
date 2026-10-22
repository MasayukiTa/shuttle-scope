"""Cloudflare 管理 API へ Bearer トークンを送る通信は TLS 検証を必ず行う (監査 #794)。

防ぐ事象: canary の自動 ban / 解除が verify=False で管理トークンを送っていた。
経路上の中間者が HTTPS を終端できればトークンを盗める。
"""
from __future__ import annotations

import types
from pathlib import Path

import pytest

from backend.routers import canary


class _FakeResponse:
    status_code = 200
    headers: dict = {}
    text = ""

    def json(self):
        return {"result": {"id": "rule-fake"}}


class _InlineThread:
    """start() で target をその場で実行する (本物の thread を作らない)。"""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target, self._args, self._kwargs = target, args, kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)


class _NoTimer:
    def __init__(self, *a, **k):
        pass

    def start(self):
        pass


@pytest.fixture
def cf_env(monkeypatch):
    monkeypatch.setenv("SS_CF_BAN_TOKEN", "fake-token-value")
    monkeypatch.setenv("SS_CF_ZONE_ID", "fake-zone")
    monkeypatch.delenv("SS_CF_CA_BUNDLE", raising=False)
    monkeypatch.setattr(canary, "threading", types.SimpleNamespace(
        Thread=_InlineThread, Timer=_NoTimer, Lock=canary.threading.Lock))
    canary._recent_bans.clear()
    yield
    canary._recent_bans.clear()


def _capture(monkeypatch):
    seen: list[dict] = []

    def fake_post(url, **kw):
        seen.append({"method": "POST", "url": url, **kw})
        return _FakeResponse()

    def fake_delete(url, **kw):
        seen.append({"method": "DELETE", "url": url, **kw})
        return _FakeResponse()

    import requests
    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(requests, "delete", fake_delete)
    return seen


def test_ban_and_unban_verify_tls_by_default(cf_env, monkeypatch):
    seen = _capture(monkeypatch)
    canary._trigger_cf_auto_ban("203.0.113.7", "test", confidence="high")
    canary._do_cf_unban_by_id("rule-fake", "203.0.113.7")
    assert [c["method"] for c in seen] == ["POST", "DELETE"]
    for call in seen:
        assert call["verify"] is True


def test_corporate_ca_bundle_is_an_explicit_path_not_a_disable(cf_env, monkeypatch, tmp_path):
    pem = tmp_path / "ca.pem"
    pem.write_text("not a real certificate", encoding="utf-8")
    monkeypatch.setenv("SS_CF_CA_BUNDLE", str(pem))
    seen = _capture(monkeypatch)
    canary._trigger_cf_auto_ban("203.0.113.8", "test", confidence="high")
    assert seen and seen[0]["verify"] == str(pem)


def test_missing_ca_bundle_fails_closed(cf_env, monkeypatch, tmp_path):
    monkeypatch.setenv("SS_CF_CA_BUNDLE", str(tmp_path / "missing.pem"))
    seen = _capture(monkeypatch)
    canary._trigger_cf_auto_ban("203.0.113.9", "test", confidence="high")
    canary._do_cf_unban_by_id("rule-fake", "203.0.113.9")
    assert seen == []  # 管理 API は呼ばれない (検証を緩めない)


def test_no_tls_disable_left_in_cloudflare_callers():
    root = Path(__file__).resolve().parents[2]
    for rel in ("backend/routers/canary.py", "scripts/cluster/cleanup_cf_expired_rules.py"):
        src = (root / rel).read_text(encoding="utf-8")
        assert "verify=False" not in src, rel
        assert "disable_warnings" not in src, rel
