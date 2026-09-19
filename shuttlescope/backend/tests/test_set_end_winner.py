"""A-8: セット終了のスコアと勝者をサーバで突き合わせる。

旧実装はクライアントが申告した winner をそのまま書いていた。21 点も 2 点差も
30 上限も見ていない。フロントは `scoreA > scoreB` で勝者を決めていたので、
**5-5 で「次のセットへ」を押すと B の勝ちとして確定**した。
勝敗はこの先の全解析の土台なので、ここが緩いと下流が全部ずれる。
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import GameSet, Match, Player
from backend.main import app


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    c = TestClient(app, headers={"X-Role": "admin"})
    yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def game_set(db_session):
    a = Player(name="セット終了A", dominant_hand="R")
    b = Player(name="セット終了B", dominant_hand="R")
    db_session.add_all([a, b])
    db_session.flush()
    m = Match(
        tournament="セット終了テスト",
        tournament_level="practice",
        round="R1",
        date=date(2026, 9, 19),
        format="singles",
        player_a_id=a.id,
        player_b_id=b.id,
        result="unknown",
    )
    db_session.add(m)
    db_session.flush()
    gs = GameSet(match_id=m.id, set_num=1)
    db_session.add(gs)
    db_session.flush()
    db_session.commit()
    return gs


def _end(client, gs, **body):
    return client.put(f"/api/sets/{gs.id}/end", json=body)


class TestSetEndValidatesTheWinner:
    @pytest.mark.parametrize("a,b,winner", [
        (21, 19, "player_a"),
        (19, 21, "player_b"),
        (22, 20, "player_a"),   # デュース
        (30, 29, "player_a"),   # ゴールデンポイント (2点差不要)
        (29, 30, "player_b"),
    ])
    def test_valid_endings_are_accepted(self, client, game_set, a, b, winner):
        res = _end(client, game_set, winner=winner, score_a=a, score_b=b)
        assert res.status_code == 200, res.text
        assert res.json()["data"]["winner"] == winner

    @pytest.mark.parametrize("a,b", [
        (5, 5),      # 同点。旧実装ではフロントが B を勝者にしていた
        (10, 8),     # 21 に届いていない
        (21, 20),    # 2 点差が無い
        (0, 0),
    ])
    def test_unfinished_scores_are_refused(self, client, game_set, a, b):
        res = _end(client, game_set, winner="player_b", score_a=a, score_b=b)
        assert res.status_code == 422, res.text

    def test_wrong_winner_for_a_finished_score_is_refused(self, client, game_set):
        """21-19 なのに B の勝ちだと申告する。"""
        res = _end(client, game_set, winner="player_b", score_a=21, score_b=19)
        assert res.status_code == 422
        assert "player_a" in res.json()["detail"]

    def test_incomplete_allows_closing_an_unfinished_set(self, client, game_set):
        """棄権・中断。明示的に申告したときだけ通す。"""
        res = _end(client, game_set, winner="player_a", score_a=5, score_b=3,
                   incomplete=True)
        assert res.status_code == 200, res.text
        assert res.json()["data"]["winner"] == "player_a"
