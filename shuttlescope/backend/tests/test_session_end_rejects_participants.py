"""セッション終了後の参加・ws-ticket・heartbeat 拒否テスト。

POST /api/sessions/{code}/end でセッションを終了したあと、
- /join は 401（存在しない/終了セッションを code oracle にしないため join_invalid と同形）
- /ws-ticket は 404（終了済みを示す）
- /heartbeat（参加者トークン経路）は 401
となり、終了後に新たな入場券や生存更新ができないことを確認する。
"""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.db.database import get_db
from backend.db.models import Player, Match


def _make_match(db) -> Match:
    pa = Player(name="選手A")
    pb = Player(name="選手B")
    db.add_all([pa, pb])
    db.flush()
    m = Match(
        tournament="テスト大会",
        tournament_level="IC",
        round="1回戦",
        date=date(2026, 4, 8),
        format="singles",
        player_a_id=pa.id,
        player_b_id=pb.id,
        result="win",
    )
    db.add(m)
    db.flush()
    return m


@pytest.fixture
def ended_session(db_session):
    """セッションを作り、1 端末を join させてから /end で終了したクライアント。

    戻り値: (client, code, password, participant_id, participant_token)
    """
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app, headers={"X-Role": "analyst"})

    match = _make_match(db_session)
    db_session.commit()

    resp = client.post("/api/sessions", json={"match_id": match.id})
    assert resp.status_code == 201
    data = resp.json()["data"]
    code = data["session_code"]
    password = data["session_password"]

    join = client.post(
        f"/api/sessions/{code}/join",
        json={
            "role": "viewer",
            "device_name": "端末1",
            "device_type": "iphone",
            "session_password": password,
        },
    )
    assert join.status_code == 200
    jdata = join.json()["data"]
    participant_id = jdata["participant_id"]
    participant_token = jdata["participant_token"]

    end = client.post(f"/api/sessions/{code}/end")
    assert end.status_code == 200
    assert end.json()["success"] is True

    yield client, code, password, participant_id, participant_token
    app.dependency_overrides.clear()


class TestSessionEndRejectsParticipants:
    def test_join_rejected_after_end(self, ended_session):
        """終了後は正しいパスワードでも参加できない（401）。"""
        client, code, password, _pid, _tok = ended_session
        resp = client.post(
            f"/api/sessions/{code}/join",
            json={
                "role": "viewer",
                "device_name": "端末2",
                "device_type": "iphone",
                "session_password": password,
            },
        )
        assert resp.status_code == 401

    def test_ws_ticket_rejected_after_end(self, ended_session):
        """終了後は既存参加者トークンでも入場券を取れない（404）。"""
        client, code, _password, pid, tok = ended_session
        resp = client.post(
            f"/api/sessions/{code}/ws-ticket",
            json={
                "role": "device",
                "participant_id": pid,
                "participant_token": tok,
            },
        )
        assert resp.status_code == 404

    def test_heartbeat_rejected_after_end(self, ended_session):
        """終了後は参加者トークン経路の heartbeat が 401 になる。"""
        client, code, _password, pid, tok = ended_session
        resp = client.post(
            f"/api/sessions/{code}/devices/{pid}/heartbeat",
            json={"participant_token": tok},
        )
        assert resp.status_code == 401
