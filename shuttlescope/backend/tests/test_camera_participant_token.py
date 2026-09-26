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

def _approve(pid: int) -> None:
    """operator がこの端末をカメラとして承認した状態にする。

    `role="device"` の入場券は承認済みでないと出ない。
    旧実装は `rejected` だけを弾いており、既定の `pending` のまま
    配信できていた (source_capability は join 時にクライアントが申告した
    device_type から決まるだけなので、何も確かめていなかった)。
    """
    db = db_module.SessionLocal()
    try:
        p = db.get(SessionParticipant, pid)
        # **pending のときだけ承認する。** 無条件に上書きすると、
        # 「拒否された端末が入り直せないこと」を確かめているテストの
        # 前提をこのヘルパが消してしまう。
        if p is not None and p.approval_status == "pending":
            p.approval_status = "approved"
            db.commit()
    finally:
        db.close()


def _ticket(client: TestClient, code: str, pid: int, token: str, role: str = "device",
            approved: bool = True):
    if role == "device" and approved:
        _approve(pid)
    return client.post(
        f"/api/sessions/{code}/ws-ticket",
        json={"participant_id": pid, "participant_token": token, "role": role},
    )


def test_a_pending_device_cannot_get_a_camera_ticket():
    """operator が承認する前に配信を始められないこと。

    承認の意思は approval_status にしか無い。`source_capability` は
    クライアントが送った device_type から決まるので、"iphone" と名乗れば
    誰でも "camera" になり、検査として成立していなかった。
    """
    code = "PTPEND"
    _make_session(code)
    with TestClient(app, base_url="http://localhost") as client:
        data = _join(client, code).json()["data"]
        resp = _ticket(client, code, data["participant_id"],
                       data["participant_token"], approved=False)

    assert resp.status_code == 403, resp.text


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
    """`source_capability` が "camera" でない端末は device 券を取れないこと。

    **この検査だけでは「カメラを名乗る」を防げない**ことに注意。
    `source_capability` は join 時にクライアントが送った `device_type` から
    決まるだけなので、`"iphone"` と申告すれば誰でも "camera" になる。
    実際に防いでいるのは上の承認検査 (approval_status == "approved") で、
    ここは「pc と申告した端末が後から device を名乗る」だけを弾く。
    両方が要る。
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


# ── QR camera -> server recording upload ──────────────────────────────────────

def _participant_upload_headers(join_data: dict, *, token: str | None = None) -> dict[str, str]:
    return {
        "Authorization": f"Participant {token or join_data['participant_token']}",
        "X-Session-Code": join_data["session_code"],
        "X-Participant-Id": str(join_data["participant_id"]),
    }


def _init_participant_upload(client: TestClient, join_data: dict, **payload_overrides):
    payload = {
        "match_id": join_data["match_id"],
        "filename": "camera_record.webm",
        "mime_type": "video/webm",
        "streaming": True,
        "total_size": 1024,
        "chunk_size": 64 * 1024,
    }
    payload.update(payload_overrides)
    return client.post(
        "/api/v1/uploads/video/init",
        json=payload,
        headers=_participant_upload_headers(join_data),
    )


def test_approved_qr_camera_can_init_upload_and_session_is_bound_to_participant(
    tmp_path, monkeypatch,
):
    from backend.db.models import UploadSession
    from backend.routers import uploads as uploads_router

    code = "PTUP01"
    _make_session(code)
    monkeypatch.setattr(uploads_router, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(uploads_router, "MIN_FREE_DISK_BYTES", 0)

    with TestClient(app, base_url="http://localhost") as client:
        joined = _join(client, code).json()["data"]
        _approve(joined["participant_id"])
        resp = _init_participant_upload(client, joined)

    assert resp.status_code == 200, resp.text
    upload_id = resp.json()["upload_id"]
    db = db_module.SessionLocal()
    try:
        upload = db.get(UploadSession, upload_id)
        assert upload is not None
        assert upload.user_id is None
        assert upload.participant_id == joined["participant_id"]
        assert upload.match_id == joined["match_id"]
    finally:
        db.close()


def test_participant_upload_rejects_bad_token_pending_device_and_match_mismatch(
    tmp_path, monkeypatch,
):
    from backend.routers import uploads as uploads_router

    code = "PTUP02"
    _make_session(code)
    monkeypatch.setattr(uploads_router, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(uploads_router, "MIN_FREE_DISK_BYTES", 0)

    with TestClient(app, base_url="http://localhost") as client:
        joined = _join(client, code).json()["data"]

        pending = _init_participant_upload(client, joined)
        assert pending.status_code == 403, pending.text

        _approve(joined["participant_id"])
        bad_token = client.post(
            "/api/v1/uploads/video/init",
            json={
                "match_id": joined["match_id"],
                "filename": "camera_record.webm",
                "mime_type": "video/webm",
                "streaming": True,
                "total_size": 1024,
                "chunk_size": 64 * 1024,
            },
            headers=_participant_upload_headers(joined, token="wrong-token"),
        )
        assert bad_token.status_code == 401, bad_token.text

        wrong_match = _init_participant_upload(
            client, joined, match_id=joined["match_id"] + 99999,
        )
        assert wrong_match.status_code == 403, wrong_match.text


def test_participant_cannot_manage_another_participants_upload(
    tmp_path, monkeypatch,
):
    from backend.routers import uploads as uploads_router

    _make_session("PTUP03A")
    _make_session("PTUP03B")
    monkeypatch.setattr(uploads_router, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(uploads_router, "MIN_FREE_DISK_BYTES", 0)

    with TestClient(app, base_url="http://localhost") as client:
        first = _join(client, "PTUP03A").json()["data"]
        second = _join(client, "PTUP03B").json()["data"]
        _approve(first["participant_id"])
        _approve(second["participant_id"])

        init = _init_participant_upload(client, first)
        assert init.status_code == 200, init.text
        upload_id = init.json()["upload_id"]

        stolen = client.get(
            f"/api/v1/uploads/video/{upload_id}/status",
            headers=_participant_upload_headers(second),
        )
        assert stolen.status_code == 403, stolen.text

        cleanup = client.delete(
            f"/api/v1/uploads/video/{upload_id}",
            headers=_participant_upload_headers(first),
        )
        assert cleanup.status_code == 200, cleanup.text


# ── QR/session participant -> ICE/TURN credentials ───────────────────────────

def _participant_ice(
    client: TestClient,
    join_data: dict,
    *,
    token: str | None = None,
):
    return client.get(
        f"/api/sessions/{join_data['session_code']}/devices/{join_data['participant_id']}/ice-config",
        headers={
            "Authorization": f"Participant {token or join_data['participant_token']}",
        },
    )


def _enable_test_turn(monkeypatch):
    from backend.routers import settings as settings_router

    cfg = {
        "turn_enabled": True,
        "turn_url": "turn:relay.example.com:3478",
        "turn_username": "static-user",
        "turn_credential": "static-password",
        "turn_static_auth_secret": "participant-shared-secret",
    }
    monkeypatch.setattr(settings_router, "_load_all", lambda _db: cfg)
    return cfg


def test_approved_camera_participant_can_get_scoped_turn_credentials(monkeypatch):
    code = "PTICECAM"
    _make_session(code)
    _enable_test_turn(monkeypatch)

    with TestClient(app, base_url="http://localhost") as client:
        joined = _join(client, code).json()["data"]

        pending = _participant_ice(client, joined)
        assert pending.status_code == 403, pending.text

        _approve(joined["participant_id"])
        resp = _participant_ice(client, joined)

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    turn = [item for item in data["ice_servers"] if item["urls"].startswith("turn:")]
    assert len(turn) == 1
    assert turn[0]["username"].endswith(
        f":participant:{joined['participant_id']}"
    )
    body = resp.text
    assert "static-user" not in body
    assert "static-password" not in body


def test_viewer_participant_can_get_turn_without_camera_approval(monkeypatch):
    code = "PTICEVIEW"
    _make_session(code)
    _enable_test_turn(monkeypatch)

    with TestClient(app, base_url="http://localhost") as client:
        joined = _join(
            client,
            code,
            role="viewer",
            device_type="pc",
            device_name="Viewer PC",
        ).json()["data"]
        resp = _participant_ice(client, joined)

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["turn_enabled"] is True


def test_participant_ice_rejects_wrong_token_and_blocked_viewer(monkeypatch):
    code = "PTICEBAD"
    _make_session(code)
    _enable_test_turn(monkeypatch)

    with TestClient(app, base_url="http://localhost") as client:
        joined = _join(
            client,
            code,
            role="viewer",
            device_type="pc",
            device_name="Viewer PC",
        ).json()["data"]

        bad = _participant_ice(client, joined, token="wrong-participant-token")
        assert bad.status_code == 401, bad.text

        db = db_module.SessionLocal()
        try:
            p = db.get(SessionParticipant, joined["participant_id"])
            assert p is not None
            p.viewer_permission = "blocked"
            db.commit()
        finally:
            db.close()

        blocked = _participant_ice(client, joined)
        assert blocked.status_code == 403, blocked.text


def test_participant_ice_does_not_reveal_another_participant_id(monkeypatch):
    code = "PTICEENUM"
    _make_session(code)
    _enable_test_turn(monkeypatch)

    with TestClient(app, base_url="http://localhost") as client:
        joined = _join(
            client,
            code,
            role="viewer",
            device_type="pc",
            device_name="Viewer PC",
        ).json()["data"]
        resp = client.get(
            f"/api/sessions/{code}/devices/{joined['participant_id'] + 9999}/ice-config",
            headers={"Authorization": f"Participant {joined['participant_token']}"},
        )

    assert resp.status_code == 401, resp.text

def test_participant_ice_is_bound_to_active_session(monkeypatch):
    code = "PTICEEND"
    _make_session(code)
    _enable_test_turn(monkeypatch)

    with TestClient(app, base_url="http://localhost") as client:
        joined = _join(
            client,
            code,
            role="viewer",
            device_type="pc",
            device_name="Viewer PC",
        ).json()["data"]

        db = db_module.SessionLocal()
        try:
            session = (
                db.query(SharedSession)
                .filter(SharedSession.session_code == code)
                .one()
            )
            session.is_active = False
            db.commit()
        finally:
            db.close()

        resp = _participant_ice(client, joined)

    assert resp.status_code == 404, resp.text
