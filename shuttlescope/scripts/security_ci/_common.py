# -*- coding: utf-8 -*-
"""CI 用 共通ヘルパ — 無認証で動く攻撃のみ。

環境変数:
  SS_ATTACK_HOST  対象ホスト (default: app.shuttle-scope.com)
  SS_ATTACK_PORT  対象ポート (default: 443)
  SS_ATTACK_INSECURE  "1" で TLS 検証をスキップ (ローカル backend 用)
"""
import json, ssl, http.client, sys, io, os, time, socket
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HOST = os.environ.get("SS_ATTACK_HOST", "app.shuttle-scope.com")
PORT = int(os.environ.get("SS_ATTACK_PORT", "443"))
INSECURE = os.environ.get("SS_ATTACK_INSECURE", "0") == "1"

if INSECURE:
    # opt-in via SS_ATTACK_INSECURE=1, used only for local backend
    CTX = ssl._create_unverified_context()  # nosec B323
else:
    CTX = ssl.create_default_context()


# Transient network failures that justify a retry. These are faults of the
# transport (production edge cold path / jitter), NOT of the app's auth
# decision. An HTTP status is never retried: that would change what the attack
# suite concludes. Only connection/read-level transport errors are retried.
_TRANSIENT = (
    TimeoutError,
    socket.timeout,
    ConnectionError,                     # incl. ConnectionReset/Refused/Aborted
    http.client.RemoteDisconnected,
    http.client.BadStatusLine,           # peer closed before status line
)

# Per-attempt timeout (seconds). Kept short so a single stalled edge connection
# fails fast and is retried on a fresh connection, instead of blocking the whole
# attempt for the old 30s. Total worst-case wall time across retries
# (15+15+15 + backoff 1+2 = ~48s) is of the same order as the former single 30s
# hang, so this hardens the client without merely inflating the timeout.
DEFAULT_TIMEOUT = float(os.environ.get("SS_ATTACK_TIMEOUT", "15"))
MAX_ATTEMPTS = int(os.environ.get("SS_ATTACK_RETRIES", "3"))


def _connect(_h, _p, timeout):
    if _p == 443:
        return http.client.HTTPSConnection(_h, context=CTX, timeout=timeout)
    elif _p == 80:
        return http.client.HTTPConnection(_h, timeout=timeout)
    return http.client.HTTPSConnection(_h, _p, context=CTX, timeout=timeout)


def req(m, p, body=None, headers=None, host=None, port=None, timeout=None,
        attempts=None):
    """Send one request, retrying only on transient transport errors.

    Returns (status, headers_dict, body) exactly as before. A read/connect
    timeout no longer escapes as an uncaught exception on the first blip; it is
    retried on a fresh connection with exponential backoff. If every attempt
    hits a transient transport error, the last exception is re-raised so a
    genuinely unreachable target still surfaces (callers decide WARN vs fail).
    """
    h = {"Content-Type": "application/json"}
    if headers: h.update(headers)
    _h = host or HOST
    _p = port or PORT
    _timeout = DEFAULT_TIMEOUT if timeout is None else timeout
    _attempts = MAX_ATTEMPTS if attempts is None else attempts
    if isinstance(body, dict): body = json.dumps(body).encode()
    elif isinstance(body, str): body = body.encode()

    last_exc = None
    for attempt in range(_attempts):
        c = None
        try:
            c = _connect(_h, _p, _timeout)
            c.request(m, p, body=body, headers=h)
            r = c.getresponse()
            return r.status, dict(r.getheaders()), r.read()
        except _TRANSIENT as e:
            last_exc = e
            try:
                if c is not None: c.close()
            except Exception:
                pass
            if attempt < _attempts - 1:
                time.sleep(2 ** attempt)  # 1s, 2s, ... backoff before retry
            continue
    raise last_exc


def wait_until_ready(path="/api/health", attempts=6, timeout=None):
    """Warm up the target before the suites run.

    The first request to a cold production edge path is the slow one (it is what
    timed out intermittently). We poll /api/health until it answers so that the
    heavy first round-trip is paid here, once, with its own generous retry
    budget, rather than inside an attack probe that has no try/except.

    Returns True if the target answered (any HTTP status means the edge is up),
    False if it never answered within the budget. Never raises.
    """
    _timeout = DEFAULT_TIMEOUT if timeout is None else timeout
    for attempt in range(attempts):
        try:
            status, _, _ = req("GET", path, timeout=_timeout, attempts=1)
            print(f"[*] warmup {path}: HTTP {status} (attempt {attempt + 1})")
            return True
        except Exception as e:
            print(f"[*] warmup {path}: {type(e).__name__} (attempt {attempt + 1})")
            if attempt < attempts - 1:
                time.sleep(2 ** min(attempt, 3))  # 1,2,4,8,8,8 backoff
    print(f"[!] warmup {path}: target not ready after {attempts} attempts")
    return False


def hget(headers, name, default=""):
    """headers (dict) から大文字小文字を無視してヘッダ値を取得する。

    http.client の getheaders() はサーバが送った元の大文字小文字を保持する
    (例: "X-Frame-Options")。req() はそれをそのまま dict 化するため、呼び出し側が
    小文字キーで h.get("x-frame-options") のように引くと常に None/default になり
    偽陽性 (permanent false HIGH) を生む。必ずこのヘルパー経由で引くこと。
    """
    name_lower = name.lower()
    for k, v in headers.items():
        if k.lower() == name_lower:
            return v
    return default


def short(b, n=140):
    if isinstance(b, bytes):
        return b.decode("utf-8", "replace")[:n]
    return str(b)[:n]


def is_expected_decoy(path: str, body: bytes | str) -> bool:
    """Return True only for known intentional deception responses.

    A bare HTTP 200 is never enough: each decoy needs stable content markers so
    a future real leak at the same path cannot be silently reclassified as safe.
    """
    raw = body if isinstance(body, bytes) else str(body).encode("utf-8", "replace")
    if path == "/graphql":
        return all(
            marker in raw
            for marker in (
                b'"__schema"',
                b'"AdminToken"',
                b'"BackupSecret"',
                b'"InternalConfig"',
            )
        )
    if path == "/dump.sql":
        return all(
            marker in raw
            for marker in (
                b"ShuttleScope DB dump (fake honeypot)",
                b"ss_canary_admin_live_",
                b"ss_canary_backup_pass_",
            )
        )
    return False


class Findings:
    """CRITICAL/HIGH/MEDIUM/LOW を集計し、CRITICAL があれば exit 1"""
    def __init__(self, suite):
        self.suite = suite
        self.rows = []

    def passed(self, label, msg=""):
        self.rows.append(("PASS", label, msg))
        print(f"  ✅ {label}: {msg[:120]}")

    def critical(self, label, msg=""):
        self.rows.append(("CRITICAL", label, msg))
        print(f"  🔴 CRITICAL {label}: {msg[:120]}")

    def high(self, label, msg=""):
        self.rows.append(("HIGH", label, msg))
        print(f"  🟧 HIGH {label}: {msg[:120]}")

    def warn(self, label, msg=""):
        self.rows.append(("WARN", label, msg))
        print(f"  ⚠️  {label}: {msg[:120]}")

    def info(self, label, msg=""):
        self.rows.append(("INFO", label, msg))

    def summary(self):
        crit = sum(1 for r in self.rows if r[0] == "CRITICAL")
        high = sum(1 for r in self.rows if r[0] == "HIGH")
        warn = sum(1 for r in self.rows if r[0] == "WARN")
        passed = sum(1 for r in self.rows if r[0] == "PASS")
        print(f"\n=== [{self.suite}] CRITICAL={crit} HIGH={high} WARN={warn} PASS={passed} ===")
        return crit, high, warn, passed
