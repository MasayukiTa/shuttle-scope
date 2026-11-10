"""Migrations must build the whole schema from an EMPTY database.

Regression guard for finding data-01: migrations 0001..0060 only ALTER the
core tables (players, users, matches, ...); none of them CREATE those tables.
On SQLite this was masked because bootstrap_database runs
Base.metadata.create_all before Alembic. On a brand-new PostgreSQL database
create_all is deliberately never run, so alembic upgrade head from empty
failed with NoSuchTableError: players. Baseline revision 0000 fixes this.
"""
from __future__ import annotations

import importlib
import importlib.util
import re
from pathlib import Path

import pytest
import sqlalchemy as sa


_CORE_TABLES = [
    "access_logs", "analysis_cache", "analysis_jobs", "center_of_gravity",
    "clip_cache", "comments", "condition_tags", "conditions", "event_bookmarks",
    "expert_labels", "human_forecasts", "live_sources", "match_cv_artifacts",
    "matches", "player_page_access", "players", "pose_frames",
    "pre_match_observations", "public_inquiries", "rallies", "refresh_tokens",
    "revoked_tokens", "session_participants", "sets", "shared_sessions",
    "shot_inferences", "shuttle_tracks", "strokes", "sync_conflicts",
    "upload_sessions", "users",
]

_DB_DIR = Path(__file__).resolve().parents[1] / "db"
_ALEMBIC_INI = _DB_DIR / "alembic.ini"
_SCRIPT_LOCATION = _DB_DIR / "migrations"


def _alembic_config(db_url):
    from alembic.config import Config
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _table_names(engine):
    insp = sa.inspect(engine)
    return set(insp.get_table_names()) - {"alembic_version"}


def _columns(engine, table):
    return {c["name"] for c in sa.inspect(engine).get_columns(table)}


def test_upgrade_head_from_empty_matches_create_all(tmp_path, monkeypatch):
    from alembic import command

    empty_db = tmp_path / "empty.db"
    fresh_db = tmp_path / "fresh.db"
    empty_url = "sqlite:///" + empty_db.as_posix()
    fresh_url = "sqlite:///" + fresh_db.as_posix()

    monkeypatch.setenv("DATABASE_URL", empty_url)

    # 1. upgrade head from a genuinely empty database (no create_all).
    command.upgrade(_alembic_config(empty_url), "head")

    migrated_engine = sa.create_engine(empty_url)
    try:
        migrated_tables = _table_names(migrated_engine)

        from backend.db.database import Base
        import backend.db.models  # noqa: F401

        fresh_engine = sa.create_engine(fresh_url)
        try:
            Base.metadata.create_all(fresh_engine)
            create_all_tables = _table_names(fresh_engine)

            missing = create_all_tables - migrated_tables
            assert not missing, (
                "upgrade head from empty is missing tables that create_all "
                "produces: " + str(sorted(missing))
            )

            for table in _CORE_TABLES:
                assert table in migrated_tables, table + " not created from empty"
                mig_cols = _columns(migrated_engine, table)
                ca_cols = _columns(fresh_engine, table)
                assert mig_cols == ca_cols, (
                    "column mismatch on " + table + ": only-in-create_all="
                    + str(sorted(ca_cols - mig_cols)) + " only-in-migrated="
                    + str(sorted(mig_cols - ca_cols))
                )
        finally:
            fresh_engine.dispose()
    finally:
        migrated_engine.dispose()

    # 3. second upgrade head is a no-op (idempotent) -- must not raise.
    command.upgrade(_alembic_config(empty_url), "head")

    verify_engine = sa.create_engine(empty_url)
    try:
        assert "players" in _table_names(verify_engine)
    finally:
        verify_engine.dispose()


def test_baseline_renders_offline_for_postgresql():
    try:
        from alembic.operations import Operations
        from alembic.runtime.migration import MigrationContext
    except Exception as exc:  # pragma: no cover
        pytest.skip("alembic unavailable: " + repr(exc))

    try:
        from sqlalchemy.dialects import postgresql  # noqa: F401
        sa.create_engine("postgresql://")
    except Exception as exc:
        pytest.skip("postgresql dialect/driver unavailable: " + repr(exc))

    class _Buffer:
        def __init__(self):
            self.chunks = []

        def write(self, s):
            self.chunks.append(s)
            return len(s)

        def flush(self):  # pragma: no cover
            return None

    baseline_path = _SCRIPT_LOCATION / "versions" / "0000_base_schema.py"
    assert baseline_path.exists(), "baseline migration missing: " + str(baseline_path)

    spec = importlib.util.spec_from_file_location("ss_baseline_0000", baseline_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    buffer = _Buffer()
    try:
        ctx = MigrationContext.configure(
            dialect_name="postgresql",
            opts={"as_sql": True, "output_buffer": buffer},
        )
    except Exception as exc:
        pytest.skip("cannot configure offline postgresql context: " + repr(exc))

    with Operations.context(ctx):
        module.upgrade()

    sql = "".join(buffer.chunks)
    assert "CREATE TABLE players" in sql, "baseline did not render CREATE TABLE players"
    assert "CREATE TABLE matches" in sql, "baseline did not render CREATE TABLE matches"
    bad = re.findall(r"BOOLEAN[^,\n]*DEFAULT\s+[01]\b", sql)
    assert not bad, "integer-literal boolean default(s) rendered for PostgreSQL: " + str(bad)
