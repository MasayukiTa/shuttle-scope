"""D-5: `sample_size` が何を数えた値なのかを宣言する。

`ConfidenceBadge` は単位ごとに閾値 (球 500/2000・ラリー 60/250・試合 10/30) も
表示も変える。宣言が無かったので UI は全部「球」として扱い、試合数を渡して
いた画面は **永久に★1つ・赤の「参考値」** に固定され、ツールチップには
「球」と出ていた。値も単位も誤りだった。

ここで固定するのは「宣言された単位が、エンドポイントが実際に渡している値と
一致していること」。一致は自動では確かめられないので、**呼び出し側を読んで
確認した結果**を表として書き、変更が意図的でないと通らないようにする。

`backend.main` を import しない。
"""
from __future__ import annotations

import pytest

from backend.analysis.analysis_registry import ANALYSIS_REGISTRY, get_analysis_meta
from backend.analysis.response_meta import build_response_meta

# backend/routers/analysis_spine.py の build_response_meta 呼び出しを読んで確認した対応。
# 右の式がその解析の sample_size として渡されている値。
VERIFIED_UNITS = {
    "epv_state":              ("rallies", "len(rallies)"),
    "state_action":           ("rallies", "len(rallies)"),
    "counterfactual_v2":      ("rallies", "len(rallies)"),
    "hazard_fatigue":         ("rallies", "len(rallies)"),
    "shot_influence":         ("rallies", "len(rallies)"),
    "bayes_matchup":          ("matches", "result_data['total_matches']"),
    "opponent_policy":        ("strokes", "result_data['total_opponent_shots']"),
    "doubles_role":           ("strokes", "result_data['total_shots']"),
    "doubles_role_stability": ("matches", "result_data['n_matches_analyzed']"),
}


class TestDeclaredUnits:
    @pytest.mark.parametrize("analysis_type,expected", [
        (k, v[0]) for k, v in VERIFIED_UNITS.items()
    ])
    def test_the_declared_unit_matches_what_the_endpoint_passes(self, analysis_type, expected):
        assert ANALYSIS_REGISTRY[analysis_type]["sample_unit"] == expected

    def test_the_meta_carries_the_unit(self):
        meta = build_response_meta("bayes_matchup", 12)
        assert meta["sample_unit"] == "matches"
        assert meta["sample_size"] == 12

    def test_an_undeclared_analysis_reports_none_rather_than_guessing(self):
        """埋まっていない解析に «球» を当てると、今と同じ誤りに戻る。"""
        meta = build_response_meta("definitely_not_registered", 5)
        assert meta["sample_unit"] is None

    def test_every_entry_has_the_key(self):
        for name, entry in ANALYSIS_REGISTRY.items():
            assert "sample_unit" in entry, name
            assert entry["sample_unit"] in (None, "strokes", "rallies", "matches"), name


class TestRoleStabilityIsItsOwnAnalysis:
    """安定性は試合数、ロール推定は打球数。同じエントリを借りられない。"""

    def test_they_are_separate_entries(self):
        assert "doubles_role_stability" in ANALYSIS_REGISTRY
        assert ANALYSIS_REGISTRY["doubles_role"]["sample_unit"] == "strokes"
        assert ANALYSIS_REGISTRY["doubles_role_stability"]["sample_unit"] == "matches"

    def test_the_stability_threshold_is_in_matches_not_shots(self):
        """打球数向けの 50 を試合数に当てると、到達し得ない閾値になる。"""
        role = get_analysis_meta("doubles_role")
        stability = get_analysis_meta("doubles_role_stability")
        assert stability["min_recommended_sample"] < role["min_recommended_sample"]
        assert stability["min_recommended_sample"] <= 30
