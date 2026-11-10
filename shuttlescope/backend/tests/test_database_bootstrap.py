"""Database bootstrap tests for fresh, legacy, and versioned SQLite files."""
from __future__ import annotations

import os
import re
import sqlite3
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event

import backend.db.database as database_module
from backend.db.database import (
    _database_is_at_alembic_head,
    _ensure_analytics_indexes,
    _ensure_unique_indexes,
    _safe_sql_column_list,
    _safe_sql_ident,
    bootstrap_database,
    create_tables,
    run_db_migrations,
)


def _sqlite_url(path: str) -> str:
    return f"sqlite:///{path}"


def _fetchall(path: str, query: str):
    con = sqlite3.connect(path)
    try:
        return con.execute(query).fetchall()
    finally:
        con.close()


# 新しい migration を追加するたびにテストの hard-coded version を更新するのは
# メンテナンス漏れの温床なので、versions/ ディレクトリを実走査して最新 head を求める。
def _alembic_head_revision() -> str:
    versions_dir = Path(__file__).resolve().parent.parent / "db" / "migrations" / "versions"
    nums = []
    for p in versions_dir.glob("*.py"):
        m = re.match(r"^(\d{4})_", p.name)
        if m:
            nums.append(m.group(1))
    if not nums:
        raise RuntimeError(f"no migration files found under {versions_dir}")
    return max(nums)


HEAD = _alembic_head_revision()


def test_bootstrap_fresh_db_creates_schema_and_stamps_head():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    eng = create_engine(_sqlite_url(path), connect_args={"check_same_thread": False})
    try:
        bootstrap_database(eng, _sqlite_url(path))
        eng.dispose()

        version = _fetchall(path, "SELECT version_num FROM alembic_version")
        dominant_hand = _fetchall(path, "PRAGMA table_info(players)")
        indexes = _fetchall(path, "PRAGMA index_list(players)")

        assert version == [(HEAD,)]
        assert any(col[1] == "dominant_hand" and col[2] == "VARCHAR(10)" and col[3] == 0 for col in dominant_hand)
        assert any(idx[1] == "uix_players_uuid" for idx in indexes)
    finally:
        eng.dispose()
        if os.path.exists(path):
            os.remove(path)


def test_bootstrap_legacy_db_runs_compatibility_and_migration():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        con = sqlite3.connect(path)
        con.execute("CREATE TABLE players (id INTEGER PRIMARY KEY, name VARCHAR, dominant_hand VARCHAR(1) NOT NULL)")
        con.execute("INSERT INTO players (name, dominant_hand) VALUES ('legacy', 'R')")
        con.commit()
        con.close()

        eng = create_engine(_sqlite_url(path), connect_args={"check_same_thread": False})
        bootstrap_database(eng, _sqlite_url(path))
        eng.dispose()

        version = _fetchall(path, "SELECT version_num FROM alembic_version")
        dominant_hand = _fetchall(path, "PRAGMA table_info(players)")

        assert version == [(HEAD,)]
        assert any(col[1] == "dominant_hand" and col[2] == "VARCHAR(10)" and col[3] == 0 for col in dominant_hand)
        assert any(col[1] == "uuid" for col in dominant_hand)
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_bootstrap_versioned_db_is_idempotent_on_repeated_startup():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    eng = create_engine(_sqlite_url(path), connect_args={"check_same_thread": False})
    try:
        bootstrap_database(eng, _sqlite_url(path))
        bootstrap_database(eng, _sqlite_url(path))
        eng.dispose()

        version = _fetchall(path, "SELECT version_num FROM alembic_version")
        assert version == [(HEAD,)]
    finally:
        eng.dispose()
        if os.path.exists(path):
            os.remove(path)


def test_sqlite_index_bootstrap_batches_commits():
    """Index bootstrap should fsync once per helper, not once per index."""
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    commits = 0

    def _count_commit(_conn):
        nonlocal commits
        commits += 1

    try:
        create_tables(eng)
        event.listen(eng, "commit", _count_commit)

        _ensure_unique_indexes(eng)
        _ensure_analytics_indexes(eng)

        assert commits == 2
        with eng.connect() as conn:
            player_indexes = {row[1] for row in conn.exec_driver_sql("PRAGMA index_list(players)")}
            stroke_indexes = {row[1] for row in conn.exec_driver_sql("PRAGMA index_list(strokes)")}

        assert "uix_players_uuid" in player_indexes
        assert "ix_strokes_shot_type" in stroke_indexes
    finally:
        event.remove(eng, "commit", _count_commit)
        eng.dispose()

def test_bootstrap_sql_identifier_guards_reject_injected_identifiers():
    assert _safe_sql_ident("matches") == "matches"
    assert _safe_sql_column_list("match_id, player_id") == "match_id, player_id"

    with pytest.raises(ValueError):
        _safe_sql_ident("matches; DROP TABLE users")
    with pytest.raises(ValueError):
        _safe_sql_column_list("match_id, player_id DESC")


def test_run_db_migrations_can_fail_closed(monkeypatch, tmp_path):
    import alembic.command

    def _boom(*_args, **_kwargs):
        raise RuntimeError("migration boom")

    monkeypatch.setattr(alembic.command, "upgrade", _boom)
    db_url = _sqlite_url(str(tmp_path / "fail.db"))
    with pytest.raises(RuntimeError, match="migration boom"):
        run_db_migrations(db_url, fail_on_error=True)


def test_alembic_head_preflight_matches_runtime_revision():
    eng = create_engine("sqlite:///:memory:")
    try:
        with eng.begin() as conn:
            conn.exec_driver_sql(
                "CREATE TABLE alembic_version "
                "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
            )
            conn.exec_driver_sql(
                "INSERT INTO alembic_version(version_num) VALUES (?)",
                (HEAD,),
            )

        assert _database_is_at_alembic_head(eng) is True

        with eng.begin() as conn:
            conn.exec_driver_sql(
                "UPDATE alembic_version SET version_num = ?",
                ("0001",),
            )
        assert _database_is_at_alembic_head(eng) is False
    finally:
        eng.dispose()


def test_versioned_postgres_at_head_skips_privileged_migration(monkeypatch):
    class _Dialect:
        name = "postgresql"

    class _Engine:
        dialect = _Dialect()

    monkeypatch.setattr(
        database_module,
        "_table_names",
        lambda _eng: {"alembic_version", "users"},
    )
    monkeypatch.setattr(
        database_module,
        "_database_is_at_alembic_head",
        lambda _eng: True,
    )
    monkeypatch.setattr(
        database_module,
        "run_db_migrations",
        lambda *_a, **_k: pytest.fail(
            "schema-current PostgreSQL must not open the privileged migration path"
        ),
    )

    bootstrap_database(
        _Engine(),
        "postgresql+psycopg://runtime@example/db",
        fail_on_migration_error=True,
    )


def test_versioned_postgres_behind_head_runs_privileged_migration(monkeypatch):
    class _Dialect:
        name = "postgresql"

    class _Engine:
        dialect = _Dialect()

    calls = []
    monkeypatch.setattr(
        database_module,
        "_table_names",
        lambda _eng: {"alembic_version", "users"},
    )
    monkeypatch.setattr(
        database_module,
        "_database_is_at_alembic_head",
        lambda _eng: False,
    )
    monkeypatch.setattr(
        database_module,
        "run_db_migrations",
        lambda url, fail_on_error=False: calls.append((url, fail_on_error)),
    )

    url = "postgresql+psycopg://runtime@example/db"
    bootstrap_database(
        _Engine(),
        url,
        fail_on_migration_error=True,
    )
    assert calls == [(url, True)]


def test_versioned_postgres_uses_alembic_only(monkeypatch):
    class _Dialect:
        name = "postgresql"

    class _Engine:
        dialect = _Dialect()

    calls = []

    monkeypatch.setattr(
        database_module,
        "_table_names",
        lambda _eng: {"alembic_version", "users"},
    )
    monkeypatch.setattr(
        database_module,
        "_database_is_at_alembic_head",
        lambda _eng: False,
    )
    monkeypatch.setattr(
        database_module,
        "run_db_migrations",
        lambda url, fail_on_error=False: calls.append((url, fail_on_error)),
    )
    monkeypatch.setattr(
        database_module,
        "create_tables",
        lambda *_a, **_k: pytest.fail("runtime role must not run create_all on PostgreSQL"),
    )
    monkeypatch.setattr(
        database_module,
        "_ensure_unique_indexes",
        lambda *_a, **_k: pytest.fail("runtime role must not create indexes on PostgreSQL"),
    )
    monkeypatch.setattr(
        database_module,
        "_ensure_analytics_indexes",
        lambda *_a, **_k: pytest.fail("runtime role must not create indexes on PostgreSQL"),
    )

    url = "postgresql+psycopg://runtime@example/db"
    bootstrap_database(
        _Engine(),
        url,
        fail_on_migration_error=True,
    )
    assert calls == [(url, True)]


def test_legacy_postgres_without_alembic_version_is_rejected(monkeypatch):
    class _Dialect:
        name = "postgresql"

    class _Engine:
        dialect = _Dialect()

    monkeypatch.setattr(database_module, "_table_names", lambda _eng: {"users"})
    with pytest.raises(RuntimeError, match="no alembic_version"):
        bootstrap_database(_Engine(), "postgresql+psycopg://runtime@example/db")
