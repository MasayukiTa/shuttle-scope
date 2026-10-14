"""camera セッションの公開入口の認可を締めた 3 点の回帰テスト。

A) operator 操作 (approve / reject / end / regenerate-password ...) の認可
   cloudflared / nginx 経由では、インターネットからの通信も TCP peer が 127.0.0.1 に
   なる。peer だけを見る旧実装は tunnel 越しの全リクエストを「ローカル」とみなし、
   (1) operator token 不要、(2) 他チームの JWT でも承認可、になっていた。
B) viewer も operator の承認が要る (ws-ticket / ice-config)
   承認が camera だけの関門だと、コード + パスワードを知る誰もが承認なしで生映像を
   受け取れた (operator UI は join 済みの viewer 全員へ自動で offer する)。
C) /end と regenerate-password は繋がっている WS も閉じる
   DB のトークンを失効させるだけでは、既に確立した WS は生きたまま残る。
   取りこぼした場合に備え、WS 側 60s 再検査ループも session 終了 / トークン失効を見る。
"""
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.db import database as db_module
from backend.db.models import (
    Match, Player, SessionParticipant, SharedSession, Team, User,
)
from backend.main import app
from backend.routers import sessions as sessions_module
from backend.utils import ws_ticket
from backend.utils.jwt_utils import create_access_token
from backend.ws.camera import camera_manager

_PASSWORD = "camera-pass-1234"
_OP_TOKEN = "operator-token-for-tests-0123456789"
# cloudflared が付けるヘッダ。peer は TestClient のまま (= loopback 扱い) で
# 「tunnel 経由」を再現する。
_TUNNEL = {"CF-Connecting-IP": "203.0.113.7"}


@pytest.fixture(autouse=True)
def _clean_state():
    yield
    camera_manager._sessions.clear()
    camera_manager._operator_owners.clear()
    ws_ticket.clear_ws_tickets()
    sessions_module._operator_tokens.clear()


# ─── 共通フィクスチャ ────────────────────────────────────────────────────────

def _make_world(code: str) -> dict:
    """チーム A の試合に紐づく active session と、A / B 両チームのユーザを作る。"""
    from backend.routers.sessions import _hash_password

    db = db_module.SessionLocal()
    try:
        team_a = Team(name=f"{code}-team-a")
        team_b = Team(name=f"{code}-team-b")
        db.add_all([team_a, team_b])
        db.flush()
        pa = Player(name=f"{code}_A", team_id=team_a.id)
        pb = Player(name=f"{code}_B", team_id=team_a.id)
        db.add_all([pa, pb])
        db.flush()
        match = Match(
            tournament="AZ Test", tournament_level="IC", round="R1",
            date=__import__("datetime").date(2026, 8, 15), format="singles",
            player_a_id=pa.id, player_b_id=pb.id, result="win",
            owner_team_id=team_a.id, is_public_pool=False,
        )
        db.add(match)
        db.flush()
        db.add(SharedSession(
            match_id=match.id, session_code=code, created_by_role="analyst",
            is_active=True, password_hash=_hash_password(_PASSWORD),
        ))

        def _user(suffix: str, role: str, team_id, player_id=None, team_name=None) -> dict:
            u = User(
                username=f"{code.lower()}-{suffix}", role=role, team_id=team_id,
                player_id=player_id,
                awaiting_admin_approval=False, consent_required=False, is_test=True,
            )
            db.add(u)
            db.flush()
            tok = create_access_token(
                user_id=u.id, role=role, team_id=team_id, player_id=player_id,
                team_name=team_name, minutes=10,
            )
            return {"Authorization": f"Bearer {tok}"}

        world = {
            # team_name も載っている JWT (本番の通常形)
            "same_team_named": _user("a-named", "analyst", team_a.id, team_name=team_a.name),
            "other_team_named": _user("b-named", "analyst", team_b.id, team_name=team_b.name),
            "same_team": _user("a-analyst", "analyst", team_a.id),
            "same_team_coach": _user("a-coach", "coach", team_a.id),
            "other_team": _user("b-analyst", "analyst", team_b.id),
            "player": _user("a-player", "player", team_a.id, player_id=pa.id),
        }
        db.commit()
        return world
    finally:
        db.close()


def _join(client: TestClient, code: str, **overrides):
    body = {
        "role": "viewer", "device_name": "iPhone", "device_type": "iphone",
        "session_password": _PASSWORD,
    }
    body.update(overrides)
    resp = client.post(f"/api/sessions/{code}/join", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _status(pid: int) -> str:
    db = db_module.SessionLocal()
    try:
        return db.get(SessionParticipant, pid).approval_status
    finally:
        db.close()


def _set(pid: int, **fields) -> None:
    db = db_module.SessionLocal()
    try:
        p = db.get(SessionParticipant, pid)
        for k, v in fields.items():
            setattr(p, k, v)
        db.commit()
    finally:
        db.close()


def _session_active(code: str) -> bool:
    db = db_module.SessionLocal()
    try:
        return db.query(SharedSession).filter(
            SharedSession.session_code == code).one().is_active
    finally:
        db.close()


def _ticket(client, code, data, role):
    return client.post(
        f"/api/sessions/{code}/ws-ticket",
        json={"participant_id": data["participant_id"],
              "participant_token": data["participant_token"], "role": role},
    )


def _ice(client, code, data):
    return client.get(
        f"/api/sessions/{code}/devices/{data['participant_id']}/ice-config",
        headers={"Authorization": f"Participant {data['participant_token']}"},
    )


def _enable_test_turn(monkeypatch):
    from backend.routers import settings as settings_router
    cfg = {
        "turn_enabled": True, "turn_url": "turn:relay.example.com:3478",
        "turn_username": "static-user", "turn_credential": "static-password",
        "turn_static_auth_secret": "participant-shared-secret",
    }
    monkeypatch.setattr(settings_router, "_load_all", lambda _db: cfg)


# ═══ A) operator 操作の認可 ═══════════════════════════════════════════════════

_OPERATOR_POSTS = ["approve", "reject"]


@pytest.mark.parametrize("action", _OPERATOR_POSTS)
def test_a_tunnel_request_with_another_teams_jwt_is_refused(action):
    code = "AZAOTH"
    world = _make_world(code)
    with TestClient(app, base_url="http://localhost") as client:
        data = _join(client, code)
        resp = client.post(
            f"/api/sessions/{code}/devices/{data['participant_id']}/{action}",
            headers={**_TUNNEL, **world["other_team"]},
        )
    assert resp.status_code == 403, resp.text
    assert _status(data["participant_id"]) == "pending"


def test_a_jwt_carrying_team_name_is_scoped_too():
    code = "AZANAM"
    world = _make_world(code)
    with TestClient(app, base_url="http://localhost") as client:
        data = _join(client, code)
        pid = data["participant_id"]
        other = client.post(f"/api/sessions/{code}/devices/{pid}/approve",
                            headers={**_TUNNEL, **world["other_team_named"]})
        assert other.status_code == 403, other.text
        assert _status(pid) == "pending"
        same = client.post(f"/api/sessions/{code}/devices/{pid}/approve",
                           headers={**_TUNNEL, **world["same_team_named"]})
    assert same.status_code == 200, same.text
    assert _status(pid) == "approved"


def test_a_tunnel_request_by_a_player_is_refused():
    code = "AZAPLY"
    world = _make_world(code)
    with TestClient(app, base_url="http://localhost") as client:
        data = _join(client, code)
        resp = client.post(
            f"/api/sessions/{code}/devices/{data['participant_id']}/approve",
            headers={**_TUNNEL, **world["player"]},
        )
    assert resp.status_code == 403, resp.text
    assert _status(data["participant_id"]) == "pending"


def test_a_tunnel_request_without_any_credential_is_refused():
    code = "AZANON"
    _make_world(code)
    with TestClient(app, base_url="http://localhost") as client:
        data = _join(client, code)
        resp = client.post(
            f"/api/sessions/{code}/devices/{data['participant_id']}/approve",
            headers=_TUNNEL,
        )
    assert resp.status_code in (401, 403), resp.text
    assert _status(data["participant_id"]) == "pending"


def test_a_spoofed_legacy_role_header_does_not_grant_access_through_the_tunnel():
    code = "AZASPF"
    world = _make_world(code)
    with TestClient(app, base_url="http://localhost") as client:
        data = _join(client, code)
        resp = client.post(
            f"/api/sessions/{code}/devices/{data['participant_id']}/approve",
            headers={**_TUNNEL, **world["other_team"],
                     "X-Role": "admin", "X-Team-Name": "anything"},
        )
    assert resp.status_code == 403, resp.text
    assert _status(data["participant_id"]) == "pending"


def test_a_operator_token_is_accepted_through_the_tunnel():
    code = "AZATOK"
    world = _make_world(code)
    sessions_module._operator_tokens[code] = _OP_TOKEN
    with TestClient(app, base_url="http://localhost") as client:
        data = _join(client, code)
        # 他チームの JWT でも、そのセッションの operator token を持っていれば通る。
        resp = client.post(
            f"/api/sessions/{code}/devices/{data['participant_id']}/approve",
            headers={**_TUNNEL, **world["other_team"], "X-Session-Token": _OP_TOKEN},
        )
        bad = client.post(
            f"/api/sessions/{code}/devices/{data['participant_id']}/reject",
            headers={**_TUNNEL, **world["other_team"], "X-Session-Token": "wrong"},
        )
    assert resp.status_code == 200, resp.text
    assert bad.status_code == 403, bad.text
    assert _status(data["participant_id"]) == "approved"


@pytest.mark.parametrize("who", ["same_team", "same_team_coach"])
def test_a_same_team_writer_jwt_is_accepted_through_the_tunnel(who):
    code = "AZASAM" + ("A" if who == "same_team" else "C")
    world = _make_world(code)
    with TestClient(app, base_url="http://localhost") as client:
        data = _join(client, code)
        pid = data["participant_id"]
        ok = client.post(
            f"/api/sessions/{code}/devices/{pid}/approve",
            headers={**_TUNNEL, **world[who]},
        )
        rej = client.post(
            f"/api/sessions/{code}/devices/{pid}/reject",
            headers={**_TUNNEL, **world[who]},
        )
    assert ok.status_code == 200, ok.text
    assert rej.status_code == 200, rej.text
    assert _status(pid) == "rejected"


def test_a_genuinely_local_request_needs_no_token():
    """Electron 同居 (peer が loopback でプロキシ痕跡なし) は従来どおり。"""
    code = "AZALOC"
    _make_world(code)
    with TestClient(app, base_url="http://localhost") as client:
        data = _join(client, code)
        resp = client.post(
            f"/api/sessions/{code}/devices/{data['participant_id']}/approve")
    assert resp.status_code == 200, resp.text
    assert _status(data["participant_id"]) == "approved"


@pytest.mark.parametrize("marker", [
    {"CF-Connecting-IP": "203.0.113.7"},
    {"X-Forwarded-For": "203.0.113.7"},
    {"X-Real-IP": "203.0.113.7"},
    {"Forwarded": "for=203.0.113.7"},
])
def test_a_every_proxy_marker_disables_the_local_shortcut(marker):
    from starlette.requests import Request
    from backend.utils.control_plane import is_direct_local_request

    def _req(headers):
        scope = {
            "type": "http", "method": "POST", "path": "/", "query_string": b"",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "client": ("127.0.0.1", 50000),
        }
        return Request(scope)

    assert is_direct_local_request(_req({})) is True
    assert is_direct_local_request(_req(marker)) is False


@pytest.mark.parametrize("path,method", [
    ("end", "post"),
    ("regenerate-password", "post"),
])
def test_a_session_wide_operations_also_refuse_another_team(path, method):
    code = "AZAEND"
    world = _make_world(code)
    with TestClient(app, base_url="http://localhost") as client:
        resp = getattr(client, method)(
            f"/api/sessions/{code}/{path}",
            headers={**_TUNNEL, **world["other_team"]},
        )
    assert resp.status_code == 403, resp.text
    assert _session_active(code) is True


def test_a_set_viewer_permission_refuses_another_team():
    code = "AZAVPM"
    world = _make_world(code)
    with TestClient(app, base_url="http://localhost") as client:
        data = _join(client, code)
        resp = client.post(
            f"/api/sessions/{code}/devices/{data['participant_id']}/set-viewer-permission",
            json={"viewer_permission": "allowed"},
            headers={**_TUNNEL, **world["other_team"]},
        )
    assert resp.status_code == 403, resp.text


# ═══ B) viewer も承認制 ═══════════════════════════════════════════════════════

def test_b_pending_viewer_gets_neither_a_ws_ticket_nor_ice_config(monkeypatch):
    code = "AZBPEN"
    _make_world(code)
    _enable_test_turn(monkeypatch)
    with TestClient(app, base_url="http://localhost") as client:
        data = _join(client, code, device_type="pc", device_name="Viewer PC")
        ticket = _ticket(client, code, data, "viewer")
        ice = _ice(client, code, data)
    assert ticket.status_code == 403, ticket.text
    assert ice.status_code == 403, ice.text


def test_b_approved_viewer_gets_both(monkeypatch):
    code = "AZBAPP"
    _make_world(code)
    _enable_test_turn(monkeypatch)
    with TestClient(app, base_url="http://localhost") as client:
        data = _join(client, code, device_type="pc", device_name="Viewer PC")
        # 実際の承認経路 (operator が approve) を通す。
        ok = client.post(
            f"/api/sessions/{code}/devices/{data['participant_id']}/approve")
        assert ok.status_code == 200, ok.text
        ticket = _ticket(client, code, data, "viewer")
        ice = _ice(client, code, data)
    assert ticket.status_code == 200, ticket.text
    assert ice.status_code == 200, ice.text


def test_b_a_blocked_approved_viewer_is_still_refused(monkeypatch):
    code = "AZBBLK"
    _make_world(code)
    _enable_test_turn(monkeypatch)
    with TestClient(app, base_url="http://localhost") as client:
        data = _join(client, code, device_type="pc", device_name="Viewer PC")
        _set(data["participant_id"], approval_status="approved",
             viewer_permission="blocked")
        ticket = _ticket(client, code, data, "viewer")
        ice = _ice(client, code, data)
    assert ticket.status_code == 403
    assert ice.status_code == 403


# ═══ C) end / regenerate-password は繋がっている WS を閉じる ═══════════════════

_ORIGIN = {"Origin": "http://localhost", "Host": "localhost"}


def _wait(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def _devices(code):
    return set(camera_manager._sessions.get(code, {}).get("devices", {}).keys())


def _viewers(code):
    return set(camera_manager._sessions.get(code, {}).get("viewers", {}).keys())


def _connect_device(client, code):
    data = _join(client, code)
    _set(data["participant_id"], approval_status="approved")
    t = _ticket(client, code, data, "device").json()["data"]["ticket"]
    return data, client.websocket_connect(f"/ws/camera/{code}?ticket={t}", headers=_ORIGIN)


def _connect_viewer(client, code):
    data = _join(client, code, device_type="pc", device_name="Viewer PC")
    _set(data["participant_id"], approval_status="approved")
    t = _ticket(client, code, data, "viewer").json()["data"]["ticket"]
    return data, client.websocket_connect(f"/ws/camera/{code}?ticket={t}", headers=_ORIGIN)


@pytest.mark.parametrize("action", ["end", "regenerate-password"])
def test_c_end_and_regenerate_close_live_device_and_viewer_sockets(action):
    code = "AZC" + ("END" if action == "end" else "PWD")
    _make_world(code)
    with TestClient(app, base_url="http://localhost") as client:
        dev, dev_ctx = _connect_device(client, code)
        vwr, vwr_ctx = _connect_viewer(client, code)
        with dev_ctx as dev_ws, vwr_ctx as vwr_ws:
            assert _wait(lambda: _devices(code) == {str(dev["participant_id"])})
            assert _wait(lambda: _viewers(code) == {str(vwr["participant_id"])})

            resp = client.post(f"/api/sessions/{code}/{action}")
            assert resp.status_code == 200, resp.text

            assert _wait(lambda: not _devices(code) and not _viewers(code)), (
                "end / regenerate-password の後も device / viewer の WS が生きている"
            )
            with pytest.raises(WebSocketDisconnect):
                dev_ws.receive_text()
            with pytest.raises(WebSocketDisconnect):
                vwr_ws.receive_text()


def _fast_recheck(monkeypatch):
    """60s ±10s の再検査間隔を ~0.1s にする (ハンドラは random.uniform で決める)。"""
    import random
    monkeypatch.setattr(random, "uniform", lambda a, b: -59.9)


def test_c_the_periodic_recheck_closes_a_socket_whose_session_has_ended(monkeypatch):
    """immediate 切断を取りこぼしても、再検査ループが終了済みセッションを拾う。"""
    _fast_recheck(monkeypatch)
    code = "AZCLP1"
    _make_world(code)
    with TestClient(app, base_url="http://localhost") as client:
        dev, dev_ctx = _connect_device(client, code)
        vwr, vwr_ctx = _connect_viewer(client, code)
        with dev_ctx as dev_ws, vwr_ctx as vwr_ws:
            assert _wait(lambda: _devices(code) and _viewers(code))
            # REST を通さず DB だけ書き換える = 即時切断が走らなかった状況
            db = db_module.SessionLocal()
            try:
                s = db.query(SharedSession).filter(
                    SharedSession.session_code == code).one()
                s.is_active = False
                db.commit()
            finally:
                db.close()
            assert _wait(lambda: not _devices(code)), "device WS が閉じられていない"
            assert _wait(lambda: not _viewers(code)), "viewer WS が閉じられていない"
            with pytest.raises(WebSocketDisconnect):
                dev_ws.receive_text()
            with pytest.raises(WebSocketDisconnect):
                vwr_ws.receive_text()


def test_c_the_periodic_recheck_closes_a_viewer_whose_token_was_revoked(monkeypatch):
    _fast_recheck(monkeypatch)
    code = "AZCLP2"
    _make_world(code)
    with TestClient(app, base_url="http://localhost") as client:
        vwr, vwr_ctx = _connect_viewer(client, code)
        with vwr_ctx as vwr_ws:
            assert _wait(lambda: _viewers(code))
            _set(vwr["participant_id"], ws_token_hash=None, ws_token_expires_at=None)
            assert _wait(lambda: not _viewers(code)), "失効した viewer が配信され続ける"
            with pytest.raises(WebSocketDisconnect):
                vwr_ws.receive_text()


def test_c_a_healthy_viewer_is_not_closed_by_the_recheck(monkeypatch):
    """誤切断しないこと (再検査が有効な接続を巻き込まない)。"""
    _fast_recheck(monkeypatch)
    code = "AZCLP3"
    _make_world(code)
    with TestClient(app, base_url="http://localhost") as client:
        vwr, vwr_ctx = _connect_viewer(client, code)
        with vwr_ctx:
            assert _wait(lambda: _viewers(code))
            time.sleep(1.0)   # 再検査が十数回走る時間
            assert _viewers(code) == {str(vwr["participant_id"])}
