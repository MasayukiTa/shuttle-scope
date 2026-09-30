from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import (
    AnalysisJob,
    Match,
    MatchCVArtifact,
    Player,
    Team,
    User,
)
from backend.main import app
from backend.routers.auth import _hash_password
from backend.utils.jwt_utils import create_access_token


def _token(*, role: str, user_id: int, team_id: int, team_name: str) -> str:
    return create_access_token(
        user_id=user_id,
        role=role,
        team_id=team_id,
        team_name=team_name,
    )


def _headers(*, role: str, user_id: int, team_id: int, team_name: str) -> dict[str, str]:
    return {
        "Authorization": (
            "Bearer "
            + _token(
                role=role,
                user_id=user_id,
                team_id=team_id,
                team_name=team_name,
            )
        )
    }


def _seed_two_teams(db):
    team_a = Team(id=8101, display_id="IDOR-A", name="IDOR Team A")
    team_b = Team(id=8102, display_id="IDOR-B", name="IDOR Team B")
    db.add_all([team_a, team_b])

    players = [
        Player(id=8201, name="A1", name_normalized="a1", team_id=team_a.id),
        Player(id=8202, name="A2", name_normalized="a2", team_id=team_a.id),
        Player(id=8203, name="B1", name_normalized="b1", team_id=team_b.id),
        Player(id=8204, name="B2", name_normalized="b2", team_id=team_b.id),
    ]
    db.add_all(players)

    users = [
        User(
            id=8301,
            username="idor_analyst_a",
            role="analyst",
            display_name="Analyst A",
            hashed_credential=_hash_password("pw"),
            team_id=team_a.id,
            team_name=team_a.name,
        ),
        User(
            id=8302,
            username="idor_coach_a",
            role="coach",
            display_name="Coach A",
            hashed_credential=_hash_password("pw"),
            team_id=team_a.id,
            team_name=team_a.name,
        ),
    ]
    db.add_all(users)

    own_match = Match(
        id=8401,
        tournament="IDOR Cup A",
        tournament_level="domestic",
        round="QF",
        date=date(2026, 9, 30),
        format="singles",
        result="unknown",
        player_a_id=8201,
        player_b_id=8202,
        owner_team_id=team_a.id,
        is_public_pool=False,
    )
    foreign_match = Match(
        id=8402,
        tournament="IDOR Cup B",
        tournament_level="domestic",
        round="QF",
        date=date(2026, 9, 30),
        format="singles",
        result="unknown",
        player_a_id=8203,
        player_b_id=8204,
        owner_team_id=team_b.id,
        is_public_pool=False,
    )
    db.add_all([own_match, foreign_match])

    # Pipeline run requires a non-empty court calibration artifact. Keeping both
    # matches calibrated ensures the attack reaches authorization rather than
    # being accidentally blocked by the privacy precondition.
    db.add_all(
        [
            MatchCVArtifact(
                match_id=own_match.id,
                artifact_type="court_calibration",
                summary='{"ready":true}',
            ),
            MatchCVArtifact(
                match_id=foreign_match.id,
                artifact_type="court_calibration",
                summary='{"ready":true}',
            ),
        ]
    )

    own_job = AnalysisJob(
        id=8501,
        match_id=own_match.id,
        job_type="full_pipeline",
        status="done",
        progress=1.0,
    )
    foreign_job = AnalysisJob(
        id=8502,
        match_id=foreign_match.id,
        job_type="full_pipeline",
        status="done",
        progress=1.0,
        worker_host="foreign-worker",
        error="foreign-private-error",
    )
    db.add_all([own_job, foreign_job])
    db.commit()

    return {
        "team_a": team_a,
        "team_b": team_b,
        "own_match": own_match,
        "foreign_match": foreign_match,
        "own_job": own_job,
        "foreign_job": foreign_job,
    }


def test_pipeline_job_list_is_team_scoped_for_analyst_and_coach(db_session):
    seeded = _seed_two_teams(db_session)
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app, raise_server_exceptions=False)
        for role, uid in (("analyst", 8301), ("coach", 8302)):
            response = client.get(
                "/api/v1/pipeline/jobs",
                headers=_headers(
                    role=role,
                    user_id=uid,
                    team_id=seeded["team_a"].id,
                    team_name=seeded["team_a"].name,
                ),
            )
            assert response.status_code == 200, response.text
            ids = {row["id"] for row in response.json()}
            assert ids == {seeded["own_job"].id}
            assert seeded["foreign_job"].id not in ids
    finally:
        app.dependency_overrides.clear()


def test_pipeline_job_detail_hides_cross_team_job_from_analyst_and_coach(db_session):
    seeded = _seed_two_teams(db_session)
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app, raise_server_exceptions=False)
        for role, uid in (("analyst", 8301), ("coach", 8302)):
            response = client.get(
                f"/api/v1/pipeline/jobs/{seeded['foreign_job'].id}",
                headers=_headers(
                    role=role,
                    user_id=uid,
                    team_id=seeded["team_a"].id,
                    team_name=seeded["team_a"].name,
                ),
            )
            assert response.status_code == 404, response.text
            assert "foreign-private-error" not in response.text
            assert "foreign-worker" not in response.text
    finally:
        app.dependency_overrides.clear()


def test_pipeline_run_cannot_enqueue_cross_team_match(db_session):
    seeded = _seed_two_teams(db_session)
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        before = db_session.query(AnalysisJob).count()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/api/v1/pipeline/run",
            json={"match_id": seeded["foreign_match"].id, "job_type": "full_pipeline"},
            headers=_headers(
                role="analyst",
                user_id=8301,
                team_id=seeded["team_a"].id,
                team_name=seeded["team_a"].name,
            ),
        )

        assert response.status_code == 404, response.text
        db_session.expire_all()
        assert db_session.query(AnalysisJob).count() == before
        assert (
            db_session.query(AnalysisJob)
            .filter(
                AnalysisJob.match_id == seeded["foreign_match"].id,
                AnalysisJob.status.in_(("queued", "running")),
            )
            .count()
            == 0
        )
    finally:
        app.dependency_overrides.clear()


def test_pipeline_run_allows_own_team_match(db_session):
    seeded = _seed_two_teams(db_session)
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            "/api/v1/pipeline/run",
            json={"match_id": seeded["own_match"].id, "job_type": "full_pipeline"},
            headers=_headers(
                role="analyst",
                user_id=8301,
                team_id=seeded["team_a"].id,
                team_name=seeded["team_a"].name,
            ),
        )
        assert response.status_code == 200, response.text
        assert response.json()["match_id"] == seeded["own_match"].id
    finally:
        app.dependency_overrides.clear()
