"""Per-user daily token budget for external insight generation.

The original POC budget lived in a process-local dict. A restart reset it and N
workers effectively multiplied the daily allowance by N. The production path
now uses the existing security_events table as an append-only token ledger:

* reserve before an external generation can start;
* reconcile the reservation to provider-reported actual token usage;
* serialize reservations per user (PostgreSQL advisory transaction lock;
  SQLite BEGIN IMMEDIATE plus a process lock for tests/local mode).

No schema migration is required and the ledger survives process restarts.
"""
from __future__ import annotations

import os
import threading
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import text

from backend.db import database as db_module
from backend.db.models import SecurityEvent


INSIGHT_BUDGET_DAILY_TOKENS = int(os.getenv("INSIGHT_BUDGET_DAILY_TOKENS", "50000"))
CHAT_BUDGET_DAILY_TOKENS = int(os.getenv("LLM_CHAT_BUDGET_DAILY_TOKENS", "200000"))

# Reserve enough for the system prompt + analytics JSON + the provider's
# max_tokens=350 response. If the provider reports fewer tokens, reconciliation
# immediately returns the unused amount to the daily budget.
INSIGHT_BUDGET_RESERVATION_TOKENS = int(
    os.getenv("INSIGHT_BUDGET_RESERVATION_TOKENS", "4096")
)

_LEDGER_EVENT = "llm_budget"
_SQLITE_LOCK = threading.Lock()

# Backward-compatible POC state/API. Kept for callers/tests that exercise the
# old helper directly; the live endpoint no longer relies on this process-local
# state.
_state: dict[int, dict[str, int]] = {}


def _today_iso() -> str:
    return date.today().isoformat()


def check_and_record_budget(user_id: int | None, tokens: int) -> tuple[bool, int]:
    """Legacy in-process helper retained for compatibility.

    Production request handling uses reserve_persistent_budget instead.
    """
    if user_id is None:
        return False, 0

    today = _today_iso()
    bucket = _state.setdefault(int(user_id), {})
    used = bucket.get(today, 0)
    proposed = used + max(int(tokens), 0)
    remaining_if_allowed = INSIGHT_BUDGET_DAILY_TOKENS - proposed

    if proposed > INSIGHT_BUDGET_DAILY_TOKENS:
        return False, max(INSIGHT_BUDGET_DAILY_TOKENS - used, 0)

    bucket[today] = proposed
    return True, max(remaining_if_allowed, 0)


def _utc_day_start() -> datetime:
    now = datetime.utcnow()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _ledger_rows(
    db,
    user_id: int,
    day_start: datetime | None = None,
) -> list[SecurityEvent]:
    start = day_start or _utc_day_start()
    end = start + timedelta(days=1)
    return (
        db.query(SecurityEvent)
        .filter(
            SecurityEvent.event_type == _LEDGER_EVENT,
            SecurityEvent.user_id == int(user_id),
            SecurityEvent.ts >= start,
            SecurityEvent.ts < end,
        )
        .order_by(SecurityEvent.id.asc())
        .all()
    )


def _find_reservation(
    db,
    user_id: int,
    reservation_id: str,
) -> SecurityEvent | None:
    """Find a recent reserve event without mixing its day into today's ledger."""
    cutoff = datetime.utcnow() - timedelta(days=2)
    rows = (
        db.query(SecurityEvent)
        .filter(
            SecurityEvent.event_type == _LEDGER_EVENT,
            SecurityEvent.user_id == int(user_id),
            SecurityEvent.ts >= cutoff,
        )
        .order_by(SecurityEvent.id.desc())
        .all()
    )
    for row in rows:
        details = row.details if isinstance(row.details, dict) else {}
        if (
            details.get("kind") == "reserve"
            and details.get("reservation_id") == reservation_id
        ):
            return row
    return None


def _ledger_used(rows: list[SecurityEvent], scope: str = "insights") -> int:
    total = 0
    for row in rows:
        details = row.details if isinstance(row.details, dict) else {}
        row_scope = str(details.get("scope") or "insights")
        if row_scope != scope:
            continue
        try:
            total += int(details.get("delta_tokens", 0) or 0)
        except (TypeError, ValueError):
            continue
    return max(total, 0)


def _lock_user_budget(db, user_id: int, dialect: str) -> None:
    """Serialize one user's budget mutation across workers/processes."""
    if dialect == "postgresql":
        # One stable 64-bit namespace + the 32-bit user id.
        lock_key = 0x5348000000000000 | (int(user_id) & 0xFFFFFFFF)
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
    elif dialect == "sqlite":
        # SQLite has no advisory locks. BEGIN IMMEDIATE obtains the database
        # write reservation before we inspect the current ledger.
        db.execute(text("BEGIN IMMEDIATE"))


def reserve_persistent_budget(
    user_id: int | None,
    tokens: int = INSIGHT_BUDGET_RESERVATION_TOKENS,
    *,
    scope: str = "insights",
    daily_limit: int | None = None,
) -> tuple[bool, int, str | None]:
    """Atomically reserve daily budget.

    Returns (allowed, remaining_after_reservation, reservation_id).
    A DB/locking failure fails closed because silently disabling a cost guard is
    worse than rejecting one generation.
    """
    if user_id is None:
        return False, 0, None

    uid = int(user_id)
    reserve = max(int(tokens), 0)
    budget_scope = str(scope or "insights")
    limit = INSIGHT_BUDGET_DAILY_TOKENS if daily_limit is None else max(int(daily_limit), 0)
    reservation_id = str(uuid.uuid4())

    db = db_module.SessionLocal()
    dialect = db.get_bind().dialect.name
    sqlite_locked = False
    try:
        if dialect == "sqlite":
            _SQLITE_LOCK.acquire()
            sqlite_locked = True
        _lock_user_budget(db, uid, dialect)
        used = _ledger_used(_ledger_rows(db, uid), budget_scope)
        proposed = used + reserve
        if proposed > limit:
            db.rollback()
            return False, max(limit - used, 0), None

        db.add(SecurityEvent(
            event_type=_LEDGER_EVENT,
            severity="info",
            user_id=uid,
            details={
                "kind": "reserve",
                "scope": budget_scope,
                "reservation_id": reservation_id,
                "budget_day": _today_iso(),
                "delta_tokens": reserve,
            },
        ))
        db.commit()
        return True, max(limit - proposed, 0), reservation_id
    except Exception:
        db.rollback()
        return False, 0, None
    finally:
        db.close()
        if sqlite_locked:
            _SQLITE_LOCK.release()


def reconcile_persistent_budget(
    user_id: int | None,
    reservation_id: str | None,
    reserved_tokens: int,
    actual_tokens: int,
) -> None:
    """Reconcile a reservation to provider-reported actual usage.

    Appends a delta row rather than mutating audit history. Repeated calls with
    the same reservation id are idempotent.
    """
    if user_id is None or not reservation_id:
        return

    uid = int(user_id)
    reserved = max(int(reserved_tokens), 0)
    actual = max(int(actual_tokens), 0)

    db = db_module.SessionLocal()
    dialect = db.get_bind().dialect.name
    sqlite_locked = False
    try:
        if dialect == "sqlite":
            _SQLITE_LOCK.acquire()
            sqlite_locked = True
        _lock_user_budget(db, uid, dialect)

        reservation = _find_reservation(db, uid, reservation_id)
        if reservation is None:
            db.rollback()
            return
        reservation_details = reservation.details if isinstance(reservation.details, dict) else {}
        budget_scope = str(reservation_details.get("scope") or "insights")

        # A request reserved just before UTC midnight can finish just after it.
        # Do not write the previous day's refund/overage into the new day's
        # allowance. Keeping the old reservation conservative is safer than
        # crediting today's budget with yesterday's unused tokens.
        if reservation.ts.date() != datetime.utcnow().date():
            db.rollback()
            return

        rows = _ledger_rows(db, uid)
        for row in rows:
            details = row.details if isinstance(row.details, dict) else {}
            if (
                details.get("kind") == "reconcile"
                and details.get("reservation_id") == reservation_id
            ):
                db.rollback()
                return

        db.add(SecurityEvent(
            event_type=_LEDGER_EVENT,
            severity="info",
            user_id=uid,
            details={
                "kind": "reconcile",
                "scope": budget_scope,
                "reservation_id": reservation_id,
                "delta_tokens": actual - reserved,
                "actual_tokens": actual,
                "reserved_tokens": reserved,
            },
        ))
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
        if sqlite_locked:
            _SQLITE_LOCK.release()


def reset_for_test() -> None:
    """Reset only the legacy in-process helper state."""
    _state.clear()
