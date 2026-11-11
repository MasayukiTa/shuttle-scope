"""POST /api/strokes/batch が各リクエストの結果を通常のアプリログに 1 行残すこと。

ログには HTTP status・already_saved か否か・保存した打球数だけを出し、個人情報・
トークン・リクエストボディは出さない。初回保存では already_saved=False、
X-Idempotency-Key なしの同一バッチ再送では already_saved=True のログが 1 行出る。
成功経路 (status 201) のみログし、失敗経路の既存の例外ログとは重複させない。
"""
from __future__ import annotations

import logging
from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import GameSet, Match, Player, User
from backend.main import app
from backend.utils.jwt_utils import create_access_token

LOGGER_NAME = "backend.routers.strokes"


@pytest.fixture()
def game_set(db_session) -> GameSet:
    a = Player(name="log A", dominant_hand="R")
    b = Player(name="log B", dominant_hand="R")
    db_session.add_all([a, b])
    db_session.flush()
    m = Match(
        tournament="log test", tournament_level="practice", round="R1",
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
        username=f"log-player-{match.player_a_id}",
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


def _result_lines(caplog) -> list[logging.LogRecord]:
    return [
        r
        for r in caplog.records
        if r.name == LOGGER_NAME and r.getMessage().startswith("strokes/batch result:")
    ]


def test_first_save_logs_one_result_line(client, game_set, caplog):
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        resp = client.post("/api/strokes/batch", json=_body(game_set.id))
    assert resp.status_code in (200, 201), resp.text

    lines = _result_lines(caplog)
    assert len(lines) == 1, [r.getMessage() for r in lines]
    msg = lines[0].getMessage()
    assert "status=201" in msg
    assert "already_saved=False" in msg
    assert "stroke_count=1" in msg


def test_resend_logs_already_saved_true(client, game_set, caplog):
    first = client.post("/api/strokes/batch", json=_body(game_set.id))
    assert first.status_code in (200, 201), first.text

    # 初回保存のログを捨て、再送分だけを捕捉する。
    caplog.clear()
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        second = client.post("/api/strokes/batch", json=_body(game_set.id))
    assert second.status_code in (200, 201), second.text

    lines = _result_lines(caplog)
    assert len(lines) == 1, [r.getMessage() for r in lines]
    msg = lines[0].getMessage()
    assert "status=201" in msg
    assert "already_saved=True" in msg
    assert "stroke_count=1" in msg


def test_result_log_has_no_pii_or_body(client, game_set, caplog):
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        resp = client.post("/api/strokes/batch", json=_body(game_set.id))
    assert resp.status_code in (200, 201), resp.text

    lines = _result_lines(caplog)
    assert len(lines) == 1
    msg = lines[0].getMessage()
    # 個人情報・トークン・ボディ由来の値を出さないこと。
    for forbidden in ("player_a", "short_service", "Bearer", "log-player", "manual_record"):
        assert forbidden not in msg, msg
