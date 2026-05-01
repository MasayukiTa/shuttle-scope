# -*- coding: utf-8 -*-
"""CI 用 共通ヘルパ — 無認証で動く攻撃のみ。

環境変数:
  SS_ATTACK_HOST  対象ホスト (default: app.shuttle-scope.com)
  SS_ATTACK_PORT  対象ポート (default: 443)
  SS_ATTACK_INSECURE  "1" で TLS 検証をスキップ (ローカル backend 用)
"""
import json, ssl, http.client, sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HOST = os.environ.get("SS_ATTACK_HOST", "app.shuttle-scope.com")
PORT = int(os.environ.get("SS_ATTACK_PORT", "443"))
INSECURE = os.environ.get("SS_ATTACK_INSECURE", "0") == "1"

if INSECURE:
    CTX = ssl._create_unverified_context()
else:
    CTX = ssl.create_default_context()


def req(m, p, body=None, headers=None, host=None, port=None, timeout=30):
    h = {"Content-Type": "application/json"}
    if headers: h.update(headers)
    _h = host or HOST
    _p = port or PORT
    if _p == 443:
        c = http.client.HTTPSConnection(_h, context=CTX, timeout=timeout)
    elif _p == 80:
        c = http.client.HTTPConnection(_h, timeout=timeout)
    else:
        c = http.client.HTTPSConnection(_h, _p, context=CTX, timeout=timeout)
    if isinstance(body, dict): body = json.dumps(body).encode()
    elif isinstance(body, str): body = body.encode()
    c.request(m, p, body=body, headers=h)
    r = c.getresponse()
    return r.status, dict(r.getheaders()), r.read()


def short(b, n=140):
    if isinstance(b, bytes):
        return b.decode("utf-8", "replace")[:n]
    return str(b)[:n]


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
