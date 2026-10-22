"""final_score と result の整合性を新しい書き込みで検査する (監査 #155 / #179 / #180)。

既存データは書き換えない。解釈できない書式 (自由記述) は判定せず通す。値はすべて架空。
"""
from __future__ import annotations

import pytest

from backend.utils.match_score import parse_set_scores, score_consistency_error
from backend.tests.test_stats_n0_guards_b import _headers, client  # noqa: F401


class TestPureRules:
    def test_parse(self):
        assert parse_set_scores("21-15, 18-21, 21-19") == [(21, 15), (18, 21), (21, 19)]
        assert parse_set_scores("21-15,21-18") == [(21, 15), (21, 18)]
        assert parse_set_scores("") is None
        assert parse_set_scores(None) is None
        assert parse_set_scores("retired in 2nd") is None

    def test_consistent_scores_pass(self):
        assert score_consistency_error("21-15, 21-18", "win") is None
        assert score_consistency_error("15-21, 18-21", "loss") is None
        assert score_consistency_error("21-15, 18-21, 21-19", "win") is None

    def test_winner_must_match_result(self):
        assert score_consistency_error("15-21, 18-21", "win") is not None
        assert score_consistency_error("21-15, 21-18", "loss") is not None

    def test_sets_after_the_match_is_decided_are_rejected(self):
        # 2 セット先取で決着した後の 3 セット目 (監査 #180 の 3-0)
        assert score_consistency_error("21-18, 21-16, 21-17", "win") is not None

    def test_unparseable_or_non_decided_results_are_not_judged(self):
        assert score_consistency_error("walkover", "win") is None
        assert score_consistency_error("21-10", "retired") is None
        assert score_consistency_error(None, "loss") is None


@pytest.fixture(autouse=True)
def _reset_limits():
    from backend.main import AdminWriteRateLimitMiddleware
    from backend.routers import auth as _auth_module
    _auth_module._IP_LOGIN_TIMES.clear()
    AdminWriteRateLimitMiddleware._state.clear()
    yield
    AdminWriteRateLimitMiddleware._state.clear()


def _body(**extra) -> dict:
    body = {
        "tournament": "ScoreCheck", "tournament_level": "IC", "round": "1R",
        "date": "2026-01-01", "format": "singles", "result": "win",
    }
    body.update(extra)
    return body


def test_create_rejects_score_that_contradicts_result(client):
    r = client.post("/api/matches", json=_body(result="loss", final_score="21-15, 21-18"),
                    headers=_headers())
    assert r.status_code == 422, r.text
    assert "final_score" in r.text


def test_create_rejects_three_sets_after_decision(client):
    r = client.post("/api/matches", json=_body(result="win", final_score="21-18, 21-16, 21-17"),
                    headers=_headers())
    assert r.status_code == 422, r.text
    assert "final_score" in r.text
