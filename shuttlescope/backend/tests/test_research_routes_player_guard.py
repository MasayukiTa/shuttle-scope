"""research / advanced / spine / bundle / prediction の全ルートが player を自分で拒否することの回帰テスト。

製品ルール: research 層の解析は player に出さない (生の勝率 / EPV / 弱点の提示を含む)。
これまで spine と bundle/review はミドルウェア (main.py の _PLAYER_FORBIDDEN_ANALYSIS_PATHS) だけが
player を止めていて、ルート自身には役割の依存が無かった。stable 内の禁止パス
(win_loss_comparison / received_vulnerability など) も同様に、一部のルートにしか依存が無かった。

  (a) 構造: 対象ルーターの全ルートが役割の依存を持つ (ミドルウェアが外れても拒否できる)
  (b) 実アプリ + player JWT: 403。analyst / admin は 403 / 401 にならない (従来どおり通る)
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import Match, Player, Team, User
from backend.main import app
from backend.routers.auth import _hash_password
from backend.utils.jwt_utils import create_access_token

_TEAM_ID = 9201
_PLAYER_USER_ID = 10


def _headers(role: str, user_id: int = 99, player_id: int | None = None) -> dict:
    tok = create_access_token(
        user_id=user_id, role=role, player_id=player_id,
        team_name="T", team_id=_TEAM_ID,
    )
    return {"Authorization": f"Bearer {tok}"}


def _routers():
    from backend.routers import (
        analysis_advanced, analysis_bundle, analysis_research, analysis_spine,
        human_forecast, prediction,
    )
    return {
        "research": analysis_research.router,
        "advanced": analysis_advanced.router,
        "spine": analysis_spine.router,
        "bundle": analysis_bundle.router,
        "prediction": prediction.router,
        "human_forecast": human_forecast.router,
    }


def _deps(route) -> list:
    return [d.call for d in route.dependant.dependencies]


def _role_dependencies() -> set:
    from backend.utils.auth import (
        require_admin, require_admin_or_analyst, require_analyst, require_non_player,
    )
    return {require_non_player, require_admin_or_analyst, require_analyst, require_admin}


def _plain_get_paths() -> list[str]:
    """パスパラメータを持たない GET ルート (research 層の全ルーター分) を /api 付きで返す。"""
    out: list[str] = []
    for router in _routers().values():
        for route in router.routes:
            methods = getattr(route, "methods", None) or set()
            path = getattr(route, "path", "")
            if "GET" in methods and "{" not in path:
                out.append(f"/api{path}")
    return sorted(set(out))


class TestStructure:
    @pytest.mark.parametrize("name", ["research", "advanced", "spine", "bundle", "prediction", "human_forecast"])
    def test_every_route_has_a_role_dependency(self, name):
        """ミドルウェアが外れても (経路が増えても) ルート自身が player を拒否する。"""
        allowed = _role_dependencies()
        router = _routers()[name]
        assert router.routes
        missing = [
            f"{sorted(getattr(r, 'methods', []))} {r.path}"
            for r in router.routes
            if not (allowed & set(_deps(r)))
        ]
        assert not missing, missing

    def test_named_forbidden_paths_in_stable_router_are_guarded(self):
        from backend.routers.analysis_stable import router as stable_router
        from backend.utils.auth import require_non_player
        from backend.utils.player_privacy import (
            PLAYER_FORBIDDEN_NAMED_ANALYSIS_PATHS, deny_player_on_forbidden_named_path,
        )
        stable_paths = {f"/api{r.path}": r for r in stable_router.routes}
        in_stable = [p for p in PLAYER_FORBIDDEN_NAMED_ANALYSIS_PATHS if p in stable_paths]
        # 少なくとも win_loss_comparison / received_vulnerability(+zone_detail) / shot_win_loss / pre_loss_patterns
        assert len(in_stable) >= 5, in_stable
        for p in in_stable:
            deps = _deps(stable_paths[p])
            assert deny_player_on_forbidden_named_path in deps or require_non_player in deps, p


@pytest.fixture
def world(db_session):
    db = db_session
    team = Team(id=_TEAM_ID, display_id="T-2", name="T")
    db.add(team)
    db.flush()
    own = Player(name="Own Player", name_normalized="own", team_id=team.id)
    db.add(own)
    db.flush()
    opp = Player(name="Opp Player", name_normalized="opp", team_id=team.id)
    db.add(opp)
    db.flush()
    db.add(User(
        id=_PLAYER_USER_ID, username="pl", role="player", display_name="x",
        hashed_credential=_hash_password("pw"), player_id=own.id,
        team_name="T", team_id=team.id,
    ))
    # match_id クエリ付きの要求は、役割ガードより前にミドルウェアが試合の存在と
    # 参加者を検証する (存在しなければ 404)。ルート自身のガードを試すには、
    # 本人が出る実在の試合を渡す必要がある。
    match = Match(
        tournament="t", tournament_level="IC", round="r", date=date(2026, 1, 10),
        format="singles", player_a_id=own.id, player_b_id=opp.id, result="win",
        annotation_status="complete", annotation_progress=1.0,
    )
    db.add(match)
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield {"db": db, "own": own, "opp": opp, "match": match}
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def _url(path: str, world: dict) -> str:
    return (
        f"{path}?player_id={world['own'].id}&match_id={world['match'].id}"
        f"&opponent_id={world['opp'].id}&partner_id={world['opp'].id}"
    )


class TestHttp:
    def test_paths_were_collected(self):
        paths = _plain_get_paths()
        assert len(paths) >= 30, paths
        assert "/api/analysis/epv" in paths
        assert "/api/analysis/epv_state_table" in paths
        assert "/api/analysis/bundle/review" in paths

    @pytest.mark.parametrize("path", _plain_get_paths())
    def test_player_gets_403(self, world, client, path):
        pid = world["own"].id
        h = _headers("player", user_id=_PLAYER_USER_ID, player_id=pid)
        r = client.get(_url(path, world), headers=h)
        assert r.status_code == 403, (path, r.status_code, r.text[:200])

    @pytest.mark.parametrize("path", _plain_get_paths())
    @pytest.mark.parametrize("role", ["analyst", "admin"])
    def test_analyst_and_admin_are_not_rejected(self, world, client, path, role):
        r = client.get(_url(path, world), headers=_headers(role))
        # 引数が足りず 422 / データ無しで 404 になるルートはある。役割で弾かれていないことだけを見る。
        assert r.status_code not in (401, 403), (path, role, r.status_code, r.text[:200])

    @pytest.mark.parametrize("path", [
        "/api/analysis/epv_state_table",
        "/api/analysis/bundle/review",
        "/api/analysis/pressure_performance",
        "/api/prediction/fatigue_risk",
    ])
    def test_coach_is_not_rejected_where_coach_was_allowed(self, world, client, path):
        r = client.get(_url(path, world), headers=_headers("coach"))
        assert r.status_code not in (401, 403), (path, r.status_code, r.text[:200])

    @pytest.mark.parametrize("path", [
        "/api/analysis/win_loss_comparison",
        "/api/analysis/received_vulnerability",
        "/api/analysis/shot_win_loss",
    ])
    def test_named_stable_paths_player_403_others_ok(self, world, client, path):
        pid = world["own"].id
        h = _headers("player", user_id=_PLAYER_USER_ID, player_id=pid)
        assert client.get(_url(path, world), headers=h).status_code == 403
        for role in ("coach", "analyst", "admin"):
            r = client.get(_url(path, world), headers=_headers(role))
            assert r.status_code not in (401, 403), (path, role, r.status_code)
