"""POST /api/strokes/batch が正常終了時に結果を 1 行だけ通常ログ (INFO) に残すこと。

仕様:
  - 初回保存・再送 (already_saved) の双方で、成功 1 回につき INFO ログが 1 行出る。
  - その行に HTTP status(=201)・already_saved 真偽・保存した stroke 数が含まれる。
  - 個人情報・トークン・リクエストボディは出さない (set_id / rally_num / player 名 /
    Authorization ヘッダ値などがログ本文に混ざらないこと)。
  - 既存の例外ログと重複しない (正常終了では ERROR/例外ログが出ない)。

捕捉方法について:
  caplog はロガーのレベル / propagate / ハンドラ構成に左右され、手元では通るが
  CI (全スイートを -n auto --dist loadfile で実行) では空になった。原因は
  backend/main.py が module ロード時に `logging.basicConfig(force=True)` を呼び、
  root のハンドラ (caplog の LogCaptureHandler を含む) を消すため。単体ファイル
  実行では import 順序が違うので通るが、全スイート順では caplog が壊れる。
  test_error_detail_redaction.py と同じく、logger.info の呼び出しそのものを
  monkeypatch で捕捉して環境非依存にする。検証内容 (1 行・status・already_saved・
  stroke 数・非 PII) は一切緩めない。
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import GameSet, Match, Player, User
from backend.main import app
from backend.routers import strokes as strokes_router
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
def client(db_session, game_set):
    app.dependency_overrides[get_db] = lambda: db_session
    match = db_session.get(Match, game_set.match_id)
    assert match is not None
    user = User(
        username=f"result-log-player-{match.player_a_id}",
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


@pytest.fixture()
def info_calls(monkeypatch):
    """strokes ルータの logger.info 呼び出しを捕捉する (環境非依存)。

    caplog は CI で basicConfig(force=True) により root ハンドラが消えて空に
    なるため、呼び出し自体を spy する。整形済みメッセージ文字列を返す。
    """
    calls: list[str] = []
    real_info = strokes_router.logger.info

    def _spy(fmt, *args, **kwargs):
        try:
            calls.append(str(fmt) % args if args else str(fmt))
        except Exception:  # noqa: BLE001 - 整形失敗時も原文を残す
            calls.append(str(fmt))
        return real_info(fmt, *args, **kwargs)

    monkeypatch.setattr(strokes_router.logger, "info", _spy)
    return calls


@pytest.fixture()
def error_calls(monkeypatch):
    """strokes ルータの logger.error / logger.exception 呼び出しを捕捉する。"""
    calls: list[str] = []

    def _make_spy(real):
        def _spy(fmt, *args, **kwargs):
            try:
                calls.append(str(fmt) % args if args else str(fmt))
            except Exception:  # noqa: BLE001
                calls.append(str(fmt))
            return real(fmt, *args, **kwargs)
        return _spy

    monkeypatch.setattr(
        strokes_router.logger, "error", _make_spy(strokes_router.logger.error)
    )
    monkeypatch.setattr(
        strokes_router.logger, "exception", _make_spy(strokes_router.logger.exception)
    )
    return calls


def _batch_log_lines(calls: list[str]) -> list[str]:
    return [m for m in calls if "strokes/batch ok" in m]


def _body(set_id: int) -> dict:
    return {
        "rally": {
            "set_id": set_id,
            "rally_num": 1,
            "server": "player_a",
            "winner": "player_a",
            "end_type": "ace",
            "rally_length": 2,
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
            },
            {
                "stroke_num": 2,
                "player": "player_b",
                "shot_type": "clear",
                "source_method": "manual",
            },
        ],
    }


def test_first_save_emits_one_info_line_with_status_and_counts(
    client, game_set, info_calls
):
    resp = client.post("/api/strokes/batch", json=_body(game_set.id))
    assert resp.status_code in (200, 201), resp.text

    lines = _batch_log_lines(info_calls)
    assert len(lines) == 1, info_calls
    msg = lines[0]
    assert "status=201" in msg
    assert "already_saved=False" in msg
    # 保存した stroke 数 (2) が出る。
    assert "saved_strokes=2" in msg


def test_resend_logs_already_saved_true(client, game_set, info_calls):
    first = client.post("/api/strokes/batch", json=_body(game_set.id))
    assert first.status_code in (200, 201), first.text

    # 初回保存のログを除外し、再送 1 回分だけを測る。
    info_calls.clear()
    second = client.post("/api/strokes/batch", json=_body(game_set.id))
    assert second.status_code in (200, 201), second.text

    lines = _batch_log_lines(info_calls)
    # 再送 1 回につき 1 行。
    assert len(lines) == 1, info_calls
    msg = lines[0]
    assert "already_saved=True" in msg
    assert "status=201" in msg
    # 既存の非削除 stroke 数 (2) を返す。
    assert "saved_strokes=2" in msg


def test_log_line_has_no_pii_or_body_or_token(client, game_set, info_calls):
    resp = client.post("/api/strokes/batch", json=_body(game_set.id))
    assert resp.status_code in (200, 201), resp.text

    lines = _batch_log_lines(info_calls)
    assert len(lines) == 1, info_calls
    msg = lines[0]
    # リクエストボディ由来の値・個人情報・トークンが本文に出ないこと。
    for forbidden in (
        "player_a", "player_b", "short_service", "clear",
        "Bearer", "Authorization", "manual_record",
    ):
        assert forbidden not in msg, f"log leaks {forbidden!r}: {msg}"


def test_successful_save_emits_no_error_log(client, game_set, error_calls):
    resp = client.post("/api/strokes/batch", json=_body(game_set.id))
    assert resp.status_code in (200, 201), resp.text

    # 正常終了では既存の例外ログ (error/exception) と重複しない。
    assert error_calls == [], error_calls
