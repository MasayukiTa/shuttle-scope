"""test_matchup_forecast_endpoint.py — MATCHUP-001 matchup_forecast エンドポイントの結合テスト

テスト設計:
- hier_bayes_loader.load_match_pairs は player_id が関与する全試合から
  (winner_id, loser_id) ペアを収集し、Bradley-Terry モデルで強さを推定する。
- シード: 3選手 (target / rival_a / rival_b) で試合を複数本生成。
  target が rival_a/b に勝つ試合を多めにすることで theta[target] が正寄りになる。
- admin ctx → allowed_player_ids=None (無制限) のため、チームスコープ不要。
"""
import pytest
from datetime import date
from fastapi.testclient import TestClient

from backend.main import app
from backend.db.database import get_db
from backend.db.models import Player, Match, GameSet, Rally, Stroke
from backend.utils.auth import (
    AuthCtx,
    get_auth,
    require_admin_or_analyst,
    require_non_player,
)


# ── テスト用 admin AuthCtx ────────────────────────────────────────────────────

def _admin_ctx() -> AuthCtx:
    return AuthCtx(role="admin", player_id=None, user_id=1, team_name=None, team_id=None)


# ── シードヘルパー ─────────────────────────────────────────────────────────────

def _make_match_with_result(
    db,
    player_a_id: int,
    player_b_id: int,
    result: str,
    match_num: int,
) -> Match:
    """result ('win' = player_a 勝ち, 'loss' = player_b 勝ち) の試合を生成する。"""
    m = Match(
        tournament=f"BT Test {match_num}",
        tournament_level="IC",
        round="R1",
        date=date(2025, 9, match_num % 28 + 1),
        format="singles",
        player_a_id=player_a_id,
        player_b_id=player_b_id,
        result=result,
        annotation_status="complete",
        annotation_progress=1.0,
    )
    db.add(m)
    db.flush()
    return m


def _seed_matchup_players(db):
    """
    3選手で複数試合を生成する。

    target が rival_a / rival_b に多く勝つことで Bradley-Terry の
    theta[target] が正寄りになり、p_win in (0, 1) の予測が確認できる。

    load_match_pairs の要件:
      - player_id 自身が関与する試合が最低1本
      - len(ids) >= 2 かつ len(pairs) >= 1 でないとモデル未実行で空返却される
    """
    target = Player(name="MatchupTarget", dominant_hand="R")
    rival_a = Player(name="MatchupRivalA", dominant_hand="R")
    rival_b = Player(name="MatchupRivalB", dominant_hand="L")
    db.add(target); db.add(rival_a); db.add(rival_b)
    db.flush()

    match_num = 0

    # target vs rival_a: target が 3 勝 1 敗
    for i in range(3):
        match_num += 1
        _make_match_with_result(db, target.id, rival_a.id, "win", match_num)
    match_num += 1
    _make_match_with_result(db, target.id, rival_a.id, "loss", match_num)

    # target vs rival_b: target が 2 勝 1 敗
    for i in range(2):
        match_num += 1
        _make_match_with_result(db, target.id, rival_b.id, "win", match_num)
    match_num += 1
    _make_match_with_result(db, target.id, rival_b.id, "loss", match_num)

    # rival_a vs rival_b: rival_a が 2 勝 (モデルに3選手間の情報を与える)
    for i in range(2):
        match_num += 1
        _make_match_with_result(db, rival_a.id, rival_b.id, "win", match_num)

    db.flush()
    return target.id


# ── フィクスチャ ──────────────────────────────────────────────────────────────

@pytest.fixture
def matchup_forecast_client(db_session):
    """シードデータ付きの TestClient を返す。"""
    target_id = _seed_matchup_players(db_session)
    db_session.flush()

    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_auth] = _admin_ctx
    app.dependency_overrides[require_admin_or_analyst] = _admin_ctx
    app.dependency_overrides[require_non_player] = _admin_ctx

    client = TestClient(app)
    yield client, target_id
    app.dependency_overrides.clear()


# ── テストケース ──────────────────────────────────────────────────────────────

class TestMatchupForecastEndpoint:

    def test_returns_200_with_success(self, matchup_forecast_client):
        """エンドポイントが 200 を返し success=True であること。"""
        client, target_id = matchup_forecast_client
        resp = client.get(f"/api/analysis/matchup_forecast?player_id={target_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True

    def test_response_has_required_keys(self, matchup_forecast_client):
        """レスポンスに player_id / strength / matchups / n_players / meta が含まれること。"""
        client, target_id = matchup_forecast_client
        resp = client.get(f"/api/analysis/matchup_forecast?player_id={target_id}")
        body = resp.json()
        data = body["data"]
        assert data["player_id"] == target_id
        assert "strength" in data
        assert "matchups" in data
        assert "n_players" in data
        meta = body["meta"]
        assert meta["analysis_type"] == "matchup_forecast"

    def test_strength_has_value_and_ci(self, matchup_forecast_client):
        """strength に value / ci_low / ci_high が含まれること。"""
        client, target_id = matchup_forecast_client
        resp = client.get(f"/api/analysis/matchup_forecast?player_id={target_id}")
        body = resp.json()
        strength = body["data"]["strength"]
        assert strength is not None, "十分な試合数があるので strength は null でないはず"
        assert "value" in strength
        assert "ci_low" in strength
        assert "ci_high" in strength
        assert isinstance(strength["value"], (int, float))

    def test_matchups_list_nonempty(self, matchup_forecast_client):
        """matchups リストが空でないこと。"""
        client, target_id = matchup_forecast_client
        resp = client.get(f"/api/analysis/matchup_forecast?player_id={target_id}")
        body = resp.json()
        matchups = body["data"]["matchups"]
        assert isinstance(matchups, list)
        assert len(matchups) >= 1, (
            f"コホートに rival_a/rival_b がいるので matchups は空でないはず: {matchups}"
        )

    def test_matchup_p_win_in_valid_range(self, matchup_forecast_client):
        """各 matchup の p_win が [0, 1] の範囲で ci_low <= p_win <= ci_high であること。"""
        client, target_id = matchup_forecast_client
        resp = client.get(f"/api/analysis/matchup_forecast?player_id={target_id}")
        body = resp.json()
        matchups = body["data"]["matchups"]
        for m in matchups:
            assert "opponent_id" in m, f"opponent_id が不足: {m}"
            assert "p_win" in m, f"p_win が不足: {m}"
            p_win = m["p_win"]
            assert 0.0 <= p_win <= 1.0, f"p_win が範囲外: {p_win}"
            assert "ci_low" in m and "ci_high" in m, f"CI キーが不足: {m}"
            assert m["ci_low"] <= p_win <= m["ci_high"], (
                f"CI 順序不正: ci_low={m['ci_low']}, p_win={p_win}, ci_high={m['ci_high']}"
            )
            assert "n_h2h" in m and m["n_h2h"] >= 0, f"n_h2h が不正: {m}"

    def test_n_players_at_least_2(self, matchup_forecast_client):
        """n_players >= 2 (target + rival 少なくとも1名) であること。"""
        client, target_id = matchup_forecast_client
        resp = client.get(f"/api/analysis/matchup_forecast?player_id={target_id}")
        body = resp.json()
        assert body["data"]["n_players"] >= 2

    def test_empty_player_returns_empty_gracefully(self, db_session):
        """試合データが存在しない player_id でも 200 空レスポンスが返ること。"""
        empty_player = Player(name="MatchupEmpty", dominant_hand="R")
        db_session.add(empty_player)
        db_session.flush()
        empty_pid = empty_player.id

        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_auth] = _admin_ctx
        app.dependency_overrides[require_admin_or_analyst] = _admin_ctx
        app.dependency_overrides[require_non_player] = _admin_ctx
        try:
            client = TestClient(app)
            resp = client.get(f"/api/analysis/matchup_forecast?player_id={empty_pid}")
            assert resp.status_code == 200
            body = resp.json()
            assert body["success"] is True
            assert body["data"]["matchups"] == []
            assert body["data"]["strength"] is None
        finally:
            app.dependency_overrides.clear()
