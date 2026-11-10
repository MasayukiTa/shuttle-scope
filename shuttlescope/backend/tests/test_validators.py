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

    @pytest.mark.parametrize("zone", ["NL", "NC", "NR"])
    def test_smash_near_net_is_saved_with_warning(self, zone):
        # 急角度のスマッシュがネット寄りに落ちるのは競技上成立する。
        # 拒否せず (valid=True)、確認用の警告だけを返す。
        stroke = {
            "stroke_num": 2,
            "shot_type": "smash",
            "land_zone": zone,
        }
        valid, message = validate_stroke(stroke)
        assert valid is True
        assert message is not None
        assert zone in message

    def test_smash_to_back_has_no_warning(self):
        valid, message = validate_stroke(
            {"stroke_num": 2, "shot_type": "smash", "land_zone": "BC"}
        )
        assert valid is True
        assert message is None

    def test_smash_near_net_still_checked_for_unknown_hit_zone(self):
        # 警告で早期 return せず、後続の検証 (ゾーン語彙) も続ける
        valid, _ = validate_stroke(
            {"stroke_num": 2, "shot_type": "smash", "land_zone": "NL", "hit_zone": "ZZ"}
        )
        assert valid is False

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
