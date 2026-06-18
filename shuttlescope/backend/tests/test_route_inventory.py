"""Route inventory regression test (Codex addendum A-002 + R39 F-002 follow-up).

目的:
  1. FastAPI app の全 /api/* route を列挙
  2. 各 route が public allowlist / auth-required / canary のいずれかに正確に分類されること
  3. near-miss path (例: /api/healthanything) が _GLOBAL_AUTH_EXEMPT に match しないこと
  4. 新規 route が無分類のまま deploy されることを CI で防ぐ

設計:
  - PUBLIC_API_ROUTES: 完全一致または明示の bounded prefix
  - ROUTES_REQUIRING_REVIEW: 既知の例外 (e.g., /api/.well-known/...)
  - 全 /api/* route について上記のどれにも該当しないなら **auth-required** とみなす
  - app.router.routes を直接走査する
"""
from __future__ import annotations

import re
from typing import Iterable

import pytest


# ─── public allowlist (一致条件) ─────────────────────────────────────────────
# (a) 完全一致
PUBLIC_EXACT_PATHS: set[str] = {
    "/api/health",
    "/api/version",
    "/api/csp_report",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/refresh",
    "/api/auth/bootstrap-status",
    "/api/auth/register",
    "/api/auth/email/verify",
    "/api/auth/password/request_reset",
    "/api/auth/password/reset",
    "/api/auth/invitation/peek",
    "/api/auth/invitation/accept",
    "/api/_internal/billing/legal_info",
}
# (b) 明示の prefix (これ以下は全部 public 扱い、別途 endpoint 内で role check)
PUBLIC_PREFIXES: tuple[str, ...] = (
    "/api/public/",
    "/api/_internal/billing/webhooks/",
    "/api/_internal/videos/",
)
# (c) GlobalAuthMiddleware の exempt regex そのものを参照したい (drift 防止)
EXPECTED_EXEMPT_REGEX_SUBSTRINGS = (
    "health(?:",
    "csp_report(?:",
    "public(?:",
    "auth/(?:login|logout|refresh|bootstrap-status|register|email/verify",
    "_internal/billing/webhooks/(?:stripe|komoju|univapay)",
    "_internal/billing/legal_info",
    "_internal/videos/",
)


def _walk_routes(routes, prefix: str = "") -> Iterable[tuple[str, set[str]]]:
    """FastAPI / Starlette の route ツリーを再帰 walk して (full_path, methods) を yield。

    FastAPI 0.137 から、`include_router()` で登録したルートは `app.router.routes`
    直下に APIRoute として平坦展開されなくなり、`_IncludedRouter` ラッパ
    (path=None) の中に内包されるよう変わった。旧来の `app.router.routes` 直走査では
    include_router 由来の全ルートを取りこぼし (got 7 のみ → CI 赤) になるため、
    `_IncludedRouter` / `Mount` を再帰展開し prefix を合成しながら全ルートを列挙する。
    0.136 以前の平坦構造でもそのまま動く (両対応)。

    `app.openapi()` を使う案もあるが、それは `include_in_schema=False` の隠し
    ルートを取りこぼす。本テストは「未分類の public ルートを検出する」セキュリティ
    目的なので、隠しルートも漏らさず拾える route ツリー走査を採用する。
    """
    from starlette.routing import Mount

    for route in routes:
        # FastAPI >=0.137: include_router 由来は _IncludedRouter に内包される。
        # `include_context.included_router` / `.prefix` 経由で実ルートへ降りる。
        ctx = getattr(route, "include_context", None)
        if ctx is not None:
            sub = getattr(ctx, "included_router", None)
            if sub is not None:
                sub_prefix = getattr(ctx, "prefix", "") or ""
                yield from _walk_routes(getattr(sub, "routes", []), prefix + sub_prefix)
                continue
        # Mount / サブアプリケーション
        if isinstance(route, Mount):
            yield from _walk_routes(
                getattr(route, "routes", []), prefix + (getattr(route, "path", "") or "")
            )
            continue
        path = getattr(route, "path", None)
        if not isinstance(path, str):
            continue
        methods = set(getattr(route, "methods", set()) or set())
        # OPTIONS は CORS preflight 用なので除外
        methods.discard("OPTIONS")
        yield prefix + path, methods


def _all_api_routes() -> Iterable[tuple[str, set[str]]]:
    """app.router.routes から /api/* の (path, methods) を yield する。

    include_router 由来 (FastAPI 0.137 の _IncludedRouter 内包) も含めて
    再帰列挙する。詳細は `_walk_routes` を参照。"""
    from backend.main import app

    for path, methods in _walk_routes(app.router.routes):
        if not path.startswith("/api/"):
            continue
        if not methods:
            continue
        yield path, methods


def _classify(path: str) -> str:
    """path を public / auth / canary / ? に分類する。"""
    if path in PUBLIC_EXACT_PATHS:
        return "public_exact"
    for pre in PUBLIC_PREFIXES:
        if path.startswith(pre):
            return "public_prefix"
    # /api/* で上のどれにも該当しないなら auth-required とみなす
    return "auth_required"


class TestRouteInventory:
    def test_all_api_routes_classified(self):
        """新規 /api/* route が分類されていない (unknown public/auth) ことを検知する。"""
        rows = list(_all_api_routes())
        assert len(rows) > 10, f"app に /api/* route が見つからない (got {len(rows)})"
        unknown = []
        for path, methods in rows:
            c = _classify(path)
            if c not in ("public_exact", "public_prefix", "auth_required"):
                unknown.append((path, list(methods), c))
        assert not unknown, (
            f"未分類 /api/* route: {unknown}\n"
            f"public なら PUBLIC_EXACT_PATHS / PUBLIC_PREFIXES に登録、それ以外は OK"
        )

    def test_public_paths_count_in_safe_range(self):
        """public 扱いの route 数が異常に増えていないことを assert。"""
        rows = list(_all_api_routes())
        public_paths = [p for p, _ in rows if _classify(p) in ("public_exact", "public_prefix")]
        # 現状 ~25 個前後。+10 余裕で 35 を上限に置く。
        # それを超えたら設計レビュー必須 (= 公開面が無自覚に拡大している可能性)。
        assert len(public_paths) < 35, (
            f"public 扱いの API route が {len(public_paths)} 個 (上限 34)。"
            f"設計レビュー必須: {public_paths}"
        )


class TestGlobalAuthExemptRegex:
    """GlobalAuthMiddleware の _GLOBAL_AUTH_EXEMPT regex が near-miss path で発火しない。

    R39 F-002 で boundary anchor を入れた。regression を防ぐ。
    """

    def test_exempt_regex_anchored(self):
        from backend.main import _GLOBAL_AUTH_EXEMPT
        pattern = _GLOBAL_AUTH_EXEMPT.pattern
        for sub in EXPECTED_EXEMPT_REGEX_SUBSTRINGS:
            assert sub in pattern, (
                f"_GLOBAL_AUTH_EXEMPT pattern が `{sub}` を含まない。drift detection。"
            )

    @pytest.mark.parametrize("path", [
        "/api/healthanything",
        "/api/health/cv",
        "/api/health_X",
        "/api/auth/loginXYZ",
        "/api/auth/loginX",
        "/api/auth/refresh_x",
        "/api/publicXYZ",
        "/api/_internal/billing/legal_infoXYZ",
        "/api/_internal/billing/legal_info_",
        "/api/csp_reportXYZ",
        "/api/_internal/videos",      # trailing / 必須
    ])
    def test_near_miss_paths_not_exempt(self, path: str):
        from backend.main import _GLOBAL_AUTH_EXEMPT
        assert _GLOBAL_AUTH_EXEMPT.match(path) is None, (
            f"近接 path `{path}` が GlobalAuthMiddleware を bypass してしまう。"
        )

    @pytest.mark.parametrize("path", [
        "/api/health",
        "/api/csp_report",
        "/api/auth/login",
        "/api/auth/refresh",
        "/api/auth/email/verify",
        "/api/auth/password/reset",
        "/api/public/contact",
        "/api/public/teams",
        "/api/_internal/billing/webhooks/stripe",
        "/api/_internal/billing/webhooks/komoju",
        "/api/_internal/billing/legal_info",
        "/api/_internal/videos/abc.mp4",
    ])
    def test_legitimate_public_paths_exempt(self, path: str):
        from backend.main import _GLOBAL_AUTH_EXEMPT
        assert _GLOBAL_AUTH_EXEMPT.match(path) is not None, (
            f"正規 public path `{path}` が exempt regex に match しない。R39 で broke した可能性。"
        )
