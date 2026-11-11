"""POST /api/strokes/batch の各成功リクエストにつき、通常のアプリログに
結果が 1 行だけ出ることを検証する。

ゴール: /strokes/batch の成否・再送 (already_saved) ・保存件数を、個人情報を
出さずに通常のアプリログだけで追えるようにする。本テストは:
  - 新規保存で already_saved=False / stroke_count=1 / status=201 の 1 行が出る
  - 再送 (同じ set_id, rally_num) で already_saved=True の 1 行が出る
  - その 1 行に個人情報 / トークン / リクエストボディの値が含まれない
を確かめる。失敗経路は既存の logger.exception が担うので本テストの対象外。
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
        tournament="result-log test", tournament_level="practice", round="R1",
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
def secret_username(db_session, game_set) -> str:
    """ログに漏れてはいけない個人識別子 (ユーザー名) を返す。"""
    match = db_session.get(Match, game_set.match_id)
    return f"secret-player-{match.player_a_id}"


@pytest.fixture()
def client(db_session, game_set, secret_username):
    app.dependency_overrides[get_db] = lambda: db_session
    match = db_session.get(Match, game_set.match_id)
    assert match is not None
    user = User(
        username=secret_username,
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
    c._token = token  # type: ignore[attr-defined]
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
                "intent_note": "SECRET_STROKE_NOTE",
            }
        ],
    }


def _result_lines(caplog) -> list[logging.LogRecord]:
    return [
        r
        for r in caplog.records
        if r.name == LOGGER_NAME and "strokes/batch saved" in r.getMessage()
    ]


def test_first_save_logs_one_line_already_saved_false(client, game_set, caplog):
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        resp = client.post("/api/strokes/batch", json=_body(game_set.id))
    assert resp.status_code in (200, 201), resp.text

    lines = _result_lines(caplog)
    assert len(lines) == 1, [r.getMessage() for r in lines]
    msg = lines[0].getMessage()
    assert "status=201" in msg
    assert "already_saved=False" in msg
    assert "stroke_count=1" in msg
    assert f"set_id={game_set.id}" in msg
    assert "rally_num=1" in msg


def test_resend_logs_already_saved_true(client, game_set, caplog):
    client.post("/api/strokes/batch", json=_body(game_set.id))
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        # 1 回目の保存で出た already_saved=False の行を計測から除く。
        # caplog は at_level ブロックの外で出たレコードも records に溜め続けるため、
        # 再送分だけを見るには 2 回目の直前でクリアする。
        caplog.clear()
        resp = client.post("/api/strokes/batch", json=_body(game_set.id))
    assert resp.status_code in (200, 201), resp.text

    lines = _result_lines(caplog)
    assert len(lines) == 1, [r.getMessage() for r in lines]
    msg = lines[0].getMessage()
    assert "already_saved=True" in msg
    assert "stroke_count=1" in msg


def test_result_line_has_no_pii_token_or_body(
    client, game_set, secret_username, caplog
):
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        client.post("/api/strokes/batch", json=_body(game_set.id))

    lines = _result_lines(caplog)
    assert len(lines) == 1
    msg = lines[0].getMessage()
    # 個人識別子 (ユーザー名) を出さない
    assert secret_username not in msg
    # アクセストークンを出さない
    assert getattr(client, "_token") not in msg
    # リクエストボディの自由記述値を出さない
    assert "SECRET_STROKE_NOTE" not in msg
