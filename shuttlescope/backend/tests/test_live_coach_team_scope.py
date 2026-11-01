"""live_coach エンドポイントの team 境界チェック (h18e)。

review out_rv2_auth/review.md defect 1: GET /api/analysis/live_anomaly と
/api/analysis/live_suggestions は _require_coach_or_higher (role だけ) しか見ず、
user_can_access_match を呼んでいなかったため、他チームの coach / analyst が
任意の match_id / player_id の shot 分布・anomaly・戦術提案を取得できた。

ここでは:
- team A が所有する非公開 match に対し、team B の coach は両エンドポイントで 404
  (enumeration 防御のため 403 ではなく 404)。
- team A の coach は 200。

setup スタイルは backend/tests/test_authenticated_is_not_authorised.py に倶い、
ORM 行は NOT NULL 列を全て埋める。認可境界だけを見たいので get_auth を
dependency_overrides で差し替え、AuthCtx.team_id を直接与える (既存の
test_live_anomaly / test_live_suggestions と同じ流儀)。
"""
from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from backend.db.models import GameSet, Match, Player, Rally, Stroke, Team
from backend.main import app
from backend.utils.auth import AuthCtx, get_auth


def _coach(team_id: int):
    """team_id を持つ coach の AuthCtx。player_id は None。"""
    return AuthCtx(role="coach", player_id=None, user_id=1, team_id=team_id)


def _seed_team_a_match(db_session):
    """team A 所有・非公開の match を作り、anomaly / suggestion が出るラリーを入れる。

    - team A / team B を作る。
    - 選手 A / B はともに team A 所属 (team B の coach が "自チーム選手登場"
      経路でも通れないことを保証する)。
    - Match.owner_team_id = team A、is_public_pool / is_demo_public は未設定
      (= False) の非公開試合。
    戻り値: (team_a_id, team_b_id, player_a_id, match_id)
    """
    team_a = Team(name="チームA")
    team_b = Team(name="チームB")
    db_session.add_all([team_a, team_b])
    db_session.flush()

    p_a = Player(name="A", team_id=team_a.id)
    p_b = Player(name="B", team_id=team_a.id)
    db_session.add_all([p_a, p_b])
    db_session.flush()

    m = Match(
        tournament="T", tournament_level="国内", round="R16",
        date=date(2026, 4, 16), format="singles",
        player_a_id=p_a.id, player_b_id=p_b.id, result="win",
        owner_team_id=team_a.id,
    )
    db_session.add(m)
    db_session.flush()

    gs = GameSet(match_id=m.id, set_num=1, score_a=21, score_b=18)
    db_session.add(gs)
    db_session.flush()

    # ベースライン (clear 主体) 20 ラリー
    for i in range(1, 21):
        r = Rally(set_id=gs.id, rally_num=i, server="player_a",
                  winner="player_a", end_type="forced_error",
                  rally_length=4, is_skipped=False)
        db_session.add(r)
        db_session.flush()
        for k in range(4):
            db_session.add(Stroke(rally_id=r.id, stroke_num=k + 1,
                                  player="player_a", shot_type="clear"))

    # 直近 5 ラリー (smash 主体) — anomaly / suggestion を出すため
    for i in range(21, 26):
        r = Rally(set_id=gs.id, rally_num=i, server="player_a",
                  winner="player_a", end_type="forced_error",
                  rally_length=4, is_skipped=False)
        db_session.add(r)
        db_session.flush()
        for k in range(4):
            db_session.add(Stroke(rally_id=r.id, stroke_num=k + 1,
                                  player="player_a", shot_type="smash"))

    db_session.commit()
    return team_a.id, team_b.id, p_a.id, m.id


def _get(endpoint: str, pid: int, mid: int):
    client = TestClient(app, base_url="http://localhost")
    params = {"player_id": pid, "match_id": mid}
    if endpoint == "live_anomaly":
        params["window"] = 5
    return client.get(f"/api/analysis/{endpoint}", params=params)


def test_live_anomaly_other_team_coach_gets_404(db_session):
    _ta, tb, pid, mid = _seed_team_a_match(db_session)
    app.dependency_overrides[get_auth] = lambda: _coach(tb)
    try:
        resp = _get("live_anomaly", pid, mid)
        assert resp.status_code == 404, resp.text
    finally:
        app.dependency_overrides.pop(get_auth, None)


def test_live_anomaly_owning_team_coach_gets_200(db_session):
    ta, _tb, pid, mid = _seed_team_a_match(db_session)
    app.dependency_overrides[get_auth] = lambda: _coach(ta)
    try:
        resp = _get("live_anomaly", pid, mid)
        assert resp.status_code == 200, resp.text
        assert "anomaly" in resp.json()
    finally:
        app.dependency_overrides.pop(get_auth, None)


def test_live_suggestions_other_team_coach_gets_404(db_session):
    _ta, tb, pid, mid = _seed_team_a_match(db_session)
    app.dependency_overrides[get_auth] = lambda: _coach(tb)
    try:
        resp = _get("live_suggestions", pid, mid)
        assert resp.status_code == 404, resp.text
    finally:
        app.dependency_overrides.pop(get_auth, None)


def test_live_suggestions_owning_team_coach_gets_200(db_session):
    ta, _tb, pid, mid = _seed_team_a_match(db_session)
    app.dependency_overrides[get_auth] = lambda: _coach(ta)
    try:
        resp = _get("live_suggestions", pid, mid)
        assert resp.status_code == 200, resp.text
        assert "items" in resp.json()
    finally:
        app.dependency_overrides.pop(get_auth, None)
