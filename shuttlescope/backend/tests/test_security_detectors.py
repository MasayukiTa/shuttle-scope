"""Missing security detections: secret_path_200 / decoy_hit, mfa_recovery_failures,
login_success_new_ip, and request_logs.user_id.

Background: a review of 5000 security_events and 5000 request_logs rows found none
of these three events, and request_logs.user_id empty on every row. Fake values
only; no log capture.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient

import backend.db.database as db_module
from backend.db.database import get_db
from backend.db.models import AccessLog, RequestLog, SecurityEvent, User
from backend.main import app
from backend.middleware.security_observability import RequestLogMiddleware
from backend.middleware.security_observability import _authenticated_user_id  # noqa: F401
from backend.routers import auth as auth_module
from backend.routers.auth import _hash_password, _hotp_value
from backend.utils import security_detectors as sd
from backend.utils import security_log
from backend.utils.jwt_utils import create_access_token

try:
    from backend.main import AdminWriteRateLimitMiddleware
except Exception:  # pragma: no cover
    AdminWriteRateLimitMiddleware = None  # type: ignore[assignment]

PUBLIC_IP = "1.2.3.4"      # fake; must be a non-private address
OTHER_IP = "5.6.7.8"


@pytest.fixture(autouse=True)
def _env(db_session, monkeypatch):
    """Point the event writers at the test DB, capture notifications, reset state."""
    monkeypatch.setattr(security_log, "SessionLocal", db_module.SessionLocal)
    sent: list[str] = []
    monkeypatch.setattr(sd, "notify_admin", lambda content: sent.append(content))
    sd.reset_mfa_failure_state()
    auth_module._IP_LOGIN_TIMES.clear()
    auth_module._mfa_failures.clear()
    if AdminWriteRateLimitMiddleware is not None:
        AdminWriteRateLimitMiddleware._state.clear()
    yield sent
    sd.reset_mfa_failure_state()
    auth_module._IP_LOGIN_TIMES.clear()
    auth_module._mfa_failures.clear()
    if AdminWriteRateLimitMiddleware is not None:
        AdminWriteRateLimitMiddleware._state.clear()


def _events(db_session, event_type: str):
    db_session.expire_all()
    return db_session.query(SecurityEvent).filter(SecurityEvent.event_type == event_type).all()


# ── 1. secret paths ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("path", [
    "/.env", "/.env.bak", "/app/.env", "/config/.env", "/backup/.env",
    "/.git/config", "/.aws/credentials", "/wp-config.php.bak", "/id_rsa",
    "/backup.sql", "/db.sqlite", "/dump.sql", "/backup.tar.gz", "/server.pem",
])
def test_secret_paths_are_recognised(path):
    assert sd.is_secret_path(path)


@pytest.mark.parametrize("path", [
    "/", "/api/health", "/assets/index-abc123.js", "/favicon.ico",
    "/api/players", "/environment", "/index.html",
])
def test_ordinary_paths_are_not_secret(path):
    assert not sd.is_secret_path(path)


def _mini_app() -> FastAPI:
    mini = FastAPI()
    mini.add_middleware(RequestLogMiddleware)

    @mini.get("/real/.env.bak")
    def real_leak():  # a real file served without the decoy marker
        return PlainTextResponse("FAKE_VALUE=1")

    @mini.get("/decoy/.env.bak")
    def decoy(request: Request):  # mimics decoy_maze._record_and_delay
        request.state.is_decoy = True
        return PlainTextResponse("FAKE_VALUE=2")

    @mini.get("/marker/.env.bak")
    def decoy_header():  # the fake .env also sends the header
        return PlainTextResponse("FAKE_VALUE=3", headers={"X-Honeyfile": "yes"})

    @mini.get("/missing/.env.bak")
    def missing():
        return PlainTextResponse("nope", status_code=404)

    @mini.get("/api/admin/backup.sql")
    def api_download():
        return PlainTextResponse("-- fake dump")

    @mini.get("/ping")
    def ping():
        return PlainTextResponse("ok")

    return mini


def test_real_secret_file_200_is_critical_and_notified(db_session, _env):
    client = TestClient(_mini_app(), client=(PUBLIC_IP, 50000))
    assert client.get("/real/.env.bak").status_code == 200
    rows = _events(db_session, "secret_path_200")
    assert len(rows) == 1
    assert rows[0].severity == "critical"
    assert rows[0].path == "/real/.env.bak"
    assert not _events(db_session, "decoy_hit")
    assert len(_env) == 1 and "secret_path_200" in _env[0]


def test_decoy_200_is_decoy_hit_not_critical(db_session, _env):
    client = TestClient(_mini_app(), client=(PUBLIC_IP, 50000))
    assert client.get("/decoy/.env.bak").status_code == 200
    assert client.get("/marker/.env.bak").status_code == 200
    assert not _events(db_session, "secret_path_200")
    assert _env == []  # decoy hits do not page anyone


def test_decoy_hit_is_deduplicated_per_ip_per_hour(db_session):
    client = TestClient(_mini_app(), client=(PUBLIC_IP, 50000))
    for _ in range(5):
        client.get("/decoy/.env.bak")
    assert len(_events(db_session, "decoy_hit")) == 1
    other = TestClient(_mini_app(), client=(OTHER_IP, 50000))
    other.get("/decoy/.env.bak")
    rows = _events(db_session, "decoy_hit")
    assert len(rows) == 2 and {r.severity for r in rows} == {"low"}


def test_non_200_and_authenticated_api_download_raise_nothing(db_session):
    client = TestClient(_mini_app(), client=(PUBLIC_IP, 50000))
    client.get("/missing/.env.bak")
    client.get("/ping")
    token = create_access_token(7, "admin")
    client.get("/api/admin/backup.sql", headers={"Authorization": f"Bearer {token}"})
    assert not _events(db_session, "secret_path_200")
    assert not _events(db_session, "decoy_hit")


def test_real_app_decoy_env_is_decoy_hit(db_session, _env):
    """The deliberate decoy in decoy_maze.py must be classified as decoy_hit."""
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app, raise_server_exceptions=False, client=(PUBLIC_IP, 50000))
        resp = client.get("/app/.env")
        assert resp.status_code == 200
        assert resp.headers.get("x-honeyfile") == "yes"
        assert len(_events(db_session, "decoy_hit")) == 1
        assert not _events(db_session, "secret_path_200")
    finally:
        app.dependency_overrides.clear()


def test_decoy_without_header_is_still_a_decoy(db_session):
    """/.ssh/id_rsa etc. are decoys that send no X-Honeyfile header."""
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app, raise_server_exceptions=False, client=(PUBLIC_IP, 50000))
        resp = client.get("/.ssh/id_rsa")
        assert resp.status_code == 200
        assert "x-honeyfile" not in resp.headers
        assert not _events(db_session, "secret_path_200")
        assert len(_events(db_session, "decoy_hit")) == 1
    finally:
        app.dependency_overrides.clear()


# nginx ingestion: only requests nginx answered itself are judged there.
def test_nginx_shipper_judges_only_nginx_served_lines():
    from backend.tools import nginx_log_shipper as sh
    assert sh._nginx_answered_itself({"status": 200, "up": "-"})
    assert sh._nginx_answered_itself({"status": 200, "up": ""})
    assert not sh._nginx_answered_itself({"status": 200, "up": "200"})
    assert not sh._nginx_answered_itself({"status": 200})  # old log format


def test_nginx_served_secret_file_is_critical(db_session, _env, tmp_path, monkeypatch):
    import json
    from backend.tools import nginx_log_shipper as sh
    monkeypatch.setattr(sh, "NGINX_LOG_DIR", tmp_path)
    monkeypatch.setattr(sh, "MAX_AGE_HOURS", 0)
    lines = [
        {"uri": "/static-root/.env", "status": 200, "up": "-", "method": "GET",
         "cf": PUBLIC_IP, "country": "XX", "ts": "2026-10-22T09:00:00+00:00", "rt": 0.001},
        {"uri": "/app/.env", "status": 200, "up": "200", "method": "GET",
         "cf": PUBLIC_IP, "country": "XX", "ts": "2026-10-22T09:00:01+00:00", "rt": 0.001,
         "honey": "yes"},
    ]
    (tmp_path / "ss_access.log").write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    monkeypatch.setattr(sh, "emit_request_log", lambda **kw: None)
    sh._ship_access_log({})
    rows = _events(db_session, "secret_path_200")
    assert len(rows) == 1 and rows[0].path == "/static-root/.env"
    assert (rows[0].details or {}).get("source") == "nginx"
    assert not _events(db_session, "decoy_hit")


# ── 2. MFA / recovery failures ──────────────────────────────────────────────
def test_mfa_failures_below_threshold_raise_nothing(db_session):
    for _ in range(sd.MFA_FAILURE_THRESHOLD - 1):
        assert sd.record_mfa_failure(11, PUBLIC_IP, "recovery") == []
    assert not _events(db_session, "mfa_recovery_failures")


def test_mfa_failures_at_threshold_raise_one_high_event_and_notify(db_session, _env):
    scopes = []
    for _ in range(sd.MFA_FAILURE_THRESHOLD + 2):
        scopes += sd.record_mfa_failure(11, PUBLIC_IP, "recovery")
    assert sorted(scopes) == ["ip", "user"]  # once per scope, not per attempt
    rows = _events(db_session, "mfa_recovery_failures")
    assert len(rows) == 2 and {r.severity for r in rows} == {"high"}
    assert all(r.user_id == 11 and r.ip_addr == PUBLIC_IP for r in rows)
    assert len(_env) == 2 and all("mfa_recovery_failures" in m for m in _env)


def test_mfa_failures_outside_window_do_not_count(db_session, monkeypatch):
    base = time.time()
    monkeypatch.setattr(sd.time, "time", lambda: base)
    sd.record_mfa_failure(12, None)
    sd.record_mfa_failure(12, None)
    monkeypatch.setattr(sd.time, "time", lambda: base + sd.MFA_FAILURE_WINDOW_SEC + 1)
    assert sd.record_mfa_failure(12, None) == []
    assert not _events(db_session, "mfa_recovery_failures")


def _totp(secret: str) -> str:
    return f"{_hotp_value(secret, int(time.time()) // 30):06d}"


def test_wrong_recovery_codes_on_mfa_login_raise_event_without_the_code(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        user = User(username="det_mfa_user", role="analyst",
                    hashed_credential=_hash_password("correct-horse-battery"))
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        client = TestClient(app, base_url="http://localhost", client=(PUBLIC_IP, 50000))
        headers = {"Authorization": f"Bearer {create_access_token(user.id, user.role)}"}
        secret = client.post("/api/auth/mfa/setup", headers=headers).json()["secret"]
        assert client.post("/api/auth/mfa/confirm", headers=headers,
                           json={"code": _totp(secret)}).status_code == 200
        auth_module._mfa_failures.clear()
        sd.reset_mfa_failure_state()
        login = client.post("/api/auth/login", json={
            "grant_type": "credential", "username": "det_mfa_user",
            "password": "correct-horse-battery"})
        mfa_token = login.json()["mfa_token"]
        wrong = "ZZZZ-ZZZZ-ZZZZ-ZZZZ"
        for i in range(sd.MFA_FAILURE_THRESHOLD):
            r = client.post("/api/auth/mfa/login",
                            headers={"Authorization": f"Bearer {mfa_token}"},
                            json={"mfa_token": mfa_token, "recovery_code": wrong})
            assert r.status_code == 401
            expect = 1 if i == sd.MFA_FAILURE_THRESHOLD - 1 else 0
            assert len(_events(db_session, "mfa_recovery_failures")) >= expect
        rows = _events(db_session, "mfa_recovery_failures")
        assert rows and all(r.user_id == user.id and r.severity == "high" for r in rows)
        assert all("ZZZZ" not in str(r.details) for r in rows)
    finally:
        app.dependency_overrides.clear()
        db_session.rollback()
        db_session.query(User).filter(User.username == "det_mfa_user").delete()
        db_session.commit()


# ── 3. login success from a new IP ──────────────────────────────────────────
def _before() -> datetime:
    return datetime.utcnow()


def test_unseen_ip_raises_high_event_for_privileged_role(db_session, _env):
    out = sd.check_login_new_ip(user_id=21, role="admin", ip=PUBLIC_IP, country="XX",
                                before=_before())
    assert out == "login_success_new_ip"
    rows = _events(db_session, "login_success_new_ip")
    assert len(rows) == 1 and rows[0].severity == "high"
    assert rows[0].ip_addr == PUBLIC_IP and rows[0].user_id == 21
    assert rows[0].details["role"] == "admin" and rows[0].details["country"] == "XX"
    assert len(_env) == 1 and PUBLIC_IP in _env[0] and "user_id=21" in _env[0]


def test_unprivileged_role_is_medium(db_session):
    sd.check_login_new_ip(user_id=22, role="player", ip=PUBLIC_IP, country=None,
                          before=_before())
    assert _events(db_session, "login_success_new_ip")[0].severity == "medium"


def test_ip_seen_in_last_30_days_is_quiet_but_older_is_new(db_session):
    now = datetime.utcnow()
    db_session.add(AccessLog(user_id=23, action="login", ip_addr=PUBLIC_IP,
                             created_at=now - timedelta(days=29)))
    db_session.add(AccessLog(user_id=23, action="login", ip_addr=OTHER_IP,
                             created_at=now - timedelta(days=31)))
    db_session.commit()
    assert sd.check_login_new_ip(user_id=23, role="coach", ip=PUBLIC_IP, country=None,
                                 before=now) is None
    assert sd.check_login_new_ip(user_id=23, role="coach", ip=OTHER_IP, country=None,
                                 before=now) == "login_success_new_ip"


def test_failed_logins_from_an_ip_do_not_make_it_known(db_session):
    now = datetime.utcnow()
    db_session.add(AccessLog(user_id=24, action="login_failed", ip_addr=PUBLIC_IP,
                             created_at=now - timedelta(days=1)))
    db_session.commit()
    assert sd.check_login_new_ip(user_id=24, role="admin", ip=PUBLIC_IP, country=None,
                                 before=now) == "login_success_new_ip"


def test_private_or_missing_ip_is_ignored(db_session):
    for ip in ("127.0.0.1", "192.168.0.5", "testclient", None, ""):
        assert sd.check_login_new_ip(user_id=25, role="admin", ip=ip, country=None,
                                     before=_before()) is None
    assert not _events(db_session, "login_success_new_ip")


def test_real_login_flow_raises_once_then_is_quiet(db_session, _env):
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        user = User(username="det_login_user", role="analyst",
                    hashed_credential=_hash_password("correct-horse-battery"))
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        client = TestClient(app, base_url="http://localhost", client=(PUBLIC_IP, 50000))
        body = {"grant_type": "credential", "username": "det_login_user",
                "password": "correct-horse-battery"}
        assert client.post("/api/auth/login", json=body).status_code == 200
        rows = _events(db_session, "login_success_new_ip")
        assert len(rows) == 1 and rows[0].severity == "high"
        assert rows[0].user_id == user.id and rows[0].ip_addr == PUBLIC_IP
        assert "correct-horse" not in str(rows[0].details) + _env[0]
        assert client.post("/api/auth/login", json=body).status_code == 200
        assert len(_events(db_session, "login_success_new_ip")) == 1
    finally:
        app.dependency_overrides.clear()
        db_session.rollback()
        db_session.query(User).filter(User.username == "det_login_user").delete()
        db_session.commit()


# ── request_logs.user_id ────────────────────────────────────────────────────
def test_request_log_records_user_id_from_valid_bearer_token(db_session):
    client = TestClient(_mini_app(), client=(PUBLIC_IP, 50000))
    client.get("/ping", headers={"Authorization": f"Bearer {create_access_token(31, 'analyst')}"})
    client.get("/ping", headers={"Authorization": "Bearer not-a-real-token"})
    client.get("/ping")
    db_session.expire_all()
    rows = db_session.query(RequestLog).filter(RequestLog.path == "/ping").order_by(RequestLog.id).all()
    assert [r.user_id for r in rows] == [31, None, None]


# ── decoy maze: crawlers, robots headers, signed deep links ─────────────────
import re

from backend.routers import canary as canary_module
from backend.routers import decoy_maze
from backend.utils import crawler_policy as cp

BING_UA = "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)"
HUMAN_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"


@pytest.fixture()
def maze(db_session, monkeypatch):
    """Real app, no tarpit delay, and any ban attempt recorded."""
    monkeypatch.setattr(decoy_maze.random, "uniform", lambda a, b: 0)
    bans: list[tuple] = []
    monkeypatch.setattr(canary_module, "_trigger_cf_auto_ban",
                        lambda *a, **k: bans.append((a, k)))
    import backend.utils.escalation_policy as ep
    monkeypatch.setattr(ep, "record_hit_and_decide",
                        lambda *a, **k: {"confidence": "high", "ttl_sec": 60})
    app.dependency_overrides[get_db] = lambda: db_session
    yield bans
    app.dependency_overrides.clear()


def _c(ip=PUBLIC_IP):
    return TestClient(app, raise_server_exceptions=False, client=(ip, 50000))


def test_crawler_ua_on_decoy_is_recorded_low_and_never_banned(db_session, maze):
    c = _c()
    for _ in range(3):
        r = c.get("/admin/login", headers={"user-agent": BING_UA})
        assert r.status_code == 200
    assert maze == []  # the escalation stub would ban every IP; none was banned
    rows = _events(db_session, "crawler_decoy_visit")
    assert len(rows) == 1 and rows[0].severity == "low"  # once per IP per day
    assert not _events(db_session, "decoy_hit")
    assert not _events(db_session, "secret_path_200")


def test_crawler_ip_range_without_crawler_ua_is_also_not_banned(db_session, maze):
    c = _c("40.77.167.5")
    assert c.get("/app/.env", headers={"user-agent": HUMAN_UA}).status_code == 200
    assert maze == []
    assert len(_events(db_session, "crawler_decoy_visit")) == 1
    assert not _events(db_session, "decoy_hit")


def test_human_ua_on_decoy_still_escalates(db_session, maze):
    """The ban path still works for a non-crawler (control for the tests above)."""
    c = _c()
    assert c.get("/admin/login", headers={"user-agent": HUMAN_UA}).status_code == 200
    assert len(maze) == 1


def test_canary_hit_by_crawler_is_not_banned(db_session, maze):
    path = sorted(canary_module._CANARY_PATHS)[0]
    r = _c().get(path, headers={"user-agent": BING_UA})
    assert r.status_code == 404
    assert maze == []
    assert len(_events(db_session, "crawler_decoy_visit")) == 1


@pytest.mark.parametrize("path", [
    "/admin/login", "/admin/dashboard", "/app/.env", "/admin/legacy",
    "/admin/media.tar.gz", "/internal/x",
])
def test_every_decoy_response_carries_noindex_header(maze, path):
    r = _c().get(path, headers={"user-agent": HUMAN_UA})
    assert r.headers.get("x-robots-tag") == "noindex, nofollow, noarchive"


def test_decoy_html_has_meta_robots_and_nofollow_links(maze):
    r = _c().get("/admin/dashboard", headers={"user-agent": HUMAN_UA})
    assert 'name="robots" content="noindex,nofollow"' in r.text
    assert '<a href=' not in r.text and 'rel="nofollow"' in r.text


@pytest.mark.parametrize("path", [
    "/admin/media.tar.gz", "/admin/services.zst", "/admin/home.gz",
    "/admin/.env.gz/settings", "/admin/anything/else", "/internal/x",
    "/admin/legacy/v1/users",
])
def test_unsigned_deep_paths_are_404(maze, path):
    assert _c().get(path, headers={"user-agent": HUMAN_UA}).status_code == 404


def test_signed_link_emitted_by_the_decoy_works_but_not_tampered_or_crawled(maze):
    c = _c()
    page = c.get("/admin/legacy", headers={"user-agent": HUMAN_UA}).text
    links = re.findall(r'href="(/admin/legacy/[^"]+\?k=[0-9a-f]+)"', page)
    assert links
    good = links[0].replace("&amp;", "&")
    assert c.get(good, headers={"user-agent": HUMAN_UA}).status_code == 200
    # same signature on another path
    sig = good.split("?k=")[1]
    assert c.get(f"/admin/legacy/other?k={sig}", headers={"user-agent": HUMAN_UA}).status_code == 404
    assert c.get(good.split("?k=")[0] + "?k=" + "0" * 24,
                 headers={"user-agent": HUMAN_UA}).status_code == 404
    # a crawler never goes deeper, even with a valid signature
    bans_before = len(maze)  # human requests above may escalate (stubbed)
    assert c.get(good, headers={"user-agent": BING_UA}).status_code == 404
    assert len(maze) == bans_before


def test_deep_levels_chain_through_signed_links_only(maze):
    c = _c()
    page = c.get("/admin/legacy", headers={"user-agent": HUMAN_UA}).text
    first = re.findall(r'href="(/admin/legacy/[^"]+\?k=[0-9a-f]+)"', page)[0]
    body = c.get(first, headers={"user-agent": HUMAN_UA}).json()
    nxt = body["data"]["see_also"]
    assert "?k=" in nxt
    assert c.get(nxt, headers={"user-agent": HUMAN_UA}).status_code == 200


def test_robots_txt_disallows_decoy_prefixes(maze):
    r = _c().get("/robots.txt")
    assert r.status_code == 200
    assert "Disallow: /admin" in r.text and "Disallow: /internal" in r.text


def test_signing_key_comes_from_environment_not_source(monkeypatch):
    monkeypatch.setenv("SS_MAZE_SIGNING_KEY", "unit-test-key-one")
    a = cp.sign_path("/admin/x")
    monkeypatch.setenv("SS_MAZE_SIGNING_KEY", "unit-test-key-two")
    assert a and a != cp.sign_path("/admin/x")
    assert not cp.verify_path("/admin/x", a)
