from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import HumanForecast, Match, Player, Team, User
from backend.main import app
from backend.routers.auth import _hash_password
from backend.utils.jwt_utils import create_access_token


def _headers(*, user_id: int, role: str, team_id: int, team_name: str) -> dict[str, str]:
    token = create_access_token(
        user_id=user_id,
        role=role,
        team_id=team_id,
        team_name=team_name,
    )
    return {"Authorization": f"Bearer {token}"}


def _client() -> TestClient:
    return TestClient(app, base_url="http://localhost", raise_server_exceptions=False)


def _seed(db):
    team_a = Team(id=9101, display_id="HF-A", name="Forecast Team A")
    team_b = Team(id=9102, display_id="HF-B", name="Forecast Team B")
    db.add_all([team_a, team_b])

    players = [
        Player(id=9201, name="A1", name_normalized="a1", team_id=team_a.id),
        Player(id=9202, name="A2", name_normalized="a2", team_id=team_a.id),
        Player(id=9203, name="B1", name_normalized="b1", team_id=team_b.id),
        Player(id=9204, name="B2", name_normalized="b2", team_id=team_b.id),
    ]
    db.add_all(players)

    db.add(
        User(
            id=9301,
            username="hf_coach_a",
            role="coach",
            display_name="HF Coach A",
            hashed_credential=_hash_password("pw"),
            team_id=team_a.id,
            team_name=team_a.name,
        )
    )

    own_match = Match(
        id=9401,
        tournament="Forecast A",
        tournament_level="domestic",
        round="QF",
        date=date(2026, 10, 1),
        format="singles",
        result="unknown",
        player_a_id=9201,
        player_b_id=9202,
        owner_team_id=team_a.id,
        is_public_pool=False,
    )
    foreign_match = Match(
        id=9402,
        tournament="Forecast B",
        tournament_level="domestic",
        round="QF",
        date=date(2026, 10, 1),
        format="singles",
        result="unknown",
        player_a_id=9203,
        player_b_id=9204,
        owner_team_id=team_b.id,
        is_public_pool=False,
    )
    db.add_all([own_match, foreign_match])

    # Legacy rows with team_id=NULL are the dangerous case: team filtering alone
    # treats them as globally visible unless match scope is checked first.
    own_legacy = HumanForecast(
        id=9501,
        match_id=own_match.id,
        player_id=9201,
        forecaster_role="coach",
        forecaster_name="legacy-own",
        predicted_outcome="win",
        team_id=None,
    )
    foreign_legacy = HumanForecast(
        id=9502,
        match_id=foreign_match.id,
        player_id=9203,
        forecaster_role="coach",
        forecaster_name="legacy-foreign-secret",
        predicted_outcome="loss",
        team_id=None,
    )
    db.add_all([own_legacy, foreign_legacy])
    db.commit()

    return team_a, own_match, foreign_match, own_legacy, foreign_legacy


def test_human_forecast_list_hides_foreign_match_even_for_legacy_null_team(db_session):
    team_a, _own_match, foreign_match, _own_forecast, foreign_forecast = _seed(db_session)
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        response = _client().get(
            f"/api/prediction/human_forecast/{foreign_match.id}",
            headers=_headers(
                user_id=9301,
                role="coach",
                team_id=team_a.id,
                team_name=team_a.name,
            ),
        )
        assert response.status_code == 404, response.text
        assert "legacy-foreign-secret" not in response.text
        assert str(foreign_forecast.id) not in response.text
    finally:
        app.dependency_overrides.clear()


def test_human_forecast_list_keeps_own_match_legacy_rows_visible(db_session):
    team_a, own_match, _foreign_match, own_forecast, _foreign_forecast = _seed(db_session)
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        response = _client().get(
            f"/api/prediction/human_forecast/{own_match.id}",
            headers=_headers(
                user_id=9301,
                role="coach",
                team_id=team_a.id,
                team_name=team_a.name,
            ),
        )
        assert response.status_code == 200, response.text
        rows = response.json()["data"]
        assert [row["id"] for row in rows] == [own_forecast.id]
    finally:
        app.dependency_overrides.clear()
