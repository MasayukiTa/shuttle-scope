from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import Match, Player, Team, User
from backend.main import app
from backend.routers.auth import _hash_password
from backend.services import youtube_live_recorder as recorder
from backend.services.youtube_live_recorder import RecordJob
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
    team_a = Team(id=10101, display_id="YT-A", name="YouTube Team A")
    team_b = Team(id=10102, display_id="YT-B", name="YouTube Team B")
    db.add_all([team_a, team_b])
    db.add_all(
        [
            Player(id=10201, name="A1", name_normalized="a1", team_id=team_a.id),
            Player(id=10202, name="A2", name_normalized="a2", team_id=team_a.id),
            Player(id=10203, name="B1", name_normalized="b1", team_id=team_b.id),
            Player(id=10204, name="B2", name_normalized="b2", team_id=team_b.id),
        ]
    )
    db.add_all(
        [
            User(
                id=10301,
                username="yt_coach_a",
                role="coach",
                display_name="YT Coach A",
                hashed_credential=_hash_password("pw"),
                team_id=team_a.id,
                team_name=team_a.name,
            ),
            User(
                id=10302,
                username="yt_coach_b",
                role="coach",
                display_name="YT Coach B",
                hashed_credential=_hash_password("pw"),
                team_id=team_b.id,
                team_name=team_b.name,
            ),
        ]
    )
    foreign_match = Match(
        id=10402,
        tournament="YT Foreign",
        tournament_level="domestic",
        round="QF",
        date=date(2026, 10, 1),
        format="singles",
        result="unknown",
        player_a_id=10203,
        player_b_id=10204,
        owner_team_id=team_b.id,
        is_public_pool=False,
    )
    db.add(foreign_match)
    db.commit()
    return team_a, team_b, foreign_match


def _foreign_job(tmp_path: Path, team_b: Team) -> RecordJob:
    job = RecordJob(
        job_id="foreign-job",
        url="https://example.com/live",
        out_path=tmp_path / "foreign.webm",
        method="drm_pending",
        status="probing",
        owner_user_id=10302,
        owner_team_id=team_b.id,
    )
    recorder._jobs[job.job_id] = job
    return job


def test_cross_team_user_cannot_read_stop_or_append_foreign_job(db_session, tmp_path):
    team_a, team_b, _foreign_match = _seed(db_session)
    job = _foreign_job(tmp_path, team_b)
    app.dependency_overrides[get_db] = lambda: db_session
    headers = _headers(
        user_id=10301,
        role="coach",
        team_id=team_a.id,
        team_name=team_a.name,
    )
    try:
        client = _client()

        status = client.get(f"/api/youtube_live/{job.job_id}/status", headers=headers)
        assert status.status_code == 404, status.text
        assert str(job.out_path) not in status.text

        chunk = client.post(
            f"/api/youtube_live/{job.job_id}/chunk",
            content=b"attacker-data",
            headers={**headers, "Content-Type": "application/octet-stream"},
        )
        assert chunk.status_code == 404, chunk.text
        assert not job.out_path.exists()

        stop = client.post(f"/api/youtube_live/{job.job_id}/stop", headers=headers)
        assert stop.status_code == 404, stop.text
        assert job.status == "probing"

        listing = client.get("/api/youtube_live/jobs", headers=headers)
        assert listing.status_code == 200, listing.text
        assert all(row["job_id"] != job.job_id for row in listing.json())
    finally:
        app.dependency_overrides.clear()
        recorder._jobs.clear()


def test_same_team_operator_can_see_team_job(db_session, tmp_path):
    _team_a, team_b, _foreign_match = _seed(db_session)
    job = _foreign_job(tmp_path, team_b)
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        response = _client().get(
            f"/api/youtube_live/{job.job_id}/status",
            headers=_headers(
                user_id=10302,
                role="coach",
                team_id=team_b.id,
                team_name=team_b.name,
            ),
        )
        assert response.status_code == 200, response.text
        assert response.json()["job_id"] == job.job_id

        listing = _client().get(
            "/api/youtube_live/jobs",
            headers=_headers(
                user_id=10302,
                role="coach",
                team_id=team_b.id,
                team_name=team_b.name,
            ),
        )
        assert listing.status_code == 200, listing.text
        assert [row["job_id"] for row in listing.json()] == [job.job_id]
    finally:
        app.dependency_overrides.clear()
        recorder._jobs.clear()


def test_start_rejects_foreign_match_before_network_probe(db_session, monkeypatch):
    team_a, _team_b, foreign_match = _seed(db_session)
    app.dependency_overrides[get_db] = lambda: db_session
    probe_calls: list[str] = []

    def _probe(*args, **kwargs):
        probe_calls.append("called")
        raise AssertionError("network probe must not run for foreign match")

    monkeypatch.setattr(recorder, "probe_hls", _probe)
    headers = _headers(
        user_id=10301,
        role="coach",
        team_id=team_a.id,
        team_name=team_a.name,
    )
    try:
        response = _client().post(
            "/api/youtube_live/start",
            json={
                "url": "https://example.com/live",
                "quality": "best",
                "match_id": foreign_match.id,
            },
            headers=headers,
        )
        assert response.status_code == 404, response.text
        assert probe_calls == []
    finally:
        app.dependency_overrides.clear()
        recorder._jobs.clear()
