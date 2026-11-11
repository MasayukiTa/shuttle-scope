"""POST /api/strokes/batch の各成功リクエストにつき、通常のアプリログに
結果が 1 行だけ出ることを検証する。

ゴール: /strokes/batch の成否・再送 (already_saved) ・保存件数を、個人情報を
出さずに通常のアプリログだけで追えるようにする。本テストは:
  - 新規保存で already_saved=False / stroke_count=1 / status=201 の 1 行が出る
  - 再送 (同じ set_id, rally_num) で already_saved=True の 1 行が出る
  - その 1 行に個人情報 / トークン / リクエストボディの値が含まれない
を確かめる。失敗経路は既存の logger.exception が担うので本テストの対象外。

logger の捕捉について: caplog はロガーのレベル / propagate / ハンドラ構成に
左右され、手元では通るが CI のフルスイート xdist 実行では同一ワーカーの
別テストが logger 構成を変えた後に records が空になり落ちる。ここで確かめたい
のは「logger.info へ所定の 1 行を渡しているか」なので、test_error_detail_redaction.py と
同じく logger.info の呼び出しそのものを monkeypatch で捕捉して環境非依存にする。
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import GameSet, Match, Player, User
from backend.main import app
from backend.routers import strokes as strokes_mod
from backend.utils.jwt_utils import create_access_token


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


def _spy_info(monkeypatch) -> list[str]:
    """backend.routers.strokes.logger.info の呼び出し内容を捕捉する。

    caplog の propagate / ハンドラ依存を避け、xdist フルスイートでも
    環境非依存に「所定の 1 行を logger.info へ渡しているか」を検証する。
    """
    calls: list[str] = []
    real_info = strokes_mod.logger.info

    def _spy(fmt, *args, **kwargs):
        try:
            calls.append(str(fmt) % args if args else str(fmt))
        except Exception:  # noqa: BLE001 - 整形失敗時も原文を残す
            calls.append(str(fmt))
        return real_info(fmt, *args, **kwargs)

    monkeypatch.setattr(strokes_mod.logger, "info", _spy)
    return calls


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


def _result_lines(calls: list[str]) -> list[str]:
    return [m for m in calls if "strokes/batch saved" in m]


def test_first_save_logs_one_line_already_saved_false(client, game_set, monkeypatch):
    calls = _spy_info(monkeypatch)
    resp = client.post("/api/strokes/batch", json=_body(game_set.id))
    assert resp.status_code in (200, 201), resp.text

    lines = _result_lines(calls)
    assert len(lines) == 1, lines
    msg = lines[0]
    assert "status=201" in msg
    assert "already_saved=False" in msg
    assert "stroke_count=1" in msg
    assert f"set_id={game_set.id}" in msg
    assert "rally_num=1" in msg


def test_resend_logs_already_saved_true(client, game_set, monkeypatch):
    # 1 回目の保存は計測外 (spy を張る前に打つ)。
    client.post("/api/strokes/batch", json=_body(game_set.id))
    calls = _spy_info(monkeypatch)
    resp = client.post("/api/strokes/batch", json=_body(game_set.id))
    assert resp.status_code in (200, 201), resp.text

    lines = _result_lines(calls)
    assert len(lines) == 1, lines
    msg = lines[0]
    assert "already_saved=True" in msg
    assert "stroke_count=1" in msg


def test_result_line_has_no_pii_token_or_body(
    client, game_set, secret_username, monkeypatch
):
    calls = _spy_info(monkeypatch)
    client.post("/api/strokes/batch", json=_body(game_set.id))

    lines = _result_lines(calls)
    assert len(lines) == 1
    msg = lines[0]
    # 個人識別子 (ユーザー名) を出さない
    assert secret_username not in msg
    # アクセストークンを出さない
    assert getattr(client, "_token") not in msg
    # リクエストボディの自由記述値を出さない
    assert "SECRET_STROKE_NOTE" not in msg
