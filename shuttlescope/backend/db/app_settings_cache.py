"""Short-TTL process-local cache for app_settings reads.

Why this exists (2026-11-06 production incident):
    The production backend showed five connections stuck in
    ``idle in transaction``. The longest (one day, twenty hours) had
    ``SELECT value FROM app_settings WHERE key=$1`` as its last statement.

    The root cause is NOT a leaked/unclosed session. Every ``SessionLocal()``
    in the backend is paired with ``close()``/``finally``/``with``. The problem
    is that the read-only settings helpers in ``routers/tracknet.py`` and
    ``routers/yolo.py`` run a ``SELECT`` on ``autocommit=False`` sessions and
    never ``commit``/``rollback``. When one of those helpers is called on a
    long-lived background session -- ``routers/tracknet.py::_run_batch`` opens a
    ``SessionLocal()`` and holds it for the entire video pass (minutes to hours)
    -- that ``SELECT`` stays the "last statement" and the connection reports
    ``idle in transaction`` for as long as the batch runs.

    Two defences are applied:
      1. The helpers rollback after reading (see routers/*.py) so the open
         read-only transaction is released immediately.
      2. This cache removes the DB round trip entirely while the value is
         fresh, so a batch that reads the same key repeatedly does not reopen
         a read transaction each time.

The cache is intentionally tiny and dependency-free so it is safe to import
from request handlers and from background threads alike. It is process-local;
settings are host-wide (admin-only) and change rarely, so a few seconds of
staleness across processes is acceptable. Writers (routers/settings.py) call
``invalidate()`` after an UPSERT so the next read reflects the change promptly.

No Windows-specific behaviour: uses ``time.monotonic`` and a plain lock.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional

# Default freshness window. Settings are host-wide and change rarely, so a
# short TTL collapses the repeated reads a single CV batch performs without
# making operator changes feel unresponsive. Kept small on purpose.
DEFAULT_TTL_SECONDS: float = 5.0

_lock = threading.Lock()
# key -> (expires_at_monotonic, value)
_store: dict[str, tuple[float, Any]] = {}


def _now() -> float:
    return time.monotonic()


def get_or_load(
    key: str,
    loader: Callable[[], Any],
    ttl: float = DEFAULT_TTL_SECONDS,
) -> Any:
    """Return a cached value for ``key`` or compute it via ``loader``.

    ``loader`` is only invoked on a miss or after the TTL elapses. The loader
    runs OUTSIDE the lock so a slow DB read does not serialise other keys; a
    benign double-load under a race is acceptable (idempotent read).
    """
    now = _now()
    with _lock:
        hit = _store.get(key)
        if hit is not None and hit[0] > now:
            return hit[1]
    value = loader()
    with _lock:
        _store[key] = (now + ttl, value)
    return value


def peek(key: str) -> Optional[Any]:
    """Return a fresh cached value or ``None`` (test/debug helper)."""
    now = _now()
    with _lock:
        hit = _store.get(key)
        if hit is not None and hit[0] > now:
            return hit[1]
    return None


def invalidate(key: Optional[str] = None) -> None:
    """Drop one key, or the whole cache when ``key`` is None.

    Called by settings writers after an UPSERT so a subsequent read does not
    serve a stale value.
    """
    with _lock:
        if key is None:
            _store.clear()
        else:
            _store.pop(key, None)


def clear() -> None:
    """Alias for a full invalidate; used by test fixtures."""
    invalidate(None)
