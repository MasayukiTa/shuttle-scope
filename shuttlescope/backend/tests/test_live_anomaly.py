"""live_anomaly endpoint tests.

- divergence 高い → anomaly=True
- sample 低い → anomaly=False
- player ロール → 403
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.db.models import GameSet, Match, Player, Rally, Stroke
from backend.main import app
from backend.utils.auth import AuthCtx, get_auth


def _coach():
    return AuthCtx(role="coach", player_id=None, user_id=1)


def _player():
    return AuthCtx(role="player", player_id=1, user_id=1)


def _seed_baseline_and_recent(db_session, recent_skew: bool):
    """選手 A のベースライン (clear 多め) と直近 (recent_skew=True なら smash 多め) を作成。"""
    p_a = Player(name="A")
    p_b = Player(name="B")
    db_session.add_all([p_a, p_b])
    db_session.flush()

    m = Match(
        tournament="T", tournament_level="国内", round="R16",
        date=date(2026, 4, 16), format="singles",
        player_a_id=p_a.id, player_b_id=p_b.id, result="win",
    )
    db_session.add(m)
    db_session.flush()

    gs = GameSet(match_id=m.id, set_num=1, score_a=21, score_b=18)
    db_session.add(gs)
    db_session.flush()

    # ベースライン: 古いラリー rally_num=1..20, clear 主体 (各 4 stroke)
    for i in range(1, 21):
        r = Rally(set_id=gs.id, rally_num=i, server="player_a",
                  winner="player_a", end_type="forced_error",
                  rally_length=4, is_skipped=False)
        db_session.add(r)
        db_session.flush()
        for k in range(4):
            db_session.add(Stroke(rally_id=r.id, stroke_num=k + 1,
                                  player="player_a", shot_type="clear"))

    # 直近 5 ラリー: rally_num 21..25
    recent_shot = "smash" if recent_skew else "clear"
    for i in range(21, 26):
        r = Rally(set_id=gs.id, rally_num=i, server="player_a",
                  winner="player_a", end_type="forced_error",
                  rally_length=4, is_skipped=False)
        db_session.add(r)
        db_session.flush()
        for k in range(4):
            db_session.add(Stroke(rally_id=r.id, stroke_num=k + 1,
                                  player="player_a", shot_type=recent_shot))
    db_session.commit()
    return p_a.id, m.id


def test_live_anomaly_detected_when_divergence_high(db_session):
    pid, mid = _seed_baseline_and_recent(db_session, recent_skew=True)
    app.dependency_overrides[get_auth] = _coach
    try:
        client = TestClient(app, base_url="http://localhost")
        r = client.get(
            "/api/analysis/live_anomaly",
            params={"player_id": pid, "match_id": mid, "window": 5},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["anomaly"] is True
        assert 0.0 <= body["confidence"] <= 1.0
        assert "弱点" not in body["headline_ja"]
        assert "weakness" not in body["headline_en"].lower()
        assert body["evidence"]["primary_shot"] in {"smash", "clear"}
    finally:
        app.dependency_overrides.pop(get_auth, None)


def test_live_anomaly_no_when_sample_low(db_session):
    """直近ラリー < 3 の場合 anomaly=False。"""
    p_a = Player(name="A2")
    p_b = Player(name="B2")
    db_session.add_all([p_a, p_b])
    db_session.flush()
    m = Match(
        tournament="T", tournament_level="国内", round="R16",
        date=date(2026, 4, 16), format="singles",
        player_a_id=p_a.id, player_b_id=p_b.id, result="win",
    )
    db_session.add(m)
    db_session.flush()
    gs = GameSet(match_id=m.id, set_num=1, score_a=5, score_b=2)
    db_session.add(gs)
    db_session.flush()
    # 直近 1 ラリーだけ
    r = Rally(set_id=gs.id, rally_num=1, server="player_a", winner="player_a",
              end_type="forced_error", rally_length=2, is_skipped=False)
    db_session.add(r)
    db_session.flush()
    db_session.add(Stroke(rally_id=r.id, stroke_num=1, player="player_a",
                          shot_type="smash"))
    db_session.commit()

    app.dependency_overrides[get_auth] = _coach
    try:
        client = TestClient(app, base_url="http://localhost")
        resp = client.get(
            "/api/analysis/live_anomaly",
            params={"player_id": p_a.id, "match_id": m.id, "window": 5},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["anomaly"] is False
    finally:
        app.dependency_overrides.pop(get_auth, None)


def test_live_anomaly_forbidden_for_player(db_session):
    pid, mid = _seed_baseline_and_recent(db_session, recent_skew=False)
    app.dependency_overrides[get_auth] = _player
    try:
        client = TestClient(app, base_url="http://localhost")
        resp = client.get(
            "/api/analysis/live_anomaly",
            params={"player_id": pid, "match_id": mid, "window": 5},
        )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(get_auth, None)
