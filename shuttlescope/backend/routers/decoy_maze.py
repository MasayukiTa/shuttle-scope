"""Decoy maze (R44) — 偽ページ・偽 API による attacker time-sink。

戦略:
  - 攻撃者が叩きそうな enumeration path を全部受けて 200/302 で誘導する。
  - 偽 admin login / 偽 admin dashboard / 偽 .env / 偽 DB dump / 偽 backup zip
  - すべて honeytoken を仕込んだ "それらしい" コンテンツを返す。
  - 大量の偽リンクを散りばめ、攻撃者の自動 crawler を再帰的に泳がせる。
  - 挑発メッセージを HTML コメントや response header に JP/EN ミックスで仕込む。
    SOC / red team が見たら笑える程度の、攻撃者だけが踏む intentional taunting。
  - 全 hit を attacker_swim.note_hit() で記録 → 将来の防御に活用。

注意:
  - これらの path はすべて include_in_schema=False で OpenAPI に出さない。
  - レスポンスは固定 + 軽量。重い処理は絶対起こさない。
  - 真の攻撃 (XSS payload を埋めるなど) は一切しない。あくまで自陣に閉じる。
"""
from __future__ import annotations

import asyncio
import html as _html
import logging
import random
import re as _re_decoy
import time
from typing import Optional


# CodeQL py/reflective-xss 対策: URL path 由来の `rest` を HTML テンプレートに
# 直挿しすると XSS リフレクション。decoy 用途であっても admin が phishing
# 経由で踏むと自身のブラウザでスクリプトが実行されうるので、必ず sanitize する。
_SAFE_PATH_RE = _re_decoy.compile(r"[^A-Za-z0-9._\-/]")


def _safe_path_segment(s: str, max_len: int = 200) -> str:
    """URL path 由来の文字列を HTML / URL に埋めるための sanitize。
    `[A-Za-z0-9._\\-/]` 以外を `_` に置換し、長さも制限する。
    """
    if not isinstance(s, str):
        s = str(s)
    if len(s) > max_len:
        s = s[:max_len]
    return _SAFE_PATH_RE.sub("_", s)

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response

logger = logging.getLogger(__name__)

router = APIRouter()

# 含めるべき全 honeytoken (R42/R43 と一貫)
_HONEYTOKENS = {
    "admin_api_key": "ss_canary_admin_live_a8f3c91b2e5d7a40bf6e2c1d4f9a8b3c",
    "backup_pass":   "ss_canary_backup_pass_2025_X8nQv3mZpKr7tL9wYeJfHaBc",
    "video_token":   "ss_canary_video_token_legacy_5fA9c2Bd7eE1fG3hI8jK0l",
    "refresh_seed":  "ss_canary_refresh_v1_b7d4e2a8c6f9013579ace02468135790",
    "worker_key":    "ss_canary_frontend_dbg_W0rK3rPr0duct10nK3y2024XYZ12",
    "xfer_token":    "ss_canary_internal_xfer_M3m0ryDump_C4n4ry_T0k3n_99",
    "staged_lure":   "ss_canary_lure_staged_R3sp0nseBait_2026_xY7zQ",
}


# 挑発メッセージ (JP / EN ミックス、HTML コメントや headers に仕込む)
_TAUNTS = [
    "<!-- you came a long way. we logged every byte. -->",
    "<!-- ご苦労様。あなたの行動は全て記録されています。 -->",
    "<!-- nice scanner. how does it feel to waste 47 minutes here? -->",
    "<!-- 何を探してるんですか？ ヒント: ここには何もありません -->",
    "<!-- the cake is a lie. so is this endpoint. -->",
    "<!-- if you're a researcher, hello. drop us a line. -->",
    "<!-- 攻撃ログは将来の防御に貴重なデータです。ありがとう -->",
    "<!-- this is not the .env you are looking for -->",
    "<!-- お探しのファイルは別の城にいます -->",
    "<!-- enjoy your stay. we sure are. -->",
]


def _taunt() -> str:
    return random.choice(_TAUNTS)


def _client_ip(request: Request) -> str:
    cf = (request.headers.get("cf-connecting-ip") or "").strip()
    if cf:
        return cf
    xff = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if xff:
        return xff
    return request.client.host if request.client else "?"


# 同時 tarpit 数の上限 (self-DoS 防止)。これを超えたら sleep せずに即応答。
# decoy_maze は全 path に広く効くので canary より多めに枠を取る。
_MAZE_MAX_CONCURRENT = 128
_maze_sem = asyncio.Semaphore(_MAZE_MAX_CONCURRENT)


async def _record_and_delay(request: Request, kind: str, detail: str,
                             min_s: float = 0.5, max_s: float = 3.0) -> None:
    """hit を記録し、tarpit する。delay は短めにして攻撃者を「進んでる」と
    錯覚させる (= 完全 freeze だと諦めて他所行くので逆効果)。

    semaphore が空いていない (= 同時 tarpit 数が上限) 場合は sleep を諦めて
    即 return する。これで flood 系攻撃でも self-DoS にならない。
    """
    ip = _client_ip(request)
    try:
        from backend.utils.attacker_swim import note_hit
        note_hit(ip, kind=kind, detail=detail)
    except Exception:
        pass
    # R45 escalation: decoy_maze 500 hits → 60s, 3000 hits → 600s ban
    # 帯域消費が酷い場合だけ短時間 edge から弾く (maze 探索の自然な範疇では
    # 発火しない閾値)。kill-switch SS_DISABLE_AUTO_CF_BAN=1 で OFF。
    # R47: 自己テスト用 allowlist (IP / header) があれば ban 経路を skip。
    import os as _os
    if (_os.environ.get("SS_DISABLE_AUTO_CF_BAN") or "").strip() != "1":
        try:
            from backend.utils.ban_allowlist import is_ban_allowlisted
            from backend.utils.escalation_policy import record_hit_and_decide
            if not is_ban_allowlisted(ip, dict(request.headers)):
                decision = record_hit_and_decide(ip, "decoy_maze")
                if decision is not None:
                    from backend.routers.canary import _trigger_cf_auto_ban
                    _trigger_cf_auto_ban(
                        ip, f"decoy_maze_flood:{detail[:60]}",
                        confidence=decision["confidence"],
                        ttl_sec=decision["ttl_sec"],
                    )
        except Exception:
            pass
    # cap 越えで即 return (攻撃者には「速く返ってきた」とだけ見える)
    if _maze_sem.locked() and _maze_sem._value <= 0:  # type: ignore[attr-defined]
        return
    try:
        async with _maze_sem:
            await asyncio.sleep(random.uniform(min_s, max_s))
    except Exception:
        return


# ─── 偽 admin login ────────────────────────────────────────────────────────
_FAKE_ADMIN_LOGIN = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><title>Admin Login</title>
<style>
body{font-family:-apple-system,Segoe UI,sans-serif;background:#1a1a1a;color:#eee;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0}
.box{background:#222;border:1px solid #333;padding:40px;border-radius:6px;width:340px}
h1{margin:0 0 24px;font-size:20px;color:#9ec3ff}
input{width:100%;box-sizing:border-box;padding:10px;background:#111;border:1px solid #444;color:#eee;margin-bottom:12px;font-family:Consolas,monospace;border-radius:3px}
button{width:100%;padding:12px;background:#2a5cb8;color:#fff;border:none;border-radius:3px;cursor:pointer;font-weight:600}
.hint{color:#888;font-size:11px;margin-top:14px;text-align:center}
</style>
</head>
<body>
__TAUNT__
<div class="box">
  <h1>Administrator Console</h1>
  <form method="POST" action="/admin/login">
    <input type="text" name="user" placeholder="username" autofocus>
    <input type="password" name="password" placeholder="password">
    <input type="hidden" name="csrf" value="__CSRF__">
    <button type="submit">Sign in</button>
  </form>
  <div class="hint">v2.4.1 | session timeout: 30min</div>
</div>
</body>
</html>"""


@router.get("/admin", include_in_schema=False)
@router.get("/admin/", include_in_schema=False)
@router.get("/admin/login", include_in_schema=False)
@router.get("/administrator", include_in_schema=False)
@router.get("/admin.php", include_in_schema=False)
@router.get("/manager/html", include_in_schema=False)
@router.get("/wp-login.php", include_in_schema=False)
@router.get("/wp-admin/", include_in_schema=False)
@router.get("/phpmyadmin/", include_in_schema=False)
@router.get("/pma/", include_in_schema=False)
@router.get("/cpanel", include_in_schema=False)
@router.get("/webadmin", include_in_schema=False)
async def fake_admin_login(request: Request):
    await _record_and_delay(request, "decoy_admin_login", request.url.path)
    csrf = f"csrf_{int(time.time())}_{random.randint(1000, 9999)}"
    html = _FAKE_ADMIN_LOGIN.replace("__TAUNT__", _taunt()).replace("__CSRF__", csrf)
    return HTMLResponse(
        html,
        headers={
            "X-Powered-By": "PHP/7.4.33",  # 偽の技術スタック (古め)
            "Server": "Apache/2.4.41 (Ubuntu)",
            "Set-Cookie": f"PHPSESSID={csrf}; Path=/; HttpOnly",
        },
    )


@router.post("/admin/login", include_in_schema=False)
@router.post("/wp-login.php", include_in_schema=False)
@router.post("/administrator", include_in_schema=False)
async def fake_admin_login_submit(request: Request):
    """POST されたら "認証成功っぽい" 偽 dashboard へ誘導する。
    実際には何も検証せず、攻撃者を迷路の次のステージへ進める。"""
    await _record_and_delay(request, "decoy_admin_login_submit",
                             request.url.path, min_s=1.0, max_s=4.0)
    # ランダムに 60% で "success" → 偽 dashboard、40% で再 login (混乱させる)
    if random.random() < 0.6:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/admin/dashboard", status_code=302,
                                headers={"X-Auth-State": "ok"})
    return HTMLResponse(
        _FAKE_ADMIN_LOGIN.replace("__TAUNT__",
            "<!-- so close. try again? もう一回どうぞ -->").replace("__CSRF__", "0"),
        status_code=401,
    )


# ─── 偽 admin dashboard ───────────────────────────────────────────────────
_FAKE_DASHBOARD = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Admin Dashboard</title>
<style>body{font-family:Segoe UI,sans-serif;background:#0f1218;color:#cbd5e0;margin:0;padding:24px}
h1{color:#9ec3ff} table{border-collapse:collapse;width:100%;margin-top:16px}
td,th{border:1px solid #2a3a55;padding:8px 12px;font-size:13px;text-align:left}
th{background:#1a2438;color:#9ec3ff} a{color:#7fb3ff}</style></head>
<body>
__TAUNT__
<h1>ShuttleScope Admin Console</h1>
<p>Welcome back, <strong>__USER__</strong>. Last login: __LAST__</p>
<table>
<tr><th>Module</th><th>Path</th><th>Status</th></tr>
<tr><td>User Management</td><td><a href="/admin/users">/admin/users</a></td><td>OK</td></tr>
<tr><td>Database Export</td><td><a href="/admin/db/export">/admin/db/export</a></td><td>OK</td></tr>
<tr><td>Backup Manager</td><td><a href="/admin/backup">/admin/backup</a></td><td>OK</td></tr>
<tr><td>Configuration</td><td><a href="/admin/config">/admin/config</a></td><td>OK</td></tr>
<tr><td>Secrets Vault</td><td><a href="/admin/secrets">/admin/secrets</a></td><td>OK</td></tr>
<tr><td>Worker Queue</td><td><a href="/admin/workers">/admin/workers</a></td><td>OK</td></tr>
<tr><td>API Tokens</td><td><a href="/admin/tokens">/admin/tokens</a></td><td>OK</td></tr>
<tr><td>Legacy</td><td><a href="/admin/legacy">/admin/legacy</a></td><td>deprecated</td></tr>
</table>
<p style="color:#666;font-size:11px;margin-top:32px">
  ShuttleScope Admin v2.4.1 — internal use only —
  <!-- you found the dashboard. how many hours did it take? どれくらい時間使った？ -->
</p>
</body></html>"""


@router.get("/admin/dashboard", include_in_schema=False)
@router.get("/admin/index", include_in_schema=False)
@router.get("/admin/home", include_in_schema=False)
async def fake_admin_dashboard(request: Request):
    await _record_and_delay(request, "decoy_admin_dashboard", request.url.path)
    user = random.choice(["administrator", "root", "ops_admin", "svc_admin"])
    last = f"2026-05-{random.randint(1,10):02d} {random.randint(8,18):02d}:{random.randint(0,59):02d}:00 UTC"
    html = (_FAKE_DASHBOARD
            .replace("__TAUNT__", _taunt())
            .replace("__USER__", user)
            .replace("__LAST__", last))
    return HTMLResponse(html)


# ─── 偽 .env ファイル系 ───────────────────────────────────────────────────
_FAKE_ENV = f"""# ShuttleScope production environment
# DO NOT COMMIT
ENVIRONMENT=production
DATABASE_URL=postgresql://ss_user:Pr0d_DB_p4ss_2024@10.0.0.21:5432/shuttlescope_prod
SECRET_KEY=B7e9F3a1Cd4E6f8A2B3C5D7E9F1A3B5C7D9E0F2A4B6C8D0E
SS_ADMIN_API_KEY={_HONEYTOKENS["admin_api_key"]}
SS_BACKUP_PASSPHRASE={_HONEYTOKENS["backup_pass"]}
SS_LEGACY_VIDEO_TOKEN={_HONEYTOKENS["video_token"]}
SS_REFRESH_TOKEN_SEED={_HONEYTOKENS["refresh_seed"]}
SS_INTERNAL_WORKER_KEY={_HONEYTOKENS["worker_key"]}
SS_INTERNAL_XFER_TOKEN={_HONEYTOKENS["xfer_token"]}
# Cloudflare
CF_API_TOKEN=cf_token_fake_3f8a9c2b1e7d6f5a4b3c2d1e0f9a8b7c
CF_ZONE_ID=fake_zone_id_72ad34efb91c2d3e4f5a6b7c8d9e0f1a
# SMTP
SMTP_HOST=smtp.shuttle-scope.com
SMTP_USER=ops@shuttle-scope.com
SMTP_PASS=Sm7p_p4ssw0rd_pr0d_zzz_FAKE
# Stripe
STRIPE_SECRET_KEY=sk_live_FAKE_51ABcdEfGhIjKlMnOpQrStUvWxYz
# Slack
SLACK_WEBHOOK=https://hooks.slack.com/services/T00000000/B00000000/FAKE
# ご苦労さま。これは餌です。enjoy.
"""


@router.get("/.env", include_in_schema=False)
@router.get("/.env.production", include_in_schema=False)
@router.get("/.env.local", include_in_schema=False)
@router.get("/.env.bak", include_in_schema=False)
@router.get("/config/.env", include_in_schema=False)
@router.get("/app/.env", include_in_schema=False)
@router.get("/api/.env.production", include_in_schema=False)
@router.get("/backup/.env", include_in_schema=False)
async def fake_env(request: Request):
    await _record_and_delay(request, "decoy_env", request.url.path)
    return PlainTextResponse(
        _FAKE_ENV,
        headers={
            "Content-Disposition": "inline; filename=.env",
            "X-Honeyfile": "yes",  # 攻撃者には見えるが意味不明な header
        },
    )


# ─── 偽 admin sub-pages ───────────────────────────────────────────────────
@router.get("/admin/users", include_in_schema=False)
async def fake_admin_users(request: Request):
    await _record_and_delay(request, "decoy_admin_users", "/admin/users")
    fake_users = [
        {"id": i, "email": f"user{i:03d}@shuttle-scope.com",
         "role": random.choice(["analyst", "coach", "admin", "player"]),
         "created_at": f"2024-{random.randint(1,12):02d}-{random.randint(1,28):02d}T00:00:00Z",
         "api_key_hint": f"ss_***{random.randint(1000,9999)}"}
        for i in range(1, 47)
    ]
    return JSONResponse({
        "success": True,
        "data": fake_users,
        "_internal_legacy_token": _HONEYTOKENS["staged_lure"],
        "_note": "// このフィールドは互換性のため残しています / kept for backward compat",
    })


@router.get("/admin/db/export", include_in_schema=False)
@router.get("/admin/backup", include_in_schema=False)
@router.get("/admin/backup/download", include_in_schema=False)
async def fake_db_export(request: Request):
    await _record_and_delay(request, "decoy_db_export", request.url.path,
                             min_s=2.0, max_s=6.0)
    # 偽の "進行中" レスポンス。攻撃者は完了を待って張り付くことになる。
    job_id = f"exp_{int(time.time())}_{random.randint(10000, 99999)}"
    return JSONResponse({
        "success": True,
        "data": {
            "job_id": job_id,
            "status": random.choice(["queued", "processing", "compressing"]),
            "progress_percent": random.randint(3, 87),
            "estimated_remaining_seconds": random.randint(120, 3600),
            "download_url": f"/admin/backup/file/{job_id}.tar.gz.enc",
            "passphrase_hint": _HONEYTOKENS["backup_pass"][:8] + "...",
        },
        "_taunt": "// good luck waiting / 気長にお待ちください",
    })


@router.get("/admin/secrets", include_in_schema=False)
@router.get("/admin/config", include_in_schema=False)
async def fake_secrets(request: Request):
    await _record_and_delay(request, "decoy_secrets", request.url.path)
    return JSONResponse({
        "success": True,
        "data": {
            "stripe_secret_key": "sk_live_FAKE_51AbCdEfGhIjKlMnOpQr",
            "admin_api_key": _HONEYTOKENS["admin_api_key"],
            "backup_passphrase": _HONEYTOKENS["backup_pass"],
            "internal_worker_key": _HONEYTOKENS["worker_key"],
            "legacy_video_token": _HONEYTOKENS["video_token"],
            "refresh_token_seed": _HONEYTOKENS["refresh_seed"],
            "internal_transfer_token": _HONEYTOKENS["xfer_token"],
            "_remark": "rotation_due: 2025-12-31 (overdue)",
        },
        "_meta": {
            "vault_version": "1.4.7",
            "last_rotated": "2024-08-12T03:14:00Z",
        },
    })


@router.get("/admin/tokens", include_in_schema=False)
async def fake_tokens(request: Request):
    await _record_and_delay(request, "decoy_tokens", "/admin/tokens")
    return JSONResponse({
        "success": True,
        "data": [
            {"id": 1, "name": "legacy_admin", "token": _HONEYTOKENS["admin_api_key"],
             "scope": "admin:*", "expires": "2030-01-01T00:00:00Z"},
            {"id": 2, "name": "worker_internal", "token": _HONEYTOKENS["worker_key"],
             "scope": "internal:worker", "expires": "2030-01-01T00:00:00Z"},
            {"id": 3, "name": "backup_service", "token": _HONEYTOKENS["xfer_token"],
             "scope": "backup:read,write", "expires": "2030-01-01T00:00:00Z"},
        ],
    })


@router.get("/admin/workers", include_in_schema=False)
async def fake_workers(request: Request):
    await _record_and_delay(request, "decoy_workers", "/admin/workers")
    return JSONResponse({
        "success": True,
        "data": [
            {"hostname": f"worker-{i:02d}.internal", "status": "running",
             "queue_depth": random.randint(0, 12),
             "last_heartbeat": f"2026-05-11T{random.randint(0,23):02d}:00:00Z"}
            for i in range(1, 9)
        ],
    })


@router.get("/admin/legacy", include_in_schema=False)
async def fake_legacy_index(request: Request):
    """迷路の深部。さらにリンクが生える。"""
    await _record_and_delay(request, "decoy_legacy", "/admin/legacy")
    html = f"""<!DOCTYPE html><html><head><title>Legacy</title></head><body>
{_taunt()}
<h1>Legacy Endpoints</h1>
<ul>
<li><a href="/admin/legacy/v1/users">v1 users</a></li>
<li><a href="/admin/legacy/v1/export">v1 export</a></li>
<li><a href="/admin/legacy/v1/secrets">v1 secrets</a></li>
<li><a href="/admin/legacy/v2/migration">v2 migration</a></li>
<li><a href="/admin/legacy/dump">full dump</a></li>
<li><a href="/admin/legacy/.git/config">.git/config</a></li>
<li><a href="/admin/legacy/backup.sql">backup.sql</a></li>
<li><a href="/admin/legacy/db.sqlite">db.sqlite</a></li>
</ul>
<p style="color:#888;font-size:11px">
  <!-- the deeper you go the less you find / 深く潜るほど何もない -->
</p>
</body></html>"""
    return HTMLResponse(html)


@router.get("/admin/legacy/{rest:path}", include_in_schema=False)
async def fake_legacy_catchall(request: Request, rest: str):
    """legacy 配下は何でも 200 を返して迷路を伸ばす。"""
    await _record_and_delay(request, "decoy_legacy_deep", f"/admin/legacy/{rest}",
                             min_s=1.0, max_s=5.0)
    return JSONResponse({
        "success": True,
        "data": {"path": rest, "deprecated": True,
                 "see_also": f"/admin/legacy/{rest}/v2"},
        "_admin_token_hint": _HONEYTOKENS["staged_lure"],
    })


# ─── 偽 git / backup ファイル ─────────────────────────────────────────────
@router.get("/.git/config", include_in_schema=False)
@router.get("/.git/HEAD", include_in_schema=False)
async def fake_git(request: Request):
    await _record_and_delay(request, "decoy_git", request.url.path)
    return PlainTextResponse(
        "[core]\n\trepositoryformatversion = 0\n\tfilemode = true\n"
        "[remote \"origin\"]\n\turl = git@internal-git.shuttle-scope.com:ops/prod.git\n"
        "[branch \"main\"]\n\tremote = origin\n\tmerge = refs/heads/main\n"
        f"# {_taunt()}\n"
    )


@router.get("/backup.sql", include_in_schema=False)
@router.get("/backup.tar.gz", include_in_schema=False)
@router.get("/db.sqlite", include_in_schema=False)
@router.get("/dump.sql", include_in_schema=False)
async def fake_backup(request: Request):
    """偽 backup ダウンロード。攻撃者をしばらく待たせる。"""
    await _record_and_delay(request, "decoy_backup_file", request.url.path,
                             min_s=3.0, max_s=8.0)
    # ヘッダだけそれっぽくしてサイズ大きいフリ
    fake_body = (
        f"-- ShuttleScope DB dump (fake honeypot)\n"
        f"-- {_taunt()}\n"
        f"-- generated: 2026-05-11 03:14:00 UTC\n"
        f"INSERT INTO users (email, api_key) VALUES "
        f"('admin@shuttle-scope.com', '{_HONEYTOKENS['admin_api_key']}');\n"
        f"INSERT INTO legacy_settings (key, value) VALUES "
        f"('backup_pass', '{_HONEYTOKENS['backup_pass']}'),"
        f"('worker_key', '{_HONEYTOKENS['worker_key']}'),"
        f"('xfer_token', '{_HONEYTOKENS['xfer_token']}');\n"
    )
    return PlainTextResponse(
        fake_body,
        headers={
            "Content-Disposition": "attachment; filename=backup.sql",
            "X-Generator": "pg_dump 14.5",
        },
    )


# ─── R45: 永遠の迷路 catch-all ────────────────────────────────────────────
# 攻撃者が想像しがちな enumeration prefix を全部 200 で受ける。
# 真の application path (e.g. /api/auth, /api/public, /api/matches, /api/players)
# は別の router が先に登録されているので match されない。残った path のみ
# decoy が受け取る。

_DEEP_RABBIT_HOLE_HTML = """<!DOCTYPE html><html><head><meta charset="UTF-8"><title>{title}</title></head>
<body style="font-family:Segoe UI,sans-serif;background:#0a1426;color:#cbd6e6;margin:0;padding:32px">
{taunt}
<h2 style="color:#9ec3ff">{title}</h2>
<p>Resource: <code>{path}</code></p>
<ul>{links}</ul>
<p style="color:#666;font-size:11px">v{ver} | {seed}</p>
</body></html>"""


def _gen_rabbit_links(base: str) -> str:
    """与えられた base path から、もっともらしいリンクをランダム生成する。
    base は URL path 由来 (user-controlled) なので _safe_path_segment + html.escape
    を必ず通す。"""
    safe_base = _safe_path_segment(base)
    leaves = [
        "config", "settings", "users", "tokens", "secrets", "backup",
        "export", "dump", "logs", "audit", "v1", "v2", "v3", "internal",
        "legacy", "deprecated", "archive", "raw", "debug", "metrics",
    ]
    picked = random.sample(leaves, k=random.randint(4, 8))
    items = []
    for leaf in picked:
        url = f"{safe_base.rstrip('/')}/{leaf}"
        esc = _html.escape(url, quote=True)
        items.append(f'<li><a href="{esc}">{esc}</a></li>')
    return "\n".join(items)


# /admin 配下: 何でも 200。これで攻撃者の crawler を再帰的に泳がせる。
@router.api_route("/admin/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                  include_in_schema=False)
async def maze_admin_catchall(request: Request, rest: str):
    await _record_and_delay(request, "decoy_admin_deep", f"/admin/{rest}",
                             min_s=0.8, max_s=4.0)
    accept = (request.headers.get("accept") or "").lower()
    if "application/json" in accept or rest.endswith(".json"):
        return JSONResponse({
            "success": True,
            "data": {
                "path": f"/admin/{rest}",
                "next": f"/admin/{rest}/v2",
                "items_count": random.randint(0, 9999),
                "_legacy_token": _HONEYTOKENS["staged_lure"],
            },
            "_meta": {"taunt": random.choice([
                "keep going", "ご苦労さま", "almost there", "もう少し",
                "the prize is just around the corner", "あと一歩",
            ])},
        })
    # CodeQL py/reflective-xss: rest は URL path 由来 (user-controlled) なので、
    # HTML テンプレートに渡す前に _safe_path_segment + html.escape を通す。
    safe_rest = _safe_path_segment(rest)
    title_raw = safe_rest.split('/')[-1] or 'index'
    return HTMLResponse(_DEEP_RABBIT_HOLE_HTML.format(
        title=_html.escape(f"Admin :: {title_raw}"),
        taunt=_taunt(),
        path=_html.escape(f"/admin/{safe_rest}"),
        links=_gen_rabbit_links(f"/admin/{safe_rest}"),
        ver=f"{random.randint(1,3)}.{random.randint(0,9)}.{random.randint(0,99)}",
        seed=random.randint(100000, 999999),
    ))


# /internal 配下も同様
@router.api_route("/internal/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                  include_in_schema=False)
async def maze_internal_catchall(request: Request, rest: str):
    await _record_and_delay(request, "decoy_internal_deep", f"/internal/{rest}",
                             min_s=0.8, max_s=4.0)
    return JSONResponse({
        "success": True,
        "data": {
            "endpoint": f"/internal/{rest}",
            "auth_required": False,  # 罠
            "rate_limit": "10000/min",
            "secrets_visible_to": ["admin", "internal_worker"],
            "_remember_to_rotate": _HONEYTOKENS["worker_key"],
        },
    })


# /api/* 系の maze は GlobalAuthMiddleware が 401 で先に弾くので登録しない。
# 攻撃者は「/api/admin/dump を叩いて 401 = 本物の admin API があるな」と
# fingerprint するが、maze 本体に届かないため意味が薄い。
# 代わりに /api を経由しない /admin /internal /.env /backup.sql 等で迷路を作る。


# 単発の「美味しそう」path
_DECOY_SINGLE_PATHS = [
    "/server-status",
    "/server-info",
    "/health/dump",
    "/metrics/private",
    "/.aws/credentials",
    "/.ssh/id_rsa",
    "/.ssh/authorized_keys",
    "/id_rsa",
    "/private.key",
    "/swagger.json",  # 真の swagger は /docs / /openapi.json で別管理
    "/api-docs",
    "/graphql",       # 我々は使ってないので叩いたら decoy
    "/graphiql",
    "/console",
    "/jolokia",
    "/actuator",
    "/actuator/health",
    "/actuator/heapdump",
    "/druid/v2",
    "/solr/admin",
    "/elasticsearch",
    "/kibana",
    "/grafana",
    "/jenkins",
]


def _make_single_handler(captured_path: str):
    async def _h(request: Request):
        await _record_and_delay(request, "decoy_single", captured_path,
                                 min_s=0.5, max_s=2.5)
        # path に応じて返すフェイクコンテンツを選ぶ
        if captured_path.endswith(("id_rsa", "private.key")):
            return PlainTextResponse(
                "-----BEGIN OPENSSH PRIVATE KEY-----\n"
                "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAABFwAAAAdz\n"
                "c2gtcn  # " + _taunt() + "\n"
                "-----END OPENSSH PRIVATE KEY-----\n"
            )
        if captured_path == "/.aws/credentials":
            return PlainTextResponse(
                "[default]\n"
                "aws_access_key_id = AKIAFAKEFAKEFAKE1234\n"
                f"aws_secret_access_key = {_HONEYTOKENS['admin_api_key']}\n"
                f"# {_taunt()}\n"
            )
        if captured_path in ("/swagger.json", "/api-docs"):
            return JSONResponse({
                "openapi": "3.0.0",
                "info": {"title": "Internal API", "version": "1.4.7"},
                "paths": {
                    "/admin/secrets": {"get": {"summary": "Get all secrets"}},
                    "/admin/db/export": {"post": {"summary": "Export full DB"}},
                    "/admin/users": {"get": {"summary": "List all users"}},
                    "/admin/tokens": {"get": {"summary": "List API tokens"}},
                },
                "_note": _taunt(),
            })
        if captured_path == "/graphql":
            # GraphQL introspection 偽応答
            return JSONResponse({
                "data": {
                    "__schema": {
                        "types": [
                            {"name": "AdminToken", "kind": "OBJECT"},
                            {"name": "BackupSecret", "kind": "OBJECT"},
                            {"name": "InternalConfig", "kind": "OBJECT"},
                        ]
                    }
                }
            })
        return JSONResponse({
            "ok": True,
            "data": {"path": captured_path, "_lure": _HONEYTOKENS["staged_lure"]},
            "_msg": _taunt(),
        })
    _h.__name__ = f"decoy_single_{captured_path.replace('/', '_').replace('.', '_')}"
    return _h


for _p in _DECOY_SINGLE_PATHS:
    router.add_api_route(
        _p,
        _make_single_handler(_p),
        methods=["GET", "POST"],
        include_in_schema=False,
    )
