"""Crawler recognition and signed decoy URLs for the decoy maze.

Observed reason (full request_logs export): Microsoft crawler ranges
(40.77.*, 52.167.*, 157.55.*, 207.46.* = bingbot and friends) fetched thousands
of decoy URLs such as /admin/media.tar.gz, /admin/services.zst, /admin/home.gz
and /admin/.env.gz/settings and received 200 for each, because the /admin and
/internal catch-alls answered 200 for any path and every page linked deeper.
They had no security_events yet, but the ban escalation would have banned them.

Policy:
  - A crawler is never counted as an attacker: no note_hit, no escalation, no
    ip_ban / Cloudflare ban. It is recorded once per IP per day as the low
    severity event 'crawler_decoy_visit'.
  - Deep maze levels are only valid when the URL carries a server signature
    (HMAC over the path) that the decoy itself emitted, and never for crawlers.

Trade-off: a crawler is recognised by its declared User-Agent or by an IP prefix.
A User-Agent is not verified (no reverse-DNS in the request path), so an attacker
who spoofs "bingbot" is also not banned by the decoy. The decoy still records the
visit. Verify with reverse DNS offline if this matters.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
from typing import Optional

from backend.utils.security_detectors import _recent_event_exists
from backend.utils.security_log import emit_security_event

_log = logging.getLogger("shuttlescope.crawler_policy")

# Single configuration point. Lower-case substrings of the User-Agent.
CRAWLER_UA_TOKENS: tuple[str, ...] = (
    "bingbot", "msnbot", "bingpreview", "adidxbot", "ahrefsbot", "googlebot",
    "duckduckbot", "duckassistbot", "pangubot", "applebot", "semrushbot",
    "mj12bot", "yandexbot", "baiduspider", "petalbot", "dotbot", "bytespider",
    "gptbot", "claudebot", "ccbot", "amazonbot", "facebookexternalhit",
)

# Observed in the request_logs export: Microsoft crawler ranges that walked the
# maze. OVH ranges were mentioned but could not be verified in the data available
# to this change, so they are deliberately NOT listed; add them here once seen.
CRAWLER_IP_PREFIXES: tuple[str, ...] = ("40.77.", "52.167.", "157.55.", "207.46.")

# One crawler_decoy_visit per IP per day (a crawler revisits thousands of times).
CRAWLER_VISIT_DEDUP_SEC = 24 * 3600

ROBOTS_TAG = "noindex, nofollow, noarchive"

# Every top-level decoy prefix, for robots.txt. Honest crawlers that obey it stay
# out; the trade-off is that listing them in robots.txt also tells a human
# attacker where the decoys are, which is acceptable because the maze is a decoy.
DECOY_ROBOTS_DISALLOW: tuple[str, ...] = (
    "/admin", "/internal", "/administrator", "/wp-admin", "/wp-login.php",
    "/phpmyadmin", "/pma", "/cpanel", "/webadmin", "/manager",
    "/backup", "/config", "/app", "/.env", "/.git", "/.aws", "/.ssh",
    "/db.sqlite", "/dump.sql", "/backup.sql", "/backup.tar.gz",
)


def robots_txt() -> str:
    lines = ["User-agent: *"] + [f"Disallow: {p}" for p in DECOY_ROBOTS_DISALLOW]
    return "\n".join(lines) + "\n"


def crawler_reason(ip: Optional[str], ua: Optional[str]) -> Optional[str]:
    """Why this request counts as a crawler, or None."""
    low = (ua or "").lower()
    for tok in CRAWLER_UA_TOKENS:
        if tok in low:
            return f"ua:{tok}"
    for pre in CRAWLER_IP_PREFIXES:
        if (ip or "").startswith(pre):
            return f"ip:{pre}"
    return None


def is_crawler(ip: Optional[str], ua: Optional[str]) -> bool:
    return crawler_reason(ip, ua) is not None


def record_crawler_decoy_visit(
    ip: Optional[str], path: str, ua: Optional[str], method: Optional[str]
) -> None:
    try:
        if _recent_event_exists("crawler_decoy_visit", ip, CRAWLER_VISIT_DEDUP_SEC):
            return
        emit_security_event(
            "crawler_decoy_visit", severity="low", ip_addr=ip, path=path,
            method=method, ua=ua, details={"reason": crawler_reason(ip, ua)},
        )
    except Exception:  # noqa: BLE001
        _log.warning("record_crawler_decoy_visit failed", exc_info=True)


# ── signed maze URLs ────────────────────────────────────────────────────────
def _key() -> bytes:
    k = (os.environ.get("SS_MAZE_SIGNING_KEY") or "").strip()
    if not k:
        try:
            from backend.config import settings
            k = settings.SECRET_KEY or ""
        except Exception:  # noqa: BLE001
            k = ""
    return k.encode("utf-8")


def sign_path(path: str) -> str:
    """Signature the decoy appends to deep links ('' when no key is available)."""
    key = _key()
    if not key:
        return ""
    return hmac.new(key, b"maze:" + path.encode("utf-8"), hashlib.sha256).hexdigest()[:24]


def verify_path(path: str, sig: Optional[str]) -> bool:
    expected = sign_path(path)
    return bool(expected) and bool(sig) and hmac.compare_digest(expected, sig)


def signed_url(path: str) -> str:
    sig = sign_path(path)
    return f"{path}?k={sig}" if sig else path
