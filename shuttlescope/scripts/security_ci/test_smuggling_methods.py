# -*- coding: utf-8 -*-
# DevSkim: ignore DS137138,DS162092,DS176209
# Intentional adversarial test code; verifies prod rejects malformed input.
"""round119 + round134: HTTP smuggling / TRACE / TE / CRLF / method override / Host"""
import sys, os, socket
sys.path.insert(0, os.path.dirname(__file__))
from _common import req, short, Findings, HOST, PORT, CTX, INSECURE


def raw_send(payload, timeout=10):
    sock = socket.create_connection((HOST, PORT), timeout=timeout)
    if PORT == 443 or not INSECURE:
        sock = CTX.wrap_socket(sock, server_hostname=HOST)
    sock.sendall(payload)
    data = b""
    try:
        while True:
            c = sock.recv(2048)
            if not c: break
            data += c
            if len(data) > 4096: break
    except Exception: pass
    sock.close()
    return data[:300]


def main():
    f = Findings("smuggling_methods")

    # XXE / SOAP
    xxe = b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><r>&x;</r>'
    s, _, b = req("POST", "/api/auth/login", body=xxe,
                  headers={"Content-Type": "application/xml"})
    if s == 200 or "/etc/passwd" in (b or b"").decode("utf-8", "replace"):
        f.critical("xxe", short(b, 80))
    else:
        f.passed("xxe", f"status={s}")

    # Transfer-Encoding 異常
    for te in ["chunked, identity", "x-foo"]:
        try:
            s, _, b = req("GET", "/api/health", headers={"Transfer-Encoding": te})
            if s in (200, 501, 400):
                f.passed(f"te:{te}", f"status={s}")
            else:
                f.warn(f"te:{te}", f"unexpected status={s}")
        except Exception as e:
            f.passed(f"te:{te}", f"connection rejected: {type(e).__name__}")

    # Method override
    for hdr in [
        {"X-HTTP-Method-Override": "DELETE"},
        {"X-HTTP-Method": "DELETE"},
        {"X-Method-Override": "DELETE"},
    ]:
        s, _, b = req("POST", "/api/matches/106",
                      body={"tournament": "x"}, headers=hdr)
        # POST /api/matches/{id} は無効 (PUT のみ)
        if s == 200:
            f.critical(f"method_override:{list(hdr.keys())[0]}", short(b, 60))
        else:
            f.passed(f"method_override:{list(hdr.keys())[0]}", f"status={s}")

    # PURGE / TRACE / CONNECT
    for m in ["PURGE", "TRACE", "CONNECT"]:
        try:
            s, _, b = req(m, "/api/health")
            if s == 200:
                f.high(f"method:{m}", f"accepted len={len(b)}")
            else:
                f.passed(f"method:{m}", f"status={s}")
        except Exception as e:
            f.passed(f"method:{m}", f"rejected: {type(e).__name__}")

    # 複数 Authorization (raw)
    if not INSECURE:
        raw = (
            f"GET /api/auth/me HTTP/1.1\r\nHost: {HOST}\r\n"
            f"Authorization: Bearer fake1\r\nAuthorization: Bearer fake2\r\n\r\n"
        ).encode()
        try:
            r = raw_send(raw)
            if b"200" in r[:30]:
                f.critical("dup_auth", "200 returned")
            else:
                f.passed("dup_auth", short(r))
        except Exception as e:
            f.warn("dup_auth", str(e)[:60])

    # CRLF in path (raw)
    if not INSECURE:
        raw = (
            b"GET /api/health\r\nX-Injected: pwned\r\n HTTP/1.1\r\n"
            b"Host: " + HOST.encode() + b"\r\n\r\n"
        )
        try:
            r = raw_send(raw)
            if b"X-Injected" in r:
                f.critical("crlf", "header reflected")
            else:
                f.passed("crlf", "rejected")
        except Exception as e:
            f.warn("crlf", str(e)[:60])

    # Host header poisoning
    for h in ["evil.example.com", "127.0.0.1", "internal.local"]:
        s, _, b = req("GET", "/api/health", headers={"Host": h})
        # Cloudflare reject = 403
        if s == 200 and b'"status":"ok"' in b:
            f.warn(f"host_poison:{h}", "200 (server ignores)")
        else:
            f.passed(f"host_poison:{h}", f"status={s}")

    crit, high, warn, passed = f.summary()
    if crit > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
