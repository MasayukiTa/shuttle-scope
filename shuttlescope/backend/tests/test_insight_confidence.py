"""インサイトに「発明した信頼度」を載せない。

`InsightItem.confidence` が数値だと UI (`ChatMessageBubble.tsx`) が
「信頼度 NN%」と描く。TemplateGenerator はそこに N の単調関数
(`N=500 → 0.7`) を入れていた。0.7 は何かを測った値ではないので、
**誰も計算していない数字が、いちばん信用できそうな見た目で出ていた**。

並べ替えには引き続きその値を使う (サンプルの多い順に 3 件) ので、
機能としては消していない。消したのは表示に回る経路だけ。
サンプル数は `metric.sample_n` と prose の中に残る。

`backend.main` を import しない。
"""
from __future__ import annotations

import pytest

from backend.analysis.insights.template import TemplateGenerator, _sample_weight


def _ctx(*, strokes: int, rallies: int, matches: int) -> dict:
    return {
        "lang": "ja",
        "player_id": 1,
        "period_days": 30,
        "analytics": {
            "sample": {"strokes": strokes, "rallies": rallies, "matches": matches},
            "recent_trend": {"last_5_match_win_rate": 0.58, "delta_vs_prior_5": 4.0},
            "shot_mix": [
                {"shot_type": "smash", "share": 0.31},
                {"shot_type": "drop", "share": 0.12},
            ],
            "conditions": {"n": 8, "avg_rpe": 6.2},
        },
    }


@pytest.fixture()
def items():
    result = TemplateGenerator().generate(_ctx(strokes=1200, rallies=300, matches=20))
    assert result["items"], "テンプレが 1 件も出していない — 前提が崩れている"
    return result["items"]


class TestNoInventedConfidence:
    def test_no_item_carries_a_confidence_number(self, items):
        for item in items:
            assert item["confidence"] is None, item["id"]

    def test_the_sample_size_is_still_reported(self, items):
        """信頼度を消した代わりに N が消えていないこと。"""
        for item in items:
            metric = item["metric"]
            assert any(k in metric for k in ("sample_n", "n")), item["id"]


class TestOrderingStillUsesSampleSize:
    def test_more_evidence_sorts_first(self):
        """並べ替えの機能は残す。0.7 を «信頼度» と呼ぶのをやめただけ。"""
        assert _sample_weight(2000) > _sample_weight(500) > _sample_weight(60)

    def test_below_the_minimum_scores_zero(self):
        assert _sample_weight(0) == 0.0
        assert _sample_weight(5) == 0.0

    def test_at_most_three_items(self, items):
        assert len(items) <= 3


class TestTooLittleDataStillReturnsNothing:
    def test_no_items_below_the_threshold(self):
        result = TemplateGenerator().generate(_ctx(strokes=3, rallies=1, matches=1))
        assert result["items"] == []


class TestAssistedProvenanceIsDisclosed:
    """C-5: CV 由来の打球を混ぜた集計に、混ぜたと書いてあること。

    `Stroke.source_method == 'assisted'` は CV 候補を適用した打球。
    読み手は「人が見て入れた値」として読むので、黙って混ぜない。
    """

    def _ctx_with(self, assisted: int) -> dict:
        ctx = _ctx(strokes=1200, rallies=300, matches=20)
        ctx["analytics"]["sample"]["assisted_strokes"] = assisted
        return ctx

    def _shot_mix_item(self, ctx):
        items = TemplateGenerator().generate(ctx)["items"]
        found = [i for i in items if i["id"] == "shot_mix"]
        assert found, [i["id"] for i in items]
        return found[0]

    def test_a_mixed_aggregate_says_so(self):
        item = self._shot_mix_item(self._ctx_with(180))
        assert "CV" in item["prose"], item["prose"]
        assert "180" in item["prose"]
        assert item["metric"]["assisted_n"] == 180

    def test_a_purely_manual_aggregate_says_nothing_extra(self):
        """0 件のとき «CV 0球» と書き足すのは雑音。"""
        item = self._shot_mix_item(self._ctx_with(0))
        assert "CV" not in item["prose"], item["prose"]
        assert item["metric"]["assisted_n"] == 0

    def test_a_summary_without_the_field_behaves_like_zero(self):
        """この項目より前に作られた集計 (assisted_strokes 無し) で落ちない。"""
        ctx = _ctx(strokes=1200, rallies=300, matches=20)
        assert "assisted_strokes" not in ctx["analytics"]["sample"]
        item = self._shot_mix_item(ctx)
        assert item["metric"]["assisted_n"] == 0
