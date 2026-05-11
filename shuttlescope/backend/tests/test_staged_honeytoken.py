"""Staged honeytoken (R43) の unit test。"""
from __future__ import annotations

import json

from backend.utils import staged_honeytoken as sh
from backend.utils import honeytoken as ht


def setup_function(_fn):
    # 各テストで内部 state を綺麗に
    with sh._suspicious_lock:
        sh._suspicious.clear()


def test_unmarked_ip_is_not_suspicious():
    assert sh.is_suspicious("198.51.100.1") is False


def test_mark_then_suspicious():
    sh.mark_suspicious("198.51.100.2", "test")
    assert sh.is_suspicious("198.51.100.2") is True
    assert "test" in sh.get_reasons("198.51.100.2")


def test_inject_into_simple_dict():
    body = json.dumps({"foo": "bar"}).encode("utf-8")
    out = sh.maybe_inject_lure_into_json_bytes(body)
    assert out is not None
    data = json.loads(out)
    # 少なくとも 1 つの inject field に LURE_TOKEN が入っている
    assert any(data.get(k) == sh.LURE_TOKEN for k in sh._INJECT_FIELDS)


def test_inject_into_envelope_data_dict():
    body = json.dumps({"success": True, "data": {"x": 1}}).encode("utf-8")
    out = sh.maybe_inject_lure_into_json_bytes(body)
    assert out is not None
    data = json.loads(out)
    # 内側 data dict にも仕込まれている
    assert any(data["data"].get(k) == sh.LURE_TOKEN for k in sh._INJECT_FIELDS)


def test_inject_skips_array_root():
    body = json.dumps([1, 2, 3]).encode("utf-8")
    assert sh.maybe_inject_lure_into_json_bytes(body) is None


def test_inject_skips_oversized_body():
    huge = b'{"x":"' + (b"A" * (300 * 1024)) + b'"}'
    assert sh.maybe_inject_lure_into_json_bytes(huge) is None


def test_inject_skips_non_json():
    assert sh.maybe_inject_lure_into_json_bytes(b"<html></html>") is None


def test_lure_token_is_registered_in_honeytokens():
    """staged lure 値が honeytoken detector に登録されていること
    (= 攻撃者がこの値を使うと R42 で必ず catch される)。"""
    assert sh.LURE_TOKEN in ht.HONEYTOKENS
    label, prov = ht.HONEYTOKENS[sh.LURE_TOKEN]
    assert prov == "staged_in_response"
