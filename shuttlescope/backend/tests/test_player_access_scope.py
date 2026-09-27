"""X-7: one visible match must not grant whole-player access."""
from __future__ import annotations

from datetime import date

from backend.db.models import Match, Player, Team
from backend.utils.auth import AuthCtx, can_access_player


def _ctx(role: str, *, team_id: int | None, player_id: int | None = None) -> AuthCtx:
    return AuthCtx(
        role=role,
        player_id=player_id,
        user_id=9001,
        team_name=None,
        team_id=team_id,
    )


def _seed(db_session):
    team_a = Team(name="Scope Team A", display_id="SCOPE-A")
    team_b = Team(name="Scope Team B", display_id="SCOPE-B")
    db_session.add_all([team_a, team_b])
    db_session.flush()

    own = Player(name="Own Player", team_id=team_a.id)
    opponent = Player(name="Opponent Roster", team_id=team_b.id)
    scouted = Player(name="Scouted Opponent", scouting_owner_team_id=team_a.id)
    other_scouted = Player(name="Other Team Scouted", scouting_owner_team_id=team_b.id)
    db_session.add_all([own, opponent, scouted, other_scouted])
    db_session.flush()

    # Team A owns a match against Team B's roster player.  This makes the match
    # visible to Team A, but must not turn the opponent's whole player record
    # into Team A data.
    match = Match(
        tournament="X7 Scope",
        tournament_level="practice",
        round="R1",
        date=date(2026, 9, 27),
        format="singles",
        player_a_id=own.id,
        player_b_id=opponent.id,
        result="win",
        owner_team_id=team_a.id,
    )
    db_session.add(match)
    db_session.commit()
    return team_a, team_b, own, opponent, scouted, other_scouted, match


def test_visible_cross_team_match_does_not_grant_player_scope(db_session):
    team_a, _, _, opponent, _, _, _ = _seed(db_session)

    analyst = _ctx("analyst", team_id=team_a.id)
    coach = _ctx("coach", team_id=team_a.id)

    assert can_access_player(analyst, opponent.id, db_session) is False
    assert can_access_player(coach, opponent.id, db_session) is False


def test_explicit_team_and_scouting_ownership_grant_player_scope(db_session):
    team_a, _, own, _, scouted, other_scouted, _ = _seed(db_session)

    analyst = _ctx("analyst", team_id=team_a.id)
    coach = _ctx("coach", team_id=team_a.id)

    assert can_access_player(analyst, own.id, db_session) is True
    assert can_access_player(coach, own.id, db_session) is True
    assert can_access_player(analyst, scouted.id, db_session) is True
    assert can_access_player(coach, scouted.id, db_session) is True
    assert can_access_player(analyst, other_scouted.id, db_session) is False


def test_admin_and_player_self_rules_are_unchanged(db_session):
    team_a, _, own, opponent, _, _, _ = _seed(db_session)

    admin = _ctx("admin", team_id=None)
    player = _ctx("player", team_id=team_a.id, player_id=own.id)

    assert can_access_player(admin, opponent.id, db_session) is True
    assert can_access_player(player, own.id, db_session) is True
    assert can_access_player(player, opponent.id, db_session) is False
