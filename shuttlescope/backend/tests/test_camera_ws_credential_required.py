"""カメラ WS に入る資格情報の回帰テスト (監査 #465 / #466)。

監査の指摘:
  #465 viewer の WS が session password / join を通らず、active な
       session_code だけで繋がる。
  #466 device の WS が participant_id の所属しか見ず、接続者本人の
       資格情報を確かめない。

現行の実装では、join が参加者トークンを発行し、それを 30 秒使い捨ての入場券
(`POST /sessions/{code}/ws-ticket`) に引き換える。`/ws/camera/{code}` は
device / viewer をこの入場券でしか受けず、身元 (session / role / participant_id)
は入場券に刻まれた値を使う。

既存テストはこのうち「別セッションの入場券」「クエリ申告の participant_id の無視」
「再利用」を見ている。ここでは次の抜けを実行時の挙動で固定する。
  - 入場券なしの device / viewer は、アプリの JWT を持っていても拒否される
  - 偽の入場券・期限切れの入場券は拒否される
  - 入場券の role は、クエリで名乗る role に勝つ
  - 他人の viewer_id を名乗っても、入場券の participant_id で登録される
"""
import pytest
from datetime import date

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.db import database as db_module
from backend.db.models import Match, Player, SessionParticipant, SharedSession
from backend.main import app
from backend.routers.sessions import _hash_password
from backend.utils import ws_ticket
from backend.utils.jwt_utils import create_access_token
from backend.ws.camera import camera_manager

_PASSWORD = "camera-pass-1234"


@pytest.fixture(autouse=True)
def _clean_state():
    yield
    camera_manager._sessions.clear()
    camera_manager._operator_owners.clear()
    ws_ticket.clear_ws_tickets()


def _make_session(code: str) -> None:
    db = db_module.SessionLocal()
    try:
        pa = Player(name=f"{code}_A")
        pb = Player(name=f"{code}_B")
        db.add_all([pa, pb])
        db.flush()
        match = Match(
            tournament="WS Cred Test", tournament_level="IC", round="R1",
            date=date(2026, 8, 15), format="singles",
            player_a_id=pa.id, player_b_id=pb.id, result="win",
        )
        db.add(match)
        db.flush()
        db.add(SharedSession(
            match_id=match.id, session_code=code, created_by_role="analyst",
            is_active=True, password_hash=_hash_password(_PASSWORD),
        ))
        db.commit()
    finally:
        db.close()


def _join(client: TestClient, code: str, uid: str) -> dict:
    resp = client.post(f"/api/sessions/{code}/join", json={
        "role": "viewer",
        "device_name": "iPhone",
        "device_type": "iphone",
        "device_uid": uid,
        "session_password": _PASSWORD,
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    # operator の承認済みにする (承認前は入場券が出ない)
    db = db_module.SessionLocal()
    try:
        p = db.get(SessionParticipant, data["participant_id"])
        p.approval_status = "approved"
        db.commit()
    finally:
        db.close()
    return data


def _ticket(client: TestClient, code: str, data: dict, role: str) -> str:
    resp = client.post(f"/api/sessions/{code}/ws-ticket", json={
        "participant_id": data["participant_id"],
        "participant_token": data["participant_token"],
        "role": role,
    })
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["ticket"]


def _app_jwt() -> str:
    """アプリにログイン済みの利用者の JWT。JWT があっても device / viewer にはなれない。"""
    return create_access_token(user_id=1, role="admin", minutes=10)


def _refused(client: TestClient, url: str) -> int:
    """接続が handshake 直後の close で拒否されることを確かめ、close code を返す。"""
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(url) as ws:
            ws.receive_text()
    return exc.value.code


def _devices(code: str) -> set:
    return set(camera_manager._sessions.get(code, {}).get("devices", {}).keys())


def _viewers(code: str) -> set:
    return set(camera_manager._sessions.get(code, {}).get("viewers", {}).keys())


# ── #465: viewer ────────────────────────────────────────────────────────────

def test_viewer_without_a_ticket_is_refused_even_with_an_app_jwt():
    code = "WCV1"
    _make_session(code)
    with TestClient(app, base_url="http://localhost") as client:
        data = _join(client, code, "uid-v1")
        jwt = _app_jwt()
        # viewer_id は join 済みの本物の participant id。それでも入場券が無ければ入れない。
        pid = data["participant_id"]
        for qs in (
            f"role=viewer&viewer_id={pid}&token={jwt}",
            f"role=viewer&vid={pid}&token={jwt}",
            f"viewer_id={pid}&token={jwt}",
        ):
            assert _refused(client, f"/ws/camera/{code}?{qs}") == 4403, qs
        assert _viewers(code) == set()


def test_viewer_with_a_made_up_or_expired_ticket_is_refused(monkeypatch):
    code = "WCV2"
    _make_session(code)
    with TestClient(app, base_url="http://localhost") as client:
        data = _join(client, code, "uid-v2")
        jwt = _app_jwt()
        # 発行されていない文字列
        assert _refused(
            client, f"/ws/camera/{code}?role=viewer&viewer_id={data['participant_id']}"
                    f"&ticket=not-a-real-ticket&token={jwt}",
        ) == 4403
        # 期限切れ (発行直後に失効する寿命で発行する)
        monkeypatch.setattr(ws_ticket, "TICKET_TTL_SEC", -1)
        expired = _ticket(client, code, data, "viewer")
        assert _refused(
            client,
            f"/ws/camera/{code}?ticket={expired}"
            f"&viewer_id={data['participant_id']}&token={jwt}",
        ) == 4403
        assert _viewers(code) == set()


def test_valid_viewer_ticket_connects_as_the_ticket_identity_not_the_query():
    code = "WCV3"
    _make_session(code)
    with TestClient(app, base_url="http://localhost") as client:
        mine = _join(client, code, "uid-v3a")
        other = _join(client, code, "uid-v3b")
        ticket = _ticket(client, code, mine, "viewer")
        with client.websocket_connect(
            f"/ws/camera/{code}?ticket={ticket}&viewer_id={other['participant_id']}"
        ):
            registered = _viewers(code)
    assert registered == {str(mine["participant_id"])}


# ── #466: device ────────────────────────────────────────────────────────────

def test_device_without_a_ticket_is_refused_even_for_an_approved_participant():
    code = "WCD1"
    _make_session(code)
    with TestClient(app, base_url="http://localhost") as client:
        data = _join(client, code, "uid-d1")
        jwt = _app_jwt()
        pid = data["participant_id"]
        # participant_id の所属が正しくても、本人の資格情報 (入場券) が無ければ入れない。
        assert _refused(
            client, f"/ws/camera/{code}?participant_id={pid}&token={jwt}",
        ) == 4403
        assert _refused(
            client, f"/ws/camera/{code}?participant_id={pid}&role=device&token={jwt}",
        ) == 4403
        assert _devices(code) == set()


def test_device_ticket_cannot_be_turned_into_a_viewer_by_the_query():
    """入場券の role が優先され、`role=viewer` を名乗っても viewer にはならない。"""
    code = "WCD2"
    _make_session(code)
    with TestClient(app, base_url="http://localhost") as client:
        data = _join(client, code, "uid-d2")
        ticket = _ticket(client, code, data, "device")
        with client.websocket_connect(
            f"/ws/camera/{code}?ticket={ticket}&role=viewer&viewer_id=somebody"
        ):
            devices, viewers = _devices(code), _viewers(code)
    assert devices == {str(data["participant_id"])}
    assert viewers == set()


def test_ticket_of_another_participant_does_not_let_you_claim_a_third_one():
    code = "WCD3"
    _make_session(code)
    with TestClient(app, base_url="http://localhost") as client:
        mine = _join(client, code, "uid-d3a")
        other = _join(client, code, "uid-d3b")
        ticket = _ticket(client, code, mine, "device")
        with client.websocket_connect(
            f"/ws/camera/{code}?ticket={ticket}&participant_id={other['participant_id']}"
        ):
            devices = _devices(code)
    assert devices == {str(mine["participant_id"])}
