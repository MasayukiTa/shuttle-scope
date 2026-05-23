"""admin-only research-tier peer-comparison のテスト。

検証:
  - cohort N<5 → available=false
  - cohort N>=5 → metrics に p25/p50/p75/mean/sd
  - demo data 除外
  - player / coach / analyst → 403
  - admin → 200
  - audit row (event_type=peer_comparison_query) 発火
"""
from __future__ import annotations

import pytest
from datetime import date
from fastapi.testclient import TestClient

from backend.main import app
from backend.db.database import get_db
from backend.db.models import (
    Player, Match, GameSet, Rally, Stroke, Team, SecurityEvent,
)
from backend.utils.auth import AuthCtx, get_auth, require_admin


# ── auth ctx helpers ────────────────────────────────────────────────────────

def _admin_ctx() -> AuthCtx:
    return AuthCtx(role="admin", player_id=None, user_id=42, team_name=None, team_id=None)


def _analyst_ctx() -> AuthCtx:
    return AuthCtx(role="analyst", player_id=None, user_id=43, team_name=None, team_id=None)


def _coach_ctx() -> AuthCtx:
    return AuthCtx(role="coach", player_id=None, user_id=44, team_name=None, team_id=None)


def _player_ctx() -> AuthCtx:
    return AuthCtx(role="player", player_id=100, user_id=45, team_name=None, team_id=None)


# ── seeding ─────────────────────────────────────────────────────────────────

def _make_player(db, name: str, *, team_id: int | None, hand: str = "R", birth_year: int = 2000) -> Player:
    p = Player(name=name, dominant_hand=hand, birth_year=birth_year, team_id=team_id)
    db.add(p)
    db.flush()
    return p


def _seed_player_with_match(db, p_a: Player, p_b: Player, *, p_a_won_rallies: int = 4, n_rallies: int = 6, fmt: str = "singles") -> None:
    """p_a と p_b の試合 + セット + ラリー + ストロークを 1 件作る。
    p_a が勝った rally で smash を打って勝率 1.0 にして metric を確実に出す。
    """
    m = Match(
        tournament="t", tournament_level="IC", round="F",
        date=date(2025, 1, 1), format=fmt,
        player_a_id=p_a.id, player_b_id=p_b.id, result="win",
    )
    db.add(m)
    db.flush()
    gs = GameSet(match_id=m.id, set_num=1, winner="player_a", score_a=21, score_b=15)
    db.add(gs)
    db.flush()
    for i in range(1, n_rallies + 1):
        winner = "player_a" if i <= p_a_won_rallies else "player_b"
        r = Rally(
            set_id=gs.id, rally_num=i, server="player_a", winner=winner,
            end_type="forced_error", rally_length=5,
            score_a_after=i, score_b_after=0,
        )
        db.add(r)
        db.flush()
        for j in range(1, 6):
            db.add(Stroke(
                rally_id=r.id, stroke_num=j,
                player="player_a" if j % 2 == 1 else "player_b",
                shot_type="smash" if j == 1 else "net_shot",
                hit_zone="BC", land_zone="NL",
            ))
    db.flush()


@pytest.fixture()
def seeded_real(db_session):
    """6 人の real player + 各 1 試合。demo team も 2 人混ぜる。"""
    # cleanup
    for model in (Stroke, Rally, GameSet, Match, Player, Team, SecurityEvent):
        db_session.query(model).delete()
    db_session.commit()

    real_team = Team(id=100, display_id="REAL", name="Real")
    demo_team = Team(id=200, display_id="__demo__", name="Demo")
    db_session.add_all([real_team, demo_team])
    db_session.flush()

    opp = _make_player(db_session, "opp", team_id=real_team.id)
    real_players = [
        _make_player(db_session, f"p{i}", team_id=real_team.id, hand="R", birth_year=2000)
        for i in range(6)
    ]
    for p in real_players:
        _seed_player_with_match(db_session, p, opp)

    # demo players — should be excluded
    demo_opp = _make_player(db_session, "demo_opp", team_id=demo_team.id)
    demo_players = [
        _make_player(db_session, f"demo_p{i}", team_id=demo_team.id, hand="R", birth_year=2000)
        for i in range(3)
    ]
    for p in demo_players:
        _seed_player_with_match(db_session, p, demo_opp)

    db_session.commit()
    app.dependency_overrides[get_db] = lambda: db_session
    yield db_session
    app.dependency_overrides.clear()


@pytest.fixture()
def seeded_small(db_session):
    """3 人のみ (N<5)."""
    for model in (Stroke, Rally, GameSet, Match, Player, Team, SecurityEvent):
        db_session.query(model).delete()
    db_session.commit()

    real_team = Team(id=100, display_id="REAL", name="Real")
    db_session.add(real_team)
    db_session.flush()
    opp = _make_player(db_session, "opp", team_id=real_team.id)
    for i in range(3):
        p = _make_player(db_session, f"sp{i}", team_id=real_team.id, hand="R", birth_year=2000)
        _seed_player_with_match(db_session, p, opp)

    db_session.commit()
    app.dependency_overrides[get_db] = lambda: db_session
    yield db_session
    app.dependency_overrides.clear()


# ── tests ───────────────────────────────────────────────────────────────────

PATH = "/api/analysis/research/peer_cohort_stats"


_BASE = "http://localhost"


def _client_as(ctx_fn):
    app.dependency_overrides[get_auth] = ctx_fn
    app.dependency_overrides[require_admin] = ctx_fn
    return TestClient(app, base_url=_BASE)


def test_insufficient_cohort_returns_unavailable(seeded_small):
    client = _client_as(_admin_ctx)
    try:
        resp = client.post(PATH, json={})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["available"] is False
        assert data["reason"] == "insufficient_cohort"
        assert data["n"] < 5
    finally:
        app.dependency_overrides.pop(require_admin, None)


def test_adequate_cohort_returns_metrics(seeded_real):
    client = _client_as(_admin_ctx)
    try:
        resp = client.post(PATH, json={})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["available"] is True
        assert data["n"] >= 5
        assert "metrics" in data
        # at least one metric should be present with full aggregate keys
        assert len(data["metrics"]) >= 1
        for _name, agg in data["metrics"].items():
            for k in ("p25", "p50", "p75", "mean", "sd", "unit"):
                assert k in agg
    finally:
        app.dependency_overrides.pop(require_admin, None)


def test_demo_players_excluded(seeded_real):
    """cohort N が real (6) のみで demo (3) を含まないこと。"""
    client = _client_as(_admin_ctx)
    try:
        resp = client.post(PATH, json={})
        assert resp.status_code == 200
        data = resp.json()["data"]
        # demo (3 players + 1 demo_opp) を含めば n>=11。
        # 除外されていれば real 6 players + 1 opp = 7 のみ。
        assert data["n"] == 7
    finally:
        app.dependency_overrides.pop(require_admin, None)


def _expect_403(ctx_fn, seeded_real):
    # require_admin はデフォルト動作させて 403 を出させる (override しない)
    app.dependency_overrides[get_auth] = ctx_fn
    # peer_comparison の audit 内部 get_auth call も同じ ctx_fn を使う
    try:
        client = TestClient(app, base_url=_BASE)
        resp = client.post(PATH, json={})
        assert resp.status_code == 403, resp.text
    finally:
        app.dependency_overrides.pop(get_auth, None)


def test_player_role_forbidden(seeded_real):
    _expect_403(_player_ctx, seeded_real)


def test_coach_role_forbidden(seeded_real):
    _expect_403(_coach_ctx, seeded_real)


def test_analyst_role_forbidden(seeded_real):
    _expect_403(_analyst_ctx, seeded_real)


def test_admin_audit_event_emitted(seeded_real, monkeypatch):
    # security_log は import 時に SessionLocal を bind 済み。
    # test in-memory engine と同じ session に書き込ませるためここで差し替える。
    from backend.utils import security_log as _sl
    from backend.db import database as _db_mod
    monkeypatch.setattr(_sl, "SessionLocal", _db_mod.SessionLocal)

    client = _client_as(_admin_ctx)
    try:
        before = seeded_real.query(SecurityEvent).filter(
            SecurityEvent.event_type == "peer_comparison_query"
        ).count()
        resp = client.post(PATH, json={"handedness": "right"})
        assert resp.status_code == 200
        seeded_real.expire_all()
        after = seeded_real.query(SecurityEvent).filter(
            SecurityEvent.event_type == "peer_comparison_query"
        ).count()
        assert after > before
    finally:
        app.dependency_overrides.pop(require_admin, None)
