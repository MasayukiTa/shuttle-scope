"""Game Day G-3: Export 署名鍵ローテ → 旧 export 即無効化演習。

事前条件:
  - SS_EXPORT_SIGNING_KEY が設定済み
  - admin としてログイン可能

手順:
  1. admin として export を 1 回実行 → JSON 取得 (旧鍵で署名)
  2. .env.development の SS_EXPORT_SIGNING_KEY を新値に更新
  3. backend 再起動 (手動)
  4. 旧 export を import 試行 → 403 (署名検証失敗) を確認
  5. 新規に export → 新鍵で署名されたものは正常に import 可能

このスクリプトは [1] の export 取得と、[4] の import 試行のみ自動化する。
[2][3] は手動実行 (鍵ファイル編集 + サービス再起動)。
"""
from __future__ import annotations

import http.client
import json
import os
import ssl
import sys
import time

HOST = os.environ.get("GAMEDAY_HOST", "app.shuttle-scope.com")
ADMIN_USER = os.environ.get("GAMEDAY_ADMIN_USER", "")
ADMIN_PASS = os.environ.get("GAMEDAY_ADMIN_PASS", "")


def conn():
    return http.client.HTTPSConnection(HOST, context=ssl.create_default_context(), timeout=15)


def req(method, path, body=None, token=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    c = conn()
    try:
        b = json.dumps(body).encode("utf-8") if body else None
        c.request(method, path, body=b, headers=h)
        r = c.getresponse()
        return r.status, r.read()
    finally:
        c.close()


def login(user, pw):
    s, body = req("POST", "/api/auth/login",
                  body={"grant_type": "password", "username": user, "password": pw})
    if s == 200:
        try:
            return json.loads(body).get("access_token")
        except Exception:
            return None
    return None


def main() -> int:
    if not ADMIN_USER or not ADMIN_PASS:
        print("ERROR: GAMEDAY_ADMIN_USER / GAMEDAY_ADMIN_PASS を設定してください")
        return 1

    print("=== Game Day G-3: Export Key Rotation ===")
    start = time.time()

    print("\n[1] admin ログイン")
    tok = login(ADMIN_USER, ADMIN_PASS)
    if not tok:
        print("FAIL: ログイン失敗")
        return 1

    # 任意の試合 ID を取得
    s, body = req("GET", "/api/matches?limit=1", token=tok)
    if s != 200:
        print("FAIL: 試合一覧取得失敗")
        return 1
    items = json.loads(body).get("data") or []
    if not items:
        print("FAIL: 試合データが存在しない")
        return 1
    match_id = items[0]["id"]
    print(f"  使用する match_id: {match_id}")

    print(f"\n[2] 旧鍵で export 取得")
    s, body = req("GET", f"/api/export/package?match_id={match_id}", token=tok)
    if s != 200:
        print(f"FAIL: export 失敗 status={s}")
        return 1
    old_pkg = json.loads(body)
    nonce = old_pkg.get("_nonce", "?")
    sig = old_pkg.get("_signature", "?")[:16]
    print(f"  nonce={nonce} signature={sig}...")

    print("\n[3] **手動操作が必要**")
    print("  a) .env.development の SS_EXPORT_SIGNING_KEY を新しい値に置換:")
    print('     python -c "import secrets; print(secrets.token_hex(32))"')
    print("  b) backend を再起動 (start.bat または PM2 restart)")
    input("\n  完了したら Enter を押してください: ")

    print("\n[4] 旧鍵で署名された export を import 試行")
    s, body = req("POST", "/api/import/package", body=old_pkg, token=tok)
    print(f"  status={s} body={body[:200].decode('utf-8', errors='replace')}")
    if s == 403:
        print("  ✅ 期待通り: 旧 export が署名検証失敗で拒否された")
    else:
        print(f"  ❌ 失敗: 旧 export が拒否されなかった (status={s})")

    print("\n[5] 新鍵で export → import が通るか確認")
    s, body = req("GET", f"/api/export/package?match_id={match_id}", token=tok)
    if s == 200:
        new_pkg = json.loads(body)
        s2, body2 = req("POST", "/api/import/package", body=new_pkg, token=tok)
        print(f"  新 export → import status={s2}")
        if s2 in (200, 201):
            print("  ✅ 新鍵での export → import OK")

    elapsed = time.time() - start
    print(f"\n=== 完了 (elapsed={elapsed:.1f}s) ===")
    print("docs/incident_response/drills/ に結果を記録してください")
    return 0


if __name__ == "__main__":
    sys.exit(main())
