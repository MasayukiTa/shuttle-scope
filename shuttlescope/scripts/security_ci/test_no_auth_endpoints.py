# -*- coding: utf-8 -*-
# DevSkim: ignore DS137138,DS162092,DS176209
# Intentional adversarial test code; verifies prod rejects malformed input.
"""round128 ベース: 無認証で 100+ endpoint をスキャン → 公開すべきでない endpoint が
200 を返したら CRITICAL。
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from _common import req, short, Findings, HOST, is_expected_decoy


PATHS = [
    # 認証必須 (これらが 200 を返したら漏洩)
    "/api/auth/me", "/api/auth/users", "/api/auth/users/1",
    "/api/matches", "/api/matches/106",
    "/api/players", "/api/players/1",
    "/api/sets?match_id=106", "/api/rallies?set_id=1", "/api/strokes?rally_id=1",
    "/api/comments?match_id=106", "/api/bookmarks?match_id=106",
    "/api/conditions?player_id=1", "/api/condition_tags?player_id=1",
    "/api/sessions/my-info",
    "/api/yolo/status", "/api/yolo/results/106",
    "/api/tracknet/status",
    "/api/admin/security/audit_log",
    "/api/admin/security/user_limits/1",
    "/api/cluster/nodes", "/api/cluster/config",

    "/api/network_diag/status",
    "/api/settings", "/api/auth/teams", "/api/players/teams",
    "/api/v1/expert/clips?match_id=106",
    "/api/v1/expert/labels?match_id=106",
    "/api/v1/expert/videos",
    "/api/v1/uploads/video/sessions",
    "/api/export/package?match_id=106",
    # OpenAPI / docs (HIDE_API_DOCS=1 で 401 想定)
    "/api/openapi.json", "/api/docs", "/api/redoc", "/api/swagger.json",
    # GraphQL: /graphql は意図的 decoy、/api/graphql は認証境界、/v1/graphql は未実装
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

# High-risk routes are probed with their actual HTTP method. The broad PATHS
# sweep above is intentionally permissive (404/405/422 are useful discovery
# outcomes), so it cannot prove that POST-only endpoints are auth-protected.
# These probes are strict: the route/method must still exist and unauthenticated
# access must be rejected by auth (401/403), not merely by 404/405.
STRICT_AUTH_PROBES = [
    # Core identity/data/admin surfaces.
    ("GET",  "/api/auth/me", None),
    ("GET",  "/api/matches?limit=1", None),
    ("GET",  "/api/players?limit=1", None),
    ("POST", "/api/sessions", {}),
    ("GET",  "/api/admin/security/audit_log", None),
    ("GET",  "/api/cluster/nodes", None),
    ("POST", "/api/db/maintenance", {}),
    ("GET",  "/api/settings", None),
    ("GET",  "/api/auth/teams", None),
    # Newer/high-impact surfaces that the legacy GET-only sweep could miss.
    ("POST", "/api/insights/chat/sessions", {"lang": "ja"}),
    ("GET",  "/api/llm/conversations", None),
    ("POST", "/api/llm/conversations", {}),
    ("GET",  "/api/cv-candidates/1", None),
    ("GET",  "/api/cv-candidates/review-queue/1", None),
    ("POST", "/api/cv-candidates/build/1", {}),
    ("GET",  "/api/webrtc/ice-config", None),
    ("POST", "/api/webrtc/test-turn", {}),
    ("POST", "/api/sync/backup", {}),
    ("POST", "/api/sync/import", {}),
    ("GET",  "/api/reports/comprehensive?player_id=1", None),
    ("POST", "/api/v1/uploads/video/init", {}),
    ("GET",  "/api/export/period?date_from=2026-01-01&date_to=2026-01-31", None),
]


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
            elif is_expected_decoy(p, b):
                f.passed(p, "verified intentional decoy")
            else:
                # Empty data is still an auth bypass. A protected endpoint must
                # reject the request, not return 200 merely because today's DB
                # happens to contain no rows.
                f.critical(p, f"AUTH BYPASS len={len(body)} {short(b, 80)}")
        elif s in (401, 403, 404, 405, 422):
            f.passed(p, f"status={s}")
        elif s == 302:
            # SPA fallback OK
            f.passed(p, "302 SPA")
        else:
            f.warn(p, f"unexpected status={s}")
    # Correct-method strict probes for sensitive write/read surfaces.
    for method, p, body in STRICT_AUTH_PROBES:
        try:
            status, _, resp_body = req(method, p, body=body)
        except Exception as e:
            f.critical(
                f"strict:{method}:{p}",
                f"probe failed: {type(e).__name__}",
            )
            continue
        if status in (401, 403):
            f.passed(f"strict:{method}:{p}", f"status={status}")
        else:
            # 404/405/422 are failures here: the probe no longer exercises
            # the intended route/method, so auth coverage has drifted.
            f.critical(
                f"strict:{method}:{p}",
                f"expected auth denial 401/403, got {status}: {short(resp_body, 80)}",
            )

    crit, high, warn, passed = f.summary()
    if crit > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
