"""Migration 0066 adds strokes.wrist_vs_racket additively and is reversible.

The official attack/defence classification needs a body-relative input that no
existing column carries. 0066 adds a single nullable column; it must not drop or
backfill anything, and upgrade/downgrade must be idempotent (bootstrap may create
the column via create_all before alembic runs).
"""
from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa

_DB_DIR = Path(__file__).resolve().parents[1] / "db"
_ALEMBIC_INI = _DB_DIR / "alembic.ini"
_SCRIPT_LOCATION = _DB_DIR / "migrations"

_TABLE = "strokes"
_COLUMN = "wrist_vs_racket"


def _alembic_config(db_url):
    from alembic.config import Config

    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _columns(engine, table):
    return {c["name"] for c in sa.inspect(engine).get_columns(table)}


def test_0066_adds_nullable_column_and_is_reversible(tmp_path, monkeypatch):
    from alembic import command

    db = tmp_path / "m.db"
    url = "sqlite:///" + db.as_posix()
    monkeypatch.setenv("DATABASE_URL", url)

    cfg = _alembic_config(url)

    # Upgrade to 0065 (before our column) then to 0066 (adds it).
    command.upgrade(cfg, "0065")
    engine = sa.create_engine(url)
    try:
        assert _COLUMN not in _columns(engine, _TABLE)
    finally:
        engine.dispose()

    command.upgrade(cfg, "0066")
    engine = sa.create_engine(url)
    try:
        cols = {c["name"]: c for c in sa.inspect(engine).get_columns(_TABLE)}
        assert _COLUMN in cols
        assert cols[_COLUMN]["nullable"] is True
    finally:
        engine.dispose()

    # Idempotent upgrade: re-running head must not raise.
    command.upgrade(cfg, "head")

    # Downgrade removes the column again, other columns untouched.
    engine = sa.create_engine(url)
    try:
        before = _columns(engine, _TABLE)
    finally:
        engine.dispose()

    command.downgrade(cfg, "0065")
    engine = sa.create_engine(url)
    try:
        after = _columns(engine, _TABLE)
        assert _COLUMN not in after
        assert before - {_COLUMN} == after
    finally:
        engine.dispose()


def test_head_upgrade_round_trips_column_via_orm(tmp_path, monkeypatch):
    """After head, a Stroke row can carry wrist_vs_racket and read it back.

    Uses the ORM so column server/python defaults (uuid, created_at, revision, ...)
    are applied; this exercises the new column on a real Stroke insert rather than
    re-listing every NOT NULL column by hand.
    """
    from alembic import command
    from sqlalchemy.orm import Session

    db = tmp_path / "orm.db"
    url = "sqlite:///" + db.as_posix()
    monkeypatch.setenv("DATABASE_URL", url)

    command.upgrade(_alembic_config(url), "head")

    from backend.db.models import Stroke

    engine = sa.create_engine(url)
    try:
        assert _COLUMN in _columns(engine, _TABLE)
        with Session(engine) as session:
            stroke = Stroke(
                rally_id=1,
                stroke_num=1,
                player="player_a",
                shot_type="clear",
                wrist_vs_racket="at_or_above",
            )
            session.add(stroke)
            session.commit()
            saved_id = stroke.id

        with Session(engine) as session:
            loaded = session.get(Stroke, saved_id)
            assert loaded is not None
            assert loaded.wrist_vs_racket == "at_or_above"
            # Not recorded stays NULL (the default meaning).
            other = Stroke(
                rally_id=1,
                stroke_num=2,
                player="player_b",
                shot_type="clear",
            )
            session.add(other)
            session.commit()
            assert other.wrist_vs_racket is None
    finally:
        engine.dispose()
