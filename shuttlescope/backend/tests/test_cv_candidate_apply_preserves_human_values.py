"""CV 候補の一括適用は、人が入力した値を書き換えない。

「高確信度適用」は試合全体のストロークに確認なしで効く。CV の信頼度は過大申告されうる
(shuttle_quality_gate 参照) ので、人の入力と食い違う候補を黙って上書きしてはならない。
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from backend.routers import cv_candidates


class _FakeDb:
    def __init__(self, stroke):
        self.stroke = stroke

    def get(self, model, ident):
        if getattr(model, "__name__", "") == "Stroke" and ident == self.stroke.id:
            return self.stroke
        return None

    def commit(self):
        pass


def _cand(value):
    return {
        "value": value,
        "confidence_score": 0.95,
        "source": "test",
        "decision_mode": "auto_filled",
        "reason_codes": [],
    }


def _artifact(land=None, hit=None, hitter=None):
    return SimpleNamespace(data=json.dumps({"rallies": {"1": {"rally_id": 1, "strokes": [{
        "stroke_id": 101, "stroke_num": 1,
        "land_zone": land, "hit_zone": hit, "hitter": hitter,
    }]}}}))


def _stroke(**kw):
    base = dict(id=101, land_zone=None, hit_zone=None, hit_zone_source=None,
                hit_zone_cv_original=None, player="player_a", source_method="manual")
    base.update(kw)
    return SimpleNamespace(**base)


def _apply(monkeypatch, stroke, artifact, fields):
    monkeypatch.setattr(cv_candidates, "_require_match_team_scope", lambda *_a, **_k: None)
    monkeypatch.setattr(cv_candidates, "_latest_artifact", lambda *_a, **_k: artifact)
    return cv_candidates.apply_cv_candidates(
        1,
        cv_candidates.ApplyRequest(mode="auto_filled", fields=fields),
        request=SimpleNamespace(),
        db=_FakeDb(stroke),
    )["data"]


ALL = ["land_zone", "hit_zone", "hitter"]


def test_human_values_survive_the_one_click_apply(monkeypatch):
    s = _stroke(land_zone="NL", hit_zone="ML", hit_zone_source="manual", player="player_a")
    data = _apply(monkeypatch, s, _artifact(_cand("BR"), _cand("BC"), _cand("player_b")), ALL)
    assert (s.land_zone, s.hit_zone, s.hit_zone_source, s.player) == ("NL", "ML", "manual", "player_a")
    assert s.source_method == "manual"          # 何も変えていないので assisted にしない
    assert data["updated_strokes"] == 0
    assert data["preserved_count"] == 3          # 黙って捨てず、変えなかった数を返す


def test_hit_zone_with_unknown_source_is_treated_as_human(monkeypatch):
    # 入力元の記録が無い既存データ (source が NULL) は人の入力とみなす
    s = _stroke(hit_zone="ML", hit_zone_source=None)
    data = _apply(monkeypatch, s, _artifact(hit=_cand("BC")), ["hit_zone"])
    assert (s.hit_zone, s.hit_zone_source) == ("ML", None)
    assert data["preserved_count"] == 1


def test_empty_fields_are_still_filled(monkeypatch):
    s = _stroke(land_zone=None, hit_zone=None)
    data = _apply(monkeypatch, s, _artifact(_cand("BR"), _cand("BC")), ["land_zone", "hit_zone"])
    assert s.land_zone == "BR"
    assert (s.hit_zone, s.hit_zone_source, s.hit_zone_cv_original) == ("BC", "cv", "BC")
    assert s.source_method == "assisted"
    assert data["land_zone_count"] == 1 and data["hit_zone_count"] == 1
    assert data["preserved_count"] == 0


def test_cv_can_refresh_its_own_earlier_hit_zone(monkeypatch):
    s = _stroke(hit_zone="BC", hit_zone_source="cv", hit_zone_cv_original="BC")
    data = _apply(monkeypatch, s, _artifact(hit=_cand("BL")), ["hit_zone"])
    assert (s.hit_zone, s.hit_zone_source, s.hit_zone_cv_original) == ("BL", "cv", "BL")
    assert data["hit_zone_count"] == 1 and data["preserved_count"] == 0


def test_agreement_is_neither_a_change_nor_a_conflict(monkeypatch):
    s = _stroke(land_zone="BR", hit_zone="BC", hit_zone_source="manual", player="player_b")
    data = _apply(monkeypatch, s, _artifact(_cand("BR"), _cand("BC"), _cand("player_b")), ALL)
    assert data["updated_strokes"] == 0
    assert data["preserved_count"] == 0
    assert s.hit_zone_source == "manual"
