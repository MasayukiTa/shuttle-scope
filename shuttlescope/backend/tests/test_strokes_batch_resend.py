"""h18a1: X-Idempotency-Key なしの batch 再送が 500 にならず、ラリーも打球も二重にならないこと。

POST /api/strokes/batch は同じ (set_id, rally_num) のバッチを X-Idempotency-Key 無しで
2 回送ると、以前は db.flush() が UNIQUE 制約 (set_id, rally_num) に当たり
捕捉されず HTTP 500 になっていた。sibling の POST /api/rallies と同じく、
既存の非削除ラリーを返し、打球を足し直さないことを確かめる。
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import GameSet, Match, Player, Rally, Stroke, User
from backend.main import app
from backend.utils.jwt_utils import create_access_token


@pytest.fixture()
def game_set(db_session) -> GameSet:
    a = Player(name="resend A", dominant_hand="R")
    b = Player(name="resend B", dominant_hand="R")
    db_session.add_all([a, b])
    db_session.flush()
    m = Match(
        tournament="resend test", tournament_level="practice", round="R1",
        date=date(2026, 11, 1), format="singles",
        player_a_id=a.id, player_b_id=b.id, result="unknown",
    )
    db_session.add(m)
    db_session.flush()
    gs = GameSet(match_id=m.id, set_num=1)
    db_session.add(gs)
    db_session.flush()
    db_session.commit()
    return gs


@pytest.fixture()
def client(db_session, game_set):
    app.dependency_overrides[get_db] = lambda: db_session
    match = db_session.get(Match, game_set.match_id)
    assert match is not None
    user = User(
        username=f"resend-player-{match.player_a_id}",
        role="player",
        player_id=match.player_a_id,
        awaiting_admin_approval=False,
        consent_required=False,
        is_test=True,
    )
    db_session.add(user)
    db_session.commit()
    token = create_access_token(
        user_id=user.id,
        role="player",
        player_id=match.player_a_id,
        minutes=10,
    )
    c = TestClient(
        app,
        base_url="http://localhost",
        headers={"Authorization": f"Bearer {token}"},
    )
    yield c
    app.dependency_overrides.clear()


def _body(set_id: int) -> dict:
    return {
        "rally": {
            "set_id": set_id,
            "rally_num": 1,
            "server": "player_a",
            "winner": "player_a",
            "end_type": "ace",
            "rally_length": 1,
            "score_a_after": 1,
            "score_b_after": 0,
            "is_deuce": False,
            "annotation_mode": "manual_record",
        },
        "strokes": [
            {
                "stroke_num": 1,
                "player": "player_a",
                "shot_type": "short_service",
                "source_method": "manual",
            }
        ],
    }


def test_resending_same_batch_without_key_does_not_duplicate_or_500(
    client, db_session, game_set
):
    first = client.post("/api/strokes/batch", json=_body(game_set.id))
    assert first.status_code in (200, 201), first.text
    first_rally_id = first.json()["data"]["rally_id"]

    second = client.post("/api/strokes/batch", json=_body(game_set.id))
    assert second.status_code in (200, 201), second.text
    assert second.json()["data"]["rally_id"] == first_rally_id

    rallies = (
        db_session.query(Rally)
        .filter(Rally.set_id == game_set.id, Rally.deleted_at.is_(None))
        .all()
    )
    assert len(rallies) == 1
    strokes = (
        db_session.query(Stroke)
        .filter(Stroke.rally_id == first_rally_id, Stroke.deleted_at.is_(None))
        .all()
    )
    assert len(strokes) == 1
