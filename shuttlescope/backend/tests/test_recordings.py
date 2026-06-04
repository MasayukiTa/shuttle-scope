"""録画/動画スロット API (match 配下, 枝番採番) のテスト。"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.db import database as db_module
from backend.db.models import Match, Player
from backend.utils.jwt_utils import create_access_token


def _bearer(role: str = "analyst", user_id: int = 1) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id=user_id, role=role, minutes=10)}"}


@pytest.fixture()
def match_id() -> int:
    db = db_module.SessionLocal()
    try:
        pa, pb = Player(name="RecA"), Player(name="RecB")
        db.add_all([pa, pb])
        db.flush()
        m = Match(
            tournament="RecTest", tournament_level="IC", round="R1",
            date=date(2026, 4, 12), format="singles",
            player_a_id=pa.id, player_b_id=pb.id, result="win",
        )
        db.add(m)
        db.commit()
        return m.id
    finally:
        db.close()


def test_create_allocates_sequential_branch_no(match_id):
    with TestClient(app) as client:
        nos = []
        for _ in range(3):
            r = client.post(f"/api/matches/{match_id}/recordings", json={"kind": "upload"}, headers=_bearer())
            assert r.status_code == 201, r.text
            nos.append(r.json()["branch_no"])
        assert nos == [1, 2, 3]


def test_live_kind_sets_recording_status(match_id):
    with TestClient(app) as client:
        r = client.post(
            f"/api/matches/{match_id}/recordings",
            json={"kind": "live", "source_kind": "rtmp", "resolution": "1280x720"},
            headers=_bearer(),
        )
        body = r.json()
        assert r.status_code == 201
        assert body["kind"] == "live" and body["status"] == "recording"
        assert body["source_kind"] == "rtmp"
        assert body["video_token"]  # 配信キーが付与される


def test_list_ordered_and_no_internal_path(match_id):
    with TestClient(app) as client:
        client.post(f"/api/matches/{match_id}/recordings", json={"kind": "upload"}, headers=_bearer())
        client.post(f"/api/matches/{match_id}/recordings", json={"kind": "live"}, headers=_bearer())
        r = client.get(f"/api/matches/{match_id}/recordings", headers=_bearer())
        assert r.status_code == 200
        data = r.json()["data"]
        assert [d["branch_no"] for d in data] == sorted(d["branch_no"] for d in data)
        # 内部パスは露出しない
        assert all("video_local_path" not in d for d in data)


def test_patch_updates_status_and_path(match_id):
    with TestClient(app) as client:
        rec = client.post(f"/api/matches/{match_id}/recordings", json={"kind": "live"}, headers=_bearer()).json()
        r = client.patch(
            f"/api/recordings/{rec['id']}",
            json={"status": "ready", "video_local_path": "/var/lib/shuttlescope/videos/x.mp4", "ended": True},
            headers=_bearer(),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ready" and body["ended_at"] is not None
        assert "video_local_path" not in body  # 露出しない


def test_create_unknown_match_404(match_id):
    with TestClient(app) as client:
        r = client.post("/api/matches/99999999/recordings", json={"kind": "upload"}, headers=_bearer())
        assert r.status_code == 404


def test_non_privileged_rejected(match_id):
    with TestClient(app) as client:
        r = client.post(f"/api/matches/{match_id}/recordings", json={"kind": "upload"}, headers=_bearer("player", 77))
        assert r.status_code in (401, 403)
