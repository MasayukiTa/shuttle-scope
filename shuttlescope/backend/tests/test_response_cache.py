"""backend/utils/response_cache.py のユニットテスト"""
from __future__ import annotations

import time

import pytest

from backend.utils import response_cache


@pytest.fixture(autouse=True)
def _reset_cache(test_engine):
    """各テストの前後でキャッシュとバージョンをリセットする（DB 行も削除）"""
    response_cache.MEMORY_CACHE.clear()
    response_cache.PLAYER_VERSION.clear()
    original_max = response_cache.MAX_ENTRIES
    # DB 側もクリア（テスト間で相互に影響しないよう）
    try:
        from backend.db.database import SessionLocal
        from backend.db.models import AnalysisCache
        with SessionLocal() as s:
            s.query(AnalysisCache).delete()
            s.commit()
    except Exception:
        pass
    yield
    response_cache.MEMORY_CACHE.clear()
    response_cache.PLAYER_VERSION.clear()
    response_cache.MAX_ENTRIES = original_max
    try:
        from backend.db.database import SessionLocal
        from backend.db.models import AnalysisCache
        with SessionLocal() as s:
            s.query(AnalysisCache).delete()
            s.commit()
    except Exception:
        pass


def test_set_get_roundtrip():
    key = response_cache.build_key("/api/analysis/foo", {"pid": "1"})
    response_cache.set(key, {"hello": "world"}, ttl=60)
    assert response_cache.get(key) == {"hello": "world"}


def test_miss_returns_none():
    assert response_cache.get("missing-key") is None


def test_ttl_expiry():
    key = response_cache.build_key("/api/analysis/foo", {"pid": "1"})
    response_cache.set(key, "value", ttl=0.05)
    assert response_cache.get(key) == "value"
    time.sleep(0.1)
    assert response_cache.get(key) is None


def test_max_entries_lru_evict(monkeypatch):
    monkeypatch.setattr(response_cache, "MAX_ENTRIES", 3)
    # DB 永続化をこのテストでは無効化（純粋な in-memory LRU 挙動の検証）
    monkeypatch.setattr(response_cache, "_db_upsert", lambda *a, **k: None)
    monkeypatch.setattr(response_cache, "_db_lookup", lambda *a, **k: None)
    response_cache.set("a", 1, ttl=60)
    response_cache.set("b", 2, ttl=60)
    response_cache.set("c", 3, ttl=60)
    # "a" をアクセスして末尾へ移動
    assert response_cache.get("a") == 1
    # 新しく追加すると今度は "b" が最古なので evict される
    response_cache.set("d", 4, ttl=60)
    assert response_cache.get("b") is None
    assert response_cache.get("a") == 1
    assert response_cache.get("c") == 3
    assert response_cache.get("d") == 4


def test_bump_version_invalidates_cache():
    params = {"pid": "1", "q": "match_id=5"}
    k1 = response_cache.build_key("/api/analysis/foo", params)
    response_cache.set(k1, "payload", ttl=60)
    assert response_cache.get(k1) == "payload"

    response_cache.bump_version()

    # 同じ params でも DATA_VERSION が変わっているのでキーが変わる
    k2 = response_cache.build_key("/api/analysis/foo", params)
    assert k1 != k2
    # 以前のキーはクリアされている
    assert response_cache.get(k1) is None
    assert response_cache.get(k2) is None


def test_build_key_is_stable_for_same_dict():
    params1 = {"pid": "1", "role": "coach", "q": "a=1&b=2"}
    params2 = {"q": "a=1&b=2", "role": "coach", "pid": "1"}  # 順序違い
    assert response_cache.build_key("/x", params1) == response_cache.build_key("/x", params2)


def test_build_key_differs_for_different_params():
    k1 = response_cache.build_key("/x", {"pid": "1"})
    k2 = response_cache.build_key("/x", {"pid": "2"})
    assert k1 != k2


def test_build_key_includes_prefix():
    k1 = response_cache.build_key("/api/analysis/a", {"pid": "1"})
    k2 = response_cache.build_key("/api/analysis/b", {"pid": "1"})
    assert k1 != k2


def test_bump_players_invalidates_only_target_player():
    """bump_players([1]) で player_id=1 のキーだけが失効し、player_id=2 は生存すること。"""
    # header 経由（pid）
    k1 = response_cache.build_key("/api/analysis/foo", {"pid": "1"})
    k2 = response_cache.build_key("/api/analysis/foo", {"pid": "2"})
    response_cache.set(k1, "v1", ttl=60)
    response_cache.set(k2, "v2", ttl=60)

    response_cache.bump_players([1])

    # 同じ params で再生成したキーは、pid=1 のみ変わる
    new_k1 = response_cache.build_key("/api/analysis/foo", {"pid": "1"})
    new_k2 = response_cache.build_key("/api/analysis/foo", {"pid": "2"})
    assert new_k1 != k1
    assert new_k2 == k2
    # 旧 k1 は到達不能（ただしエントリは一時的に残っている）
    # pid=2 のキャッシュは生きている
    assert response_cache.get(new_k2) == "v2"
    # pid=1 で新キーからは見えない（別キー）
    assert response_cache.get(new_k1) is None


def test_bump_players_extracts_from_query_string():
    """query 文字列 (q) 中の player_id=N も選手スコープとして扱うこと。"""
    params1 = {"q": "player_id=1&set_num=1"}
    params2 = {"q": "player_id=2&set_num=1"}
    k1 = response_cache.build_key("/api/analysis/foo", params1)
    k2 = response_cache.build_key("/api/analysis/foo", params2)
    response_cache.set(k1, "a", ttl=60)
    response_cache.set(k2, "b", ttl=60)

    response_cache.bump_players([1])

    new_k1 = response_cache.build_key("/api/analysis/foo", params1)
    new_k2 = response_cache.build_key("/api/analysis/foo", params2)
    assert new_k1 != k1  # pid=1 は無効化された
    assert new_k2 == k2  # pid=2 は無影響
    assert response_cache.get(new_k2) == "b"


def test_header_pid_takes_priority_over_query():
    """header の pid と query の player_id が両方ある場合、header が優先されること。"""
    params = {"pid": "1", "q": "player_id=2"}
    k_before = response_cache.build_key("/api/analysis/foo", params)

    response_cache.bump_players([2])
    # pid=1 に紐づいているのでキーは変わらない
    assert response_cache.build_key("/api/analysis/foo", params) == k_before

    response_cache.bump_players([1])
    assert response_cache.build_key("/api/analysis/foo", params) != k_before


def test_bump_version_invalidates_player_independent_keys():
    """player_id を含まないキーは bump_version() でのみ失効すること。"""
    params = {"q": "format=singles"}  # player_id を含まない
    k1 = response_cache.build_key("/api/analysis/foo", params)
    response_cache.set(k1, "payload", ttl=60)
    assert response_cache.get(k1) == "payload"

    # 関係ない選手を bump してもキーは不変
    response_cache.bump_players([999])
    assert response_cache.build_key("/api/analysis/foo", params) == k1

    # グローバル bump でキーが変わる
    response_cache.bump_version()
    k2 = response_cache.build_key("/api/analysis/foo", params)
    assert k1 != k2


def test_bump_players_skips_none():
    """None を渡しても例外を出さず、その選手分は何もしないこと。"""
    response_cache.bump_players([None, 1, None])
    assert response_cache.player_version(1) == 1
    assert response_cache.player_version(None) == 0


def test_build_key_handles_non_serializable_default():
    # default=str で datetime などは文字列化される
    from datetime import datetime
    k = response_cache.build_key("/x", {"t": datetime(2026, 1, 1)})
    assert isinstance(k, str) and len(k) > 0


# ─── 永続化バックエンド（AnalysisCache テーブル） ────────────────────────────

def test_db_restores_after_memory_clear():
    """in-memory を空にしても DB から復元されることを検証（再起動シミュレーション）"""
    key = response_cache.build_key("/api/analysis/foo", {"pid": "1"})
    response_cache.set(
        key,
        {"k": "v"},
        ttl=60,
        player_id=1,
        analysis_type="foo",
        filters_json='{"pid":"1"}',
    )
    # プロセス再起動相当：in-memory のみ全消去
    response_cache.MEMORY_CACHE.clear()

    # DB からフォールバックで復元される
    assert response_cache.get(key) == {"k": "v"}
    # in-memory にもウォームアップされていること
    assert key in response_cache.MEMORY_CACHE


def test_db_expired_row_returns_none():
    """expires_at が過去の DB 行は None を返し、削除される"""
    from datetime import datetime, timedelta
    from backend.db.database import SessionLocal
    from backend.db.models import AnalysisCache

    key = "expired-key"
    with SessionLocal() as s:
        row = AnalysisCache(
            cache_key=key,
            player_id=0,
            analysis_type="foo",
            filters_json="{}",
            result_json='{"old":true}',
            sample_size=0,
            confidence_level=0.0,
            computed_at=datetime.utcnow() - timedelta(hours=2),
            expires_at=datetime.utcnow() - timedelta(hours=1),
        )
        s.add(row)
        s.commit()

    assert response_cache.get(key) is None
    # 期限切れ行は削除済み
    with SessionLocal() as s:
        assert s.query(AnalysisCache).filter(AnalysisCache.cache_key == key).first() is None


def test_bump_players_deletes_db_rows():
    """bump_players([1]) で DB の player_id=1 行が削除され、2 は生き残る"""
    from backend.db.database import SessionLocal
    from backend.db.models import AnalysisCache

    k1 = response_cache.build_key("/api/analysis/foo", {"pid": "1"})
    k2 = response_cache.build_key("/api/analysis/foo", {"pid": "2"})
    response_cache.set(k1, "v1", ttl=60, player_id=1, analysis_type="foo")
    response_cache.set(k2, "v2", ttl=60, player_id=2, analysis_type="foo")

    response_cache.bump_players([1])

    with SessionLocal() as s:
        rows = {r.player_id for r in s.query(AnalysisCache).all()}
        assert 1 not in rows
        assert 2 in rows


def test_bump_version_clears_db():
    """bump_version() で DB の全行が削除される"""
    from backend.db.database import SessionLocal
    from backend.db.models import AnalysisCache

    k1 = response_cache.build_key("/api/analysis/foo", {"pid": "1"})
    response_cache.set(k1, "v", ttl=60, player_id=1, analysis_type="foo")

    with SessionLocal() as s:
        assert s.query(AnalysisCache).count() >= 1

    response_cache.bump_version()

    with SessionLocal() as s:
        assert s.query(AnalysisCache).count() == 0


def test_set_writes_through_to_db():
    """set() が DB にも write-through していることを検証"""
    from backend.db.database import SessionLocal
    from backend.db.models import AnalysisCache

    key = response_cache.build_key("/api/analysis/bar", {"pid": "7"})
    response_cache.set(
        key,
        {"x": 1},
        ttl=120,
        player_id=7,
        analysis_type="bar",
        filters_json='{"pid":"7"}',
    )

    with SessionLocal() as s:
        row = s.query(AnalysisCache).filter(AnalysisCache.cache_key == key).first()
        assert row is not None
        assert row.player_id == 7
        assert row.analysis_type == "bar"
        import json as _j
        assert _j.loads(row.result_json) == {"x": 1}
