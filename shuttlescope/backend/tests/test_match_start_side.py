"""C-8: 「セット1開始時に player_a が画面のどちら側に居たか」を試合に保存する。

これは **試合の事実** だが、これまで注釈者のブラウザの localStorage
(`shuttlescope.viewpoint.{matchId}`) にしか無かった。結果:

- CV は自分のラベル (画面の上側 = player_a) を人物に対応付けられない。
  セット2以降のコートチェンジ以前に、第1セットから対応が取れていなかった
- 注釈者が別の PC を使うとコート図の向きが変わる

UI (QuickStartModal の「セット1開始時の自選手の位置」) は既にこの値を聞いている。
保存先が端末だっただけ。
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import Match, Player
from backend.main import app


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    c = TestClient(app, headers={"X-Role": "admin"})
    yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def match(db_session):
    a = Player(name="開始サイドA", dominant_hand="R")
    b = Player(name="開始サイドB", dominant_hand="R")
    db_session.add_all([a, b])
    db_session.flush()
    m = Match(
        tournament="開始サイドテスト",
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
    db_session.commit()
    return m


class TestPlayerAStartSide:
    def test_existing_matches_have_no_side_and_that_is_readable(self, client, match):
        """既存試合は未設定。読み手が localStorage にフォールバックできるよう、
        欠損が欠損として見えること (勝手に 'bottom' を埋めない)。"""
        res = client.get(f"/api/matches/{match.id}")
        assert res.status_code == 200
        assert res.json()["data"]["player_a_start_side"] is None

    def test_it_can_be_set_and_read_back(self, client, match):
        res = client.put(f"/api/matches/{match.id}", json={"player_a_start_side": "top"})
        assert res.status_code == 200
        got = client.get(f"/api/matches/{match.id}").json()["data"]
        assert got["player_a_start_side"] == "top"

    @pytest.mark.parametrize("bad", ["left", "TOP", "", "上"])
    def test_only_top_or_bottom_is_accepted(self, client, match, bad):
        """語彙を固定する。CV がこれを見て人物を決めるので、想定外の値が入ると
        間違いが «サーバが言っている事実» の顔をして残る。"""
        res = client.put(f"/api/matches/{match.id}", json={"player_a_start_side": bad})
        assert res.status_code == 422

    def test_setting_it_does_not_disturb_other_fields(self, client, match):
        before = client.get(f"/api/matches/{match.id}").json()["data"]
        client.put(f"/api/matches/{match.id}", json={"player_a_start_side": "bottom"})
        after = client.get(f"/api/matches/{match.id}").json()["data"]
        for key in ("tournament", "round", "format", "player_a_id", "player_b_id"):
            assert after[key] == before[key]
