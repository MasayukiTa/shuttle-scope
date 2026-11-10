"""strokes/batch が 1 リクエスト = 1 行の結果ログを通常のアプリログに出すこと。

要求: 各 /api/strokes/batch 成功応答について、日時・HTTP status・already_saved か否か・
保存した stroke 数を 1 行で出す。個人情報・トークン・リクエストボディは出さない。既存の
例外ログ (logger.exception) とは重複させない (成功経路のみ)。

caplog はロガーのレベル / propagate / ハンドラ構成に左右されるため、ここでは strokes
ルータのロガーへ専用の logging.Handler を直接付けてレコードを捕捉する (propagate 非依存)。
"""
from __future__ import annotations

import logging
from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import GameSet, Match, Player, Rally, Stroke, User
from backend.main import app
from backend.routers import strokes as strokes_router
from backend.utils.jwt_utils import create_access_token


@pytest.fixture()
def game_set(db_session) -> GameSet:
    a = Player(name="logtest A", dominant_hand="R")
    b = Player(name="logtest B", dominant_hand="R")
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
        username=f"logtest-player-{match.player_a_id}",
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
    yield c, token
    app.dependency_overrides.clear()


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture()
def log_capture():
    """strokes ルータのロガーへ直接ハンドラを付ける (propagate / root 設定に非依存)。"""
    handler = _Capture()
    logger = strokes_router.logger
    prev_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev_level)


def _body(set_id: int, *, rally_num: int = 1, replace: bool = False, final: bool = True) -> dict:
    body = {
        "rally": {
            "set_id": set_id,
            "rally_num": rally_num,
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
    if replace:
        body["replace_strokes"] = True
        body["final"] = final
    return body


def _result_lines(handler: _Capture) -> list[str]:
    return [
        r.getMessage()
        for r in handler.records
        if r.getMessage().startswith("strokes/batch result:")
    ]


def test_first_save_logs_one_result_line(client, game_set, log_capture):
    c, _token = client
    resp = c.post("/api/strokes/batch", json=_body(game_set.id))
    assert resp.status_code in (200, 201), resp.text

    lines = _result_lines(log_capture)
    assert len(lines) == 1, lines
    line = lines[0]
    assert "status=201" in line
    assert "already_saved=False" in line
    assert "replaced=False" in line
    assert "saved_strokes=1" in line


def test_resend_logs_already_saved_true(client, game_set, log_capture):
    c, _token = client
    first = c.post("/api/strokes/batch", json=_body(game_set.id))
    assert first.status_code in (200, 201), first.text
    second = c.post("/api/strokes/batch", json=_body(game_set.id))
    assert second.status_code in (200, 201), second.text

    lines = _result_lines(log_capture)
    # 2 リクエスト = 2 行。2 行目が再送 (already_saved=True)。
    assert len(lines) == 2, lines
    assert "already_saved=False" in lines[0]
    assert "already_saved=True" in lines[1]


def test_replace_logs_replaced_true(client, game_set, log_capture):
    c, _token = client
    first = c.post("/api/strokes/batch", json=_body(game_set.id))
    assert first.status_code in (200, 201), first.text
    repl = c.post(
        "/api/strokes/batch",
        json=_body(game_set.id, replace=True, final=True),
    )
    assert repl.status_code in (200, 201), repl.text

    lines = _result_lines(log_capture)
    assert len(lines) == 2, lines
    assert "replaced=True" in lines[1]
    assert "saved_strokes=1" in lines[1]


def test_result_log_has_no_pii_or_token(client, game_set, log_capture):
    c, token = client
    resp = c.post("/api/strokes/batch", json=_body(game_set.id))
    assert resp.status_code in (200, 201), resp.text

    lines = _result_lines(log_capture)
    assert len(lines) == 1, lines
    line = lines[0]
    # 個人情報・プレイヤー名・ショット種別 (ボディ) やトークンを出さない。
    assert "player_a" not in line
    assert "short_service" not in line
    assert "logtest" not in line
    assert token not in line
    assert "Bearer" not in line
