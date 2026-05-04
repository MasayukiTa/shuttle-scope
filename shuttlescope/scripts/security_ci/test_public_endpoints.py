# -*- coding: utf-8 -*-
# DevSkim: ignore DS137138,DS162092,DS176209
# Intentional adversarial test code; verifies prod rejects malformed input.
"""round137 ベース: 公開 endpoint (contact / register / verify) の入力検証"""
import sys, os, secrets
sys.path.insert(0, os.path.dirname(__file__))
from _common import req, short, Findings


def main():
    f = Findings("public_endpoints")

    # contact form 異常入力
    payloads_500 = [
        # 巨大 message
        {"name": "x", "email": "a@b.com", "message": "x" * 100_000},
        # CRLF in name
        {"name": "test\r\nBcc: evil@y.com", "email": "x@y.com", "message": "test message hello"},
        # nested JSON / extra fields
        {"name": "x", "email": "a@b.com", "message": "test", "extra": {"deep": "x"}},
        # 制御文字
        {"name": "test\x00", "email": "x@y.com", "message": "x"},
    ]
    for p in payloads_500:
        try:
            s, _, b = req("POST", "/api/public/contact", body=p)
            if s == 500:
                f.high(f"contact:{list(p)[0]}", short(b, 60))
            elif s in (422, 400, 429):
                f.passed(f"contact:{list(p)[0]}", f"status={s}")
            elif s == 200:
                f.warn(f"contact:{list(p)[0]}", "accepted (review)")
        except Exception as e:
            f.warn(f"contact", str(e)[:60])

    # email validation
    bad_emails = [
        "user@127.0.0.1", "user@localhost", "<script>@x.com",
        "a@b", "@x.com", "user@x.com\r\nBcc:e@y.com",
    ]
    for e in bad_emails:
        s, _, b = req("POST", "/api/auth/register", body={
            "email": e, "password": "Test1234!ABC",
            "username": f"u_{secrets.token_hex(4)}",
            "display_name": "x",
        })
        if s == 201:
            f.critical(f"email:{e[:30]}", "registration accepted")
        elif s in (422, 503):
            f.passed(f"email:{e[:30]}", f"status={s}")

    # OAuth / OpenID / GraphQL probe
    for p in ["/api/oauth/authorize", "/api/oauth/token",
              "/.well-known/openid-configuration",
              "/api/openid/userinfo", "/api/.well-known/oauth-authorization-server"]:
        s, _, b = req("GET", p)
        if s == 200:
            f.high(f"oauth_probe:{p}", short(b, 60))
        else:
            f.passed(f"oauth_probe:{p}", f"status={s}")

    # 不正 verify token (uniformity check は skip — timing は CI で不安定)
    for tk in ["validlooking", "../../etc/passwd", "x" * 100]:
        s, _, b = req("GET", f"/api/auth/email/verify?token={tk}")
        if s == 500:
            f.high(f"verify:{tk[:20]}", short(b, 60))

    # 不正 password reset token
    for tk in ["fake", "x" * 100]:
        s, _, b = req("POST", "/api/auth/password/reset",
                      body={"token": tk, "new_password": "Test1234ABCDef!"})
        if s == 500:
            f.high(f"pwreset:{tk[:20]}", short(b, 60))

    crit, high, warn, passed = f.summary()
    if crit > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
