"""簡易分析「打球の高さ差」(要望8 / SD-08) の定義を固定する試験。

explain.md の計算定義と例をここで突き合わせる。4 段階 → 0〜3 の写像と、
差の取り方（絶対値 0〜3）、ダブルスで «味方への繋ぎ» を数えないことを固定する。
"""
from __future__ import annotations

import pytest

from backend.utils.validators import (
    HIT_HEIGHT_ORDER,
    VALID_HIT_HEIGHTS,
    hit_height_level,
    validate_stroke,
)
from backend.analysis.role_view import stroke_side
from backend.analysis.simple_height_diff import (
    height_diff,
    rally_height_diffs,
    summarize_height_diffs,
)


class TestHeightLevelMapping:
    def test_order_is_net_down(self):
        # ネットより上(0) → やや上(1) → やや下(2) → 下(3)
        assert HIT_HEIGHT_ORDER == (
            "above_net",
            "slightly_above",
            "slightly_below",
            "below",
        )
        assert hit_height_level("above_net") == 0
        assert hit_height_level("slightly_above") == 1
        assert hit_height_level("slightly_below") == 2
        assert hit_height_level("below") == 3

    def test_unknown_and_none_are_none(self):
        assert hit_height_level(None) is None
        assert hit_height_level("") is None
        assert hit_height_level("high") is None  # 別概念の語彙は写さない


class TestHeightDiff:
    def test_spec_example_above_net_vs_slightly_below_is_2(self):
        # 打合せで出た例: 打った人「上(ネットより上)」、受けた人「やや下」→ 差 2
        assert height_diff("above_net", "slightly_below") == 2

    def test_diff_is_absolute(self):
        assert height_diff("below", "above_net") == 3
        assert height_diff("above_net", "below") == 3

    def test_same_level_is_zero(self):
        assert height_diff("slightly_above", "slightly_above") == 0

    def test_missing_side_is_none(self):
        assert height_diff(None, "below") is None
        assert height_diff("below", None) is None


class TestRallyHeightDiffs:
    def test_singles_consecutive_are_opponents(self):
        strokes = [
            {"stroke_num": 1, "player": "player_a", "hit_height": "above_net"},
            {"stroke_num": 2, "player": "player_b", "hit_height": "slightly_below"},
            {"stroke_num": 3, "player": "player_a", "hit_height": "below"},
        ]
        # (1->2)=|0-2|=2, (2->3)=|2-3|=1
        assert rally_height_diffs(strokes) == [2, 1]

    def test_doubles_teammate_tap_is_not_a_return(self):
        # partner_a は player_a と同じチーム。繋ぎは返球関係ではないので数えない。
        strokes = [
            {"stroke_num": 1, "player": "player_a", "hit_height": "above_net"},
            {"stroke_num": 2, "player": "partner_a", "hit_height": "below"},
            {"stroke_num": 3, "player": "player_b", "hit_height": "slightly_below"},
        ]
        # 1->2 同チーム(skip), 2->3 は別チーム |3-2|=1
        assert rally_height_diffs(strokes) == [1]

    def test_missing_height_pair_skipped(self):
        strokes = [
            {"stroke_num": 1, "player": "player_a", "hit_height": None},
            {"stroke_num": 2, "player": "player_b", "hit_height": "below"},
            {"stroke_num": 3, "player": "player_a", "hit_height": "above_net"},
        ]
        # 1->2 片方欠け(skip), 2->3 |3-0|=3
        assert rally_height_diffs(strokes) == [3]

    def test_unordered_input_is_sorted(self):
        strokes = [
            {"stroke_num": 3, "player": "player_a", "hit_height": "below"},
            {"stroke_num": 1, "player": "player_a", "hit_height": "above_net"},
            {"stroke_num": 2, "player": "player_b", "hit_height": "slightly_below"},
        ]
        assert rally_height_diffs(strokes) == [2, 1]


class TestSummary:
    def test_summary_shape_and_values(self):
        r1 = [
            {"stroke_num": 1, "player": "player_a", "hit_height": "above_net"},
            {"stroke_num": 2, "player": "player_b", "hit_height": "slightly_below"},
        ]
        r2 = [
            {"stroke_num": 1, "player": "player_a", "hit_height": "below"},
            {"stroke_num": 2, "player": "player_b", "hit_height": "below"},
        ]
        out = summarize_height_diffs([r1, r2])
        assert out["pairs"] == 2
        assert out["distribution"] == {"0": 1, "1": 0, "2": 1, "3": 0}
        assert out["mean_diff"] == pytest.approx(1.0)

    def test_empty_is_none_mean(self):
        out = summarize_height_diffs([])
        assert out["pairs"] == 0
        assert out["mean_diff"] is None
        assert out["distribution"] == {"0": 0, "1": 0, "2": 0, "3": 0}


class TestDoublesReturnPairing:
    """要望8 (SD-08) の回帰: ダブルスで «相方» を相手扱いせず、相手チームの
    相方 (partner) 同士の返球も高さ差として正しく数えることを固定する。
    role_view.stroke_side が 4 つの個人枠を正しいチーム側へ写すことに依存する。
    """

    def test_partner_vs_opposing_partner_is_a_return(self):
        # partner_a が打ち、相手チームの partner_b が受ける → 返球関係として数える。
        strokes = [
            {"stroke_num": 1, "player": "partner_a", "hit_height": "above_net"},
            {"stroke_num": 2, "player": "partner_b", "hit_height": "below"},
        ]
        # 別チーム同士 |0-3|=3
        assert rally_height_diffs(strokes) == [3]

    def test_doubles_rally_counts_only_cross_team_consecutive_pairs(self):
        # player_a → partner_a (同チームの繋ぎ, skip) → player_b (返球) →
        # partner_b (player_b と同チームの繋ぎ, skip) の 4 球。
        # 別チーム同士で «連続する» のは 2->3 のみ。味方への繋ぎは前後どちらも数えない。
        strokes = [
            {"stroke_num": 1, "player": "player_a", "hit_height": "above_net"},
            {"stroke_num": 2, "player": "partner_a", "hit_height": "slightly_above"},
            {"stroke_num": 3, "player": "player_b", "hit_height": "slightly_below"},
            {"stroke_num": 4, "player": "partner_b", "hit_height": "below"},
        ]
        # 1->2 同チーム(skip), 2->3 別チーム |1-2|=1, 3->4 同チーム(skip)
        assert rally_height_diffs(strokes) == [1]

    def test_doubles_full_exchange_both_sides_alternate(self):
        # 相手と相方が交互に打ち合い、連続球が毎回別チームになる並び。
        # partner_a → player_b → partner_b は無く、A と B が 1 球ずつ交互になる形。
        strokes = [
            {"stroke_num": 1, "player": "partner_a", "hit_height": "above_net"},
            {"stroke_num": 2, "player": "player_b", "hit_height": "slightly_above"},
            {"stroke_num": 3, "player": "player_a", "hit_height": "slightly_below"},
            {"stroke_num": 4, "player": "partner_b", "hit_height": "below"},
        ]
        # 1->2 |0-1|=1, 2->3 |1-2|=1, 3->4 |2-3|=1 (すべて別チーム)
        assert rally_height_diffs(strokes) == [1, 1, 1]

    def test_all_four_slots_map_to_their_team_side(self):
        # 相方 (partner_a/partner_b) が相手扱いされない不変条件を直接固定する。
        assert stroke_side("player_a") == "player_a"
        assert stroke_side("partner_a") == "player_a"
        assert stroke_side("player_b") == "player_b"
        assert stroke_side("partner_b") == "player_b"
        assert stroke_side(None) is None
        assert stroke_side("unknown_slot") is None


class TestValidatorAcceptsHeight:
    @pytest.mark.parametrize("h", sorted(VALID_HIT_HEIGHTS))
    def test_known_height_passes(self, h):
        ok, _ = validate_stroke({"shot_type": "clear", "hit_height": h, "stroke_num": 2})
        assert ok

    def test_unknown_height_refused(self):
        ok, msg = validate_stroke({"shot_type": "clear", "hit_height": "HIGH", "stroke_num": 2})
        assert not ok
        assert "HIGH" in (msg or "")

    def test_no_height_still_allowed(self):
        ok, _ = validate_stroke({"shot_type": "clear", "hit_height": None, "stroke_num": 2})
        assert ok
