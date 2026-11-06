"""Regression tests for Boolean column server defaults.

A review found four Boolean columns (Team.is_independent, Match.is_public_pool,
Match.is_demo_public, Match.is_synthetic) declared with ``server_default="false"``
-- a plain string. SQLite stores that string literally as the text ``'false'``,
which reads back as truthy, so a raw ``INSERT`` that omits the column yields
``True`` instead of ``False``. It was fixed on main by using ``sqlalchemy.false()``
(commit 6c3f44d6).

These tests pin that fix two ways:

1. Static: every Boolean column that carries a server_default must not use a
   word-like string literal such as ``"false"``/``"true"``. ``false()``/``true()``
   render as the SQL keywords and ``text("0")``/``text("1")`` are SQL elements, so
   both are fine. The bare numeric strings ``"0"``/``"1"`` already used elsewhere in
   the schema round-trip correctly on SQLite ("0" is falsy, "1" is truthy) and are
   therefore also allowed; only the broken word form ("false"/"true", which SQLite
   stores as text that reads back as True) is rejected.
2. Behavioral: on an in-memory SQLite database, a raw ``INSERT`` that omits the
   four columns must read back as ``False`` through the ORM.
"""
from sqlalchemy import Boolean, create_engine, text
from sqlalchemy.orm import Session

from backend.db import models as _models  # noqa: F401  # register metadata
from backend.db.database import Base
from backend.db.models import Match, Team


def _string_default_value(server_default):
    """If the column's server_default is a bare Python string, return it.

    A SQLAlchemy ``DefaultClause`` wraps its argument in ``.arg``. For
    ``server_default="false"`` that ``.arg`` is the Python ``str`` "false".
    For ``false()``/``true()``/``text("0")`` the ``.arg`` is a SQL element
    (a ClauseElement), not a ``str`` -- so this returns ``None`` for them.
    """
    if server_default is None:
        return None
    arg = getattr(server_default, "arg", server_default)
    return arg if isinstance(arg, str) else None


def test_boolean_server_defaults_are_not_plain_strings():
    """Static guard: walk every mapped table and reject word-string Boolean
    defaults such as "false"/"true".

    false()/true()/text("0")/text("1") are acceptable (they are SQL elements, not
    Python strings). The bare numeric strings "0"/"1" are also acceptable because
    they round-trip correctly on SQLite. A default like "false"/"true" -- the bug
    this file pins -- must fail.
    """
    offenders = []
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if not isinstance(column.type, Boolean):
                continue
            if column.server_default is None:
                continue
            value = _string_default_value(column.server_default)
            if value is None:
                continue  # false()/true()/text(...) -- a SQL element, fine
            if value.strip() in ("0", "1"):
                continue  # numeric string literal round-trips correctly
            offenders.append(f"{table.name}.{column.name} = {value!r}")

    assert not offenders, (
        "Boolean columns must not use a word-string server_default such as "
        "'false'/'true' (SQLite stores them as text that reads back as True). "
        "Use sqlalchemy false()/true() or text('0')/text('1') instead. "
        "Offenders: " + "; ".join(offenders)
    )


def test_boolean_defaults_read_false_after_raw_insert():
    """Behavioral guard on SQLite.

    Insert a teams row and a matches row with raw SQL that omits the four
    Boolean columns, then read them back through the ORM and assert each is
    ``False`` (not the text 'false', which would be truthy).

    A raw INSERT does not trigger SQLAlchemy's Python-side ``default=`` values,
    so every NOT NULL column that has no *server* default must be supplied
    explicitly (e.g. created_at/updated_at/revision). The four target Boolean
    columns are deliberately omitted so their server_default is what fills them.
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with engine.begin() as conn:
        # teams: supply every NOT NULL column lacking a server default.
        # is_independent is omitted on purpose so its server_default applies.
        conn.execute(
            text(
                "INSERT INTO teams (uuid, name, created_at, updated_at) "
                "VALUES (:uuid, :name, :created_at, :updated_at)"
            ),
            {
                "uuid": "team-uuid-0001",
                "name": "Raw Insert Team",
                "created_at": "2026-01-01 00:00:00",
                "updated_at": "2026-01-01 00:00:00",
            },
        )
        # matches: supply every NOT NULL column lacking a server default.
        # result_source has server_default='manual'; the four target booleans
        # (is_public_pool, is_demo_public, is_synthetic) are omitted on purpose.
        conn.execute(
            text(
                "INSERT INTO matches ("
                "uuid, tournament, tournament_level, round, date, format, "
                "player_a_id, player_b_id, result, revision, "
                "annotation_status, annotation_progress, created_via_quick_start, "
                "created_at, updated_at"
                ") VALUES ("
                ":uuid, :tournament, :level, :round, :date, :format, "
                ":pa, :pb, :result, :revision, "
                ":annotation_status, :annotation_progress, :cvqs, "
                ":created_at, :updated_at"
                ")"
            ),
            {
                "uuid": "match-uuid-0001",
                "tournament": "Raw Insert Cup",
                "level": "国内",
                "round": "R1",
                "date": "2026-01-01",
                "format": "singles",
                "pa": 1,
                "pb": 2,
                "result": "win",
                "revision": 1,
                "annotation_status": "pending",
                "annotation_progress": 0.0,
                "cvqs": 0,
                "created_at": "2026-01-01 00:00:00",
                "updated_at": "2026-01-01 00:00:00",
            },
        )

    with Session(engine) as session:
        team = session.query(Team).filter_by(uuid="team-uuid-0001").one()
        match = session.query(Match).filter_by(uuid="match-uuid-0001").one()

        assert team.is_independent is False
        assert match.is_public_pool is False
        assert match.is_demo_public is False
        assert match.is_synthetic is False

    engine.dispose()
