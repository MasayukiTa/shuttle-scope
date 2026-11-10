"""token 無しの同一 device_uid 再参加が pending 行に合流し、行を量産しないこと。

本番の実機で観測された症状 (2026-11-10 19:47):
  iPhone の送信ページを再読み込みすると参加状態が消えてパスワード入力に戻り、
  入れ直すと `承認待ち` の参加者がもう 1 つ増える。device_uid を保ったまま
  join を叩き直しているのに、新しい pending 行が毎回作られていた。

期待する挙動 (sessions.py join_session, W63 所見1-b):
  - token 無しでも同じ device_uid の pending 行があればそれに合流し、
    pending 行の総数を増やさない (approval DoS / 行の氾濫を防ぐ)。
  - 合流先は必ず pending のまま。token 無しの再参加で承認を迂回しない。
  - device_uid が違えば合流せず、別の pending 行になる。

ここでは実エンドポイント (POST /api/sessions/{code}/join) を TestClient で叩き、
DB 上の pending 行数を直接数えて確かめる。
"""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.db import database as db_module
from backend.db.models import Match, Player, SharedSession, SessionParticipant
from backend.main import app
from backend.utils import ws_ticket
from backend.ws.camera import camera_manager

_PASSWORD = "camera-pass-1234"


@pytest.fixture(autouse=True)
def _clean_state():
    yield
    camera_manager._sessions.clear()
    camera_manager._operator_owners.clear()
    ws_ticket.clear_ws_tickets()


def _make_session(code: str, password: str | None = _PASSWORD) -> int:
    """パスワード付きの active session を 1 つ用意し、session_id を返す。"""
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
        session = SharedSession(
            match_id=match.id, session_code=code, created_by_role="analyst",
            is_active=True,
            password_hash=_hash_password(password) if password else None,
        )
        db.add(session)
        db.commit()
        return session.id
    finally:
        db.close()


def _join(client: TestClient, code: str, **overrides):
    body = {
        "role": "viewer",
        "device_name": "iPhone",
        "device_type": "iphone",
        "session_password": _PASSWORD,
    }
    body.update(overrides)
    return client.post(f"/api/sessions/{code}/join", json=body)


def _pending_count(session_id: int, device_uid: str | None = None) -> int:
    db = db_module.SessionLocal()
    try:
        q = (
            db.query(SessionParticipant)
            .filter(
                SessionParticipant.session_id == session_id,
                SessionParticipant.approval_status == "pending",
            )
        )
        if device_uid is not None:
            q = q.filter(SessionParticipant.device_uid == device_uid)
        return q.count()
    finally:
        db.close()


def test_tokenless_reload_with_same_uid_merges_into_one_pending_row():
    """同じ device_uid で token 無しに join を繰り返しても pending 行は 1 本のまま。

    これが症状 (1)「再読み込みのたびに承認待ちが増える」の根本原因。
    """
    code = "PENDMERGE"
    session_id = _make_session(code)
    uid = "reload-same-device-uid"
    with TestClient(app, base_url="http://localhost") as client:
        first = _join(client, code, device_uid=uid)
        assert first.status_code == 200, first.text
        first_data = first.json()["data"]

        # 送信ページの再読み込みを模す: 同じ UID、token は提示しない。
        second = _join(client, code, device_uid=uid)
        assert second.status_code == 200, second.text
        second_data = second.json()["data"]

        # さらにもう一度リロード。
        third = _join(client, code, device_uid=uid)
        assert third.status_code == 200, third.text
        third_data = third.json()["data"]

    # 3 回 join しても pending 行は 1 本に合流している。
    assert _pending_count(session_id, device_uid=uid) == 1
    assert _pending_count(session_id) == 1

    # 合流なので participant_id は同一で、reconnected が立つ。
    assert second_data["participant_id"] == first_data["participant_id"]
    assert third_data["participant_id"] == first_data["participant_id"]
    assert second_data.get("reconnected") is True
    assert third_data.get("reconnected") is True


def test_tokenless_merge_does_not_bypass_approval():
    """token 無しの合流は承認を迂回しない: 合流先は pending のまま。"""
    code = "PENDNOBYPASS"
    session_id = _make_session(code)
    uid = "no-bypass-device-uid"
    with TestClient(app, base_url="http://localhost") as client:
        first = _join(client, code, device_uid=uid)
        assert first.status_code == 200, first.text
        pid = first.json()["data"]["participant_id"]

        second = _join(client, code, device_uid=uid)
        assert second.status_code == 200, second.text
        assert second.json()["data"]["participant_id"] == pid

    db = db_module.SessionLocal()
    try:
        p = db.get(SessionParticipant, pid)
        assert p is not None
        # token を一度も証明していないので承認状態は pending のまま。
        assert p.approval_status == "pending"
    finally:
        db.close()


def test_tokenless_rejoin_with_different_uid_creates_separate_pending_rows():
    """device_uid が違えば合流せず、別の pending 行になる。"""
    code = "PENDDISTINCT"
    session_id = _make_session(code)
    with TestClient(app, base_url="http://localhost") as client:
        a = _join(client, code, device_uid="uid-alpha")
        assert a.status_code == 200, a.text
        b = _join(client, code, device_uid="uid-beta")
        assert b.status_code == 200, b.text

    assert a.json()["data"]["participant_id"] != b.json()["data"]["participant_id"]
    assert _pending_count(session_id) == 2
    assert _pending_count(session_id, device_uid="uid-alpha") == 1
    assert _pending_count(session_id, device_uid="uid-beta") == 1
