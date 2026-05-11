"""attack_pattern aggregator (R46) の unit test。"""
from __future__ import annotations

from backend.utils import attack_pattern as ap


def setup_function(_fn):
    # 各テストで in-memory state をリセット
    with ap._lock:
        ap._recent_paths.clear()
        ap._first_hits.clear()
        ap._transitions.clear()
        ap._path_hits.clear()
        ap._kind_counts.clear()
        ap._path_kind_counts.clear()
        ap._depth_by_ip.clear()


def test_normalize_drops_query_and_int_segments():
    assert ap.normalize_path("/admin/users/12345?x=1") == "/admin/users/*"
    # /admin/legacy/v1/users/v2/config/v3 — v1/v2/v3 はバージョンで残す、数値は *
    assert ap.normalize_path("/admin/legacy/v1/users/42/config/v3") == \
        "/admin/legacy/v1/users/*/config/v3"


def test_normalize_collapses_uuid_and_long_hex():
    assert ap.normalize_path("/asset/550e8400-e29b-41d4-a716-446655440000") == \
        "/asset/*"
    assert ap.normalize_path("/x/abcdef0123456789") == "/x/*"


def test_first_hit_records_entry_path():
    ap.record_hit("1.2.3.4", "/admin/login", "decoy_maze")
    snap = ap.snapshot()
    assert any(x["path"] == "/admin/login" and x["count"] == 1
               for x in snap["top_first_hits"])


def test_transition_records_after_first():
    ap.record_hit("1.2.3.4", "/admin/login", "decoy_maze")
    ap.record_hit("1.2.3.4", "/admin/dashboard", "decoy_maze")
    snap = ap.snapshot()
    pairs = [(t["from"], t["to"]) for t in snap["top_transitions"]]
    assert ("/admin/login", "/admin/dashboard") in pairs


def test_depth_distribution_buckets():
    # IP A: 1 hit → bucket "1"
    # IP B: 3 hits → bucket "2-5"
    # IP C: 10 hits → bucket "6-20"
    ap.record_hit("10.0.0.1", "/a", "decoy_maze")
    for _ in range(3):
        ap.record_hit("10.0.0.2", "/x", "decoy_maze")
    for _ in range(10):
        ap.record_hit("10.0.0.3", "/y", "decoy_maze")
    d = ap.snapshot()["depth_distribution"]
    assert d["1"] == 1
    assert d["2-5"] == 1
    assert d["6-20"] == 1


def test_kind_counts_accumulate():
    ap.record_hit("1.1.1.1", "/x", "canary")
    ap.record_hit("1.1.1.1", "/y", "canary")
    ap.record_hit("1.1.1.1", "/z", "honeytoken")
    k = ap.snapshot()["kind_counts"]
    assert k["canary"] == 2
    assert k["honeytoken"] == 1


def test_same_pattern_repeated_only_increments_counter():
    # 同じ pattern を 5 回繰り返しても row 数は増えない (count だけ +5)
    for _ in range(5):
        ap.record_hit("9.9.9.9", "/.env", "decoy_maze")
    snap = ap.snapshot()
    # /.env だけが top_first_hits / top_paths に出る
    paths_count = sum(1 for x in snap["top_paths"] if x["path"] == "/.env")
    assert paths_count == 1
    assert snap["top_paths"][0]["count"] == 5
