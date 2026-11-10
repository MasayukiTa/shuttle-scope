"""cv-candidates ルートは CV 候補 (不確実な CV 出力) を返す/書くので、player / demo / llm に開けない。

CLAUDE.md: player ロールに研究・CV 候補の出力を見せない。`_require_match_team_scope` は
「試合に出場している player」を明示的に通していたため、自分が出る試合の cv_candidates /
rally_boundaries / review-queue を player が読め、build/apply/review も叩けた。

ルート側に admin/analyst/coach のみのロールゲートを置く (yolo.py と同じ
`require_match_operator_scope` の考え方)。TestClient は middleware を全部載せた本物の
`backend.main.app` を通す (= 本番と同じ経路)。
"""
from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import GameSet, Match, MatchCVArtifact, Player, Rally, Team, User
from backend.main import app
from backend.routers.auth import _hash_password
from backend.utils.jwt_utils import create_access_token

TEAM_ID = 9611
OTHER_TEAM_ID = 9612
MARK = "CVGATE_SECRET_MARK"

# (method, path template using {mid} / {rid}, json body)
ROUTES = [
    ("GET", "/api/cv-candidates/{mid}", None),
    ("GET", "/api/cv-candidates/review-queue/{mid}", None),
    ("POST", "/api/cv-candidates/build/{mid}", {}),
    ("POST", "/api/cv-candidates/apply/{mid}", {"mode": "all"}),
    ("PUT", "/api/cv-candidates/review/{rid}", {"review_status": "completed"}),
]
IDS = [f"{m} {p.replace('/api/cv-candidates/', '')}" for m, p, _ in ROUTES]


@pytest.fixture()
def ctx(db_session):
    db = db_session
    db.add_all([
        Team(id=TEAM_ID, display_id="CVG-A", name="CVG Team A"),
        Team(id=OTHER_TEAM_ID, display_id="CVG-B", name="CVG Team B"),
    ])
    pa = Player(name="CVG PA", name_normalized="cvg pa", team_id=TEAM_ID)
    pb = Player(name="CVG PB", name_normalized="cvg pb", team_id=TEAM_ID)
    db.add_all([pa, pb])
    db.flush()
    m = Match(tournament="CVG", tournament_level="domestic", round="QF",
              date=date(2026, 10, 14), format="singles", result="unknown",
              is_public_pool=False, player_a_id=pa.id, player_b_id=pb.id,
              owner_team_id=TEAM_ID)
    db.add(m)
    db.flush()
    gs = GameSet(match_id=m.id, set_num=1, winner="player_a", score_a=21, score_b=10)
    db.add(gs)
    db.flush()
    rally = Rally(set_id=gs.id, rally_num=1, server="player_a", winner="player_a",
                  end_type="forced_error", rally_length=3, review_status="pending")
    db.add(rally)
    db.flush()
    db.add(MatchCVArtifact(
        match_id=m.id, artifact_type="cv_candidates", frame_count=1,
        data=json.dumps({
            "rallies": {str(rally.id): {"review_reason_codes": [MARK]}},
            "rally_boundaries": {"boundaries": [{"note": MARK}], "boundary_count": 1},
        })))
    users = {}
    for i, role in enumerate(("player", "demo", "llm", "coach", "analyst", "admin")):
        u = User(username=f"cvg_{role}", role=role, display_name=role,
                 hashed_credential=_hash_password("pw"),
                 player_id=pa.id if role == "player" else None,
                 team_id=None if role == "admin" else TEAM_ID,
                 team_name=None if role == "admin" else "CVG Team A",
                 consent_required=False)
        db.add(u)
        users[role] = u
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield {"client": TestClient(app, raise_server_exceptions=False),
               "mid": m.id, "rid": rally.id, "users": users, "pa": pa.id}
    finally:
        app.dependency_overrides.clear()


def _call(c, role, method, tpl, body):
    u = c["users"][role]
    tok = create_access_token(
        user_id=u.id, role=role, player_id=u.player_id,
        team_name=u.team_name, team_id=u.team_id)
    return c["client"].request(
        method, tpl.format(mid=c["mid"], rid=c["rid"]),
        headers={"Authorization": f"Bearer {tok}"}, json=body)


@pytest.mark.parametrize("role", ["player", "demo", "llm"])
@pytest.mark.parametrize("method,tpl,body", ROUTES, ids=IDS)
def test_non_operator_roles_are_rejected_and_see_no_candidate_data(ctx, role, method, tpl, body):
    r = _call(ctx, role, method, tpl, body)
    print(f"TABLE {role:7s} {method:4s} {tpl:44s} -> {r.status_code} mark_in_body={MARK in r.text}")
    assert r.status_code == 403, (role, r.status_code, r.text)
    assert MARK not in r.text


@pytest.mark.parametrize("role", ["coach", "analyst", "admin"])
@pytest.mark.parametrize("method,tpl,body", ROUTES, ids=IDS)
def test_operators_still_pass_the_auth_layer(ctx, role, method, tpl, body):
    r = _call(ctx, role, method, tpl, body)
    print(f"TABLE {role:7s} {method:4s} {tpl:44s} -> {r.status_code} mark_in_body={MARK in r.text}")
    # 認可は通る。ハンドラ側の事情 (成果物なし 4xx 等) は問わないが 401/403/404-match は不可。
    assert r.status_code not in (401, 403), (role, r.status_code, r.text)


@pytest.mark.parametrize("role", ["coach", "analyst", "admin"])
def test_operators_still_read_the_candidate_payload(ctx, role):
    r = _call(ctx, role, "GET", "/api/cv-candidates/{mid}", None)
    assert r.status_code == 200
    assert MARK in r.text
    q = _call(ctx, role, "GET", "/api/cv-candidates/review-queue/{mid}", None)
    assert q.status_code == 200 and MARK in q.text


def test_player_write_does_not_change_review_status(ctx, db_session):
    _call(ctx, "player", "PUT", "/api/cv-candidates/review/{rid}", {"review_status": "completed"})
    db_session.expire_all()
    assert db_session.get(Rally, ctx["rid"]).review_status == "pending"


# ─── ミドルウェアなし: ルート自身が守っていること ────────────────────────────

@pytest.mark.parametrize("role", ["player", "demo", "llm"])
@pytest.mark.parametrize("method,tpl,body", ROUTES, ids=IDS)
def test_routes_reject_non_operators_without_middleware(ctx, db_session, role, method, tpl, body):
    """PlayerAccessControlMiddleware の許可リストが変わっても守りが消えないこと。"""
    from fastapi import FastAPI
    from backend.routers import cv_candidates as cv_router

    bare = FastAPI()
    bare.include_router(cv_router.router, prefix="/api")
    bare.dependency_overrides[get_db] = lambda: db_session
    u = ctx["users"][role]
    tok = create_access_token(user_id=u.id, role=role, player_id=u.player_id,
                              team_name=u.team_name, team_id=u.team_id)
    c = TestClient(bare, base_url="http://localhost", raise_server_exceptions=False)
    r = c.request(method, tpl.format(mid=ctx["mid"], rid=ctx["rid"]),
                  headers={"Authorization": f"Bearer {tok}"}, json=body)
    assert r.status_code == 403, (role, method, tpl, r.status_code, r.text)
    assert MARK not in r.text
    db_session.expire_all()
    assert db_session.get(Rally, ctx["rid"]).review_status == "pending"
