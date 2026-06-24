"""test_policy_eval_endpoint.py — POL-001 DR-OPE policy_eval エンドポイントの結合テスト

テスト設計:
- dr_ope_loader は exploitability_loader を再利用するため、
  シードデータ構造は test_exploitability_endpoint.py と同一。
- 同一 score_phase|player_role 状態で smash → 勝ち / clear → 負け のパターンを
  n_rallies >= 20 で生成し、evaluate_state が uplift > 0 を返すことを検証する。
- 各ラリーに target(player_a) ストローク + opponent(player_b) 応手を持たせる
  (exploitability_loader はペアで記録するため応手も必要)。
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

def _seed_policy_player(db, n_rallies: int = 24):
    """
    対象選手 (player_a) が score_phase=early|player_role=receiver 状態で
    smash → 勝ち / clear → 負け を交互に持つデータを生成する。

    DR-OPE では uplift = V(π_target) - V(π_behavior) が計算される。
    smash 勝率 ≈ 1.0 / clear 勝率 ≈ 0.0 のとき、ソフトマックス方策は
    smash に集中するため uplift > 0 となる。

    exploitability_loader はストローク[i](player_a) + ストローク[i+1](player_b) の
    ペアで1レコードを生成するため、相手応手 (stroke_num=2) も必要。
    """
    p_target = Player(name="PolicyTarget", dominant_hand="R")
    p_opp = Player(name="PolicyOpponent", dominant_hand="R")
    db.add(p_target)
    db.add(p_opp)
    db.flush()

    match = Match(
        tournament="Policy Test",
        tournament_level="IC",
        round="QF",
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
        # 偶数: smash → 勝ち / 奇数: clear → 負け
        target_shot = "smash" if i % 2 == 0 else "clear"
        winner = "player_a" if i % 2 == 0 else "player_b"

        rally = Rally(
            set_id=gs.id,
            rally_num=i,
            # server=player_b → target は receiver
            server="player_b",
            winner=winner,
            end_type="forced_error",
            rally_length=4,
            # スコアを early phase (score_a_after <= 10) に固定して全レコードを1状態に集約
            score_a_after=5,
            score_b_after=3,
        )
        db.add(rally)
        db.flush()

        # target (player_a) のストローク — これが「行動 a」
        stroke_target = Stroke(
            rally_id=rally.id,
            stroke_num=1,
            player="player_a",
            shot_type=target_shot,
            hit_zone="BC",
            land_zone="NL",
            hit_y=0.2,
        )
        db.add(stroke_target)

        # 相手 (player_b) の応手 — これが「応手 b」(ペア成立に必要)
        stroke_opp = Stroke(
            rally_id=rally.id,
            stroke_num=2,
            player="player_b",
            shot_type="net_shot",
            hit_zone="NC",
            land_zone="BC",
            hit_y=0.8,
        )
        db.add(stroke_opp)

    db.flush()
    return p_target.id


# ── フィクスチャ ──────────────────────────────────────────────────────────────

@pytest.fixture
def policy_eval_client(db_session):
    """シードデータ付きの TestClient を返す。"""
    player_id = _seed_policy_player(db_session, n_rallies=24)
    db_session.flush()

    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_auth] = _admin_ctx
    app.dependency_overrides[require_admin_or_analyst] = _admin_ctx
    app.dependency_overrides[require_non_player] = _admin_ctx

    client = TestClient(app)
    yield client, player_id
    app.dependency_overrides.clear()


# ── テストケース ──────────────────────────────────────────────────────────────

class TestPolicyEvalEndpoint:

    def test_returns_200_with_success(self, policy_eval_client):
        """エンドポイントが 200 を返し success=True であること。"""
        client, player_id = policy_eval_client
        resp = client.get(f"/api/analysis/policy_eval?player_id={player_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True

    def test_response_has_required_keys(self, policy_eval_client):
        """レスポンスに states / summary / meta が含まれること。"""
        client, player_id = policy_eval_client
        resp = client.get(f"/api/analysis/policy_eval?player_id={player_id}")
        body = resp.json()
        assert "data" in body
        data = body["data"]
        assert "states" in data
        assert "summary" in data
        meta = body["meta"]
        assert "sample_size" in meta
        assert "confidence" in meta
        assert meta["analysis_type"] == "policy_eval"

    def test_at_least_one_state_ok_with_uplift(self, policy_eval_client):
        """十分なサンプルがある状態で status='ok' かつ ci_low <= ci_high の数値が返ること。"""
        client, player_id = policy_eval_client
        resp = client.get(f"/api/analysis/policy_eval?player_id={player_id}")
        body = resp.json()
        assert body["success"] is True
        states = body["data"]["states"]
        ok_states = [s for s in states if s["status"] == "ok"]
        assert len(ok_states) >= 1, (
            "十分なサンプルを持つ状態が少なくとも1つ ok になるはずです。"
            f" 全状態: {states}"
        )
        for s in ok_states:
            assert "uplift" in s, f"uplift キーが存在しない: {s}"
            assert isinstance(s["uplift"], (int, float)), f"uplift が数値でない: {s}"
            assert "ci_low" in s and "ci_high" in s, f"ci_low/ci_high キーが存在しない: {s}"
            assert s["ci_low"] <= s["ci_high"], (
                f"ci_low={s['ci_low']} > ci_high={s['ci_high']} (不正な CI)"
            )

    def test_summary_states_analyzed_positive(self, policy_eval_client):
        """サマリの states_analyzed が 1 以上であること。"""
        client, player_id = policy_eval_client
        resp = client.get(f"/api/analysis/policy_eval?player_id={player_id}")
        body = resp.json()
        summary = body["data"]["summary"]
        assert summary["states_analyzed"] >= 1

    def test_empty_player_returns_empty_gracefully(self, db_session):
        """データが存在しない player_id でも 200 空レスポンスが返ること。"""
        empty_player = Player(name="EmptyPolicy", dominant_hand="R")
        db_session.add(empty_player)
        db_session.flush()
        empty_pid = empty_player.id

        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_auth] = _admin_ctx
        app.dependency_overrides[require_admin_or_analyst] = _admin_ctx
        app.dependency_overrides[require_non_player] = _admin_ctx
        try:
            client = TestClient(app)
            resp = client.get(f"/api/analysis/policy_eval?player_id={empty_pid}")
            assert resp.status_code == 200
            body = resp.json()
            assert body["success"] is True
            assert body["data"]["states"] == []
            assert body["data"]["summary"]["states_analyzed"] == 0
        finally:
            app.dependency_overrides.clear()
