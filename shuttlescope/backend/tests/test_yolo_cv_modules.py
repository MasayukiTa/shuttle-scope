# coding: utf-8
"""YOLO / CV モジュール ユニットテスト

対象:
  - backend/yolo/court_mapper.py
  - backend/yolo/cv_aligner.py
  - backend/analysis/doubles_cv_engine.py (ロジック部分)
  - backend/analysis/doubles_role_inference.py (adjust_role_with_cv_signals)

DB が不要なロジック関数を対象とする。
"""
import pytest
from backend.yolo.court_mapper import (
    classify_formation,
    nearest_player_to_point,
    summarize_frame_positions,
    summarize_rally_positions,
)
from backend.yolo.cv_aligner import (
    align_match,
    _frames_in_range,
    _summarize_events,
)
from backend.analysis.doubles_cv_engine import (
    _compute_formation_tendency,
    _compute_hitter_distribution,
    _compute_pressure_map,
)
from backend.analysis.doubles_role_inference import adjust_role_with_cv_signals


# ──────────────────────────────────────────────────────────────
# court_mapper: classify_formation
# ──────────────────────────────────────────────────────────────

def _p(label: str, cx: float, cy: float) -> dict:
    return {"label": label, "centroid": [cx, cy]}


class TestClassifyFormation:
    def test_front_back(self):
        """y 差が大きい → front_back"""
        players = [_p("player_a", 0.3, 0.2), _p("player_b", 0.7, 0.7)]
        assert classify_formation(players) == "front_back"

    def test_parallel(self):
        """x 差が大きく y 差が小さい → parallel"""
        players = [_p("player_a", 0.1, 0.5), _p("player_b", 0.9, 0.5)]
        assert classify_formation(players) == "parallel"

    def test_mixed(self):
        """差が中間 → mixed"""
        players = [_p("player_a", 0.3, 0.4), _p("player_b", 0.52, 0.55)]
        assert classify_formation(players) == "mixed"

    def test_unknown_one_player(self):
        """プレイヤーが1人 → unknown"""
        players = [_p("player_a", 0.5, 0.5)]
        assert classify_formation(players) == "unknown"

    def test_unknown_empty(self):
        assert classify_formation([]) == "unknown"


# ──────────────────────────────────────────────────────────────
# court_mapper: nearest_player_to_point
# ──────────────────────────────────────────────────────────────

class TestNearestPlayer:
    def _player(self, label, cx, cy):
        return {"label": label, "centroid": [cx, cy]}

    def test_returns_closest(self):
        players = [
            self._player("player_a", 0.2, 0.2),
            self._player("player_b", 0.8, 0.8),
        ]
        result = nearest_player_to_point(players, 0.75, 0.75)
        assert result is not None
        assert result["label"] == "player_b"

    def test_ignores_non_player_labels(self):
        players = [self._player("shuttle", 0.5, 0.5)]
        assert nearest_player_to_point(players, 0.5, 0.5) is None

    def test_empty(self):
        assert nearest_player_to_point([], 0.5, 0.5) is None


# ──────────────────────────────────────────────────────────────
# court_mapper: summarize_frame_positions
# ──────────────────────────────────────────────────────────────

class TestSummarizeFramePositions:
    def _frame(self, ts, players):
        return {"timestamp_sec": ts, "players": players}

    def _full_player(self, label, cx, cy):
        return {
            "label": label,
            "centroid": [cx, cy],
            "depth_band": "front" if cy < 0.35 else ("back" if cy > 0.65 else "mid"),
            "court_side": "left" if cx < 0.5 else "right",
        }

    def test_basic_counts(self):
        p_a = self._full_player("player_a", 0.3, 0.2)  # front, left
        p_b = self._full_player("player_b", 0.7, 0.7)  # back, right
        frames = [self._frame(1.0, [p_a, p_b])]
        s = summarize_frame_positions(frames)

        assert s["total_frames"] == 1
        assert s["frames_with_both_players"] == 1
        assert s["formations"]["front_back"] == 1
        assert s["player_a_depth_band"]["front"] == 1
        assert s["player_b_depth_band"]["back"] == 1

    def test_empty_frames(self):
        s = summarize_frame_positions([])
        assert s["total_frames"] == 0
        assert s["frames_with_both_players"] == 0
        assert s["player_a_avg_position"] is None

    def test_rally_subset(self):
        p = self._full_player("player_a", 0.5, 0.5)
        frames = [
            self._frame(1.0, [p]),
            self._frame(5.0, [p]),
            self._frame(9.0, [p]),
        ]
        s = summarize_rally_positions(frames, 4.0, 6.0)
        assert s["total_frames"] == 1  # only ts=5.0 in range


# ──────────────────────────────────────────────────────────────
# cv_aligner: _frames_in_range
# ──────────────────────────────────────────────────────────────

class TestFramesInRange:
    def test_subset(self):
        frames = [{"timestamp_sec": float(i)} for i in range(10)]
        ts = [float(i) for i in range(10)]
        result = _frames_in_range(frames, ts, 2.0, 5.0)
        assert len(result) == 4
        assert result[0]["timestamp_sec"] == 2.0
        assert result[-1]["timestamp_sec"] == 5.0

    def test_empty_range(self):
        frames = [{"timestamp_sec": 1.0}]
        ts = [1.0]
        assert _frames_in_range(frames, ts, 5.0, 10.0) == []


# ──────────────────────────────────────────────────────────────
# cv_aligner: align_match end-to-end
# ──────────────────────────────────────────────────────────────

class TestAlignMatch:
    def _yolo_frame(self, ts, players=None):
        if players is None:
            players = [
                {"label": "player_a", "centroid": [0.3, 0.7], "confidence": 0.9,
                 "bbox": [0.2, 0.6, 0.4, 0.8], "foot_point": [0.3, 0.8],
                 "court_side": "left", "depth_band": "back"},
                {"label": "player_b", "centroid": [0.7, 0.3], "confidence": 0.85,
                 "bbox": [0.6, 0.2, 0.8, 0.4], "foot_point": [0.7, 0.4],
                 "court_side": "right", "depth_band": "front"},
            ]
        return {"timestamp_sec": ts, "players": players}

    def _tracknet_frame(self, ts, zone="NL", conf=0.85, x=0.3, y=0.2):
        return {"timestamp_sec": ts, "zone": zone, "confidence": conf,
                "x_norm": x, "y_norm": y}

    def test_returns_one_rally(self):
        yolo = [self._yolo_frame(1.0), self._yolo_frame(2.0)]
        tracknet = [self._tracknet_frame(1.1), self._tracknet_frame(2.1)]
        rallies = [{"rally_id": 1, "start_sec": 0.5, "end_sec": 3.0}]
        result = align_match(yolo, tracknet, rallies)
        assert len(result) == 1
        assert result[0]["rally_id"] == 1
        assert len(result[0]["events"]) == 2

    def test_event_has_required_keys(self):
        yolo = [self._yolo_frame(1.0)]
        tracknet = [self._tracknet_frame(1.0)]
        rallies = [{"rally_id": 1, "start_sec": 0.5, "end_sec": 2.0}]
        events = align_match(yolo, tracknet, rallies)[0]["events"]
        ev = events[0]
        assert "hitter_candidate" in ev
        assert "hitter_confidence" in ev
        assert "receiver_candidate" in ev
        assert "formation" in ev

    def test_empty_tracknet_produces_no_events(self):
        yolo = [self._yolo_frame(1.0)]
        rallies = [{"rally_id": 1, "start_sec": 0.5, "end_sec": 2.0}]
        result = align_match(yolo, [], rallies)
        assert result[0]["events"] == []

    def test_hitter_confidence_between_0_and_1(self):
        yolo = [self._yolo_frame(1.0)]
        tracknet = [self._tracknet_frame(1.0, x=0.3, y=0.7, conf=0.9)]
        rallies = [{"rally_id": 1, "start_sec": 0.5, "end_sec": 2.0}]
        events = align_match(yolo, tracknet, rallies)[0]["events"]
        for ev in events:
            hc = ev.get("hitter_confidence", 0.0)
            assert 0.0 <= hc <= 1.0


# ──────────────────────────────────────────────────────────────
# cv_aligner: _summarize_events
# ──────────────────────────────────────────────────────────────

class TestSummarizeEvents:
    def _event(self, hitter, formation="front_back", hitter_conf=0.7):
        return {
            "hitter_candidate": hitter,
            "hitter_confidence": hitter_conf,
            "formation": formation,
        }

    def test_counts(self):
        events = [
            self._event("player_a"),
            self._event("player_a"),
            self._event("player_b"),
            self._event(None),
        ]
        s = _summarize_events(events)
        assert s["hitter_a_count"] == 2
        assert s["hitter_b_count"] == 1
        assert s["dominant_formation"] == "front_back"

    def test_avg_confidence(self):
        events = [
            self._event("player_a", hitter_conf=0.8),
            self._event("player_a", hitter_conf=0.6),
        ]
        s = _summarize_events(events)
        assert abs(s["hitter_a_avg_confidence"] - 0.7) < 0.01

    def test_empty_events(self):
        s = _summarize_events([])
        assert s["hitter_a_count"] == 0
        assert s["dominant_formation"] == "unknown"


# ──────────────────────────────────────────────────────────────
# doubles_cv_engine: analytics functions
# ──────────────────────────────────────────────────────────────

class TestComputeFormationTendency:
    def test_front_back_dominant(self):
        summary = {
            "formations": {"front_back": 70, "parallel": 15, "mixed": 10, "unknown": 5},
            "front_back_ratio": 0.7,
            "parallel_ratio": 0.15,
        }
        result = _compute_formation_tendency(summary)
        assert result["dominant"] == "front_back"
        assert result["style_label"] == "前後陣傾向"

    def test_parallel_dominant(self):
        summary = {
            "formations": {"front_back": 10, "parallel": 80, "mixed": 10, "unknown": 0},
            "front_back_ratio": 0.1,
            "parallel_ratio": 0.8,
        }
        result = _compute_formation_tendency(summary)
        assert result["style_label"] == "平行陣傾向"

    def test_empty_formations(self):
        summary = {"formations": {}, "front_back_ratio": 0.0, "parallel_ratio": 0.0}
        result = _compute_formation_tendency(summary)
        assert result["dominant"] == "unknown"

    def test_breakdown_ratios_sum_to_one(self):
        summary = {
            "formations": {"front_back": 50, "parallel": 30, "mixed": 20},
            "front_back_ratio": 0.5,
            "parallel_ratio": 0.3,
        }
        result = _compute_formation_tendency(summary)
        total_ratio = sum(v["ratio"] for v in result["breakdown"].values())
        assert abs(total_ratio - 1.0) < 0.01


class TestComputeHitterDistribution:
    def test_basic(self):
        alignment = [
            {"summary": {"hitter_a_count": 8, "hitter_b_count": 2}},
            {"summary": {"hitter_a_count": 4, "hitter_b_count": 6}},
        ]
        result = _compute_hitter_distribution(alignment)
        assert result["hitter_a_count"] == 12
        assert result["hitter_b_count"] == 8
        assert abs(result["hitter_a_ratio"] + result["hitter_b_ratio"] - 1.0) < 0.01

    def test_rally_dominant_counts(self):
        # a=8, b=2 → a dominant (8 > 2*1.5)
        # a=3, b=6 → b dominant (6 > 3*1.5)
        alignment = [
            {"summary": {"hitter_a_count": 8, "hitter_b_count": 2}},
            {"summary": {"hitter_a_count": 3, "hitter_b_count": 6}},
        ]
        result = _compute_hitter_distribution(alignment)
        assert result["rally_dominant"]["player_a"] == 1
        assert result["rally_dominant"]["player_b"] == 1

    def test_empty(self):
        result = _compute_hitter_distribution([])
        assert result["hitter_a_count"] == 0
        assert result["hitter_b_count"] == 0


class TestComputePressureMap:
    def test_empty_returns_empty(self):
        assert _compute_pressure_map([], []) == {}

    def test_no_matching_frames_returns_empty(self):
        class FakeStroke:
            land_zone = "NL"
            timestamp_sec = 5.0

        frames = [{"timestamp_sec": 1.0, "players": []}]
        result = _compute_pressure_map(frames, [FakeStroke()])
        assert result == {}


# ──────────────────────────────────────────────────────────────
# doubles_role_inference: adjust_role_with_cv_signals
# ──────────────────────────────────────────────────────────────

class TestAdjustRoleWithCVSignals:
    def _shot_result(self, role="front", conf=0.75):
        return {"inferred_role": role, "confidence_score": conf}

    def _cv_summary_fb(self):
        return {
            "front_back_ratio": 0.65,
            "parallel_ratio": 0.15,
            "player_a_depth_band": {"front": 5, "mid": 2, "back": 1},
            "player_b_depth_band": {"front": 1, "mid": 2, "back": 6},
        }

    def _cv_summary_parallel(self):
        return {
            "front_back_ratio": 0.1,
            "parallel_ratio": 0.75,
            "player_a_depth_band": {"front": 2, "mid": 6, "back": 2},
            "player_b_depth_band": {"front": 2, "mid": 5, "back": 3},
        }

    def test_cv_available_false_on_empty(self):
        result = adjust_role_with_cv_signals(self._shot_result(), {})
        assert result["cv_available"] is False

    def test_consistent_front_back(self):
        result = adjust_role_with_cv_signals(
            self._shot_result("front", 0.75), self._cv_summary_fb()
        )
        assert result["cv_available"] is True
        assert result["agreement"] == "consistent"
        assert result["agreement_score"] > 0

    def test_player_hints(self):
        result = adjust_role_with_cv_signals(
            self._shot_result("front", 0.75), self._cv_summary_fb()
        )
        assert result["player_a_cv_role_hint"] == "front"
        assert result["player_b_cv_role_hint"] == "back"

    def test_inconsistent_detection(self):
        # parallel CV + shot_role=back → inconsistent
        result = adjust_role_with_cv_signals(
            self._shot_result("back", 0.7), self._cv_summary_parallel()
        )
        assert result["agreement"] in ("inconsistent", "partial")

    def test_agreement_score_in_range(self):
        result = adjust_role_with_cv_signals(
            self._shot_result(), self._cv_summary_fb()
        )
        assert 0.0 <= result["agreement_score"] <= 1.0
