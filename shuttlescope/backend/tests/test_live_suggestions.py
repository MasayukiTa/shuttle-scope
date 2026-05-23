"""live_suggestions endpoint tests."""
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


def _seed_winning_smash_losing_clear(db_session):
    """smash を使うラリーは勝ち、clear を使うラリーは負け、を作る (lift 差大)。"""
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
    gs = GameSet(match_id=m.id, set_num=1, score_a=21, score_b=15)
    db_session.add(gs)
    db_session.flush()

    # smash ラリー (勝ち) × 10
    for i in range(1, 11):
        r = Rally(set_id=gs.id, rally_num=i, server="player_a",
                  winner="player_a", end_type="forced_error",
                  rally_length=3, is_skipped=False)
        db_session.add(r)
        db_session.flush()
        db_session.add_all([
            Stroke(rally_id=r.id, stroke_num=1, player="player_a",
                   shot_type="smash"),
            Stroke(rally_id=r.id, stroke_num=2, player="player_b",
                   shot_type="clear"),
            Stroke(rally_id=r.id, stroke_num=3, player="player_a",
                   shot_type="smash"),
        ])

    # clear ラリー (負け) × 10
    for i in range(11, 21):
        r = Rally(set_id=gs.id, rally_num=i, server="player_a",
                  winner="player_b", end_type="forced_error",
                  rally_length=3, is_skipped=False)
        db_session.add(r)
        db_session.flush()
        db_session.add_all([
            Stroke(rally_id=r.id, stroke_num=1, player="player_a",
                   shot_type="clear"),
            Stroke(rally_id=r.id, stroke_num=2, player="player_b",
                   shot_type="smash"),
            Stroke(rally_id=r.id, stroke_num=3, player="player_a",
                   shot_type="clear"),
        ])

    db_session.commit()
    return p_a.id, m.id


def test_live_suggestions_returns_up_to_3_items_with_confidence(db_session):
    pid, mid = _seed_winning_smash_losing_clear(db_session)
    app.dependency_overrides[get_auth] = _coach
    try:
        client = TestClient(app, base_url="http://localhost")
        resp = client.get(
            "/api/analysis/live_suggestions",
            params={"player_id": pid, "match_id": mid},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        items = body["items"]
        assert len(items) <= 3
        assert len(items) >= 1
        for it in items:
            assert it["confidence"] >= 0.5
            assert "弱点" not in it["headline_ja"]
            assert "weakness" not in it["headline_en"].lower()
            assert "id" in it
            assert it["headline_ja"]
            assert it["headline_en"]
    finally:
        app.dependency_overrides.pop(get_auth, None)


def test_live_suggestions_forbidden_for_player(db_session):
    pid, mid = _seed_winning_smash_losing_clear(db_session)
    app.dependency_overrides[get_auth] = _player
    try:
        client = TestClient(app, base_url="http://localhost")
        resp = client.get(
            "/api/analysis/live_suggestions",
            params={"player_id": pid, "match_id": mid},
        )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(get_auth, None)


def test_live_suggestions_confidence_filter_no_data(db_session):
    """データなしの match は空 list。"""
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
    db_session.commit()

    app.dependency_overrides[get_auth] = _coach
    try:
        client = TestClient(app, base_url="http://localhost")
        resp = client.get(
            "/api/analysis/live_suggestions",
            params={"player_id": p_a.id, "match_id": m.id},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["items"] == []
    finally:
        app.dependency_overrides.pop(get_auth, None)
