"""Regression: analysis routes must exclude skipped and soft-deleted rallies.

Reviewer rvm3 reproduced inflated sample sizes on several analysis routes whose
Rally queries filtered only by set_id. They counted scoreboard-correction pseudo
rallies (is_skipped) and logically deleted rallies (deleted_at set) as if they
were real. This test pins the known answer: given 3 real rallies, 1 skipped, and
1 soft-deleted, the score-progression and first-return routes must report a
sample_size of 3.

Rows are created through the ORM directly (not the API), so every NOT NULL column
without a default is set explicitly (see backend/db/models.py).
"""
from datetime import date, datetime

from backend.db.models import GameSet, Match, Player, Rally, Stroke
from backend.routers.analysis_stable import (
    get_first_return_analysis,
    get_score_progression,
)


def _player(db, name):
    p = Player(name=name)
    db.add(p)
    db.flush()
    return p


def _match(db, a, b):
    m = Match(
        tournament="Test Cup",
        tournament_level="IC",
        round="R1",
        date=date(2026, 1, 1),
        format="singles",
        player_a_id=a.id,
        player_b_id=b.id,
        result="win",
    )
    db.add(m)
    db.flush()
    return m


def _set(db, match):
    s = GameSet(match_id=match.id, set_num=1)
    db.add(s)
    db.flush()
    return s


def _rally(db, game_set, rally_num, *, is_skipped=False, deleted=False):
    # player_a is the receiver on every rally (server is player_b), so these
    # rallies feed get_first_return_analysis for player_a.
    r = Rally(
        set_id=game_set.id,
        rally_num=rally_num,
        server="player_b",
        winner="player_a",
        end_type="forced_error",
        rally_length=4,
        score_a_after=rally_num,
        score_b_after=0,
        is_skipped=is_skipped,
        deleted_at=datetime(2026, 1, 2) if deleted else None,
    )
    db.add(r)
    db.flush()
    # stroke_num==2 in a receiver rally is the player's first return.
    db.add(
        Stroke(
            rally_id=r.id,
            stroke_num=2,
            player="player_a",
            shot_type="clear",
            land_zone="NL",
        )
    )
    db.flush()
    return r


def _seed(db):
    """3 real rallies + 1 skipped + 1 soft-deleted. Known answer: 3 valid."""
    a = _player(db, "A")
    b = _player(db, "B")
    match = _match(db, a, b)
    game_set = _set(db, match)
    _rally(db, game_set, 1)
    _rally(db, game_set, 2)
    _rally(db, game_set, 3)
    _rally(db, game_set, 4, is_skipped=True)
    _rally(db, game_set, 5, deleted=True)
    db.commit()
    return a, match


def test_score_progression_ignores_skipped_and_deleted(db_session):
    _a, match = _seed(db_session)
    resp = get_score_progression(match.id, db=db_session)
    assert resp["success"] is True
    assert resp["meta"]["sample_size"] == 3
    rallies = resp["data"]["sets"][0]["rallies"]
    assert [r["rally_num"] for r in rallies] == [1, 2, 3]


def test_first_return_ignores_skipped_and_deleted(db_session):
    a, _match = _seed(db_session)
    resp = get_first_return_analysis(
        a.id,
        result=None,
        tournament_level=None,
        date_from=None,
        date_to=None,
        db=db_session,
    )
    assert resp["success"] is True
    assert resp["data"]["sample_size"] == 3
    assert resp["meta"]["sample_size"] == 3
