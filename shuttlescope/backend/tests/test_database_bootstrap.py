"""Database bootstrap tests for fresh, legacy, and versioned SQLite files."""
from __future__ import annotations

import os
import sqlite3
import tempfile

from sqlalchemy import create_engine

from backend.db.database import bootstrap_database


def _sqlite_url(path: str) -> str:
    return f"sqlite:///{path}"


def _fetchall(path: str, query: str):
    con = sqlite3.connect(path)
    try:
        return con.execute(query).fetchall()
    finally:
        con.close()


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

        assert version == [("0015",)]
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

        assert version == [("0015",)]
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
        assert version == [("0015",)]
    finally:
        eng.dispose()
        if os.path.exists(path):
            os.remove(path)
