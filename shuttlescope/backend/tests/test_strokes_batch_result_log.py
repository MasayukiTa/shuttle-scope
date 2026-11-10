"""strokes/batch の各リクエスト結果が通常のアプリログに 1 行ずつ出ることの検査。

POST /api/strokes/batch は成功経路 (新規保存・already_saved 再送・置き換え) の
どれを通っても、結果を 1 行 INFO ログに残す。ログには HTTP status・already_saved
か否か・保存した stroke 数・非個人の識別子 (set_id / rally_num) だけを出し、
個人情報・トークン・リクエストボディは出さない。既存の例外ログ
(logger.exception) と重複しないこと (成功経路では exception ログが出ない) も
併せて確かめる。
"""
from __future__ import annotations

import logging
from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import GameSet, Match, Player, Rally, Stroke, User
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
        tournament="result log test", tournament_level="practice", round="R1",
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


def test_new_save_emits_one_result_log_line(client, game_set, caplog):
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        resp = client.post("/api/strokes/batch", json=_body(game_set.id))
    assert resp.status_code in (200, 201), resp.text

    lines = _result_lines(caplog)
    assert len(lines) == 1
    msg = lines[0].getMessage()
    assert lines[0].levelno == logging.INFO
    # 新規保存なので already_saved=False、保存した stroke 数は 1。
    assert "status=201" in msg
    assert "already_saved=False" in msg
    assert "stroke_count=1" in msg
    assert f"set_id={game_set.id}" in msg
    assert "rally_num=1" in msg


def test_resend_emits_already_saved_result_log_line(client, game_set, caplog):
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        first = client.post("/api/strokes/batch", json=_body(game_set.id))
        assert first.status_code in (200, 201), first.text
        # 初回保存の結果行を捨て、再送分だけを捕捉する (caplog.records は
        # テスト関数単位で蓄積されるため、at_level だけでは消えない)。
        caplog.clear()
        second = client.post("/api/strokes/batch", json=_body(game_set.id))
    assert second.status_code in (200, 201), second.text

    lines = _result_lines(caplog)
    # 再送の 1 回分だけが残る。
    assert len(lines) == 1
    msg = lines[0].getMessage()
    # 同じ (set_id, rally_num) の再送は already_saved=True で返り、打球は足さない。
    assert "already_saved=True" in msg
    assert "stroke_count=1" in msg


def test_result_log_has_no_body_token_or_pii(client, game_set, caplog):
    token = client.headers["Authorization"].split(" ", 1)[1]
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        resp = client.post("/api/strokes/batch", json=_body(game_set.id))
    assert resp.status_code in (200, 201), resp.text

    lines = _result_lines(caplog)
    assert len(lines) == 1
    msg = lines[0].getMessage()
    # トークン・選手名 (個人情報)・自由記述やボディの中身を出さない。
    assert token not in msg
    assert "Bearer" not in msg
    assert "log A" not in msg
    assert "log B" not in msg
    assert "player_a" not in msg
    assert "short_service" not in msg
    assert "source_method" not in msg


def test_success_path_emits_no_exception_log(client, game_set, caplog):
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        resp = client.post("/api/strokes/batch", json=_body(game_set.id))
    assert resp.status_code in (200, 201), resp.text

    # 成功経路では例外ログ (logger.exception = ERROR) を出さない。結果ログと
    # 二重に出さないことの担保。
    errors = [
        r for r in caplog.records
        if r.name == LOGGER_NAME and r.levelno >= logging.ERROR
    ]
    assert errors == []
