"""CV ラベル（画面上の位置）→ 試合の player_a / player_b の翻訳。

`backend/yolo/inference.py` の `player_a` は「そのフレームで上側にいた人」で、
`Stroke.player` の `player_a` は「`Match.player_a_id` 本人」。綴りが同じなので
翻訳を挟まないと、自選手が下側に映っている試合で打者が全部入れ替わる。

`backend.main` を import しないので重い依存なしで走る。
"""
from __future__ import annotations

import pytest

from backend.cv.candidate_builder import _attach_player_identity
from backend.cv.side_mapping import resolve_cv_player, side_of_player_a


class TestWhichSidePlayerAIsOn:
    @pytest.mark.parametrize("set_num,expected", [
        (1, "top"),     # 開始サイドそのまま
        (2, "bottom"),  # 1ゲーム終わってエンド交替
    ])
    def test_ends_change_after_each_game(self, set_num, expected):
        assert side_of_player_a("top", set_num) == expected

    def test_the_deciding_game_starts_on_the_original_side_again(self):
        """3ゲーム目は 2 回替わったあと = 開始サイドに戻る。"""
        assert side_of_player_a("top", 3, score_a_before=0, score_b_before=0) == "top"

    @pytest.mark.parametrize("a,b", [(11, 4), (4, 11), (11, 11), (20, 19)])
    def test_the_deciding_game_changes_ends_again_at_eleven(self, a, b):
        """最終ゲームは 11 点でもう一度替わる。ここを無視すると後半が全部逆になる。"""
        assert side_of_player_a("top", 3, score_a_before=a, score_b_before=b) == "bottom"

    @pytest.mark.parametrize("a,b", [(10, 10), (0, 10), (10, 3)])
    def test_before_eleven_it_has_not_changed_yet(self, a, b):
        assert side_of_player_a("top", 3, score_a_before=a, score_b_before=b) == "top"

    def test_the_deciding_game_without_a_score_is_not_guessed(self):
        """11 点の前か後かが分からなければ半分の確率で逆。答えない。"""
        assert side_of_player_a("top", 3) is None

    @pytest.mark.parametrize("start_side", [None, "", "left", "TOP", "up"])
    def test_an_unset_or_unknown_start_side_is_not_guessed(self, start_side):
        assert side_of_player_a(start_side, 1) is None

    @pytest.mark.parametrize("set_num", [4, 5, 0, -1, None, "1", True])
    def test_formats_we_do_not_model_are_not_guessed(self, set_num):
        """4・5ゲーム目のエンド交替規則を持っていないので推測しない。

        `True` は `isinstance(True, int)` が真なので set_num=1 として通ってしまう。
        """
        assert side_of_player_a("top", set_num) is None

    def test_bottom_is_the_mirror_of_top(self):
        for n in (1, 2):
            assert side_of_player_a("bottom", n) != side_of_player_a("top", n)


class TestTranslatingTheCvLabel:
    def test_own_player_on_top_maps_straight_through(self):
        assert resolve_cv_player("player_a", "top", 1) == "player_a"
        assert resolve_cv_player("player_b", "top", 1) == "player_b"

    def test_own_player_on_the_bottom_inverts_everything(self):
        """**これが直したかった不具合そのもの。**"""
        assert resolve_cv_player("player_a", "bottom", 1) == "player_b"
        assert resolve_cv_player("player_b", "bottom", 1) == "player_a"

    def test_the_second_set_inverts_again(self):
        assert resolve_cv_player("player_a", "top", 2) == "player_b"

    @pytest.mark.parametrize("label", ["player_c", "player_d", "player_other", None, ""])
    def test_doubles_partners_are_not_identified(self, label):
        """c/d はペア内の区別であって本人特定ではない。"""
        assert resolve_cv_player(label, "top", 1) is None


class TestAttachingItToACandidate:
    def _hitter(self):
        return {
            "value": "player_a",
            "confidence_score": 0.9,
            "source": "alignment",
            "decision_mode": "auto_apply",
            "reason_codes": [],
        }

    def test_a_resolvable_candidate_is_rewritten_and_keeps_its_origin(self):
        h = self._hitter()
        _attach_player_identity(h, start_side="bottom", set_num=1,
                                score_a_before=0, score_b_before=0)
        assert h["value"] == "player_b"
        assert h["screen_label"] == "player_a"
        assert h["player_identity_resolved"] is True
        assert h["decision_mode"] == "auto_apply"

    def test_an_unresolvable_candidate_is_not_rewritten_and_goes_to_review(self):
        """開始サイド未設定。黙って «画面上の位置» を人として書かない。"""
        h = self._hitter()
        _attach_player_identity(h, start_side=None, set_num=1,
                                score_a_before=0, score_b_before=0)
        assert h["value"] == "player_a"          # 書き換えていない
        assert h["player_identity_resolved"] is False
        assert h["decision_mode"] == "review_required"
        assert "player_identity_unmapped" in h["reason_codes"]

    def test_the_deciding_game_without_a_score_goes_to_review(self):
        h = self._hitter()
        _attach_player_identity(h, start_side="top", set_num=3,
                                score_a_before=None, score_b_before=None)
        assert h["decision_mode"] == "review_required"
        assert "player_identity_unmapped" in h["reason_codes"]

    def test_no_candidate_is_left_alone(self):
        _attach_player_identity(None, start_side="top", set_num=1,
                                score_a_before=0, score_b_before=0)
        empty = {"value": None}
        _attach_player_identity(empty, start_side="top", set_num=1,
                                score_a_before=0, score_b_before=0)
        assert "screen_label" not in empty


class TestThroughBuildCandidates:
    """`build_candidates` の出口で実際に人に翻訳されていること。

    ここが本題。旧実装は `_infer_hitter` が返した «画面上の位置» をそのまま
    `hitter.value` に置き、下流の `apply` が `Stroke.player` に書いていた。
    自選手が下側に映っている試合は打者が丸ごと入れ替わる。
    """

    def _args(self, set_num=1, score_a=0, score_b=0):
        return dict(
            match_id=1,
            rallies_db=[{
                "id": 1, "set_id": 1, "set_num": set_num,
                "score_a_before": score_a, "score_b_before": score_b,
                "rally_num": 1,
                "video_timestamp_start": 0.0, "video_timestamp_end": 10.0,
            }],
            strokes_db=[{"id": 1, "rally_id": 1, "stroke_num": 1, "timestamp_sec": 1.0}],
            tracknet_frames=[],
            yolo_frames=[],
            alignment_data=[{
                "rally_id": 1,
                "events": [{
                    "timestamp_sec": 1.0,
                    "hitter_candidate": "player_a",   # 画面の上側
                    "hitter_confidence": 0.9,
                }],
            }],
        )

    def _hitter_of(self, result):
        return result["rallies"]["1"]["strokes"][0]["hitter"]

    def test_top_side_match_keeps_the_label(self):
        from backend.cv.candidate_builder import build_candidates
        h = self._hitter_of(build_candidates(
            **self._args(), player_a_start_side="top"))
        assert h["value"] == "player_a"
        assert h["player_identity_resolved"] is True

    def test_bottom_side_match_inverts_the_label(self):
        from backend.cv.candidate_builder import build_candidates
        h = self._hitter_of(build_candidates(
            **self._args(), player_a_start_side="bottom"))
        assert h["value"] == "player_b", "画面上の位置が人として書かれている"
        assert h["screen_label"] == "player_a"

    def test_without_a_start_side_the_candidate_is_marked_for_review(self):
        from backend.cv.candidate_builder import build_candidates
        h = self._hitter_of(build_candidates(**self._args()))
        assert h["decision_mode"] == "review_required"
        assert "player_identity_unmapped" in h["reason_codes"]


class TestApplyRefusesAnUnmappedHitter:
    """人に翻訳できていない候補は `Stroke.player` に書かせない。

    `mode="all"` は decision_mode を見ずに全候補を適用するので、
    `review_required` に落とすだけでは素通りする。
    """

    def _filters(self):
        from backend.routers.cv_candidates import ApplyRequest, _field_passes_filters
        return ApplyRequest, _field_passes_filters

    def test_an_unmapped_hitter_is_refused_even_in_all_mode(self):
        ApplyRequest, passes = self._filters()
        cand = {
            "value": "player_a",
            "confidence_score": 0.95,
            "decision_mode": "review_required",
            "reason_codes": ["player_identity_unmapped"],
            "player_identity_resolved": False,
        }
        all_modes = {"auto_filled", "suggested", "review_required"}
        assert passes(cand, ApplyRequest(), all_modes) is False

    def test_a_mapped_hitter_still_applies(self):
        ApplyRequest, passes = self._filters()
        cand = {
            "value": "player_b",
            "confidence_score": 0.95,
            "decision_mode": "auto_filled",
            "reason_codes": [],
            "player_identity_resolved": True,
        }
        assert passes(cand, ApplyRequest(), {"auto_filled"}) is True

    def test_land_zone_candidates_are_unaffected(self):
        """着地ゾーンには人の同定が無いので、この検査で落ちてはいけない。"""
        ApplyRequest, passes = self._filters()
        cand = {"value": "A_front_left", "confidence_score": 0.9,
                "decision_mode": "auto_filled", "reason_codes": []}
        assert passes(cand, ApplyRequest(), {"auto_filled"}) is True


class TestItAgreesWithTheFrontendRule:
    """同じ規則が `src/utils/courtSides.ts` にもある。

    二重実装を許すには「同じ入力で同じ答え」を固定するしかない。ここは
    `src/utils/__tests__/courtSides.test.ts` の `computePlayerASide` の
    アサーションをそのまま写したもの。片方だけ直したら落ちる。

    違いは 1 点だけで、意図的:
    フロントはコート図を描くだけなので 4 ゲーム目でも値を返すが、
    こちらは `Stroke.player` に人の名前を書くので答えない (別のテストで固定)。
    """

    @pytest.mark.parametrize("start,set_num,a,b,expected", [
        ("bottom", 1, 0, 0, "bottom"),   # 第1セットは初期サイドのまま
        ("top",    1, 5, 3, "top"),
        ("bottom", 2, 0, 0, "top"),      # セットごとに入れ替わる
        ("bottom", 3, 0, 0, "bottom"),
        ("bottom", 3, 10, 8, "bottom"),  # 第3セットは11点でもう一度入れ替わる
        ("bottom", 3, 11, 8, "top"),
        ("bottom", 3, 8, 11, "top"),
    ])
    def test_same_answers_as_court_sides_ts(self, start, set_num, a, b, expected):
        assert side_of_player_a(start, set_num, a, b) == expected
