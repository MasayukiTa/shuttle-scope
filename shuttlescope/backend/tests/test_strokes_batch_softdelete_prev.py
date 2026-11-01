"""POST /api/strokes/batch: score_before を直前ラリーから計算するクエリが
論理削除 (deleted_at) 済みの行を拾わないことを確認する。

rally 1 を保存し deleted_at を立ててから、rally 2 を batch エンドポイントで
保存すると、score_a_before / score_b_before は削除済み rally の得点ではなく
(0, 0) になる。POST /api/rallies が既に行う deleted_at フィルタと同じ規則。
"""
from __future__ import annotations

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import GameSet, Match, Player, Rally, User
from backend.main import app
from backend.utils.jwt_utils import create_access_token


@pytest.fixture()
def game_set(db_session) -> GameSet:
    a = Player(name="SDPREV-A", dominant_hand="R")
    b = Player(name="SDPREV-B", dominant_hand="R")
    db_session.add_all([a, b])
    db_session.flush()
    m = Match(
        tournament="sdprev", tournament_level="practice", round="R1",
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
    user = User(
        username=f"sdprev-player-{match.player_a_id}", role="player",
        player_id=match.player_a_id, awaiting_admin_approval=False,
        consent_required=False, is_test=True,
    )
    db_session.add(user)
    db_session.commit()
    token = create_access_token(
        user_id=user.id, role="player", player_id=match.player_a_id, minutes=10,
    )
    c = TestClient(app, base_url="http://localhost",
                   headers={"Authorization": f"Bearer {token}"})
    yield c
    app.dependency_overrides.clear()


def test_batch_prev_rally_ignores_soft_deleted(client, db_session, game_set):
    # rally 1: 相手が 7 点取った状態で確定させてから論理削除する。
    r1 = Rally(
        set_id=game_set.id, rally_num=1, server="player_a", winner="player_b",
        end_type="forced_error", rally_length=4,
        score_a_before=0, score_b_before=6, score_a_after=0, score_b_after=7,
    )
    db_session.add(r1)
    db_session.flush()
    r1.deleted_at = datetime.utcnow()
    db_session.commit()

    # rally 2 を batch で保存。直前の有効ラリーは無い (r1 は削除済み) ので
    # score_before は (0, 0) でなければならない。
    body = {
        "rally": {
            "set_id": game_set.id, "rally_num": 2, "server": "player_a",
            "winner": "player_a", "end_type": "ace", "rally_length": 1,
            "score_a_after": 1, "score_b_after": 0,
        },
        "strokes": [
            {"stroke_num": 1, "player": "player_a", "shot_type": "short_service"},
        ],
    }
    res = client.post("/api/strokes/batch", json=body)
    assert res.status_code in (200, 201), res.text

    saved = (
        db_session.query(Rally)
        .filter(Rally.set_id == game_set.id, Rally.rally_num == 2)
        .first()
    )
    assert saved is not None
    assert (saved.score_a_before, saved.score_b_before) == (0, 0)
    # 削除済み rally の得点 (0, 7) を引き継いでいないこと。
    assert saved.score_b_before != 7
