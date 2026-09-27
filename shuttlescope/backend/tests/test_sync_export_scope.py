"""Match sync export must not turn one opponent match into cross-team data export."""
from __future__ import annotations

import io
import json
import zipfile
from datetime import date

import pytest
from fastapi import HTTPException

from backend.db.models import Condition, ConditionTag, Match, Player, Team
from backend.services.export_package import export_match
from backend.utils.auth import AuthCtx, check_export_match_scope


def _read_json(pkg: bytes, name: str):
    with zipfile.ZipFile(io.BytesIO(pkg), "r") as zf:
        return json.loads(zf.read(name))


def _seed_cross_team_match(db):
    ta = Team(name="Export Team A", display_id="EXPORT-A")
    tb = Team(name="Export Team B", display_id="EXPORT-B")
    db.add_all([ta, tb])
    db.flush()

    own = Player(
        name="Own Player",
        team_id=ta.id,
        nationality="JP",
        notes="own-note",
        scouting_notes="own-scouting-note",
    )
    opponent = Player(
        name="Opponent Player",
        team_id=tb.id,
        nationality="DK",
        birth_year=2001,
        notes="private-opponent-note",
        scouting_notes="private-opponent-scouting-note",
        team_history='[{"team":"Private Opponent Team"}]',
    )
    db.add_all([own, opponent])
    db.flush()

    match = Match(
        tournament="Scope Test",
        tournament_level="IC",
        round="1R",
        date=date(2026, 9, 27),
        format="singles",
        player_a_id=own.id,
        player_b_id=opponent.id,
        result="win",
        owner_team_id=ta.id,
    )
    db.add(match)
    db.flush()

    db.add_all([
        Condition(
            player_id=own.id,
            measured_at=date(2026, 9, 26),
            condition_type="weekly",
            sleep_hours=7.0,
            injury_notes="own injury",
        ),
        Condition(
            player_id=opponent.id,
            measured_at=date(2026, 9, 26),
            condition_type="weekly",
            sleep_hours=4.0,
            injury_notes="opponent private injury",
        ),
        ConditionTag(
            player_id=own.id,
            label="Own camp",
            start_date=date(2026, 9, 20),
        ),
        ConditionTag(
            player_id=opponent.id,
            label="Opponent private injury period",
            start_date=date(2026, 9, 20),
        ),
    ])
    db.flush()
    return ta, tb, own, opponent, match


def test_analyst_match_export_minimizes_opponent_identity_and_health(db_session):
    ta, _tb, own, opponent, match = _seed_cross_team_match(db_session)

    pkg = export_match(
        db_session,
        [match.id],
        actor_role="analyst",
        actor_team_id=ta.id,
    )

    players = {p["id"]: p for p in _read_json(pkg, "players.json")}
    assert players[own.id]["notes"] == "own-note"
    assert set(players[opponent.id]) == {"id", "uuid", "name"}
    assert players[opponent.id]["name"] == "Opponent Player"

    conditions = _read_json(pkg, "conditions.json")
    assert {row["player_id"] for row in conditions} <= {own.id}
    assert opponent.id not in {row["player_id"] for row in conditions}

    tags = _read_json(pkg, "condition_tags.json")
    assert {row["player_id"] for row in tags} <= {own.id}
    assert opponent.id not in {row["player_id"] for row in tags}


def test_admin_match_export_keeps_full_participant_rows(db_session):
    _ta, _tb, own, opponent, match = _seed_cross_team_match(db_session)

    pkg = export_match(
        db_session,
        [match.id],
        actor_role="admin",
        actor_team_id=None,
    )

    players = {p["id"]: p for p in _read_json(pkg, "players.json")}
    assert players[opponent.id]["notes"] == "private-opponent-note"
    assert players[opponent.id]["team_id"] is not None

    conditions = _read_json(pkg, "conditions.json")
    assert {row["player_id"] for row in conditions} == {own.id, opponent.id}
    tags = _read_json(pkg, "condition_tags.json")
    assert {row["player_id"] for row in tags} == {own.id, opponent.id}


def test_match_export_scope_uses_team_id_not_mutable_team_name(db_session):
    ta, tb, _own, _opponent, match = _seed_cross_team_match(db_session)

    ctx = AuthCtx(
        role="analyst",
        player_id=None,
        user_id=100,
        team_name="stale-name-after-rename",
        team_id=ta.id,
    )
    check_export_match_scope(ctx, [match], db_session)

    # team_name が一致していても、実体の team_id が参加チームでなければ拒否。
    wrong_team = AuthCtx(
        role="analyst",
        player_id=None,
        user_id=101,
        team_name="Export Team A",
        team_id=9_999_999,
    )
    with pytest.raises(HTTPException) as exc:
        check_export_match_scope(wrong_team, [match], db_session)
    assert exc.value.status_code == 403
