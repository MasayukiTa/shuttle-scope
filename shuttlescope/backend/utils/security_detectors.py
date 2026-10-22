"""Security detections that were missing from the event stream.

A review of 5000 security_events and 5000 request_logs rows found that three
things which the owner must be told about were never raised:

  1. secret_path_200      A 200 response on a secret-file path (.env, .git/,
                          .aws/, wp-config, id_rsa, backup dumps ...).
  2. mfa_recovery_failures  Repeated failed MFA / recovery-code attempts.
  3. login_success_new_ip   A successful login from an IP never seen for that
                          user in the previous 30 days.

Where each detector runs:
  - secret path, backend : RequestLogMiddleware (middleware/security_observability.py)
                           calls record_secret_path_response() for every response
                           that FastAPI produced.
  - secret path, nginx   : tools/nginx_log_shipper.py calls it for requests that
                           nginx answered itself (no upstream). The backend cannot
                           see those.
  - MFA failures         : routers/auth.py (_record_mfa_failure) -> record_mfa_failure().
  - new login IP         : routers/auth.py (login / mfa_login) -> check_login_new_ip().

All functions swallow their own errors: a detector must never break a request.
Nothing here ever receives or stores a password, a token or a submitted MFA code.
"""
from __future__ import annotations

import ipaddress
import logging
import re
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from typing import Optional

from backend.utils.security_log import emit_security_event

_log = logging.getLogger("shuttlescope.security_detectors")

# ── thresholds ──────────────────────────────────────────────────────────────
# Reason for 3 / 600 s: the owner required "N>=3 failed MFA or recovery-code
# attempts for the same user or IP within 10 minutes". The existing hard limit in
# routers/auth.py (_MFA_MAX_FAILURES=10 per 600 s) only returns 429 and raised no
# event, so a 3..9 attempt guessing run left no trace (observed: zero
# mfa_recovery_failures rows in the 5000-event review).
MFA_FAILURE_THRESHOLD = 3
MFA_FAILURE_WINDOW_SEC = 600

# Reason for 30 days: the owner required "not seen for that user in the previous
# 30 days". request_logs.user_id was empty on every row at review time, so the
# lookup also uses access_logs (login actions), which do carry user_id and IP.
NEW_IP_LOOKBACK_DAYS = 30

# Reason for 3600 s: crawlers hit the decoy .env family hundreds of times per
# hour from one address; one decoy_hit per IP per hour keeps the record without
# flooding security_events (review: probe-class rows dominated the 5000 events).
DECOY_DEDUP_SEC = 3600

# Roles for which a new-IP login is "high"; everyone else is "medium".
PRIVILEGED_ROLES = frozenset({"admin", "analyst", "coach"})

# Upper bound on tracked keys so unauthenticated traffic cannot grow memory.
_MAX_TRACKED_KEYS = 10_000


# ── secret path patterns ────────────────────────────────────────────────────
_SECRET_PATH_PATTERNS = (
    r"(^|/)\.env([._~-][^/]*)?$",                   # .env, .env.bak, .env.production
    r"(^|/)\.(git|svn|hg|aws|ssh|docker)(/|$)",     # repo / cloud / key directories
    r"(^|/)wp-config",                              # wp-config.php, wp-config.php.bak
    r"(^|/)\.(htpasswd|htaccess|npmrc|pypirc|netrc)$",
    r"(^|/)id_(rsa|dsa|ecdsa|ed25519)$",            # ssh private keys
    r"(^|/)private\.key$",
    r"\.(pem|p12|pfx|ppk)$",
    r"(^|/)(sftp-config|credentials|secrets?)(\.(json|ya?ml|txt|ini))?$",
    r"\.(sql|sqlite3?|bak|dump)$",                  # dumps and backups
    r"(^|/)(backup|dump|db|database|site|www)[-_.\w]*\.(zip|tar|tgz|gz|7z|rar|tar\.gz)$",
)
_SECRET_PATH_RE = re.compile("|".join("(?:%s)" % p for p in _SECRET_PATH_PATTERNS))


def is_secret_path(path: Optional[str]) -> bool:
    """True when `path` names a file that must never be served."""
    if not path:
        return False
    return _SECRET_PATH_RE.search(path.lower().split("?", 1)[0]) is not None


# ── notification (existing admin webhook) ───────────────────────────────────
def _notify_sync(content: str) -> None:
    try:
        from backend.routers.auth_email import _notify_admin_webhook
        _notify_admin_webhook(content)
    except Exception:  # noqa: BLE001
        _log.warning("admin notify failed", exc_info=True)


def notify_admin(content: str) -> None:
    """Post to the existing admin webhook (SS_ADMIN_NOTIFY_WEBHOOK_URL).

    The webhook call can take up to 10 s, so it never runs on the request path."""
    try:
        threading.Thread(target=_notify_sync, args=(content,), daemon=True).start()
    except Exception:  # noqa: BLE001
        _log.warning("admin notify thread failed", exc_info=True)


def _recent_event_exists(event_type: str, ip: Optional[str], seconds: int) -> bool:
    if not ip:
        return False
    try:
        from backend.db.database import SessionLocal
        from backend.db.models import SecurityEvent
        cutoff = datetime.utcnow() - timedelta(seconds=seconds)
        db = SessionLocal()
        try:
            return (
                db.query(SecurityEvent.id)
                .filter(
                    SecurityEvent.event_type == event_type,
                    SecurityEvent.ip_addr == ip,
                    SecurityEvent.ts >= cutoff,
                )
                .first()
                is not None
            )
        finally:
            db.close()
    except Exception:  # noqa: BLE001
        return False


# ── 1. secret path 200 / decoy hit ──────────────────────────────────────────
def record_secret_path_response(
    *,
    path: str,
    status: int,
    is_decoy: bool,
    ip: Optional[str],
    method: Optional[str] = None,
    ua: Optional[str] = None,
    request_id: Optional[str] = None,
    country: Optional[str] = None,
    source: str = "backend",
    authenticated: bool = False,
    ts: Optional[datetime] = None,
) -> Optional[str]:
    """Classify a response on a secret path. Returns the event type raised, or None.

    is_decoy must be True only when the response came from the deliberate decoy
    (decoy_maze handlers set request.state.is_decoy and the fake .env also sends
    `X-Honeyfile: yes`). A 200 without that marker is a real leak: critical.
    """
    try:
        if status != 200 or not is_secret_path(path):
            return None
        # An authenticated API download such as an admin backup export is not a
        # leak by a stranger; do not page the owner for it.
        if authenticated and path.lower().startswith("/api/"):
            return None
        details = {"country": country, "source": source}
        if is_decoy:
            if _recent_event_exists("decoy_hit", ip, DECOY_DEDUP_SEC):
                return None
            emit_security_event(
                "decoy_hit", severity="low", ip_addr=ip, path=path, method=method,
                ua=ua, request_id=request_id, details=details, ts=ts,
            )
            return "decoy_hit"
        emit_security_event(
            "secret_path_200", severity="critical", ip_addr=ip, path=path,
            method=method, ua=ua, request_id=request_id, details=details, ts=ts,
        )
        notify_admin(
            "[ShuttleScope CRITICAL] secret_path_200: HTTP 200 on a secret path "
            f"(path={path[:200]} ip={ip} country={country} source={source}). "
            "This is NOT the decoy. Check whether a real file is being served."
        )
        return "secret_path_200"
    except Exception:  # noqa: BLE001
        _log.warning("record_secret_path_response failed", exc_info=True)
        return None


# ── 2. MFA / recovery code failures ─────────────────────────────────────────
_mfa_lock = threading.Lock()
_mfa_fail_times: dict[tuple[str, str], deque] = {}
_mfa_alerted_at: dict[tuple[str, str], float] = {}


def reset_mfa_failure_state() -> None:
    """Test helper."""
    with _mfa_lock:
        _mfa_fail_times.clear()
        _mfa_alerted_at.clear()


def _mfa_hit(key: tuple[str, str], now: float) -> int:
    """Record one failure for key; return the count in the window (lock held)."""
    if len(_mfa_fail_times) > _MAX_TRACKED_KEYS:
        cutoff = now - MFA_FAILURE_WINDOW_SEC
        for k in [k for k, d in _mfa_fail_times.items() if not d or d[-1] < cutoff]:
            _mfa_fail_times.pop(k, None)
            _mfa_alerted_at.pop(k, None)
        if len(_mfa_fail_times) > _MAX_TRACKED_KEYS:
            _mfa_fail_times.clear()
            _mfa_alerted_at.clear()
    dq = _mfa_fail_times.setdefault(key, deque())
    dq.append(now)
    cutoff = now - MFA_FAILURE_WINDOW_SEC
    while dq and dq[0] < cutoff:
        dq.popleft()
    return len(dq)


def record_mfa_failure(
    user_id: Optional[int], ip: Optional[str], kind: str = "totp"
) -> list[str]:
    """Count one failed MFA / recovery-code attempt for the user and the IP.

    kind is "totp" or "recovery"; the submitted code is never passed in.
    Raises one event per user/IP per window once the count reaches the threshold.
    Returns the scopes that raised an event (for tests)."""
    raised: list[str] = []
    try:
        now = time.time()
        hits: list[tuple[str, str, int]] = []
        with _mfa_lock:
            keys = []
            if user_id:
                keys.append(("user", str(user_id)))
            if ip:
                keys.append(("ip", str(ip)))
            for key in keys:
                count = _mfa_hit(key, now)
                if count < MFA_FAILURE_THRESHOLD:
                    continue
                last = _mfa_alerted_at.get(key)
                if last is not None and now - last < MFA_FAILURE_WINDOW_SEC:
                    continue
                _mfa_alerted_at[key] = now
                hits.append((key[0], key[1], count))
        for scope, ident, count in hits:
            emit_security_event(
                "mfa_recovery_failures", severity="high", ip_addr=ip,
                user_id=user_id,
                details={"scope": scope, "count": count, "kind": kind,
                         "window_sec": MFA_FAILURE_WINDOW_SEC},
            )
            notify_admin(
                "[ShuttleScope HIGH] mfa_recovery_failures: "
                f"{count} failed MFA/recovery attempts in {MFA_FAILURE_WINDOW_SEC // 60} min "
                f"(scope={scope} user_id={user_id} ip={ip} kind={kind})."
            )
            raised.append(scope)
    except Exception:  # noqa: BLE001
        _log.warning("record_mfa_failure failed", exc_info=True)
    return raised


# ── 3. login success from a new external IP ─────────────────────────────────
# access_logs actions that mean "this user logged in successfully".
_LOGIN_SUCCESS_ACTIONS = ("login", "login_mfa_ok", "login_mfa_recovery_used")


def _is_external_ip(ip: Optional[str]) -> bool:
    try:
        addr = ipaddress.ip_address((ip or "").strip())
    except ValueError:
        return False
    return not (addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_unspecified or addr.is_reserved)


def check_login_new_ip(
    *,
    user_id: Optional[int],
    role: Optional[str],
    ip: Optional[str],
    country: Optional[str],
    before: datetime,
    method: str = "password",
) -> Optional[str]:
    """Raise login_success_new_ip when this user has not been seen on `ip` in the
    last NEW_IP_LOOKBACK_DAYS days. `before` is a UTC time taken before the login
    wrote its own access_logs row, so the login being judged does not count as
    history. Returns the event type raised, or None."""
    try:
        if not user_id or not _is_external_ip(ip):
            return None
        from backend.db.database import SessionLocal
        from backend.db.models import AccessLog, RequestLog
        since = before - timedelta(days=NEW_IP_LOOKBACK_DAYS)
        db = SessionLocal()
        try:
            seen_ip = (
                db.query(AccessLog.id)
                .filter(
                    AccessLog.user_id == user_id,
                    AccessLog.ip_addr == ip,
                    AccessLog.action.in_(_LOGIN_SUCCESS_ACTIONS),
                    AccessLog.created_at >= since,
                    AccessLog.created_at < before,
                )
                .first()
                is not None
            ) or (
                db.query(RequestLog.id)
                .filter(
                    RequestLog.user_id == user_id,
                    RequestLog.ip_addr == ip,
                    RequestLog.ts >= since,
                    RequestLog.ts < before,
                )
                .first()
                is not None
            )
            if seen_ip:
                return None
            country_seen = None
            if country:
                country_seen = (
                    db.query(RequestLog.id)
                    .filter(
                        RequestLog.user_id == user_id,
                        RequestLog.country == country,
                        RequestLog.ts >= since,
                        RequestLog.ts < before,
                    )
                    .first()
                    is not None
                )
            any_history = (
                db.query(AccessLog.id)
                .filter(
                    AccessLog.user_id == user_id,
                    AccessLog.action.in_(_LOGIN_SUCCESS_ACTIONS),
                    AccessLog.created_at >= since,
                    AccessLog.created_at < before,
                )
                .first()
                is not None
            )
        finally:
            db.close()
        severity = "high" if (role or "") in PRIVILEGED_ROLES else "medium"
        emit_security_event(
            "login_success_new_ip", severity=severity, ip_addr=ip, user_id=user_id,
            details={"role": role, "country": country, "method": method,
                     "country_seen": country_seen, "first_login_in_window": not any_history,
                     "lookback_days": NEW_IP_LOOKBACK_DAYS},
        )
        notify_admin(
            f"[ShuttleScope {severity.upper()}] login_success_new_ip: "
            f"user_id={user_id} role={role} ip={ip} country={country} "
            f"(not seen in the last {NEW_IP_LOOKBACK_DAYS} days)."
        )
        return "login_success_new_ip"
    except Exception:  # noqa: BLE001
        _log.warning("check_login_new_ip failed", exc_info=True)
        return None
