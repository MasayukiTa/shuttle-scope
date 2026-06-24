"""test_conformal_endpoint.py — CP-001 コンフォーマル予測エンドポイントの結合テスト

テスト設計:
- 2 グループに分離した勝率を持つ選手データ (~60 ラリー) を生成し、
  エンドポイントが 200 を返すこと・empirical_coverage が存在し
  target_coverage - 0.15 以上であることを検証する (有限サンプルで緩めの許容幅)。
- データなしの選手 (n < MIN_SAMPLES) でグレースフルに "insufficient" を返すことを検証する。
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

def _seed_conformal_player(db, n_rallies: int = 60):
    """
    2 グループ (smash が多いラリー vs clear が多いラリー) で勝率が分離したデータを生成。

    グループ A: smash 多用 → 勝率 3/4 程度
    グループ B: clear 多用 → 勝率 1/4 程度

    score_a_after=5, score_b_after=3 → score_phase=early
    server=player_b → player は receiver

    expected group keys:
      "early|receiver|smash" (i偶数: smash * 3 + net_shot * 1)
      "early|receiver|clear" (i奇数: clear * 3 + net_shot * 1)
    """
    p_target = Player(name="ConformalTarget", dominant_hand="R")
    p_opp = Player(name="ConformalOpponent", dominant_hand="R")
    db.add(p_target)
    db.add(p_opp)
    db.flush()

    match = Match(
        tournament="CP Test",
        tournament_level="IC",
        round="R1",
        date=date(2025, 7, 1),
        format="singles",
        player_a_id=p_target.id,
        player_b_id=p_opp.id,
        result="win",
        annotation_status="complete",
        annotation_progress=1.0,
    )
    db.add(match)
    db.flush()

    gs = GameSet(
        match_id=match.id,
        set_num=1,
        winner="player_a",
        score_a=21,
        score_b=15,
    )
    db.add(gs)
    db.flush()

    for i in range(1, n_rallies + 1):
        # 偶数ラリー: smash グループ。奇数ラリー: clear グループ。
        # 勝敗: smash グループは 3/4 勝率、clear グループは 1/4 勝率
        if i % 2 == 0:
            dominant_shot = "smash"
            # 4 ラリーのうち 3 勝: i%8 in {0,2,4} → win, i%8==6 → loss
            winner = "player_a" if (i // 2) % 4 != 0 else "player_b"
        else:
            dominant_shot = "clear"
            # 4 ラリーのうち 1 勝: i%8==1 → win, others → loss
            winner = "player_a" if (i // 2) % 4 == 0 else "player_b"

        rally = Rally(
            set_id=gs.id,
            rally_num=i,
            server="player_b",          # target は receiver
            winner=winner,
            end_type="forced_error",
            rally_length=4,
            score_a_after=5,
            score_b_after=3,
        )
        db.add(rally)
        db.flush()

        # target (player_a) が dominant_shot を 3 本 + 相手が net_shot 1 本
        for snum in range(1, 4):
            st = Stroke(
                rally_id=rally.id,
                stroke_num=snum,
                player="player_a",
                shot_type=dominant_shot,
                hit_zone="BC",
                land_zone="NL",
                hit_y=0.2,
            )
            db.add(st)

        # 相手の応手 (stroke_num=4)
        opp_st = Stroke(
            rally_id=rally.id,
            stroke_num=4,
            player="player_b",
            shot_type="net_shot",
            hit_zone="NC",
            land_zone="BC",
            hit_y=0.8,
        )
        db.add(opp_st)

    db.flush()
    return p_target.id


# ── フィクスチャ ───────────────────────────────────────────────────────────────

@pytest.fixture
def conformal_client(db_session):
    """シードデータ付きの TestClient を返す。"""
    player_id = _seed_conformal_player(db_session, n_rallies=60)
    db_session.flush()

    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_auth] = _admin_ctx
    app.dependency_overrides[require_admin_or_analyst] = _admin_ctx
    app.dependency_overrides[require_non_player] = _admin_ctx

    client = TestClient(app)
    yield client, player_id
    app.dependency_overrides.clear()


# ── テストケース ──────────────────────────────────────────────────────────────

class TestConformalEndpoint:

    def test_returns_200_success(self, conformal_client):
        """エンドポイントが 200 を返し success=True であること。"""
        client, player_id = conformal_client
        resp = client.get(f"/api/analysis/conformal?player_id={player_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True

    def test_response_has_required_keys(self, conformal_client):
        """レスポンスに必須フィールドが含まれること。"""
        client, player_id = conformal_client
        resp = client.get(f"/api/analysis/conformal?player_id={player_id}")
        body = resp.json()
        data = body["data"]
        assert "alpha" in data
        assert "target_coverage" in data
        assert "n_total" in data
        assert "n_calibration" in data
        assert "n_test" in data
        assert "empirical_coverage" in data
        assert "avg_set_size" in data
        assert "per_group" in data
        assert "validation" in data
        meta = body["meta"]
        assert "sample_size" in meta
        assert "confidence" in meta
        assert meta["analysis_type"] == "conformal"
        assert meta["tier"] == "research"
        assert meta["evidence_level"] == "exploratory"

    def test_coverage_close_to_target(self, conformal_client):
        """経験的被覆率が target_coverage - 0.15 以上であること (有限サンプル許容)。"""
        client, player_id = conformal_client
        resp = client.get(f"/api/analysis/conformal?player_id={player_id}&alpha=0.1")
        body = resp.json()
        data = body["data"]
        # 十分なサンプルがある場合のみ確認
        if data.get("status") == "insufficient":
            pytest.skip("サンプル不足のためスキップ")
        empirical = data["empirical_coverage"]
        target = data["target_coverage"]
        assert empirical is not None
        assert empirical >= target - 0.15, (
            f"経験的被覆率 {empirical:.4f} が目標 {target:.4f} - 0.15 未満です"
        )

    def test_per_group_non_empty(self, conformal_client):
        """per_group が空でないこと (グループ別予測集合が存在する)。"""
        client, player_id = conformal_client
        resp = client.get(f"/api/analysis/conformal?player_id={player_id}")
        body = resp.json()
        data = body["data"]
        if data.get("status") == "insufficient":
            pytest.skip("サンプル不足のためスキップ")
        per_group = data["per_group"]
        assert len(per_group) > 0

    def test_per_group_has_prediction_set(self, conformal_client):
        """per_group の各エントリに prediction_set が含まれること。"""
        client, player_id = conformal_client
        resp = client.get(f"/api/analysis/conformal?player_id={player_id}")
        body = resp.json()
        data = body["data"]
        if data.get("status") == "insufficient":
            pytest.skip("サンプル不足のためスキップ")
        for entry in data["per_group"]:
            assert "prediction_set" in entry
            assert isinstance(entry["prediction_set"], list)
            # 集合は win / loss のサブセット
            for label in entry["prediction_set"]:
                assert label in ("win", "loss")

    def test_alpha_parameter_changes_target_coverage(self, conformal_client):
        """alpha=0.2 にすると target_coverage=0.8 になること。"""
        client, player_id = conformal_client
        resp = client.get(f"/api/analysis/conformal?player_id={player_id}&alpha=0.2")
        body = resp.json()
        data = body["data"]
        assert abs(data["alpha"] - 0.2) < 1e-9
        assert abs(data["target_coverage"] - 0.8) < 1e-6

    def test_n_total_is_positive(self, conformal_client):
        """シードデータがある場合 n_total > 0 であること。"""
        client, player_id = conformal_client
        resp = client.get(f"/api/analysis/conformal?player_id={player_id}")
        body = resp.json()
        assert body["data"]["n_total"] > 0

    def test_empty_player_returns_insufficient(self, db_session):
        """データなし選手に対してグレースフルに insufficient を返すこと。"""
        empty_player = Player(name="EmptyConformal", dominant_hand="R")
        db_session.add(empty_player)
        db_session.flush()
        empty_pid = empty_player.id

        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_auth] = _admin_ctx
        app.dependency_overrides[require_admin_or_analyst] = _admin_ctx
        app.dependency_overrides[require_non_player] = _admin_ctx
        try:
            client = TestClient(app)
            resp = client.get(f"/api/analysis/conformal?player_id={empty_pid}")
            assert resp.status_code == 200
            body = resp.json()
            assert body["success"] is True
            data = body["data"]
            assert data["status"] == "insufficient"
            assert data["per_group"] == []
            assert data["empirical_coverage"] is None
            assert data["n_total"] == 0
        finally:
            app.dependency_overrides.clear()

    def test_validation_field_present(self, conformal_client):
        """validation フィールドに coverage_guarantee_met が含まれること。"""
        client, player_id = conformal_client
        resp = client.get(f"/api/analysis/conformal?player_id={player_id}")
        body = resp.json()
        data = body["data"]
        if data.get("status") == "insufficient":
            pytest.skip("サンプル不足のためスキップ")
        assert "coverage_guarantee_met" in data["validation"]
