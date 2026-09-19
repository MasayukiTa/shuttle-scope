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
from backend.db.models import GameSet, Match, Player, Rally, Stroke
from backend.main import app


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    c = TestClient(app, headers={"X-Role": "admin"})
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


class TestRallyCreateIsIdempotent:
    def _body(self, set_id: int) -> dict:
        return {
            "set_id": set_id, "rally_num": 1, "server": "player_a",
            "winner": "player_a", "end_type": "ace", "rally_length": 2,
        }

    def test_the_same_key_does_not_create_a_second_rally(self, client, db_session, game_set):
        h = _key("rally")
        first = client.post("/api/rallies", json=self._body(game_set.id), headers=h)
        assert first.status_code in (200, 201), first.text
        second = client.post("/api/rallies", json=self._body(game_set.id), headers=h)
        assert second.status_code in (200, 201), second.text
        assert second.json()["data"]["id"] == first.json()["data"]["id"]
        assert db_session.query(Rally).filter(Rally.set_id == game_set.id).count() == 1

    def test_a_malformed_key_is_refused_rather_than_ignored(self, client, game_set):
        """短すぎる・記号入りのキーを黙って «無し» として扱うと、
        再送防止が効いていないことに誰も気づけない。"""
        res = client.post("/api/rallies", json=self._body(game_set.id),
                          headers={"X-Idempotency-Key": "短い"})
        assert res.status_code == 400, res.text


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
