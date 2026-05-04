# -*- coding: utf-8 -*-
# DevSkim: ignore DS137138,DS162092,DS176209
# Intentional adversarial test code; verifies prod rejects malformed input.
"""round128 ベース: 無認証で 100+ endpoint をスキャン → 公開すべきでない endpoint が
200 を返したら CRITICAL。
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from _common import req, short, Findings, HOST


PATHS = [
    # 認証必須 (これらが 200 を返したら漏洩)
    "/api/auth/me", "/api/auth/users", "/api/auth/users/1",
    "/api/matches", "/api/matches/106",
    "/api/players", "/api/players/1",
    "/api/sets?match_id=106", "/api/rallies?set_id=1", "/api/strokes?rally_id=1",
    "/api/comments?match_id=106", "/api/bookmarks?match_id=106",
    "/api/conditions?player_id=1", "/api/condition_tags?player_id=1",
    "/api/sessions",
    "/api/yolo/status", "/api/yolo/results/106",
    "/api/tracknet/status",
    "/api/admin/security/audit_log",
    "/api/admin/security/user_limits/1",
    "/api/cluster/nodes", "/api/cluster/config",
    "/api/db_maintenance/status",
    "/api/network_diag/status",
    "/api/settings", "/api/teams",
    "/api/v1/expert/clips?match_id=106",
    "/api/v1/expert/labels?match_id=106",
    "/api/v1/expert/videos",
    "/api/v1/uploads/video/sessions",
    "/api/export/package?match_id=106",
    # OpenAPI / docs (HIDE_API_DOCS=1 で 401 想定)
    "/api/openapi.json", "/api/docs", "/api/redoc", "/api/swagger.json",
    # GraphQL (未実装)
    "/graphql", "/api/graphql", "/v1/graphql",
    # Admin only
    "/api/admin/products", "/api/admin/grant_entitlement",
    # Internal
    "/api/_internal/admin/audit_log",
    "/api/_internal/admin/users",
    # 公開 OK の参照
    "/api/health", "/api/auth/bootstrap-status",
    "/api/_internal/billing/legal_info",
    # Dump path
    "/.git/HEAD", "/.git/config", "/backup.zip", "/dump.sql", "/.env.local",
    "/wp-admin", "/phpmyadmin",
]

PUBLIC_OK = {"/api/health", "/api/auth/bootstrap-status",
             "/api/_internal/billing/legal_info"}


def main():
    f = Findings("no_auth_scan")
    for p in PATHS:
        try:
            s, _, b = req("GET", p)
        except Exception as e:
            f.warn(f"{p}", f"EX: {type(e).__name__}")
            continue
        body = b.decode("utf-8", "replace") if isinstance(b, bytes) else str(b)
        if s == 200:
            if p in PUBLIC_OK:
                f.passed(p, "intentionally public")
            elif len(body) < 30 or '"data":[]' in body or '"data":null' in body:
                f.passed(p, f"empty resp ({len(body)}B)")
            else:
                f.critical(p, f"AUTH BYPASS len={len(body)} {short(b, 80)}")
        elif s in (401, 403, 404, 405, 422):
            f.passed(p, f"status={s}")
        elif s == 302:
            # SPA fallback OK
            f.passed(p, "302 SPA")
        else:
            f.warn(p, f"unexpected status={s}")
    crit, high, warn, passed = f.summary()
    if crit > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
