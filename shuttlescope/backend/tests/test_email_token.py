"""M-A3 Email Token ユーティリティの単体テスト。"""
from __future__ import annotations

import os

import pytest

# テスト前に HMAC 鍵を設定
os.environ.setdefault("SS_EMAIL_TOKEN_HMAC_KEY", "test_hmac_key_for_unit_tests_only_12345")
os.environ.setdefault("SECRET_KEY", "fallback_secret_for_test")


def test_token_hash_is_deterministic_and_irreversible():
    from backend.utils.email_token import _hash_token, _generate_plain
    plain = _generate_plain()
    h1 = _hash_token(plain)
    h2 = _hash_token(plain)
    assert h1 == h2, "ハッシュは決定的であるべき"
    assert h1 != plain, "ハッシュは平文と異なる"
    assert len(h1) == 64, "SHA-256 hex は 64 文字"


def test_generate_plain_uniqueness():
    from backend.utils.email_token import _generate_plain
    s = {_generate_plain() for _ in range(200)}
    assert len(s) == 200, "トークン平文は衝突しないべき"


def test_different_keys_yield_different_hashes(monkeypatch):
    from backend.utils import email_token as et
    plain = "fixed_plain_token_value_for_test"
    monkeypatch.setenv("SS_EMAIL_TOKEN_HMAC_KEY", "key_alpha_xxxxxxxxxxxxxxxxxxxxx")
    h1 = et._hash_token(plain)
    monkeypatch.setenv("SS_EMAIL_TOKEN_HMAC_KEY", "key_beta_yyyyyyyyyyyyyyyyyyyyyy")
    h2 = et._hash_token(plain)
    assert h1 != h2, "鍵が異なればハッシュは異なる"
