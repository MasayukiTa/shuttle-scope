"""DR-OPE summary: best_state needs interval support, n is carried (audit #918)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.main import app
from backend.routers import analysis_research as ar
from backend.utils.auth import (
    AuthCtx,
    get_auth,
    require_admin_or_analyst,
    require_non_player,
)


def _admin_ctx() -> AuthCtx:
    return AuthCtx(role="admin", player_id=None, user_id=1, team_name=None, team_id=None)


def _row(n: int, behavior: float, target: float, ci_low: float, ci_high: float) -> dict:
    return {
        "n": n,
        "value_behavior": behavior,
        "value_target": target,
        "uplift": round(target - behavior, 4),
        "ci_low": ci_low,
        "ci_high": ci_high,
        "behavior_policy": {"a": 1.0},
        "target_policy": {"a": 1.0},
    }


@pytest.fixture
def client(db_session, monkeypatch):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_auth] = _admin_ctx
    app.dependency_overrides[require_admin_or_analyst] = _admin_ctx
    app.dependency_overrides[require_non_player] = _admin_ctx
    monkeypatch.setattr(
        ar,
        "load_policy_records",
        lambda *a, **k: {"early|server": [{}] * 3, "mid|server": [{}] * 5, "deuce|server": [{}] * 7},
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


def _summary(client) -> dict:
    resp = client.get("/api/analysis/policy_eval?player_id=1")
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["summary"]


def test_largest_point_estimate_without_ci_support_is_not_best(client, monkeypatch):
    rows = {
        3: _row(12, 0.50, 0.70, 0.40, 0.90),  # largest uplift, CI covers behavior value
        5: _row(30, 0.50, 0.52, 0.47, 0.57),
        7: _row(25, 0.50, 0.48, 0.44, 0.52),
    }
    monkeypatch.setattr(ar, "_dr_evaluate_state", lambda recs, temp=0.25: rows[len(recs)])
    summary = _summary(client)
    assert summary["best_state"] is None
    assert summary["top_candidate"]["state_key"] == "early|server"
    assert summary["top_candidate"]["n"] == 12


def test_best_state_requires_ci_low_above_behavior_and_carries_n(client, monkeypatch):
    rows = {
        3: _row(12, 0.50, 0.70, 0.40, 0.90),  # larger uplift but unsupported
        5: _row(40, 0.50, 0.60, 0.53, 0.67),  # supported
        7: _row(25, 0.50, 0.48, 0.44, 0.52),
    }
    monkeypatch.setattr(ar, "_dr_evaluate_state", lambda recs, temp=0.25: rows[len(recs)])
    summary = _summary(client)
    assert summary["best_state"]["state_key"] == "mid|server"
    assert summary["best_state"]["n"] == 40
