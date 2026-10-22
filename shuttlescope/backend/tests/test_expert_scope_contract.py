"""Expert labeler: team scope of the read routes, the label-save request shape, clip_url.

Cast is the same as test_cross_team_write_scope: team A owns match 1, team B owns match 2.
Each match gets one forced-error rally so it has exactly one miss stroke
(stroke 11 in match 1, stroke 12 in match 2).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.db import models as M
from backend.db.database import get_db
from backend.main import app
from backend.tests.test_cross_team_write_scope import TA, TB, _seed, tok

# The keys ExpertLabelerAnnotatePage.tsx sends (src/utils/expertLabelPayload.ts).
FRONTEND_KEYS = {
    "match_id", "stroke_id", "annotator_role", "posture_collapse",
    "weight_distribution", "shot_timing", "confidence", "comment",
}


def _frontend_body(match_id: int, stroke_id: int) -> dict:
    body = dict(
        match_id=match_id, stroke_id=stroke_id, annotator_role="coach",
        posture_collapse="minor", weight_distribution="center", shot_timing="optimal",
        confidence=3, comment="",
    )
    assert set(body) == FRONTEND_KEYS
    return body


@pytest.fixture
def client(db_session):
    _seed(db_session)
    for rid, set_id, stid in ((11, 1, 11), (12, 2, 12)):
        db_session.add(M.Rally(
            id=rid, set_id=set_id, rally_num=2, server="player_a", winner="player_b",
            end_type="forced_error", rally_length=1,
        ))
        db_session.flush()
        db_session.add(M.Stroke(
            id=stid, rally_id=rid, stroke_num=1, player="player_a", shot_type="clear",
            timestamp_sec=10.0,
        ))
    db_session.flush()
    db_session.add(M.ExpertLabel(
        match_id=1, stroke_id=11, annotator_role="coach", posture_collapse="none",
        weight_distribution="left", shot_timing="late", confidence=2, comment="A-only",
        team_id=TA,
    ))
    db_session.add(M.ExpertLabel(
        match_id=2, stroke_id=12, annotator_role="coach", posture_collapse="major",
        weight_distribution="right", shot_timing="early", confidence=2, comment="B-only",
        team_id=TB,
    ))
    db_session.commit()
    app.dependency_overrides[get_db] = lambda: db_session
    c = TestClient(app, raise_server_exceptions=False, client=("203.0.113.9", 50000))
    try:
        yield c
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("actor", ["cB", "aB"])
@pytest.mark.parametrize("path", [
    "/api/v1/expert/clips?match_id=1",
    "/api/v1/expert/labels?match_id=1",
    "/api/v1/expert/export?match_id=1&fmt=json",
    "/api/v1/expert/export?match_id=1&fmt=csv",
])
def test_foreign_team_cannot_read_match_scoped_routes(client, actor, path):
    r = client.get(path, headers=tok(actor))
    assert r.status_code in (403, 404), (path, r.status_code, r.text[:200])
    assert "A-only" not in r.text


@pytest.mark.parametrize("actor", ["cA", "aA"])
def test_own_team_can_read_match_scoped_routes(client, actor):
    r = client.get("/api/v1/expert/clips?match_id=1", headers=tok(actor))
    assert r.status_code == 200, r.text
    assert [c["stroke_id"] for c in r.json()["clips"]] == [11]
    r = client.get("/api/v1/expert/labels?match_id=1", headers=tok(actor))
    assert r.status_code == 200, r.text
    assert [x["comment"] for x in r.json()["labels"]] == ["A-only"]


def test_player_role_cannot_read_clips(client):
    r = client.get("/api/v1/expert/clips?match_id=1", headers=tok("pA1"))
    assert r.status_code in (403, 404), r.text


def test_progress_counts_only_own_team_matches(client):
    def progress(actor):
        r = client.get("/api/v1/expert/progress?annotator_role=coach", headers=tok(actor))
        assert r.status_code == 200, r.text
        return r.json()

    a = progress("cA")
    assert [p["match_id"] for p in a["per_match"]] == [1]
    assert (a["total"], a["labeled"]) == (1, 1)
    b = progress("cB")
    assert [p["match_id"] for p in b["per_match"]] == [2]
    assert (b["total"], b["labeled"]) == (1, 1)
    admin = progress("admin")
    assert sorted(p["match_id"] for p in admin["per_match"]) == [1, 2]
    assert (admin["total"], admin["labeled"]) == (2, 2)


def test_label_save_accepts_the_frontend_request_shape(client, db_session):
    r = client.post("/api/v1/expert/labels", headers=tok("cA"), json=_frontend_body(1, 11))
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["match_id"], body["stroke_id"], body["posture_collapse"]) == (1, 11, "minor")
    assert db_session.query(M.ExpertLabel).filter_by(stroke_id=11, annotator_role="coach").count() == 1


def test_label_save_rejects_frame_fields_and_skipped_values(client, db_session):
    """Skip must not be saved as a label. The backend keeps rejecting these shapes."""
    with_frames = dict(_frontend_body(1, 11), frame_index=300, clip_start_frame=210, clip_end_frame=360)
    r = client.post("/api/v1/expert/labels", headers=tok("cA"), json=with_frames)
    assert r.status_code == 422, r.text
    skipped = dict(
        _frontend_body(1, 11),
        posture_collapse="skipped", weight_distribution="skipped", shot_timing="skipped",
    )
    r = client.post("/api/v1/expert/labels", headers=tok("cA"), json=skipped)
    assert r.status_code == 422, r.text
    row = db_session.query(M.ExpertLabel).filter_by(stroke_id=11, annotator_role="coach").one()
    assert row.posture_collapse == "none"


def test_clip_url_is_never_a_dangling_link(client, db_session):
    db_session.add(M.ClipCache(
        match_id=1, stroke_id=11, clip_path="x.mp4", start_frame=0, end_frame=150, team_id=TA,
    ))
    db_session.commit()
    r = client.get("/api/v1/expert/clips?match_id=1", headers=tok("cA"))
    assert r.status_code == 200, r.text
    for clip in r.json()["clips"]:
        url = clip["clip_url"]
        if url is not None:
            assert client.get(url, headers=tok("cA")).status_code != 404, url
