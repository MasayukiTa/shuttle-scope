"""D-6: 保存済み CV 成果物の backend provenance を API/UI まで運ぶ契約。"""
from __future__ import annotations

import json
from datetime import date

import pytest

from backend.db.models import Match, MatchCVArtifact, Player
from backend.routers.tracknet import get_shuttle_track
from backend.routers.yolo import get_yolo_results


@pytest.fixture()
def match(db_session):
    a = Player(name="D6-A", dominant_hand="R")
    b = Player(name="D6-B", dominant_hand="R")
    db_session.add_all([a, b])
    db_session.flush()
    m = Match(
        tournament="D6 backend visibility",
        tournament_level="practice",
        round="R1",
        date=date(2026, 9, 26),
        format="singles",
        player_a_id=a.id,
        player_b_id=b.id,
        result="unknown",
    )
    db_session.add(m)
    db_session.commit()
    return m


def test_tracknet_shuttle_track_keeps_array_contract_and_exposes_backend(db_session, match):
    frames = [
        {
            "timestamp_sec": 1.0,
            "zone": "MC",
            "confidence": 0.91,
            "x_norm": 0.5,
            "y_norm": 0.4,
        }
    ]
    artifact = MatchCVArtifact(
        match_id=match.id,
        artifact_type="tracknet_shuttle_track",
        frame_count=len(frames),
        backend_used="mock",
        data=json.dumps(frames),
    )
    db_session.add(artifact)
    db_session.commit()

    result = get_shuttle_track(match.id, db_session)

    assert result["success"] is True
    assert result["data"] == frames
    assert isinstance(result["data"], list)
    assert result["meta"]["artifact_id"] == artifact.id
    assert result["meta"]["backend_used"] == "mock"
    assert result["meta"]["frame_count"] == 1
    assert result["meta"]["created_at"]


def test_tracknet_missing_artifact_has_empty_array_and_explicit_empty_meta(db_session, match):
    result = get_shuttle_track(match.id, db_session)

    assert result["success"] is True
    assert result["data"] == []
    assert result["meta"] == {
        "artifact_id": None,
        "backend_used": None,
        "frame_count": None,
        "created_at": None,
    }


def test_yolo_result_already_exposes_saved_backend(db_session, match):
    artifact = MatchCVArtifact(
        match_id=match.id,
        artifact_type="yolo_player_detections",
        frame_count=12,
        backend_used="onnx_cuda",
        summary=json.dumps({"frames": 12}),
        data="[]",
    )
    db_session.add(artifact)
    db_session.commit()

    result = get_yolo_results(match.id, False, db_session)

    assert result["success"] is True
    assert result["data"]["backend_used"] == "onnx_cuda"
    assert result["data"]["frame_count"] == 12
