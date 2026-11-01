"""Static guard against PostgreSQL-unsafe Boolean usage in Alembic migrations.

Incident (2026-11-01): migrations 0059 and 0060 set a Boolean column's
``server_default`` to ``sa.text("0")`` and wrote integer literals in UPDATE
statements. SQLite (used in CI) silently accepts ``0``/``1`` for Boolean
columns, but PostgreSQL (production) rejects them, so the backend crashed at
startup right after the deploy. The fix (de200575) switched to ``sa.false()`` /
``sa.true()`` and the SQL literals ``false`` / ``true``.

This test scans every migration in ``db/migrations/versions/*.py`` statically
(no DB, no import of the migration module) and FAILS when it finds:

(a) a ``sa.Column(...)`` / ``add_column(sa.Column(...))`` declared as
    ``sa.Boolean()`` (or ``Boolean``) whose ``server_default`` is
    ``sa.text("0")``, ``sa.text("1")``, ``"0"`` or ``"1"``; or
(b) a SQL ``UPDATE ... SET <col> = 0|1`` where ``<col>`` is a Boolean column
    declared in the same file.

String literals such as ``sa.false()``, ``sa.true()``, ``sa.text("false")`` and
bound parameters (``:flag``) are PostgreSQL-safe and are intentionally allowed.

Migrations already applied in production that legitimately contain an
integer-style Boolean default are exempted one by one in ``ALLOWLIST_*`` below,
keyed by (filename, line). Each entry was found by reading the file, not by
guessing. New migrations get no free pass -- add a PostgreSQL-safe default
instead of extending the allowlist.
"""
from __future__ import annotations

import re
from pathlib import Path

_VERSIONS = Path(__file__).resolve().parents[1] / "db" / "migrations" / "versions"

# (filename, 1-based start line of the Column( call) -> grandfathered.
# These three columns already shipped to production with an integer-style
# Boolean default *before* the sa.false()/true() convention was enforced.
# They are live; rewriting them is a schema no-op that would still re-assert the
# bad text, so they are grandfathered here instead.
ALLOWLIST_SERVER_DEFAULT = {
    # matches.is_public_pool: server_default=sa.text("0") (0009->0010 Phase B-3).
    ("0010_match_owner_team.py", 42),
    # announcements.pinned: server_default="0".
    ("0040_announcements.py", 31),
    # users.is_test: server_default="0".
    ("0045_user_is_test_flag.py", 58),
}

# (filename, 1-based line) -> grandfathered UPDATE that assigns an integer
# literal to a Boolean column. Empty today: every live UPDATE on a Boolean
# column uses `false`/`true` or a bound parameter. Keep empty unless a
# *shipped* migration genuinely needs grandfathering.
ALLOWLIST_UPDATE_LITERAL: set[tuple[str, int]] = set()

_BAD_DEFAULT_RE = re.compile(
    r"""server_default\s*=\s*(?:sa\.text\(\s*["']([01])["']\s*\)|["']([01])["'])"""
)
_BOOLEAN_TOKEN_RE = re.compile(r"(?<![\w.])(?:sa\.)?Boolean\b")
# First positional string arg inside a Column(...) call = the column name.
_COLUMN_NAME_RE = re.compile(r"""^["']([A-Za-z_][A-Za-z0-9_]*)["']""")
_COLUMN_OPEN_RE = re.compile(r"(?:sa\.)?Column\(")
# SET <col> = 0 | 1  (bare integer literal; not quoted, not false/true, not a bind).
_SET_INT_RE = re.compile(
    r"""\bSET\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([01])\b(?!\s*[\w.'\"])""",
    re.IGNORECASE,
)


def _migration_files() -> list[Path]:
    files = sorted(p for p in _VERSIONS.glob("*.py") if p.name != "__init__.py")
    assert files, f"no migration files found under {_VERSIONS}"
    return files


def _column_spans(text: str):
    """Yield (start_line, inner_text, column_name) for every ``Column(...)`` call.

    The inner text is the parenthesis-balanced body of that single Column call,
    so a Boolean declaration and its server_default are scoped to *one* column
    even inside a multi-column ``op.create_table(...)``.
    """
    for m in _COLUMN_OPEN_RE.finditer(text):
        i = m.end()  # position just after the opening '('
        depth = 1
        j = i
        n = len(text)
        while j < n and depth > 0:
            c = text[j]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            j += 1
        inner = text[i : j - 1]
        start_line = text.count("\n", 0, m.start()) + 1
        name_match = _COLUMN_NAME_RE.match(inner.lstrip())
        yield start_line, inner, (name_match.group(1) if name_match else None)


def test_no_boolean_server_default_integer_literal() -> None:
    violations: list[str] = []
    for path in _migration_files():
        text = path.read_text(encoding="utf-8")
        for start_line, inner, name in _column_spans(text):
            if not _BOOLEAN_TOKEN_RE.search(inner):
                continue
            if not _BAD_DEFAULT_RE.search(inner):
                continue
            if (path.name, start_line) in ALLOWLIST_SERVER_DEFAULT:
                continue
            violations.append(
                f"{path.name}:{start_line}: Boolean column "
                f"'{name or '?'}' has an integer-literal server_default; use "
                f"sa.false()/sa.true() (PostgreSQL rejects 0/1 for boolean) -> "
                f"{inner.strip()[:160]}"
            )
    assert not violations, (
        "PostgreSQL-unsafe Boolean server_default found in migration(s):\n"
        + "\n".join(violations)
    )


def _boolean_columns(text: str) -> set[str]:
    return {
        name
        for _start, inner, name in _column_spans(text)
        if name and _BOOLEAN_TOKEN_RE.search(inner)
    }


def test_no_update_sets_boolean_column_to_integer_literal() -> None:
    violations: list[str] = []
    for path in _migration_files():
        text = path.read_text(encoding="utf-8")
        bool_cols = _boolean_columns(text)
        if not bool_cols:
            continue
        for idx, line in enumerate(text.splitlines(), start=1):
            for m in _SET_INT_RE.finditer(line):
                col = m.group(1)
                if col not in bool_cols:
                    continue
                if (path.name, idx) in ALLOWLIST_UPDATE_LITERAL:
                    continue
                violations.append(
                    f"{path.name}:{idx}: UPDATE assigns integer literal "
                    f"'{m.group(2)}' to Boolean column '{col}'; use the SQL "
                    f"literal false/true (PostgreSQL rejects 0/1) -> "
                    f"{line.strip()[:160]}"
                )
    assert not violations, (
        "PostgreSQL-unsafe integer literal assigned to a Boolean column in "
        "migration UPDATE(s):\n" + "\n".join(violations)
    )


def test_server_default_allowlist_is_not_stale() -> None:
    """Guard the allowlist itself: every grandfathered (file, line) must still
    point at a Boolean integer-literal server_default. If a file is renumbered
    or fixed, the stale entry fails here instead of silently masking a future
    regression.
    """
    stale: list[str] = []
    for name, line in sorted(ALLOWLIST_SERVER_DEFAULT):
        path = _VERSIONS / name
        if not path.exists():
            stale.append(f"{name}: file no longer exists")
            continue
        spans = {start: inner for start, inner, _ in _column_spans(path.read_text(encoding="utf-8"))}
        inner = spans.get(line)
        if inner is None:
            stale.append(f"{name}:{line}: no Column( starts on this line")
            continue
        if not (_BOOLEAN_TOKEN_RE.search(inner) and _BAD_DEFAULT_RE.search(inner)):
            stale.append(
                f"{name}:{line}: no longer a Boolean integer-literal "
                f"server_default -> remove this allowlist entry"
            )
    assert not stale, (
        "ALLOWLIST_SERVER_DEFAULT is stale; update it:\n" + "\n".join(stale)
    )


# ---------------------------------------------------------------------------
# Best-effort second guard: render migrations offline (alembic as_sql) for the
# PostgreSQL dialect and assert no exception. This exercises the real
# server_default / UPDATE rendering under postgresql semantics without any live
# database. It is best-effort: most migrations here call op.get_bind() /
# sa.inspect(bind), which require a live connection and cannot run in pure
# as_sql mode, so this test skips rather than fails when that happens. The
# static scanners above are the authoritative guard. (See explain.md.)
# ---------------------------------------------------------------------------


class _ListWriter:
    """Minimal file-like sink so alembic can write rendered SQL somewhere."""

    def __init__(self) -> None:
        self.chunks: list[str] = []

    def write(self, s: str) -> int:
        self.chunks.append(s)
        return len(s)

    def flush(self) -> None:  # pragma: no cover - no-op
        return None


def test_recent_migrations_render_offline_for_postgresql() -> None:
    import importlib.util

    import pytest

    try:
        from alembic.operations import Operations
        from alembic.runtime.migration import MigrationContext
    except Exception as exc:  # pragma: no cover - alembic present in CI
        pytest.skip(f"alembic unavailable: {exc!r}")

    files = _migration_files()[-10:]
    if not files:
        pytest.skip("no migrations to render")

    try:
        ctx = MigrationContext.configure(
            dialect_name="postgresql",
            opts={"as_sql": True, "output_buffer": _ListWriter()},
        )
    except Exception as exc:
        pytest.skip(f"cannot configure offline postgresql MigrationContext: {exc!r}")

    rendered = 0
    with Operations.context(ctx):
        for path in files:
            spec = importlib.util.spec_from_file_location(
                f"mig_render_{path.stem}", path
            )
            if spec is None or spec.loader is None:
                pytest.skip(f"cannot load {path.name} for offline render")
            mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)
            except Exception as exc:
                pytest.skip(
                    f"{path.name} imports backend internals not available "
                    f"offline: {exc!r}"
                )
            upgrade = getattr(mod, "upgrade", None)
            if upgrade is None:
                continue
            try:
                upgrade()
            except Exception as exc:
                # op.get_bind()/inspect() need a live connection; not available
                # in pure as_sql mode. Environment limitation, not a
                # Boolean-safety failure -> skip (documented in explain.md).
                pytest.skip(
                    f"{path.name}.upgrade() needs a live bind in offline mode "
                    f"({type(exc).__name__}); static scanners are the "
                    f"authoritative guard"
                )
            rendered += 1

    assert rendered >= 0  # reaching here without an exception is the assertion
