"""X-9: sync conflict review must obey team ownership."""
from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.db.models import (
    Team,
    Player,
    Match,
    GameSet,
    Rally,
    Stroke,
    SyncConflict,
)
from backend.routers.sync import (
    ConflictResolveBody,
    list_conflicts,
    resolve_conflict,
)
from backend.utils.sync_meta import business_payload, compute_content_hash


def _ctx(team_id: int | None, *, admin: bool = False):
    return SimpleNamespace(team_id=team_id, is_admin=admin, is_analyst=not admin)


def _seed(db):
    ta = Team(name="Conflict Team A")
    tb = Team(name="Conflict Team B")
    db.add_all([ta, tb])
    db.flush()

    pa1 = Player(name="A1", dominant_hand="R", team_id=ta.id)
    pa2 = Player(name="A2", dominant_hand="R", team_id=ta.id)
    pb1 = Player(name="B1", dominant_hand="R", team_id=tb.id)
    pb2 = Player(name="B2", dominant_hand="R", team_id=tb.id)
    db.add_all([pa1, pa2, pb1, pb2])
    db.flush()

    ma = Match(
        tournament="A tournament",
        tournament_level="practice",
        round="R1",
        date=date(2026, 9, 27),
        format="singles",
        player_a_id=pa1.id,
        player_b_id=pa2.id,
        result="unknown",
        owner_team_id=ta.id,
    )
    mb = Match(
        tournament="B tournament",
        tournament_level="practice",
        round="R1",
        date=date(2026, 9, 27),
        format="singles",
        player_a_id=pb1.id,
        player_b_id=pb2.id,
        result="unknown",
        owner_team_id=tb.id,
    )
    db.add_all([ma, mb])
    db.flush()

    gs = GameSet(match_id=ma.id, set_num=1)
    db.add(gs)
    db.flush()
    rally = Rally(
        set_id=gs.id,
        rally_num=1,
        server="player_a",
        winner="player_a",
        end_type="winner",
        rally_length=1,
    )
    db.add(rally)
    db.flush()
    stroke = Stroke(rally_id=rally.id, stroke_num=1, player="player_a", shot_type="clear")
    db.add(stroke)
    db.flush()

    conflicts = [
        SyncConflict(
            record_table="matches",
            record_uuid=ma.uuid,
            reason="a-match",
            incoming_snapshot=json.dumps({
                "uuid": ma.uuid,
                "tournament": "incoming A",
                "owner_team_id": tb.id,
                "player_a_id": 999999,
                "updated_at": "2026-09-27T09:00:00",
            }),
        ),
        SyncConflict(
            record_table="matches",
            record_uuid=mb.uuid,
            reason="b-match",
            incoming_snapshot=json.dumps({
                "uuid": mb.uuid,
                "tournament": "incoming B",
                "updated_at": "2026-09-27T09:00:00",
            }),
        ),
        SyncConflict(
            record_table="strokes",
            record_uuid=stroke.uuid,
            reason="a-stroke",
            incoming_snapshot=json.dumps({
                "uuid": stroke.uuid,
                "shot_type": "smash",
                "rally_id": 123456,
                "updated_at": "2026-09-27T09:00:00",
            }),
        ),
    ]
    db.add_all(conflicts)
    db.commit()
    return ta, tb, ma, mb, stroke, conflicts


def test_analyst_lists_only_own_team_conflicts_including_child_rows(db_session):
    ta, _tb, _ma, _mb, _stroke, conflicts = _seed(db_session)

    result = list_conflicts(db_session, _ctx(ta.id))

    ids = {row["id"] for row in result["data"]}
    assert ids == {conflicts[0].id, conflicts[2].id}


def test_admin_lists_all_conflicts(db_session):
    _ta, _tb, _ma, _mb, _stroke, conflicts = _seed(db_session)

    result = list_conflicts(db_session, _ctx(None, admin=True))

    assert {row["id"] for row in result["data"]} == {c.id for c in conflicts}


def test_other_team_cannot_even_keep_local(db_session):
    ta, _tb, _ma, _mb, _stroke, conflicts = _seed(db_session)
    other = conflicts[1]

    with pytest.raises(HTTPException) as exc:
        resolve_conflict(
            other.id,
            ConflictResolveBody(resolution="keep_local"),
            db_session,
            _ctx(ta.id),
        )

    assert exc.value.status_code == 404
    db_session.expire_all()
    assert db_session.get(SyncConflict, other.id).resolution is None


def test_own_child_conflict_can_be_resolved_by_parent_match_owner(db_session):
    ta, _tb, _ma, _mb, _stroke, conflicts = _seed(db_session)
    child = conflicts[2]

    result = resolve_conflict(
        child.id,
        ConflictResolveBody(resolution="keep_local"),
        db_session,
        _ctx(ta.id),
    )

    assert result["success"] is True
    db_session.expire_all()
    assert db_session.get(SyncConflict, child.id).resolution == "keep_local"


def test_use_incoming_cannot_move_owner_or_foreign_keys_and_refreshes_hash(db_session):
    ta, tb, ma, _mb, _stroke, conflicts = _seed(db_session)
    conflict = conflicts[0]
    original_player_a = ma.player_a_id
    original_revision = ma.revision

    result = resolve_conflict(
        conflict.id,
        ConflictResolveBody(resolution="use_incoming"),
        db_session,
        _ctx(ta.id),
    )

    assert result["success"] is True
    db_session.expire_all()
    refreshed = db_session.get(Match, ma.id)
    assert refreshed.tournament == "incoming A"
    assert refreshed.owner_team_id == ta.id
    assert refreshed.owner_team_id != tb.id
    assert refreshed.player_a_id == original_player_a
    assert refreshed.revision == original_revision + 1
    assert refreshed.content_hash == compute_content_hash(business_payload(refreshed))
