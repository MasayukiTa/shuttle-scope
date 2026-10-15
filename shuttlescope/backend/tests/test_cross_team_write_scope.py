"""他チームの id を指す書き込み/読み取りの team scope (監査 F1-F4 + comments/bookmarks 整合)。

本物の backend.main:app (全ミドルウェア込み) を TestClient + 一時 SQLite で叩く。
peer は remote (203.0.113.9) で、テスト用の loopback 緩和には頼らない。

登場人物: team A = 試合 1 / 選手 1 (出場) / 選手 2 (同チームだが試合に出ない) / 選手 3 (外部)
          team B = 試合 2 / 選手 4
  cA/aA = A の coach/analyst, cB/aB = B の coach/analyst, pA1 = 出場 player, pA2 = 非出場 player,
  pB1 = B の player, admin
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.db import models as M
from backend.db.database import get_db
from backend.main import app
from backend.utils.jwt_utils import create_access_token

TA, TB = 1, 2
TNA, TNB = "ScopeTeamA", "ScopeTeamB"
MARK = "MARKER_A"
CODE_A = "SESSA1"
U = dict(cA=11, aA=12, pA1=13, pA2=14, cB=21, aB=22, pB1=23, admin=1)
_SPEC = {
    "cA": ("coach", None, TA, TNA), "aA": ("analyst", None, TA, TNA),
    "pA1": ("player", 1, TA, TNA), "pA2": ("player", 2, TA, TNA),
    "cB": ("coach", None, TB, TNB), "aB": ("analyst", None, TB, TNB),
    "pB1": ("player", 4, TB, TNB), "admin": ("admin", None, None, None),
}
FOREIGN_WRITERS = ["cB", "aB"]
SAME_TEAM_WRITERS = ["cA", "aA", "admin"]


def tok(kind: str) -> dict:
    role, pid, tid, tname = _SPEC[kind]
    kw = dict(user_id=U[kind], role=role, team_id=tid, team_name=tname)
    if pid:
        kw["player_id"] = pid
    return {"Authorization": "Bearer " + create_access_token(**kw)}


def _seed(db) -> None:
    for t in reversed(M.Base.metadata.sorted_tables):
        db.execute(t.delete())
    db.commit()
    db.add_all([M.Team(id=TA, display_id="SA", name=TNA), M.Team(id=TB, display_id="SB", name=TNB)])
    db.add_all([
        M.Player(id=1, name=f"{MARK}_A1", name_normalized="a1", team_id=TA),
        M.Player(id=2, name=f"{MARK}_A2", name_normalized="a2", team_id=TA),
        M.Player(id=3, name="X1", name_normalized="x1", team_id=None),
        M.Player(id=4, name="B1", name_normalized="b1", team_id=TB),
        M.Player(id=5, name="X2", name_normalized="x2", team_id=None),
    ])
    db.flush()
    for k, uid in U.items():
        role, pid, tid, tn = _SPEC[k]
        db.add(M.User(id=uid, username=f"u_{k}", role=role, player_id=pid, team_id=tid, team_name=tn,
                      consent_required=False))
    db.flush()
    common = dict(tournament_level="domestic", round="QF", date=date(2026, 9, 30), format="singles",
                  result="win", is_public_pool=False)
    db.add(M.Match(id=1, tournament=f"{MARK}_CUP", player_a_id=1, player_b_id=3, owner_team_id=TA,
                   video_local_path=f"C:/{MARK}/v.mp4", **common))
    db.add(M.Match(id=2, tournament="B_CUP", player_a_id=4, player_b_id=5, owner_team_id=TB, **common))
    db.flush()
    for mid, sid, rid, stid in ((1, 1, 1, 1), (2, 2, 2, 2)):
        db.add(M.GameSet(id=sid, match_id=mid, set_num=1))
        db.flush()
        db.add(M.Rally(id=rid, set_id=sid, rally_num=1, server="player_a", winner="player_a",
                       end_type="ace", rally_length=1))
        db.flush()
        db.add(M.Stroke(id=stid, rally_id=rid, stroke_num=1, player="player_a", shot_type="clear"))
    db.flush()
    db.add(M.ConditionTag(id=1, player_id=1, label=f"{MARK}_tag1", start_date=date(2026, 9, 1)))
    db.add(M.MatchCVArtifact(id=1, match_id=1, artifact_type="x"))
    # team_id が NULL の旧予想行 (F3)
    db.add(M.HumanForecast(id=1, match_id=1, player_id=1, forecaster_role="analyst",
                           predicted_outcome="win", team_id=None))
    db.add(M.SharedSession(id=1, match_id=1, session_code=CODE_A, created_by_role="analyst", is_active=True))
    db.commit()


@pytest.fixture
def client(db_session, monkeypatch):
    _seed(db_session)
    app.dependency_overrides[get_db] = lambda: db_session
    import backend.routers.uploads as up
    monkeypatch.setattr(up, "_validate_video_container", lambda p: (True, "stubbed"))
    c = TestClient(app, raise_server_exceptions=False, client=("203.0.113.9", 50000))
    try:
        yield c
    finally:
        app.dependency_overrides.clear()


def _mp4() -> bytes:
    ftyp = (24).to_bytes(4, "big") + b"ftyp" + b"isom" + b"\x00\x00\x02\x00" + b"isom" + b"mp41"
    return ftyp + (8).to_bytes(4, "big") + b"moov" + (8).to_bytes(4, "big") + b"mdat"


def _init(client, actor, match_id=1):
    data = _mp4()
    return client.post("/api/v1/uploads/video/init", headers=tok(actor),
                       json=dict(match_id=match_id, filename="probe.mp4", total_size=len(data),
                                 chunk_size=64 * 1024)), data


def _match1_state(db):
    db.expire_all()
    m = db.get(M.Match, 1)
    return (m.video_local_path, db.query(M.MatchCVArtifact).filter_by(match_id=1).count())


# ─── F1: uploads ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("actor", FOREIGN_WRITERS)
def test_f1_foreign_init_rejected_and_match_untouched(client, db_session, actor):
    before = _match1_state(db_session)
    r, _ = _init(client, actor)
    assert r.status_code == 403, r.text
    assert db_session.query(M.UploadSession).count() == 0
    assert _match1_state(db_session) == before


@pytest.mark.parametrize("actor", FOREIGN_WRITERS)
def test_f1_foreign_finalize_of_preexisting_upload_rejected(client, db_session, actor):
    """init をすり抜けた (旧版で作られた) upload でも finalize で他チームの試合は書き換わらない。"""
    uid = "cccccccc-0000-0000-0000-000000000001"
    db_session.add(M.UploadSession(id=uid, match_id=1, filename="p.mp4", total_size=40, chunk_size=65536,
                                   total_chunks=1, received_bitmap=b"\x01", status="uploading",
                                   user_id=U[actor]))
    db_session.commit()
    before = _match1_state(db_session)
    r = client.post(f"/api/v1/uploads/video/{uid}/finalize", headers=tok(actor))
    assert r.status_code == 403, r.text
    assert _match1_state(db_session) == before


@pytest.mark.parametrize("actor", ["pA1", "pA2", "pB1"])
def test_f1_players_cannot_upload(client, actor):
    r, _ = _init(client, actor)
    assert r.status_code == 403


@pytest.mark.parametrize("actor", SAME_TEAM_WRITERS)
def test_f1_same_team_chain_still_works(client, db_session, actor):
    r, data = _init(client, actor)
    assert r.status_code == 200, r.text
    uid = r.json()["upload_id"]
    r = client.post("/api/v1/uploads/video/chunk", headers=tok(actor), data=dict(upload_id=uid, chunk_index="0"),
                    files={"chunk": ("c.bin", data, "application/octet-stream")})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/v1/uploads/video/{uid}/finalize", headers=tok(actor))
    assert r.status_code == 200, r.text
    assert _match1_state(db_session)[0] == f"server://{uid}.mp4"


# ─── F2: media token ────────────────────────────────────────────────────────

@pytest.fixture
def livekit(monkeypatch):
    monkeypatch.setenv("LIVEKIT_URL", "wss://lk.invalid")
    monkeypatch.setenv("LIVEKIT_API_KEY", "devkey")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "devsecret_devsecret_devsecret_0123456789")


@pytest.mark.parametrize("role", ["viewer", "camera", "operator"])
@pytest.mark.parametrize("actor", FOREIGN_WRITERS)
def test_f2_foreign_media_token_rejected(client, livekit, actor, role):
    r = client.post("/api/media/token", headers=tok(actor), json=dict(session_code=CODE_A, role=role))
    assert r.status_code == 403, r.text
    assert "token" not in r.json()


@pytest.mark.parametrize("actor", ["pA2", "pB1"])
def test_f2_players_outside_the_match_rejected(client, livekit, actor):
    r = client.post("/api/media/token", headers=tok(actor), json=dict(session_code=CODE_A, role="viewer"))
    assert r.status_code == 403


@pytest.mark.parametrize("role", ["viewer", "camera", "operator"])
@pytest.mark.parametrize("actor", SAME_TEAM_WRITERS)
def test_f2_same_team_media_token_ok(client, livekit, actor, role):
    r = client.post("/api/media/token", headers=tok(actor), json=dict(session_code=CODE_A, role=role))
    assert r.status_code == 200, r.text
    assert r.json()["token"]


# ─── F3: prediction benchmark ───────────────────────────────────────────────

@pytest.mark.parametrize("actor", FOREIGN_WRITERS)
def test_f3_benchmark_null_team_rows_do_not_leak(client, actor):
    r = client.get("/api/prediction/benchmark/1", headers=tok(actor))
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["match_comparisons"] == [] and d["summary"] == [] and d["total_forecasts"] == 0
    assert MARK not in r.text and "2026-09-30" not in r.text


@pytest.mark.parametrize("actor", SAME_TEAM_WRITERS)
def test_f3_benchmark_same_team_still_sees_own_match(client, actor):
    r = client.get("/api/prediction/benchmark/1", headers=tok(actor))
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert [c["match_id"] for c in d["match_comparisons"]] == [1]
    assert d["total_forecasts"] == 1


# ─── F4: condition_tags ─────────────────────────────────────────────────────

@pytest.mark.parametrize("actor", ["pA2", "pB1", "cB", "aB"])
def test_f4_condition_tags_denied(client, actor):
    r = client.get("/api/condition_tags?player_id=1", headers=tok(actor))
    assert r.status_code in (403, 404), r.text
    assert MARK not in r.text


def test_f4_condition_tags_pa2_matches_conditions_denial(client):
    """同じ選手の /api/conditions が拒否する相手は condition_tags でも拒否される。"""
    assert client.get("/api/conditions?player_id=1", headers=tok("pA2")).status_code in (403, 404)


@pytest.mark.parametrize("actor", ["pA1", "cA", "aA", "admin"])
def test_f4_condition_tags_allowed(client, actor):
    r = client.get("/api/condition_tags?player_id=1", headers=tok(actor))
    assert r.status_code == 200, r.text
    assert [t["label"] for t in r.json()["data"]] == [f"{MARK}_tag1"]


# ─── comments / bookmarks の rally/set/stroke 整合 ───────────────────────────

@pytest.mark.parametrize("actor", ["cB", "aB"])
def test_comment_with_foreign_rally_rejected(client, db_session, actor):
    for ref in (dict(rally_id=1), dict(set_id=1), dict(stroke_id=1), dict(rally_id=2, stroke_id=1)):
        r = client.post("/api/comments", headers=tok(actor), json=dict(match_id=2, text="x", **ref))
        assert r.status_code == 422, (ref, r.text)
    assert db_session.query(M.Comment).count() == 0


@pytest.mark.parametrize("actor", ["cB", "aB"])
def test_bookmark_with_foreign_rally_rejected(client, db_session, actor):
    for ref in (dict(rally_id=1), dict(stroke_id=1), dict(rally_id=2, stroke_id=1)):
        r = client.post("/api/bookmarks", headers=tok(actor), json=dict(match_id=2, **ref))
        assert r.status_code == 422, (ref, r.text)
    assert db_session.query(M.EventBookmark).count() == 0


@pytest.mark.parametrize("actor", ["cB", "aB"])
def test_comment_bookmark_with_own_refs_still_created(client, actor):
    r = client.post("/api/comments", headers=tok(actor),
                    json=dict(match_id=2, text="ok", set_id=2, rally_id=2, stroke_id=2))
    assert r.status_code == 201, r.text
    r = client.post("/api/comments", headers=tok(actor), json=dict(match_id=2, text="plain"))
    assert r.status_code == 201, r.text
    r = client.post("/api/bookmarks", headers=tok(actor), json=dict(match_id=2, rally_id=2, stroke_id=2))
    assert r.status_code == 201, r.text
