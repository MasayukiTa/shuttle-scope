"""Phase 3: コンディション解析テスト。"""
from __future__ import annotations

from datetime import date, timedelta
from typing import List

import pytest
from fastapi.testclient import TestClient

from backend.analysis.condition_analytics import (
    best_performance_profile,
    correlation_series,
    detect_discrepancy,
    pearson,
    player_growth_insights,
)
from backend.analysis.condition_questions import WEEKLY_REQUIRED_IDS
from backend.db.database import get_db
from backend.db.models import Condition, Match, Player
from backend.main import app


# ─── pure-function tests ─────────────────────────────────────────────────────


class TestPearson:
    def test_perfect_positive(self):
        r, p = pearson([1, 2, 3, 4, 5], [2, 4, 6, 8, 10])
        assert r == pytest.approx(1.0)
        assert p == pytest.approx(0.0, abs=1e-6)

    def test_perfect_negative(self):
        r, p = pearson([1, 2, 3, 4, 5], [10, 8, 6, 4, 2])
        assert r == pytest.approx(-1.0)

    def test_small_sample_returns_none(self):
        r, p = pearson([1, 2], [3, 4])
        assert r is None and p is None

    def test_zero_variance(self):
        r, p = pearson([1, 1, 1, 1], [1, 2, 3, 4])
        assert r is None and p is None


def _cond(pid: int, dt: date, ccs: float = 100.0, **kw) -> dict:
    base = {
        "id": kw.pop("id", 1),
        "player_id": pid,
        "measured_at": dt,
        "ccs_score": ccs,
        "condition_type": "weekly",
    }
    base.update(kw)
    return base


def _match(mid: int, dt: date, a: int, b: int, result: str) -> dict:
    return {"id": mid, "date": dt, "result": result,
            "player_a_id": a, "player_b_id": b,
            "partner_a_id": None, "partner_b_id": None}


class TestCorrelationSeries:
    def test_basic_ccs_vs_win_rate(self):
        pid = 107
        base = date(2026, 3, 1)
        conds: List[dict] = []
        matches: List[dict] = []
        for i in range(8):
            d = base + timedelta(days=i * 7)
            conds.append(_cond(pid, d, ccs=80 + i * 5, id=i + 1))
            # 高 CCS ほど勝利確率高
            res = "win" if i >= 4 else "loss"
            matches.append(_match(100 + i, d, pid, 999, res))
        s = correlation_series(conds, matches, "ccs_score", "win_rate")
        assert s["n"] == 8
        assert s["pearson_r"] is not None
        assert s["pearson_r"] > 0
        assert "confidence_note" in s

    def test_unimplemented_metric(self):
        s = correlation_series([], [], "ccs_score", "unforced_error_rate")
        assert s["n"] == 0
        assert s["confidence_note"] == "condition.note.metric_unimplemented"


class TestBestProfile:
    def test_no_matches_safe(self):
        out = best_performance_profile([], [])
        assert out["key_factors"] == []
        assert out["confidence"] in ("none", "low")

    def test_basic(self):
        pid = 107
        base = date(2026, 3, 1)
        conds = []
        matches = []
        for i in range(10):
            d = base + timedelta(days=i * 7)
            conds.append(_cond(
                pid, d, ccs=70 + i * 8, id=i + 1,
                muscle_mass_kg=30 + (i * 0.3 if i >= 5 else 0),
                hooper_index=15,
            ))
            matches.append(_match(100 + i, d, pid, 999,
                                  "win" if i >= 5 else "loss"))
        out = best_performance_profile(conds, matches)
        assert out["n_top"] >= 1
        assert out["n_rest"] >= 1
        assert len(out["key_factors"]) <= 3


class TestDiscrepancy:
    def test_inbody_mental_mismatch_fires(self):
        c = _cond(1, date(2026, 4, 1), ecw_ratio=0.43, f1_physical=12)
        flags = detect_discrepancy(c)
        types = {f["type"] for f in flags}
        assert "inbody_mental_mismatch" in types

    def test_inbody_mental_mismatch_not_fires(self):
        c = _cond(1, date(2026, 4, 1), ecw_ratio=0.38, f1_physical=10)
        flags = detect_discrepancy(c)
        assert not any(f["type"] == "inbody_mental_mismatch" for f in flags)

    def test_weight_loss_fires(self):
        prev = _cond(1, date(2026, 3, 25), weight_kg=60.0, f5_sleep_life=10)
        c = _cond(1, date(2026, 4, 1), weight_kg=57.0, f5_sleep_life=10)
        flags = detect_discrepancy(c, prev_condition=prev)
        assert any(f["type"] == "weight_loss_but_good_sleep_report" for f in flags)

    def test_weight_loss_not_fires_when_small(self):
        prev = _cond(1, date(2026, 3, 25), weight_kg=60.0, f5_sleep_life=10)
        c = _cond(1, date(2026, 4, 1), weight_kg=59.5, f5_sleep_life=10)
        flags = detect_discrepancy(c, prev_condition=prev)
        assert not any(f["type"] == "weight_loss_but_good_sleep_report" for f in flags)

    def test_hooper_ccs_mismatch_fires(self):
        c = _cond(1, date(2026, 4, 1), ccs=140, hooper_index=22)
        flags = detect_discrepancy(c)
        assert any(f["type"] == "hooper_ccs_mismatch" for f in flags)

    def test_hooper_ccs_mismatch_not_fires(self):
        c = _cond(1, date(2026, 4, 1), ccs=120, hooper_index=18)
        flags = detect_discrepancy(c)
        assert not any(f["type"] == "hooper_ccs_mismatch" for f in flags)

    def test_severity_present(self):
        c = _cond(1, date(2026, 4, 1), ecw_ratio=0.43, f1_physical=12)
        for f in detect_discrepancy(c):
            assert f["severity"] in ("low", "medium", "high")


class TestGrowthInsights:
    def test_no_weakness_framing(self):
        pid = 1
        base = date(2026, 1, 1)
        conds = []
        matches = []
        for i in range(10):
            d = base + timedelta(days=i * 7)
            conds.append(_cond(
                pid, d,
                ccs=80 + (20 if i >= 7 else 0),
                id=i + 1,
                muscle_mass_kg=30 + (2 if i >= 7 else 0),
                f5_sleep_life=18 + (4 if i >= 7 else 0),
            ))
            matches.append(_match(100 + i, d, pid, 999,
                                  "win" if i >= 6 else "loss"))
        out = player_growth_insights(conds, matches)
        # 弱点表記禁止の文字列チェック
        dumped = repr(out)
        for banned in ("weakness", "weak", "negative", "弱", "悪い", "苦手"):
            assert banned not in dumped
        # i18n key は growth_positive のみ
        for card in out["growth_cards"]:
            assert card["frame"] == "growth_positive"
            assert card["i18n_key"].endswith("_positive")


# ─── HTTP layer tests ────────────────────────────────────────────────────────


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def player(db_session):
    p = Player(name="Phase3 テスト選手", dominant_hand="R")
    db_session.add(p)
    db_session.flush()
    db_session.commit()
    return p


def _seed_condition(db_session, player_id, d, **kw):
    c = Condition(
        player_id=player_id,
        measured_at=d,
        condition_type="weekly",
        **kw,
    )
    db_session.add(c)
    db_session.flush()
    return c


class TestRoleFilter:
    def test_player_discrepancy_is_403(self, client, player):
        r = client.get(
            f"/api/conditions/discrepancy?player_id={player.id}",
            headers={"X-Role": "player", "X-Player-Id": str(player.id)},
        )
        assert r.status_code == 403

    def test_coach_discrepancy_ok(self, client, player, db_session):
        _seed_condition(db_session, player.id, date(2026, 4, 1),
                        ecw_ratio=0.43, f1_physical=12.0)
        db_session.commit()
        r = client.get(
            f"/api/conditions/discrepancy?player_id={player.id}",
            headers={"X-Role": "coach"},
        )
        assert r.status_code == 200
        items = r.json()["data"]["items"]
        assert len(items) == 1

    def test_player_insights_shrunk(self, client, player, db_session):
        _seed_condition(db_session, player.id, date(2026, 4, 1), ccs_score=100.0)
        db_session.commit()
        r = client.get(
            f"/api/conditions/insights?player_id={player.id}",
            headers={"X-Role": "player", "X-Player-Id": str(player.id)},
        )
        assert r.status_code == 200
        d = r.json()["data"]
        assert "growth_cards" in d
        assert "personal_trend" in d
        # analyst 専用フィールドは含まれない
        assert "raw_factor_trends" not in d
        assert "validity_summary" not in d

    def test_analyst_insights_full(self, client, player, db_session):
        _seed_condition(db_session, player.id, date(2026, 4, 1), ccs_score=100.0)
        db_session.commit()
        r = client.get(
            f"/api/conditions/insights?player_id={player.id}",
            headers={"X-Role": "analyst"},
        )
        d = r.json()["data"]
        assert "raw_factor_trends" in d
        assert "validity_summary" in d

    def test_correlation_endpoint_basic(self, client, player, db_session):
        for i in range(5):
            _seed_condition(
                db_session, player.id, date(2026, 3, 1) + timedelta(days=i * 7),
                ccs_score=80.0 + i * 10,
            )
        db_session.commit()
        r = client.get(
            f"/api/conditions/correlation?player_id={player.id}&x=ccs_score&y=ccs_score",
            headers={"X-Role": "analyst"},
        )
        assert r.status_code == 200
        assert r.json()["data"]["n"] == 5

    def test_best_profile_empty_ok(self, client, player):
        r = client.get(
            f"/api/conditions/best_profile?player_id={player.id}",
            headers={"X-Role": "analyst"},
        )
        assert r.status_code == 200
        assert r.json()["data"]["key_factors"] == []
