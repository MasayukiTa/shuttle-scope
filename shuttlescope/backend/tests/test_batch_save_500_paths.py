"""batch_save_rally の 500 経路を 500 で終わらせない回帰テスト。

本番 request_logs (2026-11-05) で POST /api/strokes/batch が 92 回 500 を返した。
再現は 2 系統:

  1. 冪等キー無し / 冪等レコードが残らなかった後の自動再送で、同じ
     (set_id, rally_num) が部分一意制約 uq_rallies_set_id_rally_num_active に
     当たり IntegrityError -> 未捕捉 500。本来は『既に保存済み』。
  2. バックエンドの遅延・接続切れで commit/flush が OperationalError /
     DBAPIError -> 未捕捉 500。何も保存されていないのに原因不明の保存失敗に
     見える (仙台大学『保存したはずが保存失敗と出る』)。

期待する直後の挙動:
  - (1) は 201 + already_saved=True で既存ラリーを返し、行は二重化しない。
  - (2) は 503 + saved.rally=False (再送可能) を返し、500 にしない。

テストは固定の鍵・パスワードを書かない。認証は conftest の仕組みに合わせて
create_access_token で発行し、冪等キーはテスト名ごとに動的生成する。
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import DataError, OperationalError

from backend.db.database import get_db
from backend.db.models import GameSet, Match, Player, Rally, Stroke, User
from backend.main import app
from backend.utils.jwt_utils import create_access_token


@pytest.fixture()
def game_set(db_session) -> GameSet:
    a = Player(name="batch500A", dominant_hand="R")
    b = Player(name="batch500B", dominant_hand="R")
    db_session.add_all([a, b])
    db_session.flush()
    m = Match(
        tournament="batch500", tournament_level="practice", round="R1",
        date=date(2026, 11, 5), format="singles",
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
        username=f"batch500-player-{match.player_a_id}",
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


def _body(set_id: int, rally_num: int = 1) -> dict:
    return {
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


class TestKeylessResendHitsUniqueConstraintButIsNot500:
    """冪等キー無しの再送 = 部分一意制約違反。500 ではなく既存を 201 で返す。"""

    def test_second_keyless_post_returns_existing_rally_not_500(
        self, client, db_session, game_set
    ):
        first = client.post("/api/strokes/batch", json=_body(game_set.id))
        assert first.status_code in (200, 201), first.text
        first_rally_id = first.json()["data"]["rally_id"]

        # 冪等キー無しでそのまま再送 (レスポンス喪失後の自動再送に相当)
        second = client.post("/api/strokes/batch", json=_body(game_set.id))
        assert second.status_code in (200, 201), second.text
        body = second.json()
        assert body["data"]["rally_id"] == first_rally_id
        assert body["data"].get("already_saved") is True

        # 二重化していない
        assert (
            db_session.query(Rally)
            .filter(Rally.set_id == game_set.id, Rally.deleted_at.is_(None))
            .count()
            == 1
        )
        assert (
            db_session.query(Stroke)
            .filter(Stroke.rally_id == first_rally_id, Stroke.deleted_at.is_(None))
            .count()
            == 1
        )


class TestDbOutageReturns503NotTransparent500:
    """commit が接続切れで落ちるとき 503 (再送可能) を返し、500 にしない。"""

    def test_commit_operationalerror_becomes_503(
        self, client, db_session, game_set, monkeypatch
    ):
        real_commit = db_session.commit
        calls = {"n": 0}

        def flaky_commit():
            calls["n"] += 1
            # ラリー確定の commit を接続切れで落とす。
            raise OperationalError("COMMIT", {}, Exception("server closed the connection"))

        monkeypatch.setattr(db_session, "commit", flaky_commit)

        res = client.post("/api/strokes/batch", json=_body(game_set.id))
        assert res.status_code == 503, res.text
        detail = res.json()["detail"]
        assert detail["code"] == "DB_UNAVAILABLE_RETRYABLE"
        assert detail["saved"]["rally"] is False
        assert calls["n"] >= 1

        # restore and confirm nothing persisted
        monkeypatch.setattr(db_session, "commit", real_commit)
        db_session.rollback()
        assert (
            db_session.query(Rally).filter(Rally.set_id == game_set.id).count() == 0
        )


def test_commit_dataerror_returns_422(client, db_session, game_set, monkeypatch):
    def rejected_commit():
        raise DataError("COMMIT", {}, ValueError("invalid value"))

    monkeypatch.setattr(db_session, "commit", rejected_commit)
    res = client.post("/api/strokes/batch", json=_body(game_set.id))
    assert res.status_code == 422, res.text
    assert res.json()["detail"] == {
        "code": "BATCH_DATA_REJECTED",
        "message": "保存できない値が含まれています。",
        "error_type": "DataError",
        "saved": {"rally": False, "strokes": 0},
    }
