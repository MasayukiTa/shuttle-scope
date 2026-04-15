"""新しい解析エンドポイントのテスト"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from datetime import date

from backend.main import app
from backend.db.database import get_db
from backend.db.models import Player, Match, GameSet, Rally, Stroke


def make_test_player(db: Session, name: str = "テスト選手") -> Player:
    """テスト用プレイヤーを作成する"""
    player = Player(name=name, dominant_hand="R")
    db.add(player)
    db.flush()
    return player


def make_test_match(
    db: Session,
    player_a: Player,
    player_b: Player,
    result: str = "win",
    match_format: str = "singles",
    tournament_level: str = "IC",
) -> Match:
    """テスト用試合を作成する"""
    match = Match(
        tournament="テスト大会",
        tournament_level=tournament_level,
        round="1回戦",
        date=date(2025, 1, 1),
        format=match_format,
        player_a_id=player_a.id,
        player_b_id=player_b.id,
        result=result,
        annotation_status="complete",
        annotation_progress=1.0,
    )
    db.add(match)
    db.flush()
    return match


def make_test_set_and_rallies(
    db: Session,
    match: Match,
    set_num: int = 1,
    n_rallies: int = 10,
) -> GameSet:
    """テスト用セット・ラリーを作成する"""
    game_set = GameSet(
        match_id=match.id,
        set_num=set_num,
        winner="player_a",
        score_a=21,
        score_b=15,
    )
    db.add(game_set)
    db.flush()

    score_a = 0
    score_b = 0
    for i in range(1, n_rallies + 1):
        winner = "player_a" if i % 2 == 0 else "player_b"
        if winner == "player_a":
            score_a += 1
        else:
            score_b += 1

        rally = Rally(
            set_id=game_set.id,
            rally_num=i,
            server="player_a",
            winner=winner,
            end_type="forced_error",
            rally_length=5,
            score_a_after=score_a,
            score_b_after=score_b,
        )
        db.add(rally)
        db.flush()

        # ストローク追加
        for j in range(1, 6):
            player = "player_a" if j % 2 == 1 else "player_b"
            stroke = Stroke(
                rally_id=rally.id,
                stroke_num=j,
                player=player,
                shot_type="smash" if j == 1 else "defensive",
                hit_zone="BC",
                land_zone="NL",
                hit_y=0.2 if player == "player_a" else 0.8,
            )
            db.add(stroke)

    db.flush()
    return game_set


@pytest.fixture
def client_with_data(db_session):
    """テストデータ付きのHTTPクライアントを返す"""
    # テストデータ作成
    player_a = make_test_player(db_session, "山田太郎")
    player_b = make_test_player(db_session, "佐藤次郎")

    match = make_test_match(db_session, player_a, player_b, result="win")
    make_test_set_and_rallies(db_session, match, n_rallies=15)

    match2 = make_test_match(db_session, player_a, player_b, result="loss", tournament_level="SJL")
    make_test_set_and_rallies(db_session, match2, n_rallies=12)

    db_session.flush()

    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)
    yield client, player_a.id, match.id
    app.dependency_overrides.clear()


class TestNewAnalysisEndpoints:
    """新しい解析エンドポイントの結合テスト"""

    def test_score_progression_returns_200(self, client_with_data):
        """score_progression が200を返すこと"""
        client, player_id, match_id = client_with_data
        resp = client.get(f"/api/analysis/score_progression?match_id={match_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "sets" in data["data"]

    def test_win_loss_comparison_returns_200(self, client_with_data):
        """win_loss_comparison が200を返すこと"""
        client, player_id, _ = client_with_data
        resp = client.get(f"/api/analysis/win_loss_comparison?player_id={player_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "meta" in data
        assert "sample_size" in data["meta"]
        assert "confidence" in data["meta"]

    def test_tournament_level_comparison_returns_200(self, client_with_data):
        """tournament_level_comparison が200を返すこと"""
        client, player_id, _ = client_with_data
        resp = client.get(f"/api/analysis/tournament_level_comparison?player_id={player_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "levels" in data["data"]

    def test_pre_loss_patterns_returns_200(self, client_with_data):
        """pre_loss_patterns が200を返すこと"""
        client, player_id, _ = client_with_data
        resp = client.get(f"/api/analysis/pre_loss_patterns?player_id={player_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "pre_loss_1" in data["data"]
        assert "pre_loss_2" in data["data"]
        assert "pre_loss_3" in data["data"]

    def test_bundle_review_returns_all_cards(self, client_with_data):
        """振り返りタブ bundle が 6 カード分のデータを返すこと"""
        client, player_id, _ = client_with_data
        resp = client.get(f"/api/analysis/bundle/review?player_id={player_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        data = body["data"]
        for key in [
            "pre_loss_patterns",
            "pre_win_patterns",
            "effective_distribution_map",
            "received_vulnerability",
            "set_comparison",
            "rally_sequence_patterns",
        ]:
            assert key in data
        plp = data["pre_loss_patterns"]
        assert plp is not None
        assert plp["success"] is True
        assert "pre_loss_1" in plp["data"]

    def test_first_return_analysis_returns_200(self, client_with_data):
        """first_return_analysis が200を返すこと"""
        client, player_id, _ = client_with_data
        resp = client.get(f"/api/analysis/first_return_analysis?player_id={player_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "zones" in data["data"]

    def test_temporal_performance_returns_200(self, client_with_data):
        """temporal_performance が200を返すこと"""
        client, player_id, _ = client_with_data
        resp = client.get(f"/api/analysis/temporal_performance?player_id={player_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "phases" in data["data"]
        assert len(data["data"]["phases"]) == 3  # 序盤/中盤/終盤

    def test_post_long_rally_stats_returns_200(self, client_with_data):
        """post_long_rally_stats が200を返すこと"""
        client, player_id, _ = client_with_data
        resp = client.get(f"/api/analysis/post_long_rally_stats?player_id={player_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "normal" in data["data"]
        assert "post_long" in data["data"]
        assert "diff_win_rate" in data["data"]

    def test_opponent_stats_returns_200(self, client_with_data):
        """opponent_stats が200を返すこと"""
        client, player_id, _ = client_with_data
        resp = client.get(f"/api/analysis/opponent_stats?player_id={player_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "opponents" in data["data"]

    def test_epv_returns_200(self, client_with_data):
        """EPV endpoint が200を返すこと"""
        client, player_id, _ = client_with_data
        resp = client.get(f"/api/analysis/epv?player_id={player_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "top_patterns" in data["data"]
        assert "bottom_patterns" in data["data"]

    def test_interval_report_returns_200(self, client_with_data):
        """interval_report が200を返すこと"""
        client, _, match_id = client_with_data
        resp = client.get(f"/api/analysis/interval_report?match_id={match_id}&completed_set_num=1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "meta" in data
        assert "sample_size" in data["meta"]

    def test_zone_detail_returns_200(self, client_with_data):
        """zone_detail が200を返すこと"""
        client, player_id, _ = client_with_data
        resp = client.get(f"/api/analysis/zone_detail?player_id={player_id}&zone=BC&type=hit")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "zone" in data["data"]

    def test_partner_comparison_returns_200(self, client_with_data):
        """partner_comparison が200を返すこと（ダブルス試合なし）"""
        client, player_id, _ = client_with_data
        resp = client.get(f"/api/analysis/partner_comparison?player_id={player_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "partners" in data["data"]

    def test_stroke_sharing_returns_200(self, client_with_data):
        """stroke_sharing が200を返すこと"""
        client, player_id, _ = client_with_data
        resp = client.get(f"/api/analysis/stroke_sharing?player_id={player_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True


class TestEmptyDataHandling:
    """空データでのエンドポイントの動作テスト"""

    def test_score_progression_empty_match(self, client_with_data):
        """存在しないmatch_idでもクラッシュしないこと"""
        client, _, _ = client_with_data
        resp = client.get("/api/analysis/score_progression?match_id=99999")
        assert resp.status_code == 200

    def test_all_player_endpoints_with_no_data(self, client_with_data):
        """試合のないプレイヤーIDでの全エンドポイントテスト（存在しないplayer_id）"""
        client, _, _ = client_with_data

        endpoints = [
            "/api/analysis/win_loss_comparison?player_id=99999",
            "/api/analysis/tournament_level_comparison?player_id=99999",
            "/api/analysis/pre_loss_patterns?player_id=99999",
            "/api/analysis/first_return_analysis?player_id=99999",
            "/api/analysis/temporal_performance?player_id=99999",
            "/api/analysis/post_long_rally_stats?player_id=99999",
            "/api/analysis/opponent_stats?player_id=99999",
            "/api/analysis/epv?player_id=99999",
            "/api/analysis/partner_comparison?player_id=99999",
            "/api/analysis/stroke_sharing?player_id=99999",
            "/api/analysis/doubles_serve_receive?player_id=99999",
            "/api/analysis/zone_detail?player_id=99999&zone=BC&type=hit",
        ]

        for endpoint in endpoints:
            resp = client.get(endpoint)
            assert resp.status_code == 200, f"エンドポイント {endpoint} が200以外を返しました: {resp.status_code}"
            data = resp.json()
            assert "success" in data, f"エンドポイント {endpoint} のレスポンスに success がありません"

    def test_all_responses_have_meta_when_successful(self, db_session):
        """成功レスポンスに meta が含まれること"""
        player = make_test_player(db_session, "メタテスト")
        db_session.flush()

        app.dependency_overrides[get_db] = lambda: db_session
        client = TestClient(app)

        player_endpoints = [
            f"/api/analysis/win_loss_comparison?player_id={player.id}",
            f"/api/analysis/tournament_level_comparison?player_id={player.id}",
            f"/api/analysis/pre_loss_patterns?player_id={player.id}",
            f"/api/analysis/temporal_performance?player_id={player.id}",
            f"/api/analysis/opponent_stats?player_id={player.id}",
            f"/api/analysis/epv?player_id={player.id}",
        ]

        try:
            for endpoint in player_endpoints:
                resp = client.get(endpoint)
                data = resp.json()
                if data.get("success"):
                    assert "meta" in data, f"{endpoint}: meta がありません"
                    assert "sample_size" in data["meta"], f"{endpoint}: sample_size がありません"
                    assert "confidence" in data["meta"], f"{endpoint}: confidence がありません"
        finally:
            app.dependency_overrides.clear()
