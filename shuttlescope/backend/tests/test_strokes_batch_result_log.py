"""strokes/batch の各リクエスト結果が 1 行のアプリログに出ることを確認する。

batch_save_rally は成功時に INFO ログを 1 行だけ出す:
    strokes/batch result: ts=... status=201 already_saved=<bool> stroke_count=<n>

狙い:
  - 初回保存は already_saved=False, 保存した stroke 数を出す。
  - 同じ (set_id, rally_num) の再送は already_saved=True を出す (打球は足し直さない)。
  - 個人情報・トークン・リクエストボディはログに出さない (ログ本文で確認)。

既存の flush/commit 失敗の logger.exception とは別経路 (成功時のみ) なので、
正常系のこのログと例外ログは重複しない。
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

LOG_PREFIX = "strokes/batch result:"


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


def _result_lines(caplog) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.getMessage().startswith(LOG_PREFIX)
    ]


def test_first_save_emits_one_result_log_line(client, game_set, caplog):
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="backend.routers.strokes"):
        resp = client.post("/api/strokes/batch", json=_body(game_set.id))
    assert resp.status_code in (200, 201), resp.text

    lines = _result_lines(caplog)
    # リクエスト 1 回につきちょうど 1 行。
    assert len(lines) == 1, lines
    line = lines[0]
    assert "status=201" in line
    assert "already_saved=False" in line
    assert "stroke_count=1" in line
    # 日時 (UTC ISO) が入っている。
    assert "ts=" in line


def test_resend_logs_already_saved_true(client, db_session, game_set, caplog):
    # 初回保存。
    first = client.post("/api/strokes/batch", json=_body(game_set.id))
    assert first.status_code in (200, 201), first.text
    first_rally_id = first.json()["data"]["rally_id"]

    # 初回保存のログ行は対象外。再送 1 回分だけを見る。
    caplog.clear()
    # 同じ (set_id, rally_num) を X-Idempotency-Key なしで再送。
    with caplog.at_level(logging.INFO, logger="backend.routers.strokes"):
        second = client.post("/api/strokes/batch", json=_body(game_set.id))
    assert second.status_code in (200, 201), second.text

    lines = _result_lines(caplog)
    assert len(lines) == 1, lines
    line = lines[0]
    assert "status=201" in line
    assert "already_saved=True" in line
    # 再送でも打球は足し直さないので stroke_count は 1 のまま。
    assert "stroke_count=1" in line

    # DB 上もラリー 1・打球 1 のまま (再送で二重に入らない)。
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


def test_log_line_contains_no_pii_or_token(client, game_set, caplog):
    token_fragment = client.headers["Authorization"].split(" ", 1)[1][:16]
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="backend.routers.strokes"):
        resp = client.post("/api/strokes/batch", json=_body(game_set.id))
    assert resp.status_code in (200, 201), resp.text

    line = _result_lines(caplog)[0]
    # トークン・選手名・意図ノート等の本文がログに混ざらないこと。
    assert token_fragment not in line
    assert "log A" not in line
    assert "short_service" not in line
    assert "Bearer" not in line
