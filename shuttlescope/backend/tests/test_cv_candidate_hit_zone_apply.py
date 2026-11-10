from __future__ import annotations

import json
from types import SimpleNamespace

from backend.routers import cv_candidates


class _FakeDb:
    def __init__(self, stroke):
        self.stroke = stroke
        self.commits = 0

    def get(self, model, ident):
        if getattr(model, "__name__", "") == "Stroke" and ident == self.stroke.id:
            return self.stroke
        return None

    def commit(self):
        self.commits += 1


def _artifact(hit_zone):
    return SimpleNamespace(
        data=json.dumps({
            "rallies": {
                "1": {
                    "rally_id": 1,
                    "strokes": [{
                        "stroke_id": 101,
                        "stroke_num": 1,
                        "hit_zone": hit_zone,
                        "land_zone": None,
                        "hitter": None,
                    }],
                }
            }
        })
    )


def test_apply_hit_zone_marks_cv_provenance(monkeypatch):
    stroke = SimpleNamespace(
        id=101,
        hit_zone=None,
        hit_zone_source=None,
        hit_zone_cv_original=None,
        land_zone=None,
        player="player_a",
        source_method="manual",
    )
    db = _FakeDb(stroke)
    monkeypatch.setattr(cv_candidates, "_require_match_team_scope", lambda *_a, **_k: None)
    monkeypatch.setattr(
        cv_candidates,
        "_latest_artifact",
        lambda *_a, **_k: _artifact({
            "value": "BC",
            "confidence_score": 0.91,
            "source": "yolo_footpoint",
            "decision_mode": "auto_filled",
            "reason_codes": ["hit_zone:hitter_footpoint_homography"],
            "coordinate_definition": "hitter_floor_position",
        }),
    )

    result = cv_candidates.apply_cv_candidates(
        1,
        cv_candidates.ApplyRequest(mode="auto_filled", fields=["hit_zone"]),
        request=SimpleNamespace(),
        db=db,
    )

    assert stroke.hit_zone == "BC"
    assert stroke.hit_zone_source == "cv"
    assert stroke.hit_zone_cv_original == "BC"
    assert stroke.source_method == "assisted"
    assert result["data"]["hit_zone_count"] == 1
    assert result["data"]["updated_strokes"] == 1
    assert db.commits == 1


def test_default_apply_does_not_silently_change_hit_zone(monkeypatch):
    stroke = SimpleNamespace(
        id=101,
        hit_zone="NL",
        hit_zone_source="manual",
        hit_zone_cv_original=None,
        land_zone=None,
        player="player_a",
        source_method="manual",
    )
    db = _FakeDb(stroke)
    monkeypatch.setattr(cv_candidates, "_require_match_team_scope", lambda *_a, **_k: None)
    monkeypatch.setattr(
        cv_candidates,
        "_latest_artifact",
        lambda *_a, **_k: _artifact({
            "value": "BC",
            "confidence_score": 0.99,
            "source": "yolo_footpoint",
            "decision_mode": "auto_filled",
            "reason_codes": [],
            "coordinate_definition": "hitter_floor_position",
        }),
    )

    result = cv_candidates.apply_cv_candidates(
        1,
        cv_candidates.ApplyRequest(),
        request=SimpleNamespace(),
        db=db,
    )

    assert stroke.hit_zone == "NL"
    assert stroke.hit_zone_source == "manual"
    assert result["data"]["hit_zone_count"] == 0
