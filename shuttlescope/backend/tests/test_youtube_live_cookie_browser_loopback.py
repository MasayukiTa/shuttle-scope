"""YouTube Live: cookie_browser reads the backend host's browser cookies (audit #921).

yt-dlp `--cookies-from-browser` uses the profile of the account that runs the
backend. Only a loopback (local Electron/operator) caller may ask for it; a
remote admin/analyst/coach must get 403 before any network probe runs.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.main import app
from backend.services import youtube_live_recorder as recorder
from backend.utils import control_plane as cp
from backend.utils.jwt_utils import create_access_token


def _headers(role: str) -> dict[str, str]:
    token = create_access_token(user_id=10501, role=role, team_id=None, team_name=None)
    return {"Authorization": f"Bearer {token}"}


def _post(body: dict, role: str):
    client = TestClient(app, base_url="http://localhost", raise_server_exceptions=False)
    return client.post("/api/youtube_live/start", json=body, headers=_headers(role))


def _body(**extra) -> dict:
    return {"url": "https://example.com/live", "quality": "best", **extra}


def test_remote_caller_cannot_use_cookie_browser(db_session, monkeypatch):
    app.dependency_overrides[get_db] = lambda: db_session
    probes: list[tuple] = []
    monkeypatch.setattr(cp, "is_loopback_request", lambda r: False)
    monkeypatch.setattr(recorder, "probe_hls", lambda *a, **k: probes.append(a) or False)
    try:
        for role in ("admin", "analyst", "coach"):
            resp = _post(_body(cookie_browser="chrome"), role)
            assert resp.status_code == 403, f"{role}: {resp.status_code} {resp.text}"
        assert probes == [], "yt-dlp probe must not run with host browser cookies"
    finally:
        app.dependency_overrides.clear()
        recorder._jobs.clear()


def test_loopback_caller_may_use_cookie_browser(db_session, monkeypatch):
    app.dependency_overrides[get_db] = lambda: db_session
    seen: list[tuple] = []
    monkeypatch.setattr(cp, "is_loopback_request", lambda r: True)
    monkeypatch.setattr(recorder, "probe_hls", lambda *a, **k: seen.append(a) or False)
    try:
        resp = _post(_body(cookie_browser="chrome"), "admin")
        assert resp.status_code == 200, resp.text
        assert seen and seen[0][1] == "chrome"
    finally:
        app.dependency_overrides.clear()
        recorder._jobs.clear()


def test_remote_caller_without_cookie_browser_is_unaffected(db_session, monkeypatch):
    app.dependency_overrides[get_db] = lambda: db_session
    monkeypatch.setattr(cp, "is_loopback_request", lambda r: False)
    monkeypatch.setattr(recorder, "probe_hls", lambda *a, **k: False)
    try:
        resp = _post(_body(), "coach")
        assert resp.status_code == 200, resp.text
    finally:
        app.dependency_overrides.clear()
        recorder._jobs.clear()
