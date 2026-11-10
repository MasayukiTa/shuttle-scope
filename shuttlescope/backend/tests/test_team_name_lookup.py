from __future__ import annotations

from datetime import datetime

from backend.db.models import Team
from backend.routers.auth import _find_active_team_by_name, _resolve_team_for_user_create


def _seed(db):
    live = Team(id=9601, display_id="TN-A", name="Sakura Club")
    gone = Team(id=9602, display_id="TN-B", name="Deleted Club", deleted_at=datetime(2026, 1, 1))
    db.add_all([live, gone])
    db.commit()
    return live


def test_lookup_ignores_case_width_and_spacing(db_session):
    live = _seed(db_session)
    for typed in ("Sakura Club", "sakura club", "SAKURA  CLUB", "Ｓａｋｕｒａ　Ｃｌｕｂ", " Sakura Club "):
        found = _find_active_team_by_name(db_session, typed)
        assert found is not None and found.id == live.id, typed


def test_lookup_does_not_merge_different_names_or_deleted_teams(db_session):
    _seed(db_session)
    assert _find_active_team_by_name(db_session, "Sakura Clubs") is None
    assert _find_active_team_by_name(db_session, "Deleted Club") is None
    assert _find_active_team_by_name(db_session, "   ") is None


def test_user_create_reuses_team_instead_of_creating_a_near_duplicate(db_session):
    live = _seed(db_session)
    before = db_session.query(Team).count()
    team = _resolve_team_for_user_create(
        db_session, team_id=None, independent=False, team_name="sakura  club"
    )
    assert team.id == live.id
    assert db_session.query(Team).count() == before
