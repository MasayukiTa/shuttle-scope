"""Game Day G-2: 全 JWT 失効 → 再ログイン演習。

事前条件:
  - 検証用環境であること
  - admin アカウントとパスワードが手元にあること

手順:
  1. 演習前: admin が普通に GET /api/users/me できることを確認
  2. POST /api/admin/security/revoke_all_tokens を実行
  3. 既存トークンで再リクエスト → 401 が返ることを確認
  4. 再ログイン → 新トークンで GET /api/users/me が成功することを確認
"""
from __future__ import annotations

import http.client
import json
import os
import ssl
import sys
import time
from typing import Optional

# 環境変数で接続先を切り替え
HOST = os.environ.get("GAMEDAY_HOST", "app.shuttle-scope.com")
USE_SSL = os.environ.get("GAMEDAY_USE_SSL", "1") == "1"
ADMIN_USER = os.environ.get("GAMEDAY_ADMIN_USER", "")
ADMIN_PASS = os.environ.get("GAMEDAY_ADMIN_PASS", "")


def conn():
    if USE_SSL:
        return http.client.HTTPSConnection(HOST, context=ssl.create_default_context(), timeout=15)
    return http.client.HTTPConnection(HOST, timeout=15)


def req(method: str, path: str, body: Optional[dict] = None, token: Optional[str] = None) -> tuple[int, str]:
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    c = conn()
    try:
        b = json.dumps(body).encode("utf-8") if body else None
        c.request(method, path, body=b, headers=h)
        r = c.getresponse()
        return r.status, r.read().decode("utf-8", errors="replace")
    finally:
        c.close()


def login(user: str, pw: str) -> Optional[str]:
    s, body = req("POST", "/api/auth/login", body={
        "grant_type": "password", "username": user, "password": pw,
    })
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

    print("=== Game Day G-2: Token Compromise ===")
    start = time.time()

    print("\n[1] 演習前: admin ログイン")
    tok1 = login(ADMIN_USER, ADMIN_PASS)
    if not tok1:
        print("FAIL: admin ログイン失敗")
        return 1
    s, _ = req("GET", "/api/auth/me", token=tok1)
    print(f"  /api/auth/me with old token: {s}")
    assert s == 200, "演習前にトークンが既に無効"

    print("\n[2] 全トークン失効を実行")
    s, body = req("POST", "/api/admin/security/revoke_all_tokens", body={}, token=tok1)
    print(f"  status={s} body={body[:200]}")

    print("\n[3] 既存トークンで再リクエスト → 401 期待")
    s, _ = req("GET", "/api/auth/me", token=tok1)
    print(f"  /api/auth/me with revoked token: {s}")

    print("\n[4] 再ログイン")
    tok2 = login(ADMIN_USER, ADMIN_PASS)
    if not tok2:
        print("FAIL: 再ログイン失敗")
        return 1
    s, _ = req("GET", "/api/auth/me", token=tok2)
    print(f"  /api/auth/me with new token: {s}")
    assert s == 200, "新トークンでも認証失敗"

    elapsed = time.time() - start
    print(f"\n=== 完了 (elapsed={elapsed:.1f}s) ===")
    print("docs/incident_response/drills/ に結果記録してください")
    return 0


if __name__ == "__main__":
    sys.exit(main())
