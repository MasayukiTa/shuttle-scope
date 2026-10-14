"""strokes.land_zone_source: land_zone の入力元 ('cv' / 'human' / NULL)。

CV 自動適用は、空欄か CV 自身が前に書いた値 (source == 'cv') だけを更新する。
NULL (列の追加前の既存データ) や 'human' の値は人の入力として残す。
人が API で land_zone を指定・変更したら 'human' を記録する。
"""
from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import GameSet, Match, Player, Rally, Stroke, User
from backend.main import app
from backend.routers import cv_candidates
from backend.utils.jwt_utils import create_access_token


# ---------------------------------------------------------------- fixtures

@pytest.fixture()
def game_set(db_session) -> GameSet:
    a = Player(name="LZS-A", dominant_hand="R")
    b = Player(name="LZS-B", dominant_hand="R")
    db_session.add_all([a, b])
    db_session.flush()
    m = Match(
        tournament="lzs", tournament_level="practice", round="R1",
        date=date(2026, 10, 14), format="singles",
        player_a_id=a.id, player_b_id=b.id, result="unknown",
    )
    db_session.add(m)
    db_session.flush()
    gs = GameSet(match_id=m.id, set_num=1)
    db_session.add(gs)
    db_session.flush()
    db_session.commit()
    return gs


@pytest.fixture()
def rally(db_session, game_set) -> Rally:
    r = Rally(set_id=game_set.id, rally_num=1, server="player_a", winner="player_a",
              end_type="ace", rally_length=0)
    db_session.add(r)
    db_session.flush()
    db_session.commit()
    return r


@pytest.fixture()
def client(db_session, game_set):
    app.dependency_overrides[get_db] = lambda: db_session
    match = db_session.get(Match, game_set.match_id)
    user = User(
        username=f"lzs-player-{match.player_a_id}", role="player",
        player_id=match.player_a_id, awaiting_admin_approval=False,
        consent_required=False, is_test=True,
    )
    db_session.add(user)
    db_session.commit()
    token = create_access_token(
        user_id=user.id, role="player", player_id=match.player_a_id, minutes=10,
    )
    c = TestClient(app, base_url="http://localhost",
                   headers={"Authorization": f"Bearer {token}"})
    yield c
    app.dependency_overrides.clear()


def _stroke(db_session, rally, **kw) -> Stroke:
    base = dict(rally_id=rally.id, stroke_num=1, player="player_a", shot_type="clear")
    base.update(kw)
    s = Stroke(**base)
    db_session.add(s)
    db_session.commit()
    return s


def _cand(value):
    return {"value": value, "confidence_score": 0.95, "source": "test",
            "decision_mode": "auto_filled", "reason_codes": []}


def _apply(monkeypatch, db_session, stroke, value):
    artifact = SimpleNamespace(data=json.dumps({"rallies": {"1": {"rally_id": 1, "strokes": [{
        "stroke_id": stroke.id, "stroke_num": 1,
        "land_zone": _cand(value), "hit_zone": None, "hitter": None,
    }]}}}))
    monkeypatch.setattr(cv_candidates, "_require_match_team_scope", lambda *_a, **_k: None)
    monkeypatch.setattr(cv_candidates, "_latest_artifact", lambda *_a, **_k: artifact)
    data = cv_candidates.apply_cv_candidates(
        1,
        cv_candidates.ApplyRequest(mode="auto_filled", fields=["land_zone"]),
        request=SimpleNamespace(),
        db=db_session,
    )["data"]
    db_session.refresh(stroke)
    return data


# ------------------------------------------------------- CV auto-apply rules

def test_cv_fills_empty_and_marks_cv(monkeypatch, db_session, rally):
    s = _stroke(db_session, rally, land_zone=None)
    data = _apply(monkeypatch, db_session, s, "BR")
    assert (s.land_zone, s.land_zone_source) == ("BR", "cv")
    assert data["land_zone_count"] == 1 and data["preserved_count"] == 0


def test_cv_overwrites_its_own_earlier_value(monkeypatch, db_session, rally):
    s = _stroke(db_session, rally, land_zone="NL", land_zone_source="cv")
    data = _apply(monkeypatch, db_session, s, "BR")
    assert (s.land_zone, s.land_zone_source) == ("BR", "cv")
    assert data["land_zone_count"] == 1 and data["preserved_count"] == 0


def test_cv_does_not_overwrite_human_value(monkeypatch, db_session, rally):
    s = _stroke(db_session, rally, land_zone="NL", land_zone_source="human")
    data = _apply(monkeypatch, db_session, s, "BR")
    assert (s.land_zone, s.land_zone_source) == ("NL", "human")
    assert data["land_zone_count"] == 0 and data["preserved_count"] == 1


def test_cv_does_not_overwrite_legacy_null_source_value(monkeypatch, db_session, rally):
    s = _stroke(db_session, rally, land_zone="NL", land_zone_source=None)
    data = _apply(monkeypatch, db_session, s, "BR")
    assert (s.land_zone, s.land_zone_source) == ("NL", None)
    assert data["land_zone_count"] == 0 and data["preserved_count"] == 1


# ----------------------------------------------------- human edits via the API

def test_create_stroke_with_land_zone_marks_human(client, db_session, rally):
    res = client.post(f"/api/strokes?rally_id={rally.id}",
                      json={"stroke_num": 1, "player": "player_a", "shot_type": "clear",
                            "land_zone": "BL"})
    assert res.status_code == 201, res.text
    assert res.json()["data"]["land_zone_source"] == "human"
    s = db_session.get(Stroke, res.json()["data"]["id"])
    assert s.land_zone_source == "human"


def test_create_stroke_without_land_zone_has_no_source(client, db_session, rally):
    res = client.post(f"/api/strokes?rally_id={rally.id}",
                      json={"stroke_num": 1, "player": "player_a", "shot_type": "clear"})
    assert res.status_code == 201, res.text
    assert res.json()["data"]["land_zone_source"] is None


def test_batch_save_marks_human_only_where_land_zone_given(client, db_session, game_set):
    body = {
        "rally": {"set_id": game_set.id, "rally_num": 1, "server": "player_a",
                  "winner": "player_a", "end_type": "ace", "rally_length": 2,
                  "score_a_after": 1, "score_b_after": 0},
        "strokes": [
            {"stroke_num": 1, "player": "player_a", "shot_type": "short_service",
             "land_zone": "NL"},
            {"stroke_num": 2, "player": "player_b", "shot_type": "clear"},
        ],
    }
    res = client.post("/api/strokes/batch", json=body)
    assert res.status_code in (200, 201), res.text
    rows = {s.stroke_num: s for s in db_session.query(Stroke).all()}
    assert rows[1].land_zone_source == "human"
    assert rows[2].land_zone_source is None


def test_human_edit_marks_human_and_then_cv_no_longer_overwrites(
    client, monkeypatch, db_session, rally
):
    s = _stroke(db_session, rally, land_zone="NL", land_zone_source="cv")
    body = {"stroke_num": 1, "player": "player_a", "shot_type": "clear", "land_zone": "BR"}
    res = client.put(f"/api/strokes/{s.id}", json=body)
    assert res.status_code == 200, res.text
    db_session.refresh(s)
    assert (s.land_zone, s.land_zone_source) == ("BR", "human")

    data = _apply(monkeypatch, db_session, s, "ML")
    assert (s.land_zone, s.land_zone_source) == ("BR", "human")
    assert data["land_zone_count"] == 0


def test_put_resending_unchanged_cv_value_keeps_cv(client, db_session, rally):
    s = _stroke(db_session, rally, land_zone="NL", land_zone_source="cv")
    body = {"stroke_num": 1, "player": "player_a", "shot_type": "clear", "land_zone": "NL"}
    assert client.put(f"/api/strokes/{s.id}", json=body).status_code == 200
    db_session.refresh(s)
    assert s.land_zone_source == "cv"


def test_put_clearing_land_zone_clears_source(client, db_session, rally):
    s = _stroke(db_session, rally, land_zone="NL", land_zone_source="human")
    body = {"stroke_num": 1, "player": "player_a", "shot_type": "clear"}
    assert client.put(f"/api/strokes/{s.id}", json=body).status_code == 200
    db_session.refresh(s)
    assert (s.land_zone, s.land_zone_source) == (None, None)


# ----------------------------------------------------------------- migration

_VERSIONS = Path(__file__).resolve().parents[1] / "db" / "migrations" / "versions"


def _load_migration():
    path = next(_VERSIONS.glob("0056_*.py"))
    spec = importlib.util.spec_from_file_location("mig_0056_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(engine, fn):
    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            fn()


def test_migration_0056_chain_and_additive_idempotent_upgrade():
    mod = _load_migration()
    assert mod.revision == "0056" and mod.down_revision == "0055"

    engine = sa.create_engine("sqlite://")  # in-memory, never a real app DB
    with engine.begin() as conn:
        conn.execute(sa.text(
            "CREATE TABLE strokes (id INTEGER PRIMARY KEY, land_zone VARCHAR(5))"))
        conn.execute(sa.text("INSERT INTO strokes (id, land_zone) VALUES (1, 'NL'), (2, NULL)"))

    _run(engine, mod.upgrade)
    cols = {c["name"]: c for c in sa.inspect(engine).get_columns("strokes")}
    assert "land_zone_source" in cols and cols["land_zone_source"]["nullable"] is True
    with engine.begin() as conn:
        rows = conn.execute(sa.text(
            "SELECT id, land_zone, land_zone_source FROM strokes ORDER BY id")).all()
    assert [tuple(r) for r in rows] == [(1, "NL", None), (2, None, None)]  # no backfill

    _run(engine, mod.upgrade)  # idempotent
    assert [c["name"] for c in sa.inspect(engine).get_columns("strokes")].count(
        "land_zone_source") == 1

    _run(engine, mod.downgrade)
    assert "land_zone_source" not in {c["name"] for c in sa.inspect(engine).get_columns("strokes")}
    _run(engine, mod.downgrade)  # idempotent too


def test_migration_0056_is_the_single_head():
    import re
    revs, downs = {}, set()
    for p in _VERSIONS.glob("[0-9]*.py"):
        text = p.read_text(encoding="utf-8")
        rev = re.search(r'^revision[^=]*=\s*"([^"]+)"', text, re.M).group(1)
        down = re.search(r'^down_revision[^=]*=\s*"?([^"\n]+?)"?\s*$', text, re.M).group(1)
        revs[rev] = down
        downs.add(down)
    assert [r for r in revs if r not in downs] == ["0056"]
