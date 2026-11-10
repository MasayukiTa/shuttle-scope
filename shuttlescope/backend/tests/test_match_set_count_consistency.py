"""final_score のセット数と記録済みセット数の整合性を検査する (監査 #155)。

監査 #155: id=104 は final_score が 2 セットなのに記録済みセットは 1 、rally_count=0で
result=win だった。更新時に final_score のセット数が記録済み GameSet 数を超えたら
fail closed で拒否する。既存データは書き換えない。値はすべて架空。
"""
from __future__ import annotations

from datetime import date

import pytest

from backend.db.models import GameSet, Match, Player
from backend.utils.match_score import set_count_consistency_error
from backend.tests.test_stats_n0_guards_b import _headers, client  # noqa: F401


class TestPureRules:
    def test_recorded_sets_cover_final_score_pass(self):
        assert set_count_consistency_error("21-15, 21-18", 2, "win") is None
        assert set_count_consistency_error("21-15", 1, "win") is None

    def test_final_score_more_sets_than_recorded_is_rejected(self):
        # #155 の中核: 2 セットの final_score なのに記録済みは 1 セット
        assert set_count_consistency_error("21-10, 21-18", 1, "win") is not None
        assert set_count_consistency_error("15-21, 18-21", 1, "loss") is not None

    def test_no_recorded_sets_is_not_judged(self):
        # クイック入力でスコアを先に入れた段階 (記録セット 0) は壊さない
        assert set_count_consistency_error("21-10, 21-18", 0, "win") is None
        assert set_count_consistency_error("21-10, 21-18", None, "win") is None

    def test_unparseable_or_non_decided_results_are_not_judged(self):
        assert set_count_consistency_error("walkover", 1, "win") is None
        assert set_count_consistency_error("21-10", 1, "unfinished") is None
        assert set_count_consistency_error(None, 1, "win") is None


@pytest.fixture(autouse=True)
def _reset_limits():
    from backend.main import AdminWriteRateLimitMiddleware
    from backend.routers import auth as _auth_module
    _auth_module._IP_LOGIN_TIMES.clear()
    AdminWriteRateLimitMiddleware._state.clear()
    yield
    AdminWriteRateLimitMiddleware._state.clear()


def _match_with_one_set(db):
    a = Player(name="A155", dominant_hand="R")
    b = Player(name="B155", dominant_hand="R")
    db.add(a)
    db.add(b)
    db.flush()
    m = Match(
        tournament="SetCount155", tournament_level="IC", round="1R",
        date=date(2026, 1, 1), format="singles",
        player_a_id=a.id, player_b_id=b.id, result="win",
        final_score="21-10", annotation_status="complete", annotation_progress=1.0,
    )
    db.add(m)
    db.flush()
    gs = GameSet(match_id=m.id, set_num=1, winner="player_a", score_a=21, score_b=10)
    db.add(gs)
    db.flush()
    return m


def test_update_rejects_final_score_with_more_sets_than_recorded(client, db_session):
    m = _match_with_one_set(db_session)
    r = client.put(
        f"/api/matches/{m.id}",
        json={"final_score": "21-10, 21-18"},
        headers=_headers(),
    )
    assert r.status_code == 422, r.text
    assert "final_score" in r.text


def test_update_allows_final_score_matching_recorded_sets(client, db_session):
    m = _match_with_one_set(db_session)
    r = client.put(
        f"/api/matches/{m.id}",
        json={"final_score": "21-12"},
        headers=_headers(),
    )
    assert r.status_code == 200, r.text
