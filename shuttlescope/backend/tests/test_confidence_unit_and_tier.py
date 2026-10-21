"""check_confidence: 表示単位の n・tier・区間幅 / コンフォーマルのグループ規則 (監査 B4 / C5 / C6 / #50)"""
import pytest

from backend.utils.confidence import (
    check_confidence,
    VERDICT_MIN_SAMPLE,
    REFERENCE_LABEL,
    WIDE_INTERVAL_WIDTH,
)
from backend.analysis.confidence import calc_confidence

HIGH_LABEL = "高信頼（実用レベル）"


class TestUnitN:
    def test_whole_cohort_high_without_unit(self):
        # 従来どおり: 全体 53 件だけなら高信頼 (descriptive_basic は 10 件の 5 倍 = 50 から)
        assert check_confidence("descriptive_basic", 53)["level"] == "high"

    def test_pair_with_16_matches_is_not_high(self):
        # 全体 53 試合でもペアが 16 試合なら 16 で判定する
        c = check_confidence("descriptive_basic", 53, unit_n=16)
        assert c["level"] == "medium"
        assert c["label"] != HIGH_LABEL
        assert c["n_used"] == 16

    def test_unit_n_never_raises_confidence_above_total(self):
        c = check_confidence("descriptive_basic", 8, unit_n=100)
        assert c["n_used"] == 8
        assert c["level"] == "low"

    def test_tiny_unit_is_lowest_band(self):
        c = check_confidence("descriptive_basic", 53, unit_n=2)
        assert c["level"] == "low"
        assert "10件以上推奨" in c["warning"]


class TestTierCap:
    @pytest.mark.parametrize("n", [10, 50, 5000])
    def test_research_tier_is_capped_at_reference(self, n):
        c = check_confidence("descriptive_basic", n, tier="research")
        assert c["level"] == "low"
        assert c["stars"] == "★☆☆"
        assert c["label"] == REFERENCE_LABEL
        assert c["label"] != HIGH_LABEL
        assert c["capped_by"] == "tier"

    def test_exploratory_evidence_is_capped(self):
        c = check_confidence("descriptive_basic", 5000, evidence_level="exploratory")
        assert c["label"] == REFERENCE_LABEL

    def test_stable_and_advanced_are_not_capped(self):
        for tier in ("stable", "advanced", None):
            c = check_confidence("descriptive_basic", 5000, tier=tier)
            assert c["level"] == "high"
            assert "capped_by" not in c

    def test_research_with_tiny_sample_keeps_data_accumulating_label(self):
        c = check_confidence("descriptive_basic", 3, tier="research")
        assert c["level"] == "low"
        assert c["label"] != REFERENCE_LABEL
        assert "capped_by" not in c

    def test_research_with_pair_total_53_pair_16(self):
        c = check_confidence("descriptive_basic", 53, tier="research", unit_n=16)
        assert c["level"] == "low"
        assert c["label"] != HIGH_LABEL


class TestIntervalWidth:
    def test_wide_interval_is_capped_at_low(self):
        c = check_confidence("descriptive_basic", 100, interval_width=WIDE_INTERVAL_WIDTH + 0.01)
        assert c["level"] == "low"
        assert c["capped_by"] == "interval"

    def test_narrow_interval_keeps_level(self):
        c = check_confidence("descriptive_basic", 100, interval_width=0.1)
        assert c["level"] == "high"

    def test_interval_width_exactly_at_limit_is_allowed(self):
        c = check_confidence("descriptive_basic", 100, interval_width=WIDE_INTERVAL_WIDTH)
        assert c["level"] == "high"


class TestSingleImplementation:
    def test_calc_confidence_uses_same_labels_and_stroke_thresholds(self):
        assert calc_confidence(100)["level"] == "low"
        assert calc_confidence(499)["level"] == "low"
        assert calc_confidence(500)["level"] == "medium"
        assert calc_confidence(1999)["level"] == "medium"
        assert calc_confidence(2000)["level"] == "high"
        assert calc_confidence(2000)["label"] == HIGH_LABEL


class TestConformalGroupRule:
    def test_threshold_is_the_shared_verdict_minimum(self):
        from backend.routers.analysis_research import CONFORMAL_MIN_GROUP_N
        assert CONFORMAL_MIN_GROUP_N == VERDICT_MIN_SAMPLE

    def test_small_groups_get_no_winrate_or_chips(self, db_session):
        """n=2 のグループは p_win / prediction_set が null で insufficient=True。"""
        from datetime import date
        from fastapi.testclient import TestClient
        from backend.main import app
        from backend.db.database import get_db
        from backend.db.models import Player, Match, GameSet, Rally, Stroke
        from backend.utils.auth import (
            AuthCtx, get_auth, require_admin_or_analyst, require_non_player,
        )
        from backend.routers.analysis_research import CONFORMAL_MIN_GROUP_N

        p1 = Player(name="CGroupT", dominant_hand="R")
        p2 = Player(name="CGroupO", dominant_hand="R")
        db_session.add_all([p1, p2])
        db_session.flush()
        m = Match(
            tournament="CG", tournament_level="IC", round="R1", date=date(2025, 7, 1),
            format="singles", player_a_id=p1.id, player_b_id=p2.id, result="win",
            annotation_status="complete", annotation_progress=1.0,
        )
        db_session.add(m)
        db_session.flush()
        gs = GameSet(match_id=m.id, set_num=1, winner="player_a", score_a=21, score_b=15)
        db_session.add(gs)
        db_session.flush()
        # 大グループ (smash) 58 ラリー + 小グループ (clear) 2 ラリー
        for i in range(1, 61):
            shot = "clear" if i > 58 else "smash"
            winner = "player_a" if i % 3 else "player_b"
            r = Rally(
                set_id=gs.id, rally_num=i, server="player_b", winner=winner,
                end_type="forced_error", rally_length=4, score_a_after=5, score_b_after=3,
            )
            db_session.add(r)
            db_session.flush()
            for sn in range(1, 4):
                db_session.add(Stroke(
                    rally_id=r.id, stroke_num=sn, player="player_a", shot_type=shot,
                    hit_zone="BC", land_zone="NL", hit_y=0.2,
                ))
            db_session.add(Stroke(
                rally_id=r.id, stroke_num=4, player="player_b", shot_type="net_shot",
                hit_zone="NC", land_zone="BC", hit_y=0.8,
            ))
        db_session.commit()

        ctx = AuthCtx(role="admin", player_id=None, user_id=1, team_name=None, team_id=None)
        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_auth] = lambda: ctx
        app.dependency_overrides[require_admin_or_analyst] = lambda: ctx
        app.dependency_overrides[require_non_player] = lambda: ctx
        try:
            resp = TestClient(app).get(f"/api/analysis/conformal?player_id={p1.id}")
        finally:
            app.dependency_overrides.clear()
        body = resp.json()
        data = body["data"]
        assert data.get("status") != "insufficient"
        groups = {g["group"].split("|")[-1]: g for g in data["per_group"]}
        small, big = groups["clear"], groups["smash"]
        assert small["n"] == 2 < CONFORMAL_MIN_GROUP_N
        assert small["insufficient"] is True
        assert small["p_win"] is None and small["prediction_set"] is None
        assert big["insufficient"] is False
        assert isinstance(big["prediction_set"], list)
        # research 解析なので全体の信頼度も実用レベルにならない
        assert body["meta"]["confidence"]["label"] != HIGH_LABEL
