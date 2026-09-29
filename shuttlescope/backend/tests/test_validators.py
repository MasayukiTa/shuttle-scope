"""ストローク整合性チェックのテスト"""
import pytest
from backend.utils.validators import validate_stroke, validate_rally


class TestValidateStroke:
    def test_valid_stroke(self):
        stroke = {
            "stroke_num": 1,
            "shot_type": "short_service",
            "land_zone": "NL",
        }
        valid, error = validate_stroke(stroke)
        assert valid is True
        assert error is None

    def test_smash_cannot_land_near_net(self):
        stroke = {
            "stroke_num": 2,
            "shot_type": "smash",
            "land_zone": "NL",
        }
        valid, error = validate_stroke(stroke)
        assert valid is False
        assert error is not None

    def test_short_service_cannot_land_at_back(self):
        stroke = {
            "stroke_num": 1,
            "shot_type": "short_service",
            "land_zone": "BL",
        }
        valid, error = validate_stroke(stroke)
        assert valid is False

    def test_net_shot_cannot_land_at_back(self):
        stroke = {
            "stroke_num": 2,
            "shot_type": "net_shot",
            "land_zone": "BC",
        }
        valid, error = validate_stroke(stroke)
        assert valid is False

    def test_cant_reach_with_land_zone_is_invalid(self):
        stroke = {
            "stroke_num": 2,
            "shot_type": "cant_reach",
            "land_zone": "ML",
        }
        valid, error = validate_stroke(stroke)
        assert valid is False

    def test_cant_reach_without_land_zone_is_valid(self):
        stroke = {
            "stroke_num": 2,
            "shot_type": "cant_reach",
            "land_zone": None,
        }
        valid, error = validate_stroke(stroke)
        assert valid is True

    def test_service_on_non_first_stroke_is_invalid(self):
        stroke = {
            "stroke_num": 2,
            "shot_type": "short_service",
            "land_zone": "NL",
        }
        valid, error = validate_stroke(stroke)
        assert valid is False


class TestValidateRally:
    def test_valid_rally(self):
        rally = {"rally_length": 2, "server": "player_a"}
        strokes = [
            {"stroke_num": 1, "shot_type": "short_service"},
            {"stroke_num": 2, "shot_type": "smash"},
        ]
        valid, error = validate_rally(rally, strokes)
        assert valid is True

    def test_empty_strokes_is_invalid(self):
        rally = {"rally_length": 0}
        valid, error = validate_rally(rally, [])
        assert valid is False

    def test_stroke_num_mismatch_is_invalid(self):
        rally = {"rally_length": 2}
        strokes = [
            {"stroke_num": 1, "shot_type": "clear"},
            {"stroke_num": 3, "shot_type": "smash"},  # 番号が飛んでいる
        ]
        valid, error = validate_rally(rally, strokes)
        assert valid is False

    def test_rally_length_mismatch_is_invalid(self):
        rally = {"rally_length": 5}  # 実際は2球
        strokes = [
            {"stroke_num": 1, "shot_type": "clear"},
            {"stroke_num": 2, "shot_type": "smash"},
        ]
        valid, error = validate_rally(rally, strokes)
        assert valid is False
