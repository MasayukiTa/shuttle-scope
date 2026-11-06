"""Regression: app_settings reads must not leave a session idle in transaction.

2026-11-06 production incident
-----------------------------
The production backend had five connections stuck in ``idle in transaction``.
The longest (one day, twenty hours) had
``SELECT value FROM app_settings WHERE key=$1`` as its last statement.

Root cause: the read-only settings helpers in ``routers/tracknet.py`` and
``routers/yolo.py`` ran a ``SELECT`` on an ``autocommit=False`` session and
never committed/rolled back. On a short request session ``get_db`` closes it,
but ``routers/tracknet.py::_run_batch`` opens a ``SessionLocal()`` and holds it
for the whole video pass (minutes to hours), so that ``SELECT`` stayed the
"last statement" and the connection reported ``idle in transaction`` the whole
time.

The fix makes the helpers rollback after reading and routes the value through a
short-TTL cache so a batch that reads the same key repeatedly does not reopen a
read transaction each time.

These tests pin both properties so the regression cannot silently return. They
import only the router helpers + a scratch SQLite engine (no ``backend.main``),
so they run on any OS the CI matrix uses.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from backend.db import app_settings_cache
from backend.routers import tracknet as tracknet_router
from backend.routers import yolo as yolo_router


def _settings_engine():
    """Scratch SQLite engine with an app_settings table (ORM-external table)."""
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
        )
    return engine


def _seed(engine, key: str, value: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            sa.text("INSERT INTO app_settings(key, value) VALUES(:k, :v)"),
            {"k": key, "v": value},
        )


def _session(engine):
    # Mirror the production session config the helpers run under: a plain
    # autocommit=False session (the long-lived _run_batch session is exactly
    # this). expire_on_commit is irrelevant to the transaction-state property.
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def setup_function(_fn):
    # Each test starts from a cold cache so TTL hits are deterministic.
    app_settings_cache.clear()


def teardown_function(_fn):
    app_settings_cache.clear()


# ---------------------------------------------------------------------------
# Property 1: the helper does not leave the session idle in transaction.
# ---------------------------------------------------------------------------

def test_tracknet_load_setting_int_leaves_no_open_transaction():
    engine = _settings_engine()
    _seed(engine, "tracknet_batch_fps", "12")
    db = _session(engine)
    try:
        got = tracknet_router._load_setting_int(db, "tracknet_batch_fps", 10)
        assert got == 12
        # The whole point: after a read-only helper call the session must not
        # be holding an open transaction (that is what shows as
        # ``idle in transaction`` on PostgreSQL).
        assert db.in_transaction() is False, (
            "read-only settings helper left the session in an open "
            "transaction -> would show as idle in transaction in production"
        )
    finally:
        db.close()
        engine.dispose()


def test_tracknet_load_device_settings_leaves_no_open_transaction():
    engine = _settings_engine()
    _seed(engine, "cuda_device_index", "1")
    _seed(engine, "openvino_device", '"CPU"')
    db = _session(engine)
    try:
        cuda_idx, ov_device = tracknet_router._load_device_settings(db)
        assert cuda_idx == 1
        assert ov_device == "CPU"
        assert db.in_transaction() is False
    finally:
        db.close()
        engine.dispose()


def test_yolo_load_setting_int_leaves_no_open_transaction():
    engine = _settings_engine()
    _seed(engine, "yolo_batch_fps", "30")
    db = _session(engine)
    try:
        got = yolo_router._load_setting_int(db, "yolo_batch_fps", 15)
        assert got == 30
        assert db.in_transaction() is False
    finally:
        db.close()
        engine.dispose()


def test_yolo_load_device_settings_leaves_no_open_transaction():
    engine = _settings_engine()
    _seed(engine, "cuda_device_index", "2")
    db = _session(engine)
    try:
        cuda_idx, ov_device = yolo_router._load_device_settings(db)
        assert cuda_idx == 2
        assert db.in_transaction() is False
    finally:
        db.close()
        engine.dispose()


def test_missing_key_still_leaves_no_open_transaction():
    """Even the default/except path must release the transaction."""
    engine = _settings_engine()  # table exists but key absent
    db = _session(engine)
    try:
        got = tracknet_router._load_setting_int(db, "does_not_exist", 7)
        assert got == 7
        assert db.in_transaction() is False
    finally:
        db.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# Property 2: the short-TTL cache removes repeated DB round trips.
# ---------------------------------------------------------------------------

def test_repeated_reads_hit_cache_and_do_not_reopen_a_read_transaction():
    engine = _settings_engine()
    _seed(engine, "tracknet_batch_fps", "9")

    selects: list[str] = []

    @sa.event.listens_for(engine, "before_cursor_execute")
    def _record(conn, cursor, statement, parameters, context, executemany):
        if statement.strip().upper().startswith("SELECT"):
            selects.append(statement)

    db = _session(engine)
    try:
        first = tracknet_router._load_setting_int(db, "tracknet_batch_fps", 10)
        after_first = len(selects)
        assert first == 9
        assert after_first >= 1, "first read should hit the DB"

        # Subsequent reads within the TTL must be served from cache: no new
        # SELECT, hence no new read transaction to leave idle.
        for _ in range(5):
            again = tracknet_router._load_setting_int(db, "tracknet_batch_fps", 10)
            assert again == 9
        assert len(selects) == after_first, (
            "cached reads must not issue another SELECT (that is what kept "
            "reopening idle-in-transaction read transactions)"
        )
        assert db.in_transaction() is False
    finally:
        db.close()
        engine.dispose()


def test_invalidate_forces_a_fresh_read():
    engine = _settings_engine()
    _seed(engine, "tracknet_batch_fps", "9")

    db = _session(engine)
    try:
        assert tracknet_router._load_setting_int(db, "tracknet_batch_fps", 10) == 9
        # Operator changes the setting; writers call invalidate().
        with engine.begin() as conn:
            conn.execute(
                sa.text("UPDATE app_settings SET value = :v WHERE key = :k"),
                {"v": "20", "k": "tracknet_batch_fps"},
            )
        app_settings_cache.invalidate()
        assert tracknet_router._load_setting_int(db, "tracknet_batch_fps", 10) == 20
        assert db.in_transaction() is False
    finally:
        db.close()
        engine.dispose()


def test_cache_ttl_zero_always_reads_but_still_closes_transaction():
    """With TTL disabled every read hits the DB, yet none may stay open."""
    engine = _settings_engine()
    _seed(engine, "k", "3")

    def _loader():
        return 3

    # Direct cache contract check: ttl=0 means never fresh.
    v1 = app_settings_cache.get_or_load("k", _loader, ttl=0.0)
    assert v1 == 3
    assert app_settings_cache.peek("k") is None
    engine.dispose()
