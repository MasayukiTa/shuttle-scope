"""セッション共有 URL の公開 HTTPS オリジン先頭付け (fix/session-share-public-origin)。

症状: 公開 HTTPS (app.shuttle-scope.com) で記録画面を開いていても、
_session_to_dict が LAN IP / localhost の URL しか返さず、別ネットワークの
端末が開けなかった。named tunnel が無くても、リクエストの Host と
 X-Forwarded-Proto が公開 HTTPS なら、その origin を先頭に足す。
"""
from datetime import date
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.db.database import get_db
from backend.db.models import Player, Match
from backend.routers.sessions import _public_https_origin


def _make_match(db):
    pa = Player(name="Aさん")
    pb = Player(name="Bさん")
    db.add(pa)
    db.add(pb)
    db.flush()
    m = Match(
        tournament="テスト大会",
        tournament_level="IC",
        round="1回戦",
        date=date(2025, 1, 1),
        format="singles",
        player_a_id=pa.id,
        player_b_id=pb.id,
        result="win",
    )
    db.add(m)
    db.flush()
    return m


@pytest.fixture
def client_and_match(db_session):
    match = _make_match(db_session)
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app, headers={"X-Role": "admin"})
    yield client, match.id
    app.dependency_overrides.clear()


class TestPublicHttpsOriginHelper:
    """_public_https_origin のユニット。公開ドメインだけ origin を返す。"""

    class _Req:
        def __init__(self, headers, scheme="http"):
            from starlette.datastructures import Headers, URL
            self.headers = Headers(headers)
            self.url = URL(f"{scheme}://placeholder/")

    def test_public_domain_over_forwarded_https_returns_origin(self):
        req = self._Req({
            "host": "app.shuttle-scope.com",
            "x-forwarded-proto": "https",
        })
        assert _public_https_origin(req) == "https://app.shuttle-scope.com"

    def test_plain_http_is_rejected(self):
        req = self._Req({
            "host": "app.shuttle-scope.com",
            "x-forwarded-proto": "http",
        })
        assert _public_https_origin(req) is None

    def test_localhost_is_rejected(self):
        req = self._Req({"host": "localhost:8765", "x-forwarded-proto": "https"})
        assert _public_https_origin(req) is None

    def test_private_lan_ip_is_rejected(self):
        req = self._Req({"host": "192.168.0.5:8765", "x-forwarded-proto": "https"})
        assert _public_https_origin(req) is None

    def test_none_request_returns_none(self):
        assert _public_https_origin(None) is None

    def test_hostile_forwarded_host_is_rejected(self):
        # SSRF / host-injection: an attacker-controlled X-Forwarded-Host that is
        # not a configured public host must NOT be reflected into a share URL.
        req = self._Req({
            "host": "app.shuttle-scope.com",
            "x-forwarded-host": "attacker.example",
            "x-forwarded-proto": "https",
        })
        assert _public_https_origin(req) is None

    def test_hostile_host_header_is_rejected(self):
        req = self._Req({
            "host": "evil.attacker.test",
            "x-forwarded-proto": "https",
        })
        assert _public_https_origin(req) is None

    def test_lookalike_suffix_host_is_rejected(self):
        # Not a substring/suffix match: app.shuttle-scope.com.attacker.test
        # must be rejected even though it contains the real host as a prefix.
        req = self._Req({
            "host": "app.shuttle-scope.com.attacker.test",
            "x-forwarded-proto": "https",
        })
        assert _public_https_origin(req) is None

    def test_configured_public_host_still_returns_origin(self):
        # The normal, allowlisted host still works after the guard is added.
        req = self._Req({
            "host": "app.shuttle-scope.com",
            "x-forwarded-proto": "https",
        })
        assert _public_https_origin(req) == "https://app.shuttle-scope.com"


class TestSessionToDictPublicOrigin:
    """エンドポイント経由: 公開 Host のとき camera_sender_urls の先頭が公開 https。"""

    def _create(self, client, match_id, headers):
        resp = client.post(
            "/api/sessions",
            json={"match_id": match_id, "created_by_role": "analyst"},
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        return resp.json()["data"]

    def test_public_host_prepends_https_camera_url(self, client_and_match, monkeypatch):
        client, match_id = client_and_match
        monkeypatch.setattr("backend.routers.sessions._named_tunnel_url", lambda: None)
        data = self._create(client, match_id, {
            "host": "app.shuttle-scope.com",
            "x-forwarded-proto": "https",
        })
        cam = data["camera_sender_urls"]
        assert cam, "camera_sender_urls should not be empty"
        assert cam[0].startswith("https://app.shuttle-scope.com/")
        assert "/camera/" in cam[0]
        assert data.get("public_origin_active") is True

    def test_public_host_prepends_https_coach_url(self, client_and_match, monkeypatch):
        client, match_id = client_and_match
        monkeypatch.setattr("backend.routers.sessions._named_tunnel_url", lambda: None)
        data = self._create(client, match_id, {
            "host": "app.shuttle-scope.com",
            "x-forwarded-proto": "https",
        })
        coach = data["coach_urls"]
        assert coach[0].startswith("https://app.shuttle-scope.com/")

    def test_localhost_host_keeps_legacy_urls(self, client_and_match, monkeypatch):
        client, match_id = client_and_match
        monkeypatch.setattr("backend.routers.sessions._named_tunnel_url", lambda: None)
        data = self._create(client, match_id, {
            "host": "localhost:8765",
            "x-forwarded-proto": "http",
        })
        cam = data["camera_sender_urls"]
        assert not any(urlparse(u).hostname == "app.shuttle-scope.com" for u in cam)
        assert data.get("public_origin_active") is False

    def test_password_never_in_urls(self, client_and_match, monkeypatch):
        client, match_id = client_and_match
        monkeypatch.setattr("backend.routers.sessions._named_tunnel_url", lambda: None)
        data = self._create(client, match_id, {
            "host": "app.shuttle-scope.com",
            "x-forwarded-proto": "https",
        })
        pw = data.get("session_password")
        assert pw
        for key in ("coach_urls", "camera_sender_urls"):
            for u in data.get(key) or []:
                assert pw not in u
