"""Database bootstrap tests for fresh, legacy, and versioned SQLite files."""
from __future__ import annotations

import os
import re
import sqlite3
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, event

from backend.db.database import (
    _ensure_analytics_indexes,
    _ensure_unique_indexes,
    bootstrap_database,
    create_tables,
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
