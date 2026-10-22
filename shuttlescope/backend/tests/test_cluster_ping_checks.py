"""cluster.topology.ping_node: 疎通確認の内訳 (checks) のテスト

「NG」の一語ではなく、ICMP / HTTP のどちらがなぜ失敗したかを返すことを確認する。
実ネットワークには出ず、ping_icmp と urllib を差し替えて検証する。
"""
from __future__ import annotations

import urllib.request

import pytest

from backend.cluster import topology


def _icmp(ok: bool, reason=None, latency_ms: int = 5):
    def _fake(ip, timeout=2.0):
        out = {"reachable": ok, "latency_ms": latency_ms, "via": "icmp"}
        if reason:
            out["reason"] = reason
        return out
    return _fake


def test_icmp_success_has_single_check(monkeypatch):
    monkeypatch.setattr(topology, "ping_icmp", _icmp(True))
    res = topology.ping_node("192.168.0.2")
    assert res["reachable"] is True
    assert res["via"] == "icmp"
    assert [c["kind"] for c in res["checks"]] == ["icmp"]
    assert res["checks"][0]["ok"] is True


def test_both_fail_reports_each_reason(monkeypatch):
    monkeypatch.setattr(topology, "ping_icmp", _icmp(False, reason="no_reply", latency_ms=2003))

    def _boom(url, timeout=None):
        raise TimeoutError("timed out")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    res = topology.ping_node("192.168.0.2")
    assert res["reachable"] is False
    kinds = {c["kind"]: c for c in res["checks"]}
    assert kinds["icmp"]["ok"] is False
    assert kinds["icmp"]["reason"] == "no_reply"
    assert kinds["http"]["ok"] is False
    assert kinds["http"]["reason"] == "timeout"


def test_public_address_is_not_probed_over_http(monkeypatch):
    monkeypatch.setattr(topology, "ping_icmp", _icmp(False, reason="no_reply"))

    def _must_not_call(url, timeout=None):
        raise AssertionError("クラスタ外アドレスへ HTTP で接続してはならない")

    monkeypatch.setattr(urllib.request, "urlopen", _must_not_call)
    res = topology.ping_node("8.8.8.8")
    http = [c for c in res["checks"] if c["kind"] == "http"][0]
    assert http["ok"] is False
    assert http["reason"] == "blocked_address"


def test_invalid_ip_reason_from_icmp():
    res = topology.ping_icmp("not-an-ip")
    assert res["reachable"] is False
    assert res["reason"] == "invalid_ip"


def test_http_success_after_icmp_failure(monkeypatch):
    monkeypatch.setattr(topology, "ping_icmp", _icmp(False, reason="no_reply"))

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=None: _Resp())
    res = topology.ping_node("192.168.0.2")
    assert res["reachable"] is True
    assert res["via"] == "http"
    assert [c["kind"] for c in res["checks"]] == ["icmp", "http"]
    assert res["checks"][1]["ok"] is True
