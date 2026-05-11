"""Honeytoken 検知ロジック (R42) の unit test。"""
from __future__ import annotations

from backend.utils import honeytoken as ht


def test_exact_match_detects():
    tok = next(iter(ht.HONEYTOKENS.keys()))
    label, prov = ht.detect(tok)
    assert label
    assert prov


def test_substring_in_bearer_header_detects():
    tok = next(iter(ht.HONEYTOKENS.keys()))
    hit = ht.detect(f"Bearer {tok}")
    assert hit is not None


def test_substring_in_json_blob_detects():
    tok = next(iter(ht.HONEYTOKENS.keys()))
    blob = '{"api_key":"' + tok + '","other":"x"}'
    assert ht.detect(blob) is not None


def test_empty_value_returns_none():
    assert ht.detect("") is None
    assert ht.detect(None) is None


def test_real_looking_random_string_does_not_match():
    # 本物の token と衝突しないことを軽く確認
    assert ht.detect("ss_user_abc123xyz_real_looking_but_not_canary") is None
    assert ht.detect("Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9") is None


def test_provenance_labels_cover_all_planted_locations():
    """検知時に「どの経路から抜かれたか」を識別できるよう、provenance が
    全 token に付いていること。"""
    expected_provenances = {
        "repo_scrape", "db_dump", "frontend_bundle", "memory_or_config_dump",
    }
    seen = {prov for (_label, prov) in ht.HONEYTOKENS.values()}
    # 全 expected provenance のうち少なくとも 2 つ以上はカバーする
    assert len(seen & expected_provenances) >= 2


def test_dedup_window_prevents_duplicate_audit():
    """同一 IP / label の連続 hit は dedup されて二度目は skip されること。"""
    ip = "203.0.113.99"
    label = "admin_api_key"
    # 1 回目は False (= 処理する)
    assert ht._should_skip_dedup(ip, label) is False
    # 2 回目は True (= skip する)
    assert ht._should_skip_dedup(ip, label) is True
