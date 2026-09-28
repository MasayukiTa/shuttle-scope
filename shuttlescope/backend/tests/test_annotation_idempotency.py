"""X-8: 再送で注釈が二重に入らないこと。

`src/utils/mobileAnnotateQueue.ts` は毎回 `X-Idempotency-Key` を送る。
再送が起きるのは「サーバは処理したがレスポンスを失った」とき — まさに
あのキューが想定している iOS の背景化・弱電波の状況。
ヘッダを読まないと 1 ラリー・1 打球が二重に入り、`rally_length` と
下流のカウントが静かにずれる。

キューが載せる POST は `POST /api/rallies` と
`POST /api/strokes?rally_id=...` の 2 つ、それに注釈画面の
`POST /api/strokes/batch`。PUT / DELETE は結果が同じなので対象外。
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import GameSet, Match, Player, Rally, Stroke, User
from backend.main import app
from backend.utils.jwt_utils import create_access_token


@pytest.fixture()
def client(db_session, game_set):
    app.dependency_overrides[get_db] = lambda: db_session
    match = db_session.get(Match, game_set.match_id)
    assert match is not None
    user = User(
        username=f"idem-player-{match.player_a_id}",
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
def game_set(db_session) -> GameSet:
    a = Player(name="冪等A", dominant_hand="R")
    b = Player(name="冪等B", dominant_hand="R")
    db_session.add_all([a, b])
    db_session.flush()
    m = Match(
        tournament="冪等テスト", tournament_level="practice", round="R1",
        date=date(2026, 9, 19), format="singles",
        player_a_id=a.id, player_b_id=b.id, result="unknown",
    )
    db_session.add(m)
    db_session.flush()
    gs = GameSet(match_id=m.id, set_num=1)
    db_session.add(gs)
    db_session.flush()
    db_session.commit()
    return gs


def _key(suffix: str) -> dict:
    # 形式: URL-safe / 8-128 文字
    return {"X-Idempotency-Key": f"itest-{suffix}-0001"}


def _simulate_server_restart() -> None:
    """Drop process-local idempotency state while preserving the DB.

    This is the relevant server-restart boundary for an offline client: the
    browser still has the queued X-Idempotency-Key, but the backend process has
    lost every in-memory cache entry and must hydrate the dedup record from DB.
    """
    from backend.utils import idempotency as idem
    with idem._lock:
        idem._records.clear()


class TestRallyCreateIsIdempotent:
    def _body(self, set_id: int) -> dict:
        return {
            "set_id": set_id, "rally_num": 1, "server": "player_a",
            "winner": "player_a", "end_type": "ace", "rally_length": 2,
            "score_a_after": 1, "score_b_after": 0,
        }

    def test_the_same_key_does_not_create_a_second_rally(self, client, db_session, game_set):
        h = _key("rally")
        first = client.post("/api/rallies", json=self._body(game_set.id), headers=h)
        assert first.status_code in (200, 201), first.text
        second = client.post("/api/rallies", json=self._body(game_set.id), headers=h)
        assert second.status_code in (200, 201), second.text
        assert second.json()["data"]["id"] == first.json()["data"]["id"]
        assert db_session.query(Rally).filter(Rally.set_id == game_set.id).count() == 1

    def test_same_rally_key_survives_backend_process_restart(
        self, client, db_session, game_set
    ):
        h = _key("rally-restart")
        first = client.post("/api/rallies", json=self._body(game_set.id), headers=h)
        assert first.status_code in (200, 201), first.text

        _simulate_server_restart()

        retry = client.post("/api/rallies", json=self._body(game_set.id), headers=h)
        assert retry.status_code in (200, 201), retry.text
        assert retry.json()["data"]["id"] == first.json()["data"]["id"]
        assert db_session.query(Rally).filter(Rally.set_id == game_set.id).count() == 1

    @pytest.mark.parametrize("bad", ["short", "has spaces here", "x" * 200, "semi;colon"])
    def test_a_malformed_key_is_refused_rather_than_ignored(self, client, game_set, bad):
        """短すぎる・記号入りのキーを黙って «無し» として扱うと、
        再送防止が効いていないことに誰も気づけない。

        ヘッダ値は latin-1 までなので、ここに日本語は置けない
        (`UnicodeEncodeError` になるだけで、検査の確認にならない)。
        """
        res = client.post("/api/rallies", json=self._body(game_set.id),
                          headers={"X-Idempotency-Key": bad})
        assert res.status_code == 400, res.text


    def test_player_cannot_write_rally_for_an_unrelated_match(
        self, client, db_session
    ):
        outsider_a = Player(name="outsider A", dominant_hand="R")
        outsider_b = Player(name="outsider B", dominant_hand="R")
        db_session.add_all([outsider_a, outsider_b])
        db_session.flush()
        other_match = Match(
            tournament="scope test",
            tournament_level="practice",
            round="R1",
            date=date(2026, 9, 28),
            format="singles",
            player_a_id=outsider_a.id,
            player_b_id=outsider_b.id,
            result="unknown",
        )
        db_session.add(other_match)
        db_session.flush()
        other_set = GameSet(match_id=other_match.id, set_num=1)
        db_session.add(other_set)
        db_session.commit()

        res = client.post(
            "/api/rallies",
            json=self._body(other_set.id),
            headers=_key("foreign-rally"),
        )
        assert res.status_code == 403, res.text
        assert (
            db_session.query(Rally)
            .filter(Rally.set_id == other_set.id)
            .count()
            == 0
        )


class TestStrokeCreateIsIdempotent:
    """キューが載せるもう一つの POST。これだけ冪等化されていなかった。"""

    def _rally(self, client, db_session, game_set) -> int:
        r = Rally(
            set_id=game_set.id, rally_num=1, server="player_a", winner="player_a",
            end_type="ace", rally_length=0,
        )
        db_session.add(r)
        db_session.flush()
        db_session.commit()
        return r.id

    def _body(self) -> dict:
        return {"stroke_num": 1, "player": "player_a", "shot_type": "clear",
                "land_zone": "BL"}

    def test_the_same_key_does_not_create_a_second_stroke(self, client, db_session, game_set):
        rally_id = self._rally(client, db_session, game_set)
        h = _key("stroke")
        first = client.post(f"/api/strokes?rally_id={rally_id}", json=self._body(), headers=h)
        assert first.status_code in (200, 201), first.text
        second = client.post(f"/api/strokes?rally_id={rally_id}", json=self._body(), headers=h)
        assert second.status_code in (200, 201), second.text
        assert second.json()["data"]["id"] == first.json()["data"]["id"]
        assert db_session.query(Stroke).filter(Stroke.rally_id == rally_id).count() == 1

    def test_same_stroke_key_survives_backend_process_restart(
        self, client, db_session, game_set
    ):
        rally_id = self._rally(client, db_session, game_set)
        h = _key("stroke-restart")
        first = client.post(
            f"/api/strokes?rally_id={rally_id}",
            json=self._body(),
            headers=h,
        )
        assert first.status_code in (200, 201), first.text

        _simulate_server_restart()

        retry = client.post(
            f"/api/strokes?rally_id={rally_id}",
            json=self._body(),
            headers=h,
        )
        assert retry.status_code in (200, 201), retry.text
        assert retry.json()["data"]["id"] == first.json()["data"]["id"]
        assert db_session.query(Stroke).filter(Stroke.rally_id == rally_id).count() == 1

    def test_a_different_key_still_records_a_second_stroke(self, client, db_session, game_set):
        """別の打球は別の打球。重複除去が効きすぎて入力が消えては困る。"""
        rally_id = self._rally(client, db_session, game_set)
        client.post(f"/api/strokes?rally_id={rally_id}", json=self._body(), headers=_key("s1"))
        body2 = self._body()
        body2["stroke_num"] = 2
        client.post(f"/api/strokes?rally_id={rally_id}", json=body2, headers=_key("s2"))
        assert db_session.query(Stroke).filter(Stroke.rally_id == rally_id).count() == 2

    def test_without_a_key_nothing_changes(self, client, db_session, game_set):
        """ヘッダを送らない経路は従来どおり。"""
        rally_id = self._rally(client, db_session, game_set)
        client.post(f"/api/strokes?rally_id={rally_id}", json=self._body())
        body2 = self._body()
        body2["stroke_num"] = 2
        client.post(f"/api/strokes?rally_id={rally_id}", json=body2)
        assert db_session.query(Stroke).filter(Stroke.rally_id == rally_id).count() == 2



class TestBatchOfflineReplayIsIdempotent:
    def _body(self, set_id: int) -> dict:
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

    def test_batch_retry_after_backend_restart_does_not_duplicate(
        self, client, db_session, game_set
    ):
        headers = _key("batch-restart")
        first = client.post(
            "/api/strokes/batch",
            json=self._body(game_set.id),
            headers=headers,
        )
        assert first.status_code in (200, 201), first.text
        first_rally_id = first.json()["data"]["rally_id"]

        _simulate_server_restart()

        retry = client.post(
            "/api/strokes/batch",
            json=self._body(game_set.id),
            headers=headers,
        )
        assert retry.status_code in (200, 201), retry.text
        assert retry.json()["data"]["rally_id"] == first_rally_id
        assert db_session.query(Rally).filter(Rally.set_id == game_set.id).count() == 1
        assert db_session.query(Stroke).filter(Stroke.rally_id == first_rally_id).count() == 1



class TestPlayerAnnotationWriteBoundary:
    def test_player_can_update_and_delete_own_rally(self, client, game_set):
        create = client.post(
            "/api/rallies",
            json={
                "set_id": game_set.id,
                "rally_num": 1,
                "server": "player_a",
                "winner": "player_a",
                "end_type": "ace",
                "rally_length": 1,
                "score_a_after": 1,
                "score_b_after": 0,
            },
            headers=_key("own-rally-write"),
        )
        assert create.status_code in (200, 201), create.text
        rally_id = create.json()["data"]["id"]

        update = client.put(
            f"/api/rallies/{rally_id}",
            json={"rally_length": 3},
        )
        assert update.status_code == 200, update.text
        assert update.json()["data"]["rally_length"] == 3

        delete = client.delete(f"/api/rallies/{rally_id}")
        assert delete.status_code == 200, delete.text

    def test_player_annotation_allowlist_does_not_open_generic_writes(self, client):
        # The request body is intentionally incomplete. Middleware must reject
        # the route on role before the matches handler can return validation 422.
        res = client.post("/api/matches", json={})
        assert res.status_code == 403, res.text
