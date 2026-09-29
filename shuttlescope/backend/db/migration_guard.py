"""PostgreSQL migration serialization and production URL guards."""
from __future__ import annotations

import os
import time

from sqlalchemy.engine import make_url


MIGRATION_ADVISORY_LOCK_KEY = 1397247052  # stable app-specific int64 key
DEFAULT_LOCK_WAIT_SEC = 30.0
DEFAULT_DDL_LOCK_TIMEOUT_SEC = 30.0


def _positive_seconds(env_name: str, default: float) -> float:
    raw = (os.environ.get(env_name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{env_name} must be numeric, got {raw!r}") from exc
    if value <= 0:
        raise RuntimeError(f"{env_name} must be > 0, got {value}")
    return value


def validate_production_migration_url(
    runtime_url: str,
    migration_url: str,
    *,
    is_production: bool,
) -> None:
    """Reject migration credentials that target the wrong DB or runtime role."""
    if not is_production or not runtime_url.startswith("postgresql"):
        return
    if not migration_url:
        raise RuntimeError(
            "SS_DB_MIGRATION_URL is required for PostgreSQL production migrations"
        )

    runtime = make_url(runtime_url)
    migration = make_url(migration_url)
    runtime_target = (
        runtime.host or "",
        runtime.port or 5432,
        runtime.database or "",
    )
    migration_target = (
        migration.host or "",
        migration.port or 5432,
        migration.database or "",
    )
    if migration_target != runtime_target:
        raise RuntimeError(
            "SS_DB_MIGRATION_URL must target the same host/port/database as DATABASE_URL"
        )
    if (runtime.username or "") == (migration.username or ""):
        raise RuntimeError(
            "SS_DB_MIGRATION_URL must use a dedicated migration role, not runtime role"
        )


def acquire_postgres_migration_lock(connection) -> None:
    """Serialize Alembic runs across concurrently starting backend processes."""
    wait_sec = _positive_seconds(
        "SS_DB_MIGRATION_LOCK_WAIT_SEC",
        DEFAULT_LOCK_WAIT_SEC,
    )
    deadline = time.monotonic() + wait_sec
    while True:
        acquired = bool(
            connection.exec_driver_sql(
                f"SELECT pg_try_advisory_lock({MIGRATION_ADVISORY_LOCK_KEY})"
            ).scalar()
        )
        # Session advisory locks survive commit, while this closes SQLAlchemy's
        # implicit transaction before Alembic opens its migration transaction.
        connection.commit()
        if acquired:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"timed out waiting {wait_sec:g}s for ShuttleScope migration lock"
            )
        time.sleep(0.25)

    ddl_lock_sec = _positive_seconds(
        "SS_DB_MIGRATION_DDL_LOCK_TIMEOUT_SEC",
        DEFAULT_DDL_LOCK_TIMEOUT_SEC,
    )
    timeout_ms = max(1, int(ddl_lock_sec * 1000))
    connection.exec_driver_sql(f"SET lock_timeout = '{timeout_ms}ms'")
    connection.commit()


def release_postgres_migration_lock(connection) -> None:
    """Best-effort explicit unlock; connection close is the final safety net."""
    try:
        connection.exec_driver_sql(
            f"SELECT pg_advisory_unlock({MIGRATION_ADVISORY_LOCK_KEY})"
        )
        connection.commit()
    except Exception:
        try:
            connection.rollback()
        except Exception:
            pass
