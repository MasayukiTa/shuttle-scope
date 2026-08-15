"""参加者スコープの WS 資格情報と一回限り入場券。

背景:
  カメラ signaling WS はどのロールにもアプリの JWT を要求していた。しかし
  カメラを担う iOS 端末はアカウントを持たず、想定 UX は
  「QR を読む → セッションパスワードを入れる → カメラになる」である。
  結果、その経路は本番構成で一度も成立していなかった。

  さらに WS は「session_code を知っていて、そのセッションに属する
  participant_id を名乗れば通す」だけだったので、他のカメラになりすませた。

  join がセッションパスワードを検証したうえで参加者トークンを発行し、
  それを 30 秒使い捨ての入場券に引き換える。入場券には session / role /
  participant_id が刻まれ、WS はクライアント申告の同名クエリを採用しない。
"""
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.db import database as db_module
from backend.db.models import Match, Player, SharedSession, SessionParticipant
from backend.main import app
from backend.routers.sessions import _hash_ws_token
from backend.utils import ws_ticket
from backend.ws.camera import camera_manager

_PASSWORD = "camera-pass-1234"


@pytest.fixture(autouse=True)
def _clean_state():
    yield
    camera_manager._sessions.clear()
    camera_manager._operator_owners.clear()
    ws_ticket.clear_ws_tickets()


def _make_session(code: str, password: str | None = _PASSWORD) -> None:
    """パスワード付きの active session を 1 つ用意する。"""
    from backend.routers.sessions import _hash_password

    db = db_module.SessionLocal()
    try:
        pa = Player(name=f"{code}_A")
        pb = Player(name=f"{code}_B")
        db.add_all([pa, pb])
        db.flush()
        match = Match(
            tournament="PT Test", tournament_level="IC", round="R1",
            date=date(2026, 8, 15), format="singles",
            player_a_id=pa.id, player_b_id=pb.id, result="win",
        )
        db.add(match)
        db.flush()
        db.add(SharedSession(
            match_id=match.id, session_code=code, created_by_role="analyst",
            is_active=True,
            password_hash=_hash_password(password) if password else None,
        ))
        db.commit()
    finally:
        db.close()


def _join(client: TestClient, code: str, **overrides) -> dict:
    body = {
        "role": "viewer",
        "device_name": "iPhone",
        "device_type": "iphone",
        "session_password": _PASSWORD,
    }
    body.update(overrides)
    return client.post(f"/api/sessions/{code}/join", json=body)


# ── join が資格情報を出すこと ────────────────────────────────────────────────

def test_join_without_app_login_returns_a_participant_token():
    """アプリの JWT を持たない端末でも、パスワードだけで参加できること。

    join が GlobalAuthMiddleware の例外に入っていなければ 401 になる。
    """
    code = "PTJOIN"
    _make_session(code)
    with TestClient(app, base_url="http://localhost") as client:
        resp = _join(client, code)

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["participant_token"], "参加者トークンが返っていない"
    assert len(data["participant_token"]) >= 32


def test_token_is_stored_only_as_a_hash():
    """DB に平文が残らないこと（漏れても資格情報として使えない）。"""
    code = "PTHASH"
    _make_session(code)
    with TestClient(app, base_url="http://localhost") as client:
        data = _join(client, code).json()["data"]

    token = data["participant_token"]
    db = db_module.SessionLocal()
    try:
        p = db.get(SessionParticipant, data["participant_id"])
        assert p.ws_token_hash == _hash_ws_token(token)
        assert p.ws_token_hash != token
        assert p.ws_token_expires_at > datetime.utcnow()
    finally:
        db.close()


def test_wrong_session_password_is_still_rejected():
    code = "PTPW"
    _make_session(code)
    with TestClient(app, base_url="http://localhost") as client:
        # 拒否されることを確かめるための誤ったパスワード (テスト用固定値)
        resp = _join(client, code, session_password="wrong-password")  # nosec B106
    assert resp.status_code == 401


# ── 入場券 ──────────────────────────────────────────────────────────────────

def _ticket(client: TestClient, code: str, pid: int, token: str, role: str = "device"):
    return client.post(
        f"/api/sessions/{code}/ws-ticket",
        json={"participant_id": pid, "participant_token": token, "role": role},
    )


def test_ticket_is_issued_for_a_valid_participant_token():
    code = "PTTK"
    _make_session(code)
    with TestClient(app, base_url="http://localhost") as client:
        data = _join(client, code).json()["data"]
        resp = _ticket(client, code, data["participant_id"], data["participant_token"])

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["ticket"]


def test_ticket_is_refused_for_a_wrong_token():
    code = "PTBAD"
    _make_session(code)
    with TestClient(app, base_url="http://localhost") as client:
        data = _join(client, code).json()["data"]
        resp = _ticket(client, code, data["participant_id"], "not-the-right-token-value")

    assert resp.status_code == 401


def test_ticket_is_refused_after_the_operator_rejects_the_device():
    """拒否した端末が資格情報を持ったまま入り直せないこと。"""
    code = "PTREJ"
    _make_session(code)
    with TestClient(app, base_url="http://localhost") as client:
        data = _join(client, code).json()["data"]

        db = db_module.SessionLocal()
        try:
            p = db.get(SessionParticipant, data["participant_id"])
            p.approval_status = "rejected"
            p.ws_token_hash = None          # reject endpoint が行う失効と同じ
            p.ws_token_expires_at = None
            db.commit()
        finally:
            db.close()

        resp = _ticket(client, code, data["participant_id"], data["participant_token"])

    assert resp.status_code == 401


def test_expired_token_is_refused():
    code = "PTEXP"
    _make_session(code)
    with TestClient(app, base_url="http://localhost") as client:
        data = _join(client, code).json()["data"]

        db = db_module.SessionLocal()
        try:
            p = db.get(SessionParticipant, data["participant_id"])
            p.ws_token_expires_at = datetime.utcnow() - timedelta(seconds=1)
            db.commit()
        finally:
            db.close()

        resp = _ticket(client, code, data["participant_id"], data["participant_token"])

    assert resp.status_code == 401


def test_a_non_camera_participant_cannot_claim_the_device_role():
    """要求された role を鵜呑みにしないこと。

    これを見ないと、映像を受けるだけの端末が「カメラです」と名乗って
    operator に offer を投げ、表示中の映像を差し替えられる。
    """
    code = "PTROLE"
    _make_session(code)
    with TestClient(app, base_url="http://localhost") as client:
        # device_type=pc → source_capability は "none" になる
        data = _join(client, code, device_type="pc", device_name="PC").json()["data"]
        as_device = _ticket(client, code, data["participant_id"],
                            data["participant_token"], role="device")
        as_viewer = _ticket(client, code, data["participant_id"],
                            data["participant_token"], role="viewer")

    assert as_device.status_code == 403, as_device.text
    assert as_viewer.status_code == 200, as_viewer.text


def test_blocked_participant_cannot_claim_the_viewer_role():
    code = "PTBLOCK"
    _make_session(code)
    with TestClient(app, base_url="http://localhost") as client:
        data = _join(client, code).json()["data"]
        db = db_module.SessionLocal()
        try:
            p = db.get(SessionParticipant, data["participant_id"])
            p.viewer_permission = "blocked"
            db.commit()
        finally:
            db.close()
        resp = _ticket(client, code, data["participant_id"],
                       data["participant_token"], role="viewer")

    assert resp.status_code == 403


def test_ending_the_session_revokes_every_participant_token():
    """終了したセッションの入場券を取り直せないこと。"""
    code = "PTEND"
    _make_session(code)
    with TestClient(app, base_url="http://localhost") as client:
        data = _join(client, code).json()["data"]
        assert client.post(f"/api/sessions/{code}/end").status_code == 200

        db = db_module.SessionLocal()
        try:
            p = db.get(SessionParticipant, data["participant_id"])
            assert p.ws_token_hash is None, "終了後もトークンが残っている"
        finally:
            db.close()


def test_regenerating_the_password_revokes_every_participant_token():
    """パスワードを変えたら旧パスワードで得た資格情報が死ぬこと。"""
    code = "PTREGEN"
    _make_session(code)
    with TestClient(app, base_url="http://localhost") as client:
        data = _join(client, code).json()["data"]
        assert client.post(
            f"/api/sessions/{code}/regenerate-password").status_code == 200
        resp = _ticket(client, code, data["participant_id"], data["participant_token"])

    assert resp.status_code == 401


def test_a_failed_precondition_does_not_burn_the_ticket():
    """前提条件で弾かれただけで入場券を焼かないこと。

    先に消費すると、URL を打ち間違えた一回で正規の入場券が失われる。
    """
    code = "PTBURN"
    other = "PTBURN2"
    _make_session(code)
    _make_session(other)
    with TestClient(app, base_url="http://localhost") as client:
        data = _join(client, code).json()["data"]
        ticket = _ticket(
            client, code, data["participant_id"], data["participant_token"],
        ).json()["data"]["ticket"]

        # 別セッションへ誤接続 → 拒否される
        try:
            with client.websocket_connect(f"/ws/camera/{other}?ticket={ticket}") as ws:
                ws.receive_text()
        except Exception:
            pass

        # 正しいセッションへは依然として使えること
        with client.websocket_connect(f"/ws/camera/{code}?ticket={ticket}"):
            registered = set(camera_manager._sessions[code]["devices"].keys())

    assert registered == {str(data["participant_id"])}


def test_ticket_cannot_be_used_twice():
    claim_ticket = ws_ticket.issue_ws_ticket("PTONCE", "device", "7")
    assert ws_ticket.consume_ws_ticket(claim_ticket) is not None
    assert ws_ticket.consume_ws_ticket(claim_ticket) is None


def test_expired_ticket_is_not_consumable(monkeypatch):
    """期限切れの入場券は使えないこと（ログに残った URL の再利用を防ぐ）。"""
    monkeypatch.setattr(ws_ticket, "TICKET_TTL_SEC", -1)
    ticket = ws_ticket.issue_ws_ticket("PTTTL", "device", "7")
    assert ws_ticket.consume_ws_ticket(ticket) is None


# ── WS: 入場券に刻まれた身元が使われること ──────────────────────────────────

def test_ws_uses_the_identity_in_the_ticket_not_the_query():
    """クライアントが別の participant_id を名乗っても入場券の身元が使われること。

    これが効いていないと「session_code さえ知っていれば他のカメラを騙れる」。
    """
    code = "PTBIND"
    _make_session(code)
    with TestClient(app, base_url="http://localhost") as client:
        mine = _join(client, code, device_uid="uid-mine").json()["data"]
        other = _join(client, code, device_uid="uid-other").json()["data"]
        assert mine["participant_id"] != other["participant_id"]

        ticket = _ticket(
            client, code, mine["participant_id"], mine["participant_token"],
        ).json()["data"]["ticket"]

        # 入場券は自分のものだが、クエリでは他人の participant_id を主張する
        url = (
            f"/ws/camera/{code}?ticket={ticket}"
            f"&participant_id={other['participant_id']}&role=operator"
        )
        with client.websocket_connect(url):
            registered = set(camera_manager._sessions[code]["devices"].keys())

    assert registered == {str(mine["participant_id"])}, (
        f"クエリ申告の participant_id が採用されている: {registered}"
    )


def test_ticket_bound_to_another_session_is_refused():
    """入場券は発行元セッション以外では通らないこと。"""
    code = "PTXSESS"
    other = "PTXOTHER"[:10]
    _make_session(code)
    _make_session(other)
    with TestClient(app, base_url="http://localhost") as client:
        data = _join(client, code).json()["data"]
        ticket = _ticket(
            client, code, data["participant_id"], data["participant_token"],
        ).json()["data"]["ticket"]

        # close(4403) されるので受信は例外になる。例外の型は環境差があるため
        # 「別セッションに登録されていないこと」で判定する。
        try:
            with client.websocket_connect(f"/ws/camera/{other}?ticket={ticket}") as ws:
                ws.receive_text()
        except Exception:
            pass

        assert other not in camera_manager._sessions or not (
            camera_manager._sessions[other]["devices"]
        ), "別セッションの入場券で登録されている"
