"""研究系解析エンドポイントのテスト
対象: pair_synergy, opponent_adaptive_shots, rally_sequence_patterns,
      confidence_calibration, counterfactual_shots, spatial_density,
      opponent_type_affinity
"""
import pytest
from fastapi.testclient import TestClient
from datetime import date

from backend.main import app
from backend.db.database import get_db
from backend.db.models import Player, Match, GameSet, Rally, Stroke
from backend.utils.auth import (
    AuthCtx,
    get_auth,
    require_admin_or_analyst,
    require_non_player,
)


def _admin_auth_ctx() -> AuthCtx:
    """テスト用の admin AuthCtx (router-level Depends 差し替え用)."""
    return AuthCtx(role="admin", player_id=None, user_id=1, team_name=None, team_id=None)


def _make_player(db, name, hand="R"):
    p = Player(name=name, dominant_hand=hand)
    db.add(p)
    db.flush()
    return p


def _make_match(db, pa, pb, result="win", level="IC", match_date=None, partner_a=None, partner_b=None):
    m = Match(
        tournament="テスト大会",
        tournament_level=level,
        round="1回戦",
        date=match_date or date(2025, 1, 10),
        format="singles" if not partner_a else "doubles",
        player_a_id=pa.id,
        player_b_id=pb.id,
        partner_a_id=partner_a.id if partner_a else None,
        partner_b_id=partner_b.id if partner_b else None,
        result=result,
        annotation_status="complete",
    )
    db.add(m)
    db.flush()
    return m


def _make_rallies(db, match, n=12, avg_len=7):
    gs = GameSet(match_id=match.id, set_num=1, winner="player_a", score_a=21, score_b=15)
    db.add(gs)
    db.flush()
    sa, sb = 0, 0
    for i in range(1, n + 1):
        winner = "player_a" if i % 3 != 0 else "player_b"
        if winner == "player_a":
            sa += 1
        else:
            sb += 1
        r = Rally(set_id=gs.id, rally_num=i, server="player_a",
                  winner=winner, end_type="forced_error",
                  rally_length=avg_len, score_a_after=sa, score_b_after=sb)
        db.add(r)
        db.flush()
        shot_types = ["clear", "smash", "defensive", "net_shot", "clear"]
        for j in range(1, avg_len + 1):
            player = "player_a" if j % 2 == 1 else "player_b"
            s = Stroke(
                rally_id=r.id,
                stroke_num=j,
                player=player,
                shot_type=shot_types[(j - 1) % len(shot_types)],
                hit_zone="BC",
                land_zone="NL",
                hit_x=0.5,
                hit_y=0.2 if player == "player_a" else 0.8,
                land_x=0.5,
                land_y=0.8 if player == "player_a" else 0.2,
            )
            db.add(s)
        db.flush()
    return gs


@pytest.fixture
def research_client(db_session):
    pa = _make_player(db_session, "研究選手A")
    partner = _make_player(db_session, "パートナー")
    opp1 = _make_player(db_session, "相手1")
    opp2 = _make_player(db_session, "相手2")

    m1 = _make_match(db_session, pa, opp1, result="win")
    _make_rallies(db_session, m1, n=15, avg_len=5)
    m2 = _make_match(db_session, pa, opp2, result="loss", level="SJL",
                     match_date=date(2025, 3, 1))
    _make_rallies(db_session, m2, n=12, avg_len=12)
    m3 = _make_match(db_session, pa, opp1, result="win", level="IC",
                     match_date=date(2025, 6, 1))
    _make_rallies(db_session, m3, n=10, avg_len=7)

    # ダブルス試合
    m_d = _make_match(db_session, pa, opp1, result="win",
                      partner_a=partner, match_date=date(2025, 2, 1))
    _make_rallies(db_session, m_d, n=10)

    db_session.flush()

    app.dependency_overrides[get_db] = lambda: db_session
    # research / advanced tier の router-level Depends を bypass
    # (700e3dd で player role bypass 防御として require_admin_or_analyst を導入したため)
    app.dependency_overrides[get_auth] = _admin_auth_ctx
    app.dependency_overrides[require_admin_or_analyst] = _admin_auth_ctx
    app.dependency_overrides[require_non_player] = _admin_auth_ctx
    client = TestClient(app)
    yield client, pa.id, partner.id, opp1.id, m1.id
    app.dependency_overrides.clear()


class TestOpponentTypeAffinity:
    def test_returns_200(self, research_client):
        client, pid, *_ = research_client
        resp = client.get(f"/api/analysis/opponent_type_affinity?player_id={pid}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "affinity" in body["data"]
        assert "summary" in body["data"]

    def test_summary_includes_wins_field(self, research_client):
        """summary の各エントリに wins フィールドが含まれること（バグ修正確認）"""
        client, pid, *_ = research_client
        resp = client.get(f"/api/analysis/opponent_type_affinity?player_id={pid}")
        summary = resp.json()["data"]["summary"]
        for entry in summary:
            assert "wins" in entry
            assert isinstance(entry["wins"], int)
            assert entry["wins"] >= 0
            assert entry["wins"] <= entry["match_count"]

    def test_empty_player_returns_empty(self, research_client):
        client, *_ = research_client
        resp = client.get("/api/analysis/opponent_type_affinity?player_id=999999")
        assert resp.status_code == 200
        assert resp.json()["data"]["summary"] == []


class TestPairSynergy:
    def test_returns_200(self, research_client):
        client, pid, *_ = research_client
        resp = client.get(f"/api/analysis/pair_synergy?player_id={pid}")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_has_meta_sample_size(self, research_client):
        client, pid, *_ = research_client
        resp = client.get(f"/api/analysis/pair_synergy?player_id={pid}")
        assert "sample_size" in resp.json()["meta"]

    def test_empty_player_no_crash(self, research_client):
        client, *_ = research_client
        resp = client.get("/api/analysis/pair_synergy?player_id=999999")
        assert resp.status_code == 200


class TestOpponentAdaptiveShots:
    def test_returns_200(self, research_client):
        client, pid, _, opp_id, *_ = research_client
        resp = client.get(f"/api/analysis/opponent_adaptive_shots?player_id={pid}")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_has_required_fields(self, research_client):
        client, pid, *_ = research_client
        resp = client.get(f"/api/analysis/opponent_adaptive_shots?player_id={pid}")
        body = resp.json()
        assert "meta" in body
        assert "sample_size" in body["meta"]


class TestRallySequencePatterns:
    def test_returns_200(self, research_client):
        client, pid, *_ = research_client
        resp = client.get(f"/api/analysis/rally_sequence_patterns?player_id={pid}")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_patterns_are_list(self, research_client):
        client, pid, *_ = research_client
        resp = client.get(f"/api/analysis/rally_sequence_patterns?player_id={pid}")
        data = resp.json()["data"]
        assert isinstance(data, (list, dict))


class TestConfidenceCalibration:
    def test_returns_200(self, research_client):
        client, pid, *_ = research_client
        resp = client.get(f"/api/analysis/confidence_calibration?player_id={pid}")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


class TestCounterfactualShots:
    def test_returns_200(self, research_client):
        client, pid, *_ = research_client
        resp = client.get(f"/api/analysis/counterfactual_shots?player_id={pid}")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_has_meta(self, research_client):
        client, pid, *_ = research_client
        resp = client.get(f"/api/analysis/counterfactual_shots?player_id={pid}")
        assert "meta" in resp.json()

    def test_empty_player_no_crash(self, research_client):
        client, *_ = research_client
        resp = client.get("/api/analysis/counterfactual_shots?player_id=999999")
        assert resp.status_code == 200


class TestSpatialDensity:
    def test_returns_200(self, research_client):
        client, pid, *_ = research_client
        resp = client.get(f"/api/analysis/spatial_density?player_id={pid}")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_has_grid(self, research_client):
        client, pid, *_ = research_client
        resp = client.get(f"/api/analysis/spatial_density?player_id={pid}")
        data = resp.json()["data"]
        assert "grid" in data
        assert "grid_width" in data
        assert "grid_height" in data
