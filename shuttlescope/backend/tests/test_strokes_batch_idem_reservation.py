"""冪等キーを「処理の最初」に予約する方式の回帰テスト。

旧実装は commit 成功後にしか冪等レコードを残さなかった (store は commit の後で
しか呼ばれない)。そのため commit より前に失敗したリクエスト — 本番 2026-11-05 の
DB 一過性エラーで 503 を返す経路 — は冪等レコードを残さず、同じ X-Idempotency-Key の
自動再送が本処理を最初からやり直していた。再送が (set_id, rally_num) の一意制約や
strokes の重複を踏み、500 や二重保存に化ける余地があった。

予約方式で守りたい挙動:
  1. commit 前に失敗 (503) したら予約は解放され、**同じキーの再送が成功する**
     (そして二重化しない)。
  2. 成功したリクエストの同じキーでの再送は、本処理を再実行せず保存済み応答を
     replay する。

テストは固定の鍵・パスワードを書かない。認証は conftest の仕組みに合わせて
create_access_token で発行し、冪等キーはテストごとに動的生成する。
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from backend.db.database import get_db
from backend.db.models import GameSet, Match, Player, Rally, Stroke, User
from backend.main import app
from backend.utils.jwt_utils import create_access_token


@pytest.fixture()
def game_set(db_session) -> GameSet:
    a = Player(name="idemresvA", dominant_hand="R")
    b = Player(name="idemresvB", dominant_hand="R")
    db_session.add_all([a, b])
    db_session.flush()
    m = Match(
        tournament="idemresv", tournament_level="practice", round="R1",
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
        username=f"idemresv-player-{match.player_a_id}",
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


def _key() -> str:
    # テストごとに一意なキー。固定値を書かない。
    return "idemresv-" + uuid.uuid4().hex


class TestReservationReleasedOnCommitFailureAllowsRetry:
    """commit 前の 503 で予約が解放され、同じキーの再送が成功する。"""

    def test_503_then_same_key_retry_succeeds_without_duplication(
        self, client, db_session, game_set, monkeypatch
    ):
        key = _key()

        # 1 回目: commit を一過性 DB エラーで落とす -> 503。
        real_commit = db_session.commit

        def flaky_commit():
            raise OperationalError("COMMIT", {}, Exception("server closed the connection"))

        monkeypatch.setattr(db_session, "commit", flaky_commit)
        first = client.post(
            "/api/strokes/batch",
            json=_body(game_set.id),
            headers={"X-Idempotency-Key": key},
        )
        assert first.status_code == 503, first.text
        assert first.json()["detail"]["code"] == "DB_UNAVAILABLE_RETRYABLE"

        # commit を復旧し、何も残っていないことを確認。
        monkeypatch.setattr(db_session, "commit", real_commit)
        db_session.rollback()
        assert db_session.query(Rally).filter(Rally.set_id == game_set.id).count() == 0

        # 2 回目: **同じキー** で再送。予約が解放されているので本処理が走り、201。
        second = client.post(
            "/api/strokes/batch",
            json=_body(game_set.id),
            headers={"X-Idempotency-Key": key},
        )
        assert second.status_code in (200, 201), second.text
        rally_id = second.json()["data"]["rally_id"]

        # 二重化していない。
        assert (
            db_session.query(Rally)
            .filter(Rally.set_id == game_set.id, Rally.deleted_at.is_(None))
            .count()
            == 1
        )
        assert (
            db_session.query(Stroke)
            .filter(Stroke.rally_id == rally_id, Stroke.deleted_at.is_(None))
            .count()
            == 1
        )


class TestSuccessfulRequestReplaysOnResend:
    """成功後の同じキー再送は本処理を再実行せず保存済み応答を replay する。"""

    def test_same_key_after_success_replays_and_does_not_duplicate(
        self, client, db_session, game_set
    ):
        key = _key()
        first = client.post(
            "/api/strokes/batch",
            json=_body(game_set.id),
            headers={"X-Idempotency-Key": key},
        )
        assert first.status_code in (200, 201), first.text
        rally_id = first.json()["data"]["rally_id"]

        second = client.post(
            "/api/strokes/batch",
            json=_body(game_set.id),
            headers={"X-Idempotency-Key": key},
        )
        assert second.status_code in (200, 201), second.text
        # 同じ rally_id を返し、行は 1 つのまま。
        assert second.json()["data"]["rally_id"] == rally_id
        assert (
            db_session.query(Rally)
            .filter(Rally.set_id == game_set.id, Rally.deleted_at.is_(None))
            .count()
            == 1
        )
