"""
test_stage2_engines.py — Stage 2 エンジンのユニットテスト

対象:
  - backend.analysis.recommendation_engine  (Stage 2-A)
  - backend.analysis.growth_engine           (Stage 2-B)
  - backend.analysis.opponent_classifier     (Stage 2-C)
"""
import math
import pytest
from unittest.mock import MagicMock, patch


# ──────────────────────────────────────────────────────────────────────────────
# Stage 2-A: recommendation_engine
# ──────────────────────────────────────────────────────────────────────────────

class TestRecommendationEngine:
    """recommendation_engine.py のユニットテスト"""

    # ── compute_player_baseline ─────────────────────────────────────────────

    def _make_rally(self, set_id, winner):
        r = MagicMock()
        r.set_id = set_id
        r.winner = winner
        return r

    def test_baseline_all_wins(self):
        from backend.analysis.recommendation_engine import compute_player_baseline
        rallies = [self._make_rally(1, "player_a") for _ in range(10)]
        role_by_match = {1: "player_a"}
        set_to_match = {1: 1}
        result = compute_player_baseline(rallies, role_by_match, set_to_match)
        assert result == 1.0

    def test_baseline_all_losses(self):
        from backend.analysis.recommendation_engine import compute_player_baseline
        rallies = [self._make_rally(1, "player_b") for _ in range(10)]
        role_by_match = {1: "player_a"}
        set_to_match = {1: 1}
        result = compute_player_baseline(rallies, role_by_match, set_to_match)
        assert result == 0.0

    def test_baseline_half_wins(self):
        from backend.analysis.recommendation_engine import compute_player_baseline
        rallies = (
            [self._make_rally(1, "player_a") for _ in range(5)]
            + [self._make_rally(1, "player_b") for _ in range(5)]
        )
        role_by_match = {1: "player_a"}
        set_to_match = {1: 1}
        result = compute_player_baseline(rallies, role_by_match, set_to_match)
        assert result == 0.5

    def test_baseline_empty_rallies(self):
        from backend.analysis.recommendation_engine import compute_player_baseline
        result = compute_player_baseline([], {}, {})
        assert result == 0.5

    def test_baseline_unknown_set(self):
        """set_to_match に存在しない set_id は無視される"""
        from backend.analysis.recommendation_engine import compute_player_baseline
        rallies = [self._make_rally(99, "player_a") for _ in range(5)]
        role_by_match = {1: "player_a"}
        set_to_match = {}  # 99 → None → skip
        result = compute_player_baseline(rallies, role_by_match, set_to_match)
        assert result == 0.5  # データなし → fallback

    # ── score_recommendation_item ────────────────────────────────────────────

    def test_score_zero_count(self):
        from backend.analysis.recommendation_engine import score_recommendation_item
        assert score_recommendation_item(0, 0, 0.5) == 0.0

    def test_score_high_effect(self):
        from backend.analysis.recommendation_engine import score_recommendation_item
        # n=100, wins=80, baseline=0.5 → effect=0.3
        score = score_recommendation_item(100, 80, 0.5, norm_n=300.0)
        expected = round(math.log(101) / math.log(301) * 0.3, 4)
        assert abs(score - expected) < 1e-4

    def test_score_below_baseline(self):
        """ベースライン以下でも effect = |wr - baseline| で正のスコア"""
        from backend.analysis.recommendation_engine import score_recommendation_item
        score = score_recommendation_item(50, 10, 0.5, norm_n=300.0)
        assert score > 0.0

    # ── build_recommendation_item ────────────────────────────────────────────

    def test_build_item_below_min_samples(self):
        from backend.analysis.recommendation_engine import build_recommendation_item
        result = build_recommendation_item("shot", "smash", "スマッシュ", 3, 2, 0.5, min_samples=5)
        assert result is None

    def test_build_item_above_baseline(self):
        from backend.analysis.recommendation_engine import build_recommendation_item
        item = build_recommendation_item("shot", "smash", "スマッシュ", 50, 40, 0.5)
        assert item is not None
        assert item["category"] == "shot"
        assert item["key"] == "smash"
        assert item["win_rate"] == 0.8
        assert item["delta_from_baseline"] == round(0.8 - 0.5, 3)
        assert "継続強化" in item["title"]

    def test_build_item_below_baseline(self):
        from backend.analysis.recommendation_engine import build_recommendation_item
        item = build_recommendation_item("zone", "NL", "左前エリア", 30, 9, 0.5)
        assert item is not None
        assert item["win_rate"] == 0.3
        assert "改善余地" in item["title"] or "伸びしろ" in item["body"]

    def test_build_item_confidence_levels(self):
        from backend.analysis.recommendation_engine import build_recommendation_item
        low = build_recommendation_item("shot", "drive", "ドライブ", 10, 7, 0.5)
        mid = build_recommendation_item("shot", "drive", "ドライブ", 50, 35, 0.5)
        high = build_recommendation_item("shot", "drive", "ドライブ", 150, 105, 0.5)
        assert low["confidence_level"] == "★"
        assert mid["confidence_level"] == "★★"
        assert high["confidence_level"] == "★★★"

    # ── rank_recommendations ─────────────────────────────────────────────────

    def test_rank_sorted_by_score(self):
        from backend.analysis.recommendation_engine import rank_recommendations
        items = [
            {"priority_score": 0.1, "title": "A"},
            {"priority_score": 0.5, "title": "B"},
            {"priority_score": 0.3, "title": "C"},
        ]
        ranked = rank_recommendations(items, top_n=3)
        assert ranked[0]["rank"] == 1
        assert ranked[0]["title"] == "B"
        assert ranked[1]["title"] == "C"
        assert ranked[2]["title"] == "A"

    def test_rank_top_n_limit(self):
        from backend.analysis.recommendation_engine import rank_recommendations
        items = [{"priority_score": float(i), "title": str(i)} for i in range(10)]
        ranked = rank_recommendations(items, top_n=5)
        assert len(ranked) == 5


# ──────────────────────────────────────────────────────────────────────────────
# Stage 2-B: growth_engine
# ──────────────────────────────────────────────────────────────────────────────

class TestGrowthEngine:
    """growth_engine.py のユニットテスト"""

    # ── compute_opponent_strength ────────────────────────────────────────────

    def _make_player(self, world_ranking=None):
        p = MagicMock()
        p.world_ranking = world_ranking
        return p

    def _make_match_result(self, player_a_id, player_b_id, result):
        m = MagicMock()
        m.player_a_id = player_a_id
        m.player_b_id = player_b_id
        m.result = result
        return m

    def test_strength_rank_1(self):
        from backend.analysis.growth_engine import compute_opponent_strength
        db = MagicMock()
        db.get.return_value = self._make_player(world_ranking=1)
        db.query.return_value.filter.return_value.all.return_value = []
        assert compute_opponent_strength(db, 1) == 1.0

    def test_strength_rank_500(self):
        from backend.analysis.growth_engine import compute_opponent_strength
        db = MagicMock()
        db.get.return_value = self._make_player(world_ranking=500)
        db.query.return_value.filter.return_value.all.return_value = []
        assert compute_opponent_strength(db, 1) == 0.0

    def test_strength_rank_250_approx(self):
        from backend.analysis.growth_engine import compute_opponent_strength
        db = MagicMock()
        db.get.return_value = self._make_player(world_ranking=250)
        db.query.return_value.filter.return_value.all.return_value = []
        s = compute_opponent_strength(db, 1)
        assert 0.49 < s < 0.51

    def test_strength_no_ranking_fallback_to_win_rate(self):
        from backend.analysis.growth_engine import compute_opponent_strength
        db = MagicMock()
        db.get.return_value = self._make_player(world_ranking=None)
        # 5試合中3勝（player_a として）
        matches = [
            self._make_match_result(99, 1, "win"),
            self._make_match_result(99, 1, "win"),
            self._make_match_result(99, 1, "win"),
            self._make_match_result(99, 1, "loss"),
            self._make_match_result(99, 1, "loss"),
        ]
        db.query.return_value.filter.return_value.all.return_value = matches
        s = compute_opponent_strength(db, 99)
        assert s == 0.6

    def test_strength_insufficient_matches(self):
        """試合数 < 3 のときは 0.5 を返す"""
        from backend.analysis.growth_engine import compute_opponent_strength
        db = MagicMock()
        db.get.return_value = self._make_player(world_ranking=None)
        db.query.return_value.filter.return_value.all.return_value = [
            self._make_match_result(99, 1, "win"),
            self._make_match_result(99, 1, "loss"),
        ]
        assert compute_opponent_strength(db, 99) == 0.5

    # ── weighted_win_rate ────────────────────────────────────────────────────

    def _make_match_with_role(self, player_a_id, player_b_id, result):
        m = MagicMock()
        m.player_a_id = player_a_id
        m.player_b_id = player_b_id
        m.result = result
        return m

    def test_weighted_win_rate_all_win(self):
        from backend.analysis.growth_engine import weighted_win_rate
        player_id = 1
        matches = [self._make_match_with_role(1, 2, "win") for _ in range(3)]
        cache = {2: 0.8}
        result = weighted_win_rate(matches, player_id, cache)
        assert result == 1.0

    def test_weighted_win_rate_all_loss(self):
        from backend.analysis.growth_engine import weighted_win_rate
        player_id = 1
        matches = [self._make_match_with_role(1, 2, "loss") for _ in range(3)]
        cache = {2: 0.6}
        result = weighted_win_rate(matches, player_id, cache)
        assert result == 0.0

    def test_weighted_win_rate_empty(self):
        from backend.analysis.growth_engine import weighted_win_rate
        result = weighted_win_rate([], 1, {})
        assert result is None

    # ── strength_weighted_moving_avg ─────────────────────────────────────────

    def test_moving_avg_window_3(self):
        from backend.analysis.growth_engine import strength_weighted_moving_avg
        points = [
            {"match_id": i, "date": "2024-01-01", "value": float(i), "strength_weight": 0.5, "opponent_id": 2}
            for i in range(1, 6)
        ]
        result = strength_weighted_moving_avg(points, window_size=3)
        # i=2 (index 2): window=[1,2,3] → avg=2.0
        assert result[2]["moving_avg"] == 2.0
        assert result[0]["moving_avg"] is None
        assert result[1]["moving_avg"] is None

    def test_moving_avg_fields_present(self):
        from backend.analysis.growth_engine import strength_weighted_moving_avg
        points = [
            {"match_id": i, "date": "2024-01-01", "value": 0.5, "strength_weight": 0.7, "opponent_id": 2}
            for i in range(4)
        ]
        result = strength_weighted_moving_avg(points, window_size=3)
        for p in result:
            assert "moving_avg" in p
            assert "weighted_moving_avg" in p

    # ── compute_growth_trend ─────────────────────────────────────────────────

    def test_trend_improving(self):
        from backend.analysis.growth_engine import compute_growth_trend
        points = [
            {"value": 0.3 + i * 0.02, "weighted_moving_avg": 0.3 + i * 0.02}
            for i in range(8)
        ]
        result = compute_growth_trend(points, window_size=3, metric="win_rate", trend_delta=0.03)
        assert result["trend"] == "improving"

    def test_trend_declining(self):
        from backend.analysis.growth_engine import compute_growth_trend
        points = [
            {"value": 0.8 - i * 0.02, "weighted_moving_avg": 0.8 - i * 0.02}
            for i in range(8)
        ]
        result = compute_growth_trend(points, window_size=3, metric="win_rate", trend_delta=0.03)
        assert result["trend"] == "declining"

    def test_trend_pending_insufficient(self):
        from backend.analysis.growth_engine import compute_growth_trend
        points = [{"value": 0.5, "weighted_moving_avg": 0.5} for _ in range(3)]
        result = compute_growth_trend(points, window_size=3, metric="win_rate")
        assert result["trend"] == "pending"

    def test_trend_avg_rally_length_always_stable(self):
        from backend.analysis.growth_engine import compute_growth_trend
        points = [
            {"value": 5.0 + i, "weighted_moving_avg": 5.0 + i}
            for i in range(8)
        ]
        result = compute_growth_trend(points, window_size=3, metric="avg_rally_length")
        assert result["trend"] == "stable"

    def test_trend_has_weighted_fields(self):
        from backend.analysis.growth_engine import compute_growth_trend
        points = [{"value": 0.5, "weighted_moving_avg": 0.5} for _ in range(6)]
        result = compute_growth_trend(points, window_size=3, metric="win_rate")
        assert "weighted_trend" in result
        assert "weighted_trend_delta" in result


# ──────────────────────────────────────────────────────────────────────────────
# Stage 2-C: opponent_classifier
# ──────────────────────────────────────────────────────────────────────────────

class TestOpponentClassifier:
    """opponent_classifier.py のユニットテスト"""

    # ── classify_style ───────────────────────────────────────────────────────

    def test_classify_style_attacker(self):
        from backend.analysis.opponent_classifier import classify_style
        # avg_len=4 < 6, smash_rate=0.35 >= 0.30
        assert classify_style(4.0, 0.35) == "攻撃型"

    def test_classify_style_defender(self):
        from backend.analysis.opponent_classifier import classify_style
        # avg_len=12 >= 10
        assert classify_style(12.0, 0.05) == "守備型"

    def test_classify_style_balanced(self):
        from backend.analysis.opponent_classifier import classify_style
        assert classify_style(7.0, 0.15) == "バランス型"

    # ── classify_pace ────────────────────────────────────────────────────────

    def test_classify_pace_fast(self):
        from backend.analysis.opponent_classifier import classify_pace
        assert classify_pace(0.35) == "fast"

    def test_classify_pace_slow(self):
        from backend.analysis.opponent_classifier import classify_pace
        assert classify_pace(0.05) == "slow"

    def test_classify_pace_medium(self):
        from backend.analysis.opponent_classifier import classify_pace
        assert classify_pace(0.20) == "medium"

    # ── classify_rally_length ────────────────────────────────────────────────

    def test_classify_rally_length_short(self):
        from backend.analysis.opponent_classifier import classify_rally_length
        assert classify_rally_length(4.0) == "short"

    def test_classify_rally_length_long(self):
        from backend.analysis.opponent_classifier import classify_rally_length
        assert classify_rally_length(11.0) == "long"

    def test_classify_rally_length_medium(self):
        from backend.analysis.opponent_classifier import classify_rally_length
        assert classify_rally_length(7.0) == "medium"

    # ── classify_handedness ──────────────────────────────────────────────────

    def test_classify_handedness_right(self):
        from backend.analysis.opponent_classifier import classify_handedness
        db = MagicMock()
        p = MagicMock()
        p.dominant_hand = "R"
        db.get.return_value = p
        assert classify_handedness(db, 1) == "right"

    def test_classify_handedness_left(self):
        from backend.analysis.opponent_classifier import classify_handedness
        db = MagicMock()
        p = MagicMock()
        p.dominant_hand = "L"
        db.get.return_value = p
        assert classify_handedness(db, 1) == "left"

    def test_classify_handedness_unknown_when_none(self):
        from backend.analysis.opponent_classifier import classify_handedness
        db = MagicMock()
        db.get.return_value = None
        assert classify_handedness(db, 99) == "unknown"

    # ── classify_court_zone ──────────────────────────────────────────────────

    def test_classify_court_zone_front(self):
        from backend.analysis.opponent_classifier import classify_court_zone
        assert classify_court_zone(0.5) == "front"

    def test_classify_court_zone_rear(self):
        from backend.analysis.opponent_classifier import classify_court_zone
        assert classify_court_zone(0.1) == "rear"

    def test_classify_court_zone_balanced(self):
        from backend.analysis.opponent_classifier import classify_court_zone
        assert classify_court_zone(0.35) == "balanced"

    # ── aggregate_affinity_by_axis ───────────────────────────────────────────

    def _make_match(self, player_a_id, player_b_id, result):
        m = MagicMock()
        m.player_a_id = player_a_id
        m.player_b_id = player_b_id
        m.result = result
        return m

    def test_aggregate_affinity_basic(self):
        from backend.analysis.opponent_classifier import aggregate_affinity_by_axis
        player_id = 1
        # 相手 2 は "fast", 相手 3 は "slow"
        classified = {
            2: {"axes": {"pace": "fast"}},
            3: {"axes": {"pace": "slow"}},
        }
        matches = [
            self._make_match(1, 2, "win"),   # vs fast → 勝ち
            self._make_match(1, 2, "win"),   # vs fast → 勝ち
            self._make_match(1, 3, "loss"),  # vs slow → 負け
        ]
        result = aggregate_affinity_by_axis("pace", classified, matches, player_id)
        fast_entry = next(r for r in result if r["label"] == "fast")
        slow_entry = next(r for r in result if r["label"] == "slow")
        assert fast_entry["win_rate"] == 1.0
        assert fast_entry["match_count"] == 2
        assert slow_entry["win_rate"] == 0.0

    def test_aggregate_affinity_sorted_desc(self):
        from backend.analysis.opponent_classifier import aggregate_affinity_by_axis
        player_id = 1
        classified = {
            2: {"axes": {"handedness": "right"}},
            3: {"axes": {"handedness": "left"}},
        }
        matches = [
            self._make_match(1, 2, "win"),
            self._make_match(1, 3, "loss"),
        ]
        result = aggregate_affinity_by_axis("handedness", classified, matches, player_id)
        assert result[0]["win_rate"] >= result[-1]["win_rate"]
