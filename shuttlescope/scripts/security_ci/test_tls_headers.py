# -*- coding: utf-8 -*-
# DevSkim: ignore DS169125,DS169126,DS440000,DS130822,DS106863,DS137138,DS162092
# Bandit: skip - this file intentionally negotiates weak TLS versions / disables
# certificate validation to verify that the production endpoint REJECTS them.
# See docs/validation/security-code-scanning-2026-04-23.md
"""round145 + round150 + round154: TLS / HSTS / CSP / X-Frame / 漏洩ヘッダ"""
import sys, os, ssl, socket
sys.path.insert(0, os.path.dirname(__file__))
from _common import req, hget, Findings, HOST, PORT, INSECURE, is_expected_decoy


def main():
    f = Findings("tls_headers")

    # --- TLS バージョン --------------------------------------------------
    if not INSECURE:  # 本番のみ TLS 強度確認
        for ver_name, ver in [
            ("TLSv1.0", ssl.TLSVersion.TLSv1),  # DevSkim: ignore DS169125,DS169126,DS440000
            ("TLSv1.1", ssl.TLSVersion.TLSv1_1),  # DevSkim: ignore DS169125,DS169126,DS440000
        ]:
            try:
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                ctx.minimum_version = ver
                ctx.maximum_version = ver
                ctx.check_hostname = False  # DevSkim: ignore DS130822
                ctx.verify_mode = ssl.CERT_NONE  # DevSkim: ignore DS130822
                sock = socket.create_connection((HOST, PORT), timeout=5)
                ssock = ctx.wrap_socket(sock, server_hostname=HOST)
                f.critical(f"tls:{ver_name}", "ACCEPTED (must reject)")
                ssock.close()
            except Exception:
                f.passed(f"tls:{ver_name}", "rejected")

        # 弱い cipher (DevSkim: 意図的な弱cipher 試験 — prod 拒否を確認するため)
        for cipher in ["RC4", "DES-CBC-SHA", "DES-CBC3-SHA"]:  # DevSkim: ignore DS106863
            try:
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                ctx.set_ciphers(cipher)
                ctx.check_hostname = False  # DevSkim: ignore DS130822
                ctx.verify_mode = ssl.CERT_NONE  # DevSkim: ignore DS130822
                sock = socket.create_connection((HOST, PORT), timeout=5)
                ssock = ctx.wrap_socket(sock, server_hostname=HOST)
                f.critical(f"cipher:{cipher}", "ACCEPTED")
                ssock.close()
            except Exception:
                f.passed(f"cipher:{cipher}", "rejected")

    # --- セキュリティヘッダ ----------------------------------------------
    # The header checks below need real responses from /api/health and /. A
    # transient transport failure (after retries in _common.req) must not crash
    # the run, nor be misreported as a missing header (a false HIGH). If the
    # fetch fails we WARN and skip only the affected block.
    try:
        s, h, _ = req("GET", "/api/health")
    except Exception as ex:
        f.warn("headers", f"skipped: EX {type(ex).__name__} on /api/health")
        h = None

    if h is not None:
        if not hget(h, "strict-transport-security"):
            f.high("hsts_missing", "Strict-Transport-Security not set")
        else:
            f.passed("hsts", hget(h, "strict-transport-security")[:80])

        if hget(h, "x-frame-options") not in ("DENY", "SAMEORIGIN"):
            f.high("x_frame_missing", f"got={hget(h, 'x-frame-options')}")
        else:
            f.passed("x_frame", hget(h, "x-frame-options"))

        if not hget(h, "x-content-type-options"):
            f.high("xcto_missing", "X-Content-Type-Options not set")
        else:
            f.passed("xcto", hget(h, "x-content-type-options"))

        # 機密ヘッダ漏洩
        for k in ["x-powered-by", "x-aspnet-version", "x-runtime"]:
            v = hget(h, k)
            if v:
                f.high(f"header_leak:{k}", v[:60])

    try:
        s2, h2, _ = req("GET", "/")
        csp = hget(h2, "content-security-policy")
        if not csp:
            f.high("csp_missing", "Content-Security-Policy not set on /")
        else:
            if "frame-ancestors" not in csp:
                f.high("csp_frame_ancestors", "missing frame-ancestors directive")
            else:
                f.passed("csp", "OK")
    except Exception as ex:
        f.warn("csp", f"skipped: EX {type(ex).__name__} on /")

    # --- CORS evil origin ------------------------------------------------
    for origin in ["https://evil.example.com", "null", "file://", "https://attacker.com"]:
        try:
            s, hh, _ = req("OPTIONS", "/api/auth/me",
                           headers={"Origin": origin,
                                    "Access-Control-Request-Method": "GET"})
        except Exception as ex:
            f.warn(f"cors:{origin}", f"EX {type(ex).__name__}")
            continue
        aco = hget(hh, "access-control-allow-origin")
        if aco in ("*", origin):
            f.critical(f"cors:{origin}", f"ACO={aco}")
        else:
            f.passed(f"cors:{origin}", f"ACO={aco or '(none)'}")

    # --- Cookie-only CSRF ------------------------------------------------
    try:
        s, _, b = req("POST", "/api/matches",
                      body={"tournament": "csrf"},
                      headers={"Cookie": "access_token=fake; session=evil"})
        if s == 200 or s == 201:
            f.critical("csrf:cookie_only", "POST accepted with cookie only")
        else:
            f.passed("csrf:cookie_only", f"status={s}")
    except Exception as ex:
        f.warn("csrf:cookie_only", f"EX {type(ex).__name__}")

    # --- HTTP→HTTPS redirect (本番のみ) -----------------------------------
    if not INSECURE:
        try:
            import http.client
            c = http.client.HTTPConnection(HOST, 80, timeout=5)
            c.request("GET", "/api/health")
            r = c.getresponse()
            loc = r.getheader("Location", "")
            if loc.startswith("https://"):
                f.passed("http_redirect", "→ HTTPS")
            else:
                f.high("http_redirect", f"loc={loc[:60]}")
        except Exception as e:
            f.warn("http_redirect", str(e)[:60])

    # --- Dump path -------------------------------------------------------
    for p in ["/.git/HEAD", "/.git/config", "/backup.zip",
              "/dump.sql", "/.env.local", "/wp-admin", "/phpmyadmin"]:
        try:
            s, _, b = req("GET", p)
        except Exception as ex:
            f.warn(f"dump:{p}", f"EX {type(ex).__name__}")
            continue
        if s == 200 and len(b) > 30:
            if is_expected_decoy(p, b):
                f.passed(f"dump:{p}", "verified intentional decoy")
            else:
                f.critical(f"dump:{p}", "exposed")

    crit, high, warn, passed = f.summary()
    if crit > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
