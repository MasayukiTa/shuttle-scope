from __future__ import annotations

from pathlib import Path

import pytest

from backend.db import migration_guard as guard


class _Scalar:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _FakeConnection:
    def __init__(self, lock_results):
        self.lock_results = iter(lock_results)
        self.sql = []
        self.commits = 0
        self.rollbacks = 0

    def exec_driver_sql(self, sql):
        self.sql.append(sql)
        if "pg_try_advisory_lock" in sql:
            return _Scalar(next(self.lock_results))
        if "pg_advisory_unlock" in sql:
            return _Scalar(True)
        return _Scalar(None)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_production_migration_url_must_match_database_target():
    runtime = "postgresql+psycopg://ss_user@db.example:5432/shuttlescope"
    migration = "postgresql+psycopg://ss_migration@other.example:5432/shuttlescope"
    with pytest.raises(RuntimeError, match="same host/port/database"):
        guard.validate_production_migration_url(
            runtime, migration, is_production=True
        )


def test_production_migration_url_requires_distinct_role():
    runtime = "postgresql+psycopg://ss_user@db.example:5432/shuttlescope"
    migration = "postgresql+psycopg://ss_user@db.example:5432/shuttlescope"
    with pytest.raises(RuntimeError, match="dedicated migration role"):
        guard.validate_production_migration_url(
            runtime, migration, is_production=True
        )


def test_dev_does_not_enforce_dedicated_role():
    url = "postgresql+psycopg://dev@localhost/shuttlescope"
    guard.validate_production_migration_url(url, "", is_production=False)


def test_postgres_migration_lock_retries_and_sets_ddl_timeout(monkeypatch):
    conn = _FakeConnection([False, False, True])
    monkeypatch.setenv("SS_DB_MIGRATION_LOCK_WAIT_SEC", "2")
    monkeypatch.setenv("SS_DB_MIGRATION_DDL_LOCK_TIMEOUT_SEC", "7")
    monkeypatch.setattr(guard.time, "sleep", lambda _seconds: None)

    guard.acquire_postgres_migration_lock(conn)

    assert sum("pg_try_advisory_lock" in sql for sql in conn.sql) == 3
    assert "SET lock_timeout = '7000ms'" in conn.sql
    assert conn.commits == 4


def test_postgres_migration_lock_times_out(monkeypatch):
    conn = _FakeConnection([False] * 20)
    monkeypatch.setenv("SS_DB_MIGRATION_LOCK_WAIT_SEC", "0.001")
    monkeypatch.setattr(guard.time, "sleep", lambda _seconds: None)

    ticks = iter([0.0, 1.0, 1.0, 1.0])
    monkeypatch.setattr(guard.time, "monotonic", lambda: next(ticks))

    with pytest.raises(RuntimeError, match="timed out waiting"):
        guard.acquire_postgres_migration_lock(conn)


def test_release_postgres_migration_lock_is_explicit():
    conn = _FakeConnection([True])
    guard.release_postgres_migration_lock(conn)
    assert any("pg_advisory_unlock" in sql for sql in conn.sql)
    assert conn.commits == 1


def test_production_bootstrap_is_not_dispatched_to_executor():
    main_src = (
        Path(__file__).resolve().parents[1] / "main.py"
    ).read_text(encoding="utf-8")
    strict_branch = main_src.split("if strict_bootstrap:", 1)[1].split(
        "else:", 1
    )[0]
    assert "bootstrap_database(" in strict_branch
    assert "run_in_executor" not in strict_branch

def test_production_migration_url_accepts_same_target_with_distinct_role():
    runtime = "postgresql+psycopg://ss_user@db.example:5432/shuttlescope"
    migration = "postgresql+psycopg://ss_migration@db.example:5432/shuttlescope"
    guard.validate_production_migration_url(
        runtime, migration, is_production=True
    )
