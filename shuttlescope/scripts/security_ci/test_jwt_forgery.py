# -*- coding: utf-8 -*-
"""round122 + round133 ベース: JWT 偽造 11 種 × 主要 23 endpoint = 253 プローブ。
全て 401 を期待。1 つでも 200 が返ったら CRITICAL。
"""
import json, base64, hmac, hashlib, time, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from _common import req, short, Findings


def b64u(b):
    if isinstance(b, str): b = b.encode()
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def make_jwt(header, payload, key=b""):
    h = b64u(json.dumps(header, separators=(",", ":")))
    p = b64u(json.dumps(payload, separators=(",", ":")))
    msg = f"{h}.{p}".encode()
    if header.get("alg") == "none":
        return f"{h}.{p}."
    sig = hmac.new(key, msg, hashlib.sha256).digest() if header.get("alg") == "HS256" else b""
    return f"{h}.{p}.{b64u(sig)}"


NOW = int(time.time())
TOKS = {
    "alg_none":           make_jwt({"alg": "none", "typ": "JWT"}, {"sub": "1", "role": "admin", "exp": NOW + 3600}),
    "hs256_empty_key":    make_jwt({"alg": "HS256", "typ": "JWT"}, {"sub": "1", "role": "admin", "exp": NOW + 3600}, key=b""),
    "hs256_null_str_key": make_jwt({"alg": "HS256", "typ": "JWT"}, {"sub": "1", "role": "admin", "exp": NOW + 3600}, key=b"null"),
    "expired":            make_jwt({"alg": "HS256", "typ": "JWT"}, {"sub": "1", "role": "admin", "exp": NOW - 3600}, key=b"x"),
    "no_sub":             make_jwt({"alg": "HS256", "typ": "JWT"}, {"role": "admin", "exp": NOW + 3600}, key=b"x"),
    "kid_inj":            make_jwt({"alg": "HS256", "kid": "../../etc/passwd", "typ": "JWT"}, {"sub": "1", "role": "admin", "exp": NOW + 3600}, key=b"x"),
    "jku_inj":            make_jwt({"alg": "HS256", "jku": "http://evil.example.com/jwks", "typ": "JWT"}, {"sub": "1", "role": "admin", "exp": NOW + 3600}, key=b"x"),
    "role_pwn":           make_jwt({"alg": "HS256"}, {"sub": "5", "role": "admin", "exp": NOW + 3600}, key=b"x"),
    "garbage":            "not.a.jwt.at.all",
    "empty":              "",
    "crit_header":        make_jwt({"alg": "HS256", "crit": ["evil"], "evil": "bypass"}, {"sub": "1", "role": "admin", "exp": NOW + 3600}, key=b"x"),
}

TARGETS = [
    "/api/auth/me", "/api/auth/users",
    "/api/matches?limit=1", "/api/matches/106",
    "/api/players?limit=1",
    "/api/conditions?player_id=1",
    "/api/bookmarks?match_id=106",
    "/api/comments?match_id=106",
    "/api/sessions",
    "/api/yolo/results/106",
    "/api/admin/security/audit_log?since_hours=1&limit=5",
    "/api/v1/expert/clips?match_id=106",
    "/api/v1/expert/videos",
    "/api/v1/uploads/video/sessions",
    "/api/export/package?match_id=106",
    "/api/settings",
    "/api/teams",
    "/api/cluster/nodes",
    "/api/db_maintenance/status",
]


def main():
    f = Findings("jwt_forgery")
    for tk_name, tk in TOKS.items():
        h = {"Authorization": f"Bearer {tk}"} if tk else {}
        for p in TARGETS:
            try:
                s, _, b = req("GET", p, headers=h)
            except Exception as e:
                f.warn(f"{tk_name}:{p}", f"EX {type(e).__name__}")
                continue
            if s == 200:
                # 200 が返ったら bypass
                f.critical(f"{tk_name}:{p}", short(b, 80))
            elif s in (302, 405):
                pass  # silent
            else:
                # 401/403/404/422 OK
                pass

    # Authorization spoof バリエーション
    SPOOFS = [
        ("empty_bearer", {"Authorization": "Bearer "}),
        ("basic_auth",   {"Authorization": "Basic YWRtaW46cGFzcw=="}),
        ("xauth_header", {"X-Authorization": "Bearer fake.jwt.token"}),
        ("cookie_only",  {"Cookie": "access_token=fake.jwt.token"}),
    ]
    for label, hdr in SPOOFS:
        try:
            s, _, b = req("GET", "/api/auth/me", headers=hdr)
            if s == 200:
                f.critical(f"spoof:{label}", short(b, 80))
            else:
                f.passed(f"spoof:{label}", f"status={s}")
        except Exception as e:
            f.warn(f"spoof:{label}", f"EX {type(e).__name__}")

    crit, high, warn, passed = f.summary()
    print(f"  Total probes: {len(TOKS)} tokens × {len(TARGETS)} endpoints + {len(SPOOFS)} spoofs")
    if crit > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
