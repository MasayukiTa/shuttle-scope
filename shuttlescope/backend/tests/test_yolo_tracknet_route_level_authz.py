"""yolo / tracknet の match_id ルートが、ルート自身で role と team scope を強制すること (F2)。

これらのルートは従来、`TeamScopeAccessControlMiddleware._MATCH_ID_PATTERNS` の
path 正規表現と GlobalAuthMiddleware (有効な JWT なら誰でも通す) だけで守られていた。
path / 正規表現を改名すると守りが黙って消え、player / demo / llm を含む任意のロールが
ハンドラに到達する。ルート側に依存性を置いて二重化した。

このテストはミドルウェアを **一切載せない** 素の FastAPI app にルータだけをマウントして叩く。
つまりミドルウェアの正規表現が無効化された状態と同じで、ここで 403 が返るなら
ハンドラ自身が守っている。
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import Match, Player, Team
from backend.routers import tracknet as tracknet_router
from backend.routers import yolo as yolo_router
from backend.utils.auth import require_match_operator_scope, require_match_scope_dep
from backend.utils.jwt_utils import create_access_token

# (method, path template, kind) kind: "write" = admin/analyst/coach のみ, "read" = match scope のみ
ROUTES = [
    ("DELETE", "/api/yolo/results/{mid}", "write"),
    ("POST", "/api/yolo/batch/{mid}", "write"),
    ("POST", "/api/yolo/frame_detect/{mid}", "write"),
    ("POST", "/api/yolo/align/{mid}", "write"),
    ("POST", "/api/yolo/assign_and_track/{mid}", "write"),
    ("POST", "/api/tracknet/batch/{mid}", "write"),
    ("GET", "/api/yolo/results/{mid}", "read"),
    ("GET", "/api/yolo/results/{mid}/frames", "read"),
    ("GET", "/api/yolo/alignment/{mid}", "read"),
    ("GET", "/api/yolo/identity_track/{mid}", "read"),
    ("GET", "/api/yolo/movement_stats/{mid}", "read"),
    ("GET", "/api/yolo/doubles_analysis/{mid}", "read"),
    ("GET", "/api/tracknet/shuttle_track/{mid}", "read"),
    ("GET", "/api/tracknet/resume_check/{mid}", "read"),
]
IDS = [f"{m} {p.replace('/api/', '')}" for m, p, _ in ROUTES]

TEAM_A, TEAM_B = 9101, 9102
OWN_MATCH, FOREIGN_MATCH = 9401, 9402
PLAYER_A1, PLAYER_A2, PLAYER_B1, PLAYER_B2 = 9201, 9202, 9203, 9204


def _tok(role: str, *, team_id: int | None, team_name: str | None, player_id: int | None = None) -> dict:
    kw = dict(user_id=9301, role=role, team_id=team_id, team_name=team_name)
    if player_id is not None:
        kw["player_id"] = player_id
    return {"Authorization": "Bearer " + create_access_token(**kw)}


@pytest.fixture()
def client(db_session):
    db = db_session
    db.add_all([
        Team(id=TEAM_A, display_id="F2-A", name="F2 Team A"),
        Team(id=TEAM_B, display_id="F2-B", name="F2 Team B"),
    ])
    db.add_all([
        Player(id=PLAYER_A1, name="A1", name_normalized="a1", team_id=TEAM_A),
        Player(id=PLAYER_A2, name="A2", name_normalized="a2", team_id=TEAM_A),
        Player(id=PLAYER_B1, name="B1", name_normalized="b1", team_id=TEAM_B),
        Player(id=PLAYER_B2, name="B2", name_normalized="b2", team_id=TEAM_B),
    ])
    common = dict(tournament="F2 Cup", tournament_level="domestic", round="QF",
                  date=date(2026, 9, 30), format="singles", result="unknown",
                  is_public_pool=False)
    db.add_all([
        Match(id=OWN_MATCH, player_a_id=PLAYER_A1, player_b_id=PLAYER_A2,
              owner_team_id=TEAM_A, **common),
        Match(id=FOREIGN_MATCH, player_a_id=PLAYER_B1, player_b_id=PLAYER_B2,
              owner_team_id=TEAM_B, **common),
    ])
    db.commit()

    # ミドルウェアなし: ルータだけをマウントする。
    app = FastAPI()
    app.include_router(yolo_router.router, prefix="/api")
    app.include_router(tracknet_router.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, base_url="http://localhost", raise_server_exceptions=False)


def _call(client, method, path_tpl, mid, headers):
    return client.request(method, path_tpl.format(mid=mid), headers=headers, json={} if method != "GET" else None)


# ─── (a) 守りが効いていること ────────────────────────────────────────────────

@pytest.mark.parametrize("method,path,kind", ROUTES, ids=IDS)
def test_other_team_is_rejected_without_middleware(client, method, path, kind):
    for role in ("analyst", "coach"):
        h = _tok(role, team_id=TEAM_B, team_name="F2 Team B")
        r = _call(client, method, path, OWN_MATCH, h)
        assert r.status_code == 403, (role, r.status_code, r.text)


@pytest.mark.parametrize("method,path,kind", ROUTES, ids=IDS)
def test_player_is_rejected_without_middleware(client, method, path, kind):
    # 他チーム選手 (どの routes でも不可) と、自チームだが当該試合に出ない選手。
    h_other = _tok("player", team_id=TEAM_B, team_name="F2 Team B", player_id=PLAYER_B1)
    assert _call(client, method, path, OWN_MATCH, h_other).status_code == 403
    if kind == "write":
        # 書き込み系は、試合に出場している選手本人でも不可。
        h_self = _tok("player", team_id=TEAM_A, team_name="F2 Team A", player_id=PLAYER_A1)
        r = _call(client, method, path, OWN_MATCH, h_self)
        assert r.status_code == 403, r.text


@pytest.mark.parametrize("role", ["demo", "llm"])
@pytest.mark.parametrize("method,path,kind", ROUTES, ids=IDS)
def test_demo_and_llm_are_rejected_without_middleware(client, method, path, kind, role):
    h = _tok(role, team_id=TEAM_A, team_name="F2 Team A")
    assert _call(client, method, path, OWN_MATCH, h).status_code == 403


@pytest.mark.parametrize("method,path,kind", ROUTES, ids=IDS)
def test_missing_match_is_404_not_a_handler_reach(client, method, path, kind):
    h = _tok("analyst", team_id=TEAM_A, team_name="F2 Team A")
    assert _call(client, method, path, 987654, h).status_code == 404


# ─── (b) 許可された呼び手は認可層を通る ──────────────────────────────────────

@pytest.mark.parametrize("method,path,kind", ROUTES, ids=IDS)
def test_own_team_operator_passes_auth_layer(client, method, path, kind):
    for role in ("analyst", "coach"):
        h = _tok(role, team_id=TEAM_A, team_name="F2 Team A")
        r = _call(client, method, path, OWN_MATCH, h)
        # 認可は通る。ハンドラ側の都合 (動画なし 400 / body 検証 422 等) は問わない。
        assert r.status_code not in (401, 403), (role, r.status_code, r.text)


@pytest.mark.parametrize("method,path,kind", [r for r in ROUTES if r[2] == "read"],
                         ids=[i for i, r in zip(IDS, ROUTES) if r[2] == "read"])
def test_participating_player_can_still_read_own_match(client, method, path, kind):
    """読み取りは既存の match 読み取り方針どおり: 出場選手本人は通る (広げない)。"""
    h = _tok("player", team_id=TEAM_A, team_name="F2 Team A", player_id=PLAYER_A1)
    r = _call(client, method, path, OWN_MATCH, h)
    assert r.status_code not in (401, 403), (r.status_code, r.text)


def test_admin_passes_on_any_match(client):
    h = _tok("admin", team_id=None, team_name=None)
    r = _call(client, "DELETE", "/api/yolo/results/{mid}", FOREIGN_MATCH, h)
    assert r.status_code not in (401, 403), r.text


# ─── 構造ガード: 依存性がルートに付いていること ──────────────────────────────

def _route_deps(method: str, path: str):
    for mod in (yolo_router, tracknet_router):
        for r in mod.router.routes:
            if isinstance(r, APIRoute) and r.path == path.replace("/api", "").format(mid="{match_id}") \
                    and method in r.methods:
                return {d.call for d in r.dependant.dependencies}
    raise AssertionError(f"route not found: {method} {path}")


@pytest.mark.parametrize("method,path,kind", ROUTES, ids=IDS)
def test_route_declares_its_own_guard(method, path, kind):
    deps = _route_deps(method, path)
    expected = require_match_operator_scope if kind == "write" else require_match_scope_dep
    assert expected in deps
