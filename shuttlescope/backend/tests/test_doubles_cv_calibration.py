"""B-4: doubles CV のコート依存解析は calibration を必須にする。"""
from __future__ import annotations

import json
from datetime import date

from backend.analysis import doubles_cv_engine as engine_mod
from backend.cv.court_adapter import CourtAdapter
from backend.db.models import Match, MatchCVArtifact, Player


def _make_match(db_session) -> Match:
    a = Player(name="B4-A", dominant_hand="R")
    b = Player(name="B4-B", dominant_hand="R")
    db_session.add_all([a, b])
    db_session.flush()
    match = Match(
        tournament="B4 calibration",
        tournament_level="practice",
        round="R1",
        date=date(2026, 9, 28),
        format="mens_doubles",
        player_a_id=a.id,
        player_b_id=b.id,
        result="unknown",
    )
    db_session.add(match)
    db_session.flush()
    return match


def _add_yolo_artifact(db_session, match_id: int) -> MatchCVArtifact:
    frames = [{
        "frame_idx": 0,
        "timestamp_sec": 1.0,
        "players": [
            {
                "label": "player_a",
                "centroid": [0.10, 0.10],
                "foot_point": [0.25, 0.30],
                "depth_band": "front",
                "court_side": "left",
            },
            {
                "label": "player_b",
                "centroid": [0.90, 0.90],
                "foot_point": [0.75, 0.70],
                "depth_band": "back",
                "court_side": "right",
            },
        ],
    }]
    # Deliberately stale/raw summary. The live analysis must not trust this.
    artifact = MatchCVArtifact(
        match_id=match_id,
        artifact_type="yolo_player_detections",
        frame_count=1,
        backend_used="test",
        data=json.dumps(frames),
        summary=json.dumps({
            "coordinate_space": "image_normalized",
            "court_calibrated": False,
            "front_back_ratio": 0.99,
            "player_a_avg_position": [0.10, 0.10],
        }),
    )
    db_session.add(artifact)
    db_session.commit()
    return artifact


def test_uncalibrated_doubles_cv_is_explicitly_unavailable(monkeypatch, db_session):
    match = _make_match(db_session)
    _add_yolo_artifact(db_session, match.id)
    monkeypatch.setattr(
        engine_mod.CourtAdapter,
        "for_match",
        classmethod(lambda cls, _match_id: CourtAdapter()),
    )

    result = engine_mod.compute_doubles_cv_analytics(match.id, db_session)

    assert result["available"] is False
    assert result["calibration_required"] is True
    assert result["yolo_frame_count"] == 1
    assert "formation_tendency" not in result
    assert "pressure_map" not in result


def test_calibrated_doubles_cv_recomputes_summary_from_raw_frames(monkeypatch, db_session):
    match = _make_match(db_session)
    _add_yolo_artifact(db_session, match.id)
    H = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    adapter = CourtAdapter(homography=H, homography_inv=H)
    monkeypatch.setattr(
        engine_mod.CourtAdapter,
        "for_match",
        classmethod(lambda cls, _match_id: adapter),
    )

    result = engine_mod.compute_doubles_cv_analytics(match.id, db_session)

    assert result["available"] is True
    summary = result["position_summary"]
    assert summary["court_calibrated"] is True
    assert summary["coordinate_space"] == "court_normalized"
    assert summary["player_a_avg_position"] == [0.25, 0.3]
    assert summary["player_b_avg_position"] == [0.75, 0.7]
    # Proves the stale artifact summary was not reused.
    assert summary["front_back_ratio"] != 0.99
