"""監査 #598 / #600 / #591 の認可回帰テスト。

- #598: /api/media/token の camera / viewer は join 済み・承認済みの参加者資格を要求する。
- #600: demo ロールも TeamScope の対象 (他チームの match-id API は 404)。
        検証済み demo read (?demo=1 + demo データ) は従来どおり読める。
- #591: demo は /api/settings と /api/sessions/my-info を参照できない。

トークンは create_access_token で都度生成し、固定の秘密値は使わない。
LiveKit は load_config / issue_access_token を差し替え、環境変数に依存しない。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import backend.main as main_mod
from backend.db.database import get_db
from backend.db.models import (
    Match,
    Player,
    SessionParticipant,
    SharedSession,
    Team,
    User,
)
from backend.main import app
from backend.routers import media as media_mod
from backend.routers.auth import _hash_password
from backend.routers.sessions import _hash_ws_token
from backend.utils.jwt_utils import create_access_token

_BASE = "http://localhost"

DEMO_TEAM_ID = 7701
REAL_TEAM_ID = 7702
OTHER_TEAM_ID = 7703
DEMO_PID, DEMO_OPP = 7711, 7712
REAL_PID, REAL_OPP = 7721, 7722
OTHER_PID, OTHER_OPP = 7731, 7732
DEMO_MATCH, REAL_MATCH, OTHER_MATCH, POOL_MATCH = 9701, 9702, 9703, 9704
DEMO_UID = 7791

CODE_A = "SECA01"
CODE_B = "SECB01"
GOOD_TOKEN = "participant-token-for-session-a-0001"
OTHER_TOKEN = "participant-token-for-session-b-0002"


def _wipe(db):
    for model in (SessionParticipant, SharedSession, Match, Player, User, Team):
        db.query(model).delete()
    db.commit()


def _match(mid, a, b, owner, **extra):
    return Match(
        id=mid, tournament="t", tournament_level="その他", round="F",
        date=date(2025, 1, 1), format="singles",
        player_a_id=a, player_b_id=b, result="win", owner_team_id=owner,
        **extra,
    )


def _participant(session_id, token, **kw):
    base = dict(
        session_id=session_id, role="viewer", device_name="d", device_type="iphone",
        device_class="phone", connection_role="viewer", source_capability="camera",
        connection_state="idle", approval_status="approved", viewer_permission="default",
        display_size_class="standard", authenticated_at=datetime.utcnow(),
        last_heartbeat=datetime.utcnow(), is_connected=True,
        ws_token_hash=_hash_ws_token(token),
        ws_token_expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    base.update(kw)
    return SessionParticipant(**base)


@pytest.fixture()
def seeded(db_session):
    _wipe(db_session)
    db = db_session
    db.add(Team(id=DEMO_TEAM_ID, display_id="__sec_demo__", name="SecDemo"))
    db.add(Team(id=REAL_TEAM_ID, display_id="SECREAL", name="Sec Real"))
    db.add(Team(id=OTHER_TEAM_ID, display_id="SECOTHER", name="Sec Other"))
    db.add(User(
        id=DEMO_UID, username="sec591demo", role="demo", display_name="Demo",
        team_id=DEMO_TEAM_ID, player_id=DEMO_PID,
        hashed_credential=_hash_password("x"),
    ))
    for pid, tid in (
        (DEMO_PID, DEMO_TEAM_ID), (DEMO_OPP, DEMO_TEAM_ID),
        (REAL_PID, REAL_TEAM_ID), (REAL_OPP, REAL_TEAM_ID),
        (OTHER_PID, OTHER_TEAM_ID), (OTHER_OPP, OTHER_TEAM_ID),
    ):
        db.add(Player(id=pid, name=f"p{pid}", team_id=tid))
    db.add(_match(DEMO_MATCH, DEMO_PID, DEMO_OPP, DEMO_TEAM_ID))
    db.add(_match(REAL_MATCH, REAL_PID, REAL_OPP, REAL_TEAM_ID))
    db.add(_match(OTHER_MATCH, OTHER_PID, OTHER_OPP, OTHER_TEAM_ID))
    db.add(_match(POOL_MATCH, OTHER_PID, OTHER_OPP, OTHER_TEAM_ID, is_public_pool=True))
    db.commit()
    sess_a = SharedSession(match_id=REAL_MATCH, session_code=CODE_A, created_by_role="coach",
                           password_hash="x:y", is_active=True)
    sess_b = SharedSession(match_id=REAL_MATCH, session_code=CODE_B, created_by_role="coach",
                           password_hash="x:y", is_active=True)
    db.add_all([sess_a, sess_b])
    db.commit()
    db.add(_participant(sess_a.id, GOOD_TOKEN))                      # id 取得のため先に追加
    db.add(_participant(sess_b.id, OTHER_TOKEN))
    db.commit()
    main_mod._DEMO_TEAM_CACHE["team_id"] = None
    main_mod._DEMO_TEAM_CACHE["ts"] = 0.0
    app.dependency_overrides[get_db] = lambda: db
    yield db
    app.dependency_overrides.clear()
    _wipe(db)


def _auth(role, *, uid, team_id=None, team_name=None, player_id=None):
    tok = create_access_token(
        user_id=uid, role=role, player_id=player_id, team_name=team_name, team_id=team_id,
    )
    return {"Authorization": f"Bearer {tok}"}


def _coach():
    return _auth("coach", uid=7792, team_id=REAL_TEAM_ID, team_name="Sec Real")


def _demo():
    return _auth("demo", uid=DEMO_UID, team_id=DEMO_TEAM_ID, player_id=DEMO_PID)


@pytest.fixture()
def livekit(monkeypatch):
    cfg = SimpleNamespace(configured=True, url="wss://livekit.invalid")
    monkeypatch.setattr(media_mod, "load_config", lambda: cfg)
    monkeypatch.setattr(media_mod, "issue_access_token", lambda *a, **k: "stub-livekit-jwt")


def _participant_of(db, code, token):
    sess = db.query(SharedSession).filter(SharedSession.session_code == code).one()
    p = db.query(SessionParticipant).filter(SessionParticipant.session_id == sess.id).one()
    return p.id


def _post_media(client, body):
    return client.post("/api/media/token", json=body, headers=_coach())


# ── #598 /media/token ────────────────────────────────────────────────────────

@pytest.mark.parametrize("role", ["viewer", "camera"])
def test_media_token_without_participant_credential_is_403(seeded, livekit, role):
    client = TestClient(app, base_url=_BASE)
    r = _post_media(client, {"session_code": CODE_A, "role": role})
    assert r.status_code == 403, r.text


def test_media_token_wrong_participant_token_is_403(seeded, livekit):
    client = TestClient(app, base_url=_BASE)
    pid = _participant_of(seeded, CODE_A, GOOD_TOKEN)
    r = _post_media(client, {
        "session_code": CODE_A, "role": "viewer",
        "participant_id": pid, "participant_token": "x" * 32,
    })
    assert r.status_code == 403, r.text


def test_media_token_credential_of_another_session_is_403(seeded, livekit):
    client = TestClient(app, base_url=_BASE)
    pid_b = _participant_of(seeded, CODE_B, OTHER_TOKEN)
    r = _post_media(client, {
        "session_code": CODE_A, "role": "viewer",
        "participant_id": pid_b, "participant_token": OTHER_TOKEN,
    })
    assert r.status_code == 403, r.text


def test_media_token_pending_participant_is_403(seeded, livekit):
    client = TestClient(app, base_url=_BASE)
    pid = _participant_of(seeded, CODE_A, GOOD_TOKEN)
    p = seeded.get(SessionParticipant, pid)
    p.approval_status = "pending"
    seeded.commit()
    r = _post_media(client, {
        "session_code": CODE_A, "role": "viewer",
        "participant_id": pid, "participant_token": GOOD_TOKEN,
    })
    assert r.status_code == 403, r.text


def test_media_token_camera_requires_camera_capability(seeded, livekit):
    client = TestClient(app, base_url=_BASE)
    pid = _participant_of(seeded, CODE_A, GOOD_TOKEN)
    p = seeded.get(SessionParticipant, pid)
    p.source_capability = "none"
    seeded.commit()
    r = _post_media(client, {
        "session_code": CODE_A, "role": "camera",
        "participant_id": pid, "participant_token": GOOD_TOKEN,
    })
    assert r.status_code == 403, r.text


@pytest.mark.parametrize("role", ["viewer", "camera"])
def test_media_token_approved_participant_still_gets_token(seeded, livekit, role):
    client = TestClient(app, base_url=_BASE)
    pid = _participant_of(seeded, CODE_A, GOOD_TOKEN)
    r = _post_media(client, {
        "session_code": CODE_A, "role": role,
        "participant_id": pid, "participant_token": GOOD_TOKEN,
    })
    assert r.status_code == 200, r.text
    assert r.json()["token"] == "stub-livekit-jwt"


def test_media_token_operator_path_is_unchanged(seeded, livekit):
    client = TestClient(app, base_url=_BASE)
    r = _post_media(client, {"session_code": CODE_A, "role": "operator"})
    assert r.status_code == 200, r.text


# ── #600 demo の team scope ──────────────────────────────────────────────────

@pytest.mark.parametrize("path", [
    f"/api/yolo/results/{OTHER_MATCH}",
    f"/api/yolo/results/{OTHER_MATCH}/frames",
    f"/api/tracknet/shuttle_track/{OTHER_MATCH}",
    f"/api/tracknet/resume_check/{OTHER_MATCH}",
    f"/api/yolo/results/{POOL_MATCH}",
])
def test_demo_cannot_reach_other_team_match_ids(seeded, path):
    client = TestClient(app, base_url=_BASE)
    r = client.get(path, headers=_demo())
    assert r.status_code == 404, r.text


def test_demo_cannot_delete_or_start_cv_on_other_team_match(seeded):
    client = TestClient(app, base_url=_BASE)
    assert client.delete(f"/api/yolo/results/{OTHER_MATCH}", headers=_demo()).status_code == 404
    assert client.post(f"/api/yolo/batch/{OTHER_MATCH}", headers=_demo(), json={}).status_code == 404
    assert client.post(f"/api/tracknet/batch/{OTHER_MATCH}", headers=_demo(), json={}).status_code == 404


def test_demo_own_team_match_is_not_hidden_by_the_scope(seeded):
    """自チーム (demo team) の試合は scope に隠されない (404 にならない)。"""
    client = TestClient(app, base_url=_BASE)
    r = client.get(f"/api/yolo/results/{DEMO_MATCH}", headers=_demo())
    assert r.status_code != 404, r.text


def test_demo_verified_read_of_demo_match_still_works(seeded):
    """公開デモ表示: ?demo=1 + demo データの GET は従来どおり 200 / X-Is-Demo。"""
    client = TestClient(app, base_url=_BASE)
    r = client.get(f"/api/matches/{DEMO_MATCH}?demo=1", headers=_demo())
    assert r.status_code == 200, r.text
    assert r.headers.get("X-Is-Demo") == "1"


def test_demo_flag_does_not_unlock_other_team_match(seeded):
    client = TestClient(app, base_url=_BASE)
    r = client.get(f"/api/yolo/results/{OTHER_MATCH}?demo=1", headers=_demo())
    assert r.status_code == 404, r.text


def test_coach_team_scope_is_unchanged(seeded):
    client = TestClient(app, base_url=_BASE)
    assert client.get(f"/api/yolo/results/{OTHER_MATCH}", headers=_coach()).status_code == 404
    assert client.get(f"/api/yolo/results/{POOL_MATCH}", headers=_coach()).status_code != 404


# ── #591 internal info for demo ──────────────────────────────────────────────

@pytest.mark.parametrize("path", ["/api/settings", "/api/sessions/my-info"])
def test_demo_cannot_read_internal_info(seeded, path):
    client = TestClient(app, base_url=_BASE)
    r = client.get(path, headers=_demo())
    assert r.status_code == 403, r.text


@pytest.mark.parametrize("path", ["/api/settings", "/api/sessions/my-info"])
def test_coach_can_still_read_internal_info(seeded, path):
    client = TestClient(app, base_url=_BASE)
    r = client.get(path, headers=_coach())
    assert r.status_code == 200, r.text
