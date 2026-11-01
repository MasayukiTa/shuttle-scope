"""h10a2: sessions.py の認可ハードニング 3 件の回帰テスト。

#613 device_heartbeat の JWT fallback が session scope を検証せず、他チームの
     認証ユーザが他端末の heartbeat を打てた (IDOR)。
#697 register_source が participant_id の session 所属を検証せず、別セッションの
     participant を LiveSource に関連付けられた。
#699 set-role が active_camera を直接許可し、activate-camera の 4 台上限を迂回できた。
"""
import datetime

import pytest
from fastapi.testclient import TestClient

from backend.db import database as db_module
from backend.db.models import (
    LiveSource, Match, Player, SessionParticipant, SharedSession, Team, User,
)
from backend.main import app
from backend.routers import sessions as sessions_module
from backend.utils.jwt_utils import create_access_token

_PASSWORD = "camera-pass-h10a2"
_TUNNEL = {"CF-Connecting-IP": "203.0.113.9"}


@pytest.fixture(autouse=True)
def _clean_state():
    yield
    sessions_module._operator_tokens.clear()


def _make_world(code: str) -> dict:
    """チーム A の試合に紐づく active session と、A / B 両チームの analyst を作る。"""
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
            tournament="H10A2 Test", tournament_level="IC", round="R1",
            date=datetime.date(2026, 8, 15), format="singles",
            player_a_id=pa.id, player_b_id=pb.id, result="win",
            owner_team_id=team_a.id, is_public_pool=False,
        )
        db.add(match)
        db.flush()
        session = SharedSession(
            match_id=match.id, session_code=code, created_by_role="analyst",
            is_active=True, password_hash=_hash_password(_PASSWORD),
        )
        db.add(session)
        db.flush()

        def _user(suffix, role, team_id, team_name):
            u = User(
                username=f"{code.lower()}-{suffix}", role=role, team_id=team_id,
                awaiting_admin_approval=False, consent_required=False, is_test=True,
            )
            db.add(u)
            db.flush()
            tok = create_access_token(
                user_id=u.id, role=role, team_id=team_id, team_name=team_name, minutes=10,
            )
            return {"Authorization": f"Bearer {tok}"}

        world = {
            "session_id": session.id,
            "same_team": _user("a-analyst", "analyst", team_a.id, team_a.name),
            "other_team": _user("b-analyst", "analyst", team_b.id, team_b.name),
        }
        db.commit()
        return world
    finally:
        db.close()


def _add_participant(session_id, role="camera_candidate", **fields):
    db = db_module.SessionLocal()
    try:
        p = SessionParticipant(
            session_id=session_id, device_name="iPhone", device_type="iphone",
            role="viewer", connection_role=role, approval_status="approved",
            **fields,
        )
        db.add(p)
        db.commit()
        return p.id
    finally:
        db.close()


def _role(pid):
    db = db_module.SessionLocal()
    try:
        return db.get(SessionParticipant, pid).connection_role
    finally:
        db.close()


# ─── #613 device_heartbeat cross-team IDOR ──────────────────────────────────

def test_heartbeat_jwt_other_team_denied():
    code = "H10A2HB1"
    world = _make_world(code)
    pid = _add_participant(world["session_id"])
    client = TestClient(app)
    # 他チームの analyst が tunnel 経由で heartbeat を打つ → scope 外で拒否 (fail closed)
    r = client.post(
        f"/api/sessions/{code}/devices/{pid}/heartbeat",
        json={}, headers={**world["other_team"], **_TUNNEL},
    )
    assert r.status_code in (403, 404), r.text


def test_heartbeat_jwt_same_team_ok():
    code = "H10A2HB2"
    world = _make_world(code)
    pid = _add_participant(world["session_id"])
    client = TestClient(app)
    r = client.post(
        f"/api/sessions/{code}/devices/{pid}/heartbeat",
        json={}, headers={**world["same_team"], **_TUNNEL},
    )
    assert r.status_code == 200, r.text


# ─── #697 register_source participant must belong to session ────────────────

def test_register_source_foreign_participant_rejected():
    code = "H10A2RS1"
    world = _make_world(code)
    # 別セッション (チーム B) の participant を作る
    other = _make_world("H10A2RS1B")
    foreign_pid = _add_participant(other["session_id"])
    client = TestClient(app)
    r = client.post(
        f"/api/sessions/{code}/sources",
        json={"source_kind": "usb_camera", "participant_id": foreign_pid},
        headers={**world["same_team"], **_TUNNEL},
    )
    assert r.status_code == 404, r.text


def test_register_source_own_participant_ok():
    code = "H10A2RS2"
    world = _make_world(code)
    pid = _add_participant(world["session_id"])
    client = TestClient(app)
    r = client.post(
        f"/api/sessions/{code}/sources",
        json={"source_kind": "usb_camera", "participant_id": pid},
        headers={**world["same_team"], **_TUNNEL},
    )
    assert r.status_code == 201, r.text


def test_register_source_no_participant_ok():
    code = "H10A2RS3"
    world = _make_world(code)
    client = TestClient(app)
    r = client.post(
        f"/api/sessions/{code}/sources",
        json={"source_kind": "pc_local"},
        headers={**world["same_team"], **_TUNNEL},
    )
    assert r.status_code == 201, r.text


# ─── #699 set-role must not bypass the 4-camera limit ───────────────────────

def test_set_role_rejects_active_camera():
    code = "H10A2SR1"
    world = _make_world(code)
    pid = _add_participant(world["session_id"])
    client = TestClient(app)
    r = client.post(
        f"/api/sessions/{code}/devices/{pid}/set-role",
        json={"connection_role": "active_camera"},
        headers={**world["same_team"], **_TUNNEL},
    )
    assert r.status_code == 400, r.text
    assert _role(pid) != "active_camera"


def test_set_role_allows_camera_candidate():
    code = "H10A2SR2"
    world = _make_world(code)
    pid = _add_participant(world["session_id"], role="viewer")
    client = TestClient(app)
    r = client.post(
        f"/api/sessions/{code}/devices/{pid}/set-role",
        json={"connection_role": "camera_candidate"},
        headers={**world["same_team"], **_TUNNEL},
    )
    assert r.status_code == 200, r.text
    assert _role(pid) == "camera_candidate"


def test_activate_camera_still_enforces_limit():
    code = "H10A2SR3"
    world = _make_world(code)
    # 既に 4 台 active。5 台目の昇格は 409。
    for _ in range(4):
        _add_participant(world["session_id"], role="active_camera")
    fifth = _add_participant(world["session_id"], role="camera_candidate")
    client = TestClient(app)
    r = client.post(
        f"/api/sessions/{code}/devices/{fifth}/activate-camera",
        headers={**world["same_team"], **_TUNNEL},
    )
    assert r.status_code == 409, r.text
