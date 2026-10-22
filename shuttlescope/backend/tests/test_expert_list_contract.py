"""Expert labeler: 一覧の状態・日付フィルタと clips / labels の応答形式。"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import GameSet, Match, Player, Rally, Stroke, User
from backend.main import app
from backend.routers.expert import _is_plausible_match_date, _review_status
from backend.utils.auth import AuthCtx, get_auth
from backend.utils.jwt_utils import create_access_token


def _admin_ctx() -> AuthCtx:
    return AuthCtx(role="admin", player_id=None, user_id=1, team_name=None, team_id=None)


def _mk_match(db, pa, pb, d: date, *, misses: int, video: str | None = None) -> Match:
    m = Match(
        tournament="T", tournament_level="IC", round="1R", date=d, format="singles",
        player_a_id=pa.id, player_b_id=pb.id, result="win",
        annotation_status="complete", annotation_progress=1.0,
        video_local_path=video,
    )
    db.add(m)
    db.flush()
    gs = GameSet(match_id=m.id, set_num=1, winner="player_a", score_a=21, score_b=10)
    db.add(gs)
    db.flush()
    for i in range(1, misses + 1):
        r = Rally(
            set_id=gs.id, rally_num=i, server="player_a", winner="player_b",
            end_type="forced_error", rally_length=4, score_a_after=0, score_b_after=i,
        )
        db.add(r)
        db.flush()
        db.add(Stroke(
            rally_id=r.id, stroke_num=1, player="player_a", shot_type="smash",
            hit_zone="BC", timestamp_sec=10.0 * i,
        ))
    db.flush()
    return m


@pytest.fixture
def seeded(db_session):
    pa = Player(name="A", dominant_hand="R")
    pb = Player(name="B", dominant_hand="R")
    db_session.add_all([pa, pb])
    db_session.flush()
    old = _mk_match(db_session, pa, pb, date(2025, 1, 10), misses=2, video="x.mp4")
    new = _mk_match(db_session, pa, pb, date(2025, 6, 1), misses=0)
    bad = _mk_match(db_session, pa, pb, date(1, 1, 1), misses=3, video="y.mp4")
    admin_user = User(
        id=900101, username="expert_admin", role="admin",
        totp_enabled=True, consent_required=False,
        awaiting_admin_approval=False, is_test=True,
    )
    db_session.add(admin_user)
    db_session.commit()
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_auth] = _admin_ctx
    token = create_access_token(user_id=admin_user.id, role="admin")
    client = TestClient(app, headers={"Authorization": f"Bearer {token}"})
    try:
        yield client, old, new, bad
    finally:
        app.dependency_overrides.clear()


def test_review_status_covers_each_state():
    assert _review_status(0, 0, True) == "no_targets"
    assert _review_status(5, 0, False) == "no_video"
    assert _review_status(5, 0, True) == "clips_pending"
    assert _review_status(5, 2, True) == "ready"


def test_implausible_dates_are_rejected():
    assert not _is_plausible_match_date(None)
    assert not _is_plausible_match_date(date(1, 1, 1))
    assert not _is_plausible_match_date(date(9999, 12, 31))
    assert _is_plausible_match_date(date(2025, 6, 1))


def test_videos_lists_state_newest_first_and_hides_bad_dates(seeded):
    client, old, new, bad = seeded
    r = client.get("/api/v1/expert/videos")
    assert r.status_code == 200, r.text
    rows = r.json()
    assert [x["match_id"] for x in rows] == [new.id, old.id]
    by_id = {x["match_id"]: x for x in rows}
    assert by_id[new.id]["review_status"] == "no_targets"
    assert by_id[old.id]["review_status"] == "clips_pending"
    assert by_id[old.id]["miss_count"] == 2
    assert by_id[old.id]["has_video"] is True
    assert by_id[old.id]["date"] == "2025-01-10"


def test_clips_and_labels_use_wrapped_shape_with_frame_range(seeded):
    client, old, _new, _bad = seeded
    r = client.get(f"/api/v1/expert/clips?match_id={old.id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["clips"]) == 2
    first = body["clips"][0]
    assert first["clip_start_frame"] == max(0, first["frame_index"] - 90)
    assert first["clip_end_frame"] == first["frame_index"] + 60
    assert first["clip_url"] is None
    r = client.get(f"/api/v1/expert/labels?match_id={old.id}")
    assert r.status_code == 200, r.text
    assert r.json() == {"labels": []}
