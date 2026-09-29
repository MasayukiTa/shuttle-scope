"""
test_stage3_engines.py — Stage 3 エンジンのユニットテスト

対象:
  - backend.analysis.counterfactual_engine  (Stage 3-A)
  - backend.analysis.epv_engine             (Stage 3-B)
"""
import pytest
from unittest.mock import MagicMock


# ──────────────────────────────────────────────────────────────────────────────
# Stage 3-A: counterfactual_engine
# ──────────────────────────────────────────────────────────────────────────────

class TestCounterfactualEngine:
    """counterfactual_engine.py のユニットテスト"""

    # ── classify_score_pressure ────────────────────────────────────────────

    def test_pressure_neutral(self):
        from backend.analysis.counterfactual_engine import classify_score_pressure
        assert classify_score_pressure(5, 7, True) == "neutral"

    def test_pressure_high_score(self):
        from backend.analysis.counterfactual_engine import classify_score_pressure
        assert classify_score_pressure(18, 15, True) == "pressure"

    def test_pressure_opponent_high(self):
        from backend.analysis.counterfactual_engine import classify_score_pressure
        assert classify_score_pressure(10, 19, True) == "pressure"

    def test_pressure_behind(self):
        from backend.analysis.counterfactual_engine import classify_score_pressure
        # my=5, opp=9 → diff=4 > 3 → behind
        assert classify_score_pressure(5, 9, True) == "behind"

    def test_pressure_behind_player_b(self):
        from backend.analysis.counterfactual_engine import classify_score_pressure
        # player_is_a=False → my=9, opp=5 → leading, not behind
        assert classify_score_pressure(5, 9, False) == "neutral"

    # ── classify_rally_phase ──────────────────────────────────────────────

    def test_phase_early(self):
        from backend.analysis.counterfactual_engine import classify_rally_phase
        assert classify_rally_phase(1) == "early"
        assert classify_rally_phase(3) == "early"

    def test_phase_mid(self):
        from backend.analysis.counterfactual_engine import classify_rally_phase
        assert classify_rally_phase(4) == "mid"
        assert classify_rally_phase(7) == "mid"

    def test_phase_late(self):
        from backend.analysis.counterfactual_engine import classify_rally_phase
        assert classify_rally_phase(8) == "late"
        assert classify_rally_phase(15) == "late"

    # ── build_context_key / build_simple_context_key ──────────────────────

    def test_build_context_key(self):
        from backend.analysis.counterfactual_engine import build_context_key
        key = build_context_key("smash", "pressure", "mid", "BL")
        assert key == ("smash", "pressure", "mid", "BL")

    def test_build_context_key_no_zone(self):
        from backend.analysis.counterfactual_engine import build_context_key
        key = build_context_key("smash", "neutral", "early", None)
        assert key == ("smash", "neutral", "early", "unknown")

    def test_build_simple_context_key(self):
        from backend.analysis.counterfactual_engine import build_simple_context_key
        key = build_simple_context_key("drop")
        assert key == ("drop",)

    # ── collect_context_stats ─────────────────────────────────────────────

    def _make_rally(self, rally_id, set_id, winner, score_a=5, score_b=5):
        r = MagicMock()
        r.id = rally_id
        r.set_id = set_id
        r.winner = winner
        r.score_a_before = score_a
        r.score_b_before = score_b
        r.rally_num = rally_id
        return r

    def _make_stroke(self, player, shot_type, stroke_num, land_zone=None):
        s = MagicMock()
        s.player = player
        s.shot_type = shot_type
        s.stroke_num = stroke_num
        s.land_zone = land_zone
        return s

    def test_collect_context_stats_basic(self):
        from backend.analysis.counterfactual_engine import collect_context_stats
        rallies = [self._make_rally(1, 10, "player_a")]
        strokes_by_rally = {
            1: [
                self._make_stroke("player_b", "smash", 1),
                self._make_stroke("player_a", "clear", 2),
            ],
        }
        role_by_match = {100: "player_a"}
        set_to_match = {10: 100}

        ext, simple = collect_context_stats(
            rallies, strokes_by_rally, role_by_match, set_to_match,
        )
        # simple: prev=smash → response=clear
        assert ("smash",) in simple
        assert "clear" in simple[("smash",)]
        assert simple[("smash",)]["clear"]["count"] == 1
        assert simple[("smash",)]["clear"]["wins"] == 1

    def test_collect_context_stats_extended(self):
        from backend.analysis.counterfactual_engine import collect_context_stats
        rallies = [self._make_rally(1, 10, "player_a", score_a=18, score_b=15)]
        strokes_by_rally = {
            1: [
                self._make_stroke("player_b", "smash", 1, land_zone="BL"),
                self._make_stroke("player_a", "lob", 2),
            ],
        }
        role_by_match = {100: "player_a"}
        set_to_match = {10: 100}

        ext, simple = collect_context_stats(
            rallies, strokes_by_rally, role_by_match, set_to_match,
        )
        # extended: (smash, pressure, early, BL)
        assert ("smash", "pressure", "early", "BL") in ext

    def test_collect_context_stats_no_prev_shot_skipped(self):
        from backend.analysis.counterfactual_engine import collect_context_stats
        rallies = [self._make_rally(1, 10, "player_a")]
        # 自分のショットのみ → prev_shot なし → スキップ
        strokes_by_rally = {
            1: [self._make_stroke("player_a", "clear", 1)],
        }
        role_by_match = {100: "player_a"}
        set_to_match = {10: 100}

        ext, simple = collect_context_stats(
            rallies, strokes_by_rally, role_by_match, set_to_match,
        )
        assert len(simple) == 0

    # ── build_comparisons ─────────────────────────────────────────────────

    def test_build_comparisons_basic(self):
        from backend.analysis.counterfactual_engine import build_comparisons
        stats = {
            ("smash",): {
                "clear": {"count": 10, "wins": 8},
                "lob": {"count": 10, "wins": 3},
                "drive": {"count": 2, "wins": 1},  # min_obs 未満
            },
        }
        labels = {"clear": "クリア", "lob": "ロブ", "drive": "ドライブ"}
        result = build_comparisons(stats, labels, min_obs=5, min_lift=0.05, top_n=5)
        assert len(result) == 1
        assert result[0]["recommended"] == "clear"
        assert result[0]["lift"] > 0

    def test_build_comparisons_no_lift(self):
        from backend.analysis.counterfactual_engine import build_comparisons
        stats = {
            ("smash",): {
                "clear": {"count": 10, "wins": 5},
                "lob": {"count": 10, "wins": 5},
            },
        }
        result = build_comparisons(stats, {}, min_obs=5, min_lift=0.05, top_n=5)
        assert len(result) == 0

    def test_build_comparisons_with_context_features(self):
        from backend.analysis.counterfactual_engine import build_comparisons
        stats = {
            ("smash", "pressure", "late", "BL"): {
                "clear": {"count": 10, "wins": 9},
                "lob": {"count": 10, "wins": 2},
            },
        }
        result = build_comparisons(
            stats, {"clear": "クリア", "lob": "ロブ"},
            min_obs=5, min_lift=0.05, top_n=5,
            include_context_features=True,
        )
        assert len(result) == 1
        assert "context_features" in result[0]
        assert result[0]["context_features"]["score_pressure"] == "pressure"

    # ── summarize_by_dimension ────────────────────────────────────────────

    def test_summarize_by_dimension(self):
        from backend.analysis.counterfactual_engine import summarize_by_dimension
        stats = {
            ("smash", "pressure", "late", "BL"): {
                "clear": {"count": 10, "wins": 8},
            },
            ("drop", "neutral", "early", "MC"): {
                "lob": {"count": 5, "wins": 2},
            },
        }
        result = summarize_by_dimension(stats)
        assert "by_pressure" in result
        assert "by_phase" in result
        assert "pressure" in result["by_pressure"]
        assert "neutral" in result["by_pressure"]
        assert result["by_pressure"]["pressure"]["total"] == 10


# ──────────────────────────────────────────────────────────────────────────────
# Stage 3-B: epv_engine
# ──────────────────────────────────────────────────────────────────────────────

class TestEpvEngine:
    """epv_engine.py のユニットテスト"""

    # ── classify_score_state ──────────────────────────────────────────────

    def test_score_state_leading(self):
        from backend.analysis.epv_engine import classify_score_state
        assert classify_score_state(10, 5, True) == "leading"

    def test_score_state_trailing(self):
        from backend.analysis.epv_engine import classify_score_state
        assert classify_score_state(5, 10, True) == "trailing"

    def test_score_state_tied(self):
        from backend.analysis.epv_engine import classify_score_state
        assert classify_score_state(8, 8, True) == "tied"

    def test_score_state_player_b(self):
        from backend.analysis.epv_engine import classify_score_state
        # player_is_a=False → my=10, opp=5 → leading
        assert classify_score_state(5, 10, False) == "leading"

    # ── classify_rally_phase ──────────────────────────────────────────────

    def test_rally_phase_early(self):
        from backend.analysis.epv_engine import classify_rally_phase
        assert classify_rally_phase(1) == "early"
        assert classify_rally_phase(3) == "early"

    def test_rally_phase_mid(self):
        from backend.analysis.epv_engine import classify_rally_phase
        assert classify_rally_phase(4) == "mid"
        assert classify_rally_phase(7) == "mid"

    def test_rally_phase_late(self):
        from backend.analysis.epv_engine import classify_rally_phase
        assert classify_rally_phase(8) == "late"

    # ── classify_momentum ─────────────────────────────────────────────────

    def test_momentum_hot(self):
        from backend.analysis.epv_engine import classify_momentum
        assert classify_momentum([True, True, True]) == "hot"
        assert classify_momentum([False, True, True, True]) == "hot"

    def test_momentum_cold(self):
        from backend.analysis.epv_engine import classify_momentum
        assert classify_momentum([False, False, False]) == "cold"
        assert classify_momentum([True, False, False, False]) == "cold"

    def test_momentum_neutral_short(self):
        from backend.analysis.epv_engine import classify_momentum
        assert classify_momentum([True]) == "neutral"
        assert classify_momentum([]) == "neutral"

    def test_momentum_cold_one_win(self):
        from backend.analysis.epv_engine import classify_momentum
        # last3=[True, False, False] → wins=1 → cold
        assert classify_momentum([True, False, False]) == "cold"

    # ── build_state_key ───────────────────────────────────────────────────

    def test_build_state_key(self):
        from backend.analysis.epv_engine import build_state_key
        key = build_state_key("leading", "mid", "hot")
        assert key == ("leading", "mid", "hot")

    # ── compute_state_epv ─────────────────────────────────────────────────

    def _make_rally(self, rally_id, set_id, winner, score_a=5, score_b=5):
        r = MagicMock()
        r.id = rally_id
        r.set_id = set_id
        r.winner = winner
        r.score_a_before = score_a
        r.score_b_before = score_b
        r.rally_num = rally_id
        return r

    def _make_stroke(self, player, shot_type, stroke_num, shot_quality=None):
        s = MagicMock()
        s.player = player
        s.shot_type = shot_type
        s.stroke_num = stroke_num
        s.shot_quality = shot_quality
        return s

    def test_compute_state_epv_empty(self):
        from backend.analysis.epv_engine import compute_state_epv
        result = compute_state_epv([], {}, {}, {})
        assert result["global_epv"] == {}
        assert result["state_epv"] == {}

    def test_compute_state_epv_basic(self):
        from backend.analysis.epv_engine import compute_state_epv
        rallies = [
            self._make_rally(1, 10, "player_a", 5, 5),
            self._make_rally(2, 10, "player_b", 6, 5),
        ]
        strokes_by_rally = {
            1: [self._make_stroke("player_a", "smash", 1)],
            2: [self._make_stroke("player_a", "clear", 1)],
        }
        role_by_match = {100: "player_a"}
        set_to_match = {10: 100}

        result = compute_state_epv(rallies, strokes_by_rally, role_by_match, set_to_match)
        assert "global_epv" in result
        assert "state_summary" in result
        # smash で勝ち、clear で負け → smash の EPV > 0, clear < 0
        assert result["global_epv"].get("smash", 0) > 0
        assert result["global_epv"].get("clear", 0) < 0

    def test_compute_state_epv_state_summary_dimensions(self):
        from backend.analysis.epv_engine import compute_state_epv
        rallies = [
            self._make_rally(1, 10, "player_a", 10, 5),
            self._make_rally(2, 10, "player_a", 5, 10),
        ]
        strokes_by_rally = {
            1: [self._make_stroke("player_a", "smash", 2)],
            2: [self._make_stroke("player_a", "smash", 5)],
        }
        role_by_match = {100: "player_a"}
        set_to_match = {10: 100}

        result = compute_state_epv(rallies, strokes_by_rally, role_by_match, set_to_match)
        summary = result["state_summary"]
        assert "by_score_state" in summary
        assert "by_rally_phase" in summary
        assert "by_momentum" in summary

    # ── compute_state_influence ───────────────────────────────────────────

    def test_compute_state_influence_basic(self):
        from backend.analysis.epv_engine import compute_state_influence
        strokes = [
            {"id": 1, "shot_type": "smash", "shot_quality": "good", "stroke_num": 1},
            {"id": 2, "shot_type": "clear", "shot_quality": "neutral", "stroke_num": 5},
        ]
        result = compute_state_influence(strokes, rally_won=True, score_state="tied", momentum="neutral")
        assert len(result) == 2
        assert result[0]["stroke_id"] == 1
        assert result[0]["influence_score"] > 0
        assert "state_factors" in result[0]

    def test_compute_state_influence_win_vs_loss(self):
        from backend.analysis.epv_engine import compute_state_influence
        strokes = [{"id": 1, "shot_type": "smash", "shot_quality": "neutral", "stroke_num": 3}]
        win_result = compute_state_influence(strokes, rally_won=True, score_state="tied", momentum="neutral")
        loss_result = compute_state_influence(strokes, rally_won=False, score_state="tied", momentum="neutral")
        assert win_result[0]["influence_score"] > loss_result[0]["influence_score"]

    def test_compute_state_influence_trailing_higher(self):
        from backend.analysis.epv_engine import compute_state_influence
        strokes = [{"id": 1, "shot_type": "smash", "shot_quality": "neutral", "stroke_num": 5}]
        trailing = compute_state_influence(strokes, True, "trailing", "neutral")
        leading = compute_state_influence(strokes, True, "leading", "neutral")
        # trailing の pressure_mult=1.15 > leading の 0.9
        assert trailing[0]["influence_score"] >= leading[0]["influence_score"]

    def test_compute_state_influence_late_phase_higher(self):
        from backend.analysis.epv_engine import compute_state_influence
        strokes_late = [{"id": 1, "shot_type": "smash", "shot_quality": "neutral", "stroke_num": 10}]
        strokes_early = [{"id": 1, "shot_type": "smash", "shot_quality": "neutral", "stroke_num": 1}]
        late_r = compute_state_influence(strokes_late, True, "tied", "neutral")
        early_r = compute_state_influence(strokes_early, True, "tied", "neutral")
        # late の phase_mult=1.2 > early の 0.8
        assert late_r[0]["influence_score"] >= early_r[0]["influence_score"]

    def test_compute_state_influence_momentum_hot(self):
        from backend.analysis.epv_engine import compute_state_influence
        strokes = [{"id": 1, "shot_type": "drive", "shot_quality": "neutral", "stroke_num": 5}]
        hot = compute_state_influence(strokes, True, "tied", "hot")
        cold = compute_state_influence(strokes, True, "tied", "cold")
        assert hot[0]["influence_score"] >= cold[0]["influence_score"]

    def test_compute_state_influence_capped_at_1(self):
        from backend.analysis.epv_engine import compute_state_influence
        # excellent quality + smash + trailing + late + hot → 高い値でも 1.0 上限
        strokes = [{"id": 1, "shot_type": "smash", "shot_quality": "excellent", "stroke_num": 10}]
        result = compute_state_influence(strokes, True, "trailing", "hot")
        assert result[0]["influence_score"] <= 1.0

    def test_compute_state_influence_state_factors_present(self):
        from backend.analysis.epv_engine import compute_state_influence
        strokes = [{"id": 1, "shot_type": "net_shot", "shot_quality": None, "stroke_num": 2}]
        result = compute_state_influence(strokes, False, "leading", "cold")
        sf = result[0]["state_factors"]
        assert sf["score_state"] == "leading"
        assert sf["rally_phase"] == "early"
        assert sf["momentum"] == "cold"
        assert sf["pressure_mult"] == 0.9
        assert sf["phase_mult"] == 0.8
        assert sf["momentum_mult"] == 0.9

    def test_compute_state_influence_empty(self):
        from backend.analysis.epv_engine import compute_state_influence
        result = compute_state_influence([], True, "tied", "neutral")
        assert result == []
