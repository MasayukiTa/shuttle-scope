"""Game Day G-4: video_token 一斉再発行演習。

事前条件:
  - admin としてログイン可能
  - 試合データが存在 (1 件以上)

手順:
  1. 任意の試合の video_token を取得
  2. 旧 token で /api/videos/{token}/stream → 200 を確認
  3. POST /api/admin/security/reissue_all_video_tokens を実行
  4. 旧 token で再リクエスト → 404 (即無効化) を確認
  5. 試合一覧を再取得 → 新 token で再生 OK を確認
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

    print("=== Game Day G-4: Mass video_token Reissue ===")
    start = time.time()

    print("\n[1] admin ログイン")
    tok = login(ADMIN_USER, ADMIN_PASS)
    if not tok:
        print("FAIL: ログイン失敗")
        return 1

    print("\n[2] 試合の video_token を取得")
    s, body = req("GET", "/api/matches?limit=10", token=tok)
    if s != 200:
        print(f"FAIL: 試合一覧取得失敗 status={s}")
        return 1
    items = json.loads(body).get("data") or []
    target = None
    for it in items:
        if it.get("video_token"):
            target = it
            break
    if target is None:
        print("FAIL: video_token を持つ試合がない (PUT /api/matches で video_local_path を設定してから再実行)")
        return 1
    old_tok = target["video_token"]
    match_id = target["id"]
    print(f"  match_id={match_id} old_token={old_tok}")

    print("\n[3] 旧 token で動画 stream → 200 期待")
    s, _ = req("HEAD", f"/api/videos/{old_tok}/stream", token=tok)
    print(f"  HEAD status: {s}")

    print("\n[4] reissue_all_video_tokens 実行 (本当に全試合の token が変わる)")
    confirm = input("  続行しますか? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("  中止しました")
        return 0
    s, body = req("POST", "/api/admin/security/reissue_all_video_tokens",
                  body={}, token=tok)
    print(f"  status={s} body={body[:200].decode('utf-8', errors='replace')}")

    print("\n[5] 旧 token で再リクエスト → 404 期待")
    s, _ = req("HEAD", f"/api/videos/{old_tok}/stream", token=tok)
    print(f"  HEAD status (旧 token): {s}")
    if s == 404:
        print("  ✅ 期待通り: 旧 token が即無効化された")
    else:
        print(f"  ❌ 失敗: 旧 token がまだ生きている (status={s})")

    print("\n[6] 試合一覧を再取得して新 token を確認")
    s, body = req("GET", f"/api/matches/{match_id}", token=tok)
    if s == 200:
        new_data = json.loads(body).get("data", {})
        new_tok = new_data.get("video_token")
        print(f"  new_token={new_tok}")
        if new_tok and new_tok != old_tok:
            s2, _ = req("HEAD", f"/api/videos/{new_tok}/stream", token=tok)
            print(f"  新 token HEAD status: {s2} (200 期待)")

    elapsed = time.time() - start
    print(f"\n=== 完了 (elapsed={elapsed:.1f}s) ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
