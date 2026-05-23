"""Slice Z tests: section filter, period bulk export, report date filtering, role gate."""
from __future__ import annotations

import json
from datetime import date
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.main import app
from backend.db.database import get_db
from backend.db.models import Player, Match, GameSet, Rally, Stroke
from backend.utils.auth import AuthCtx, get_auth


def _admin_ctx() -> AuthCtx:
    return AuthCtx(role="admin", player_id=None, user_id=1, team_name=None, team_id=None)


def _player_ctx(pid: int) -> AuthCtx:
    return AuthCtx(role="player", player_id=pid, user_id=2, team_name=None, team_id=None)


def _mk_match(db: Session, pa: Player, pb: Player, d: date, tour: str = "T") -> Match:
    m = Match(
        tournament=tour,
        tournament_level="IC",
        round="1R",
        date=d,
        format="singles",
        player_a_id=pa.id,
        player_b_id=pb.id,
        result="win",
        annotation_status="complete",
        annotation_progress=1.0,
    )
    db.add(m)
    db.flush()
    return m


def _mk_set_rally(db: Session, m: Match, n_rallies: int = 3) -> GameSet:
    gs = GameSet(match_id=m.id, set_num=1, winner="player_a", score_a=21, score_b=10)
    db.add(gs)
    db.flush()
    for i in range(1, n_rallies + 1):
        r = Rally(
            set_id=gs.id,
            rally_num=i,
            server="player_a",
            winner="player_a" if i % 2 == 0 else "player_b",
            end_type="forced_error",
            rally_length=4,
            score_a_after=i,
            score_b_after=0,
        )
        db.add(r)
        db.flush()
        s = Stroke(rally_id=r.id, stroke_num=1, player="player_a", shot_type="smash", hit_zone="BC")
        db.add(s)
    db.flush()
    return gs


@pytest.fixture
def seeded(db_session):
    pa = Player(name="A", dominant_hand="R")
    pb = Player(name="B", dominant_hand="R")
    db_session.add_all([pa, pb])
    db_session.flush()
    m1 = _mk_match(db_session, pa, pb, date(2025, 1, 10))
    m2 = _mk_match(db_session, pa, pb, date(2025, 3, 15))
    m3 = _mk_match(db_session, pa, pb, date(2025, 6, 1))
    for mm in (m1, m2, m3):
        _mk_set_rally(db_session, mm)
    db_session.flush()

    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_auth] = _admin_ctx
    # routers call get_auth(request) directly, so dependency_overrides は効かない。
    # X-Role ヘッダで admin 認証する (loopback + ENVIRONMENT=development で有効)。
    client = TestClient(app, headers={"X-Role": "admin"})
    try:
        yield client, db_session, pa, [m1, m2, m3]
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 1) data_package: section filter
# ---------------------------------------------------------------------------

class TestDataPackageSections:
    def test_default_returns_full_output(self, seeded):
        client, _, _, matches = seeded
        # signing は env に SECRET が必要なので環境次第。署名失敗時は 500 になり得るので
        # signing 関数をパススルー化する。
        with patch("backend.utils.export_signing.sign_package", side_effect=lambda p: p):
            r = client.get(f"/api/export/package?match_id={matches[0].id}")
        assert r.status_code == 200, r.text
        data = r.json()
        # full output: 全キーが存在する
        for key in ("match", "players", "sets", "rallies", "strokes"):
            assert key in data, f"key {key} missing"
        # backward compat: X-Sections-Applied は default 全部
        assert "X-Sections-Applied" in r.headers
        applied = r.headers["X-Sections-Applied"].split(",")
        assert set(applied) >= {"meta", "sets", "rallies", "strokes", "conditions", "reports"}

    def test_filter_omits_unselected_keys(self, seeded):
        client, _, _, matches = seeded
        r = client.get(f"/api/export/package?match_id={matches[0].id}&sections=meta,sets")
        assert r.status_code == 200, r.text
        data = r.json()
        assert "match" in data  # meta
        assert "players" in data
        assert "sets" in data
        assert "rallies" not in data
        assert "strokes" not in data
        assert "conditions" not in data
        assert "reports" not in data
        assert r.headers.get("X-Sections-Applied") == "meta,sets"

    def test_reports_section_present_when_requested(self, seeded):
        client, _, _, matches = seeded
        r = client.get(f"/api/export/package?match_id={matches[0].id}&sections=reports")
        assert r.status_code == 200, r.text
        data = r.json()
        assert "reports" in data
        assert data["reports"]["match_id"] == matches[0].id
        assert "match" not in data
        assert "sets" not in data


# ---------------------------------------------------------------------------
# 2) export_period
# ---------------------------------------------------------------------------

class TestExportPeriod:
    def test_range_filters_matches(self, seeded):
        client, _, pa, matches = seeded
        r = client.get(
            f"/api/export/period?player_id={pa.id}&date_from=2025-02-01&date_to=2025-04-30"
        )
        assert r.status_code == 200, r.text
        items = r.json()
        # 2025-03-15 の 1 件だけが範囲内
        assert len(items) == 1
        assert items[0]["match"]["id"] == matches[1].id
        assert r.headers.get("X-Date-Range") == "2025-02-01..2025-04-30"

    def test_ndjson_streams(self, seeded):
        client, _, pa, _ = seeded
        r = client.get(f"/api/export/period?player_id={pa.id}&format=ndjson")
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("application/x-ndjson")
        lines = [ln for ln in r.text.strip().split("\n") if ln]
        assert len(lines) == 3
        for ln in lines:
            obj = json.loads(ln)
            assert "match" in obj

    def test_413_when_over_cap(self, seeded):
        client, db, pa, _ = seeded
        # Match を 501 件まで増やして cap 超過させる
        pb = db.query(Player).filter(Player.name == "B").first()
        for i in range(501):
            mx = Match(
                tournament="bulk",
                tournament_level="IC",
                round="1R",
                date=date(2024, 1, 1),
                format="singles",
                player_a_id=pa.id,
                player_b_id=pb.id,
                result="win",
                annotation_status="complete",
                annotation_progress=1.0,
            )
            db.add(mx)
        db.flush()
        r = client.get(f"/api/export/period?player_id={pa.id}&date_from=2024-01-01&date_to=2024-01-01")
        assert r.status_code == 413, r.text


class TestExportPeriodRoleGate:
    def test_player_role_forbidden(self, seeded):
        client, _, pa, _ = seeded
        # X-Role: player を渡すと export_period の role gate が 403 を返す
        r = client.get(
            f"/api/export/period?player_id={pa.id}",
            headers={"X-Role": "player", "X-Player-Id": str(pa.id)},
        )
        assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# 3) reports.scouting + player_growth date filtering
# ---------------------------------------------------------------------------

class TestReportsDateFilter:
    def test_scouting_narrows_matches(self, seeded):
        client, _, pa, matches = seeded
        # 範囲なし: 3 試合
        r_all = client.get(f"/api/reports/scouting?player_id={pa.id}")
        # PDF or JSON fallback. JSON path expected if reportlab not configured for fonts.
        # We rely on "total_matches" inside JSON fallback. If PDF, just confirm header.
        if r_all.headers.get("content-type", "").startswith("application/json"):
            assert r_all.json()["data"]["total_matches"] == 3

        r_narrow = client.get(
            f"/api/reports/scouting?player_id={pa.id}&date_from=2025-02-01&date_to=2025-04-30"
        )
        assert r_narrow.status_code == 200
        assert r_narrow.headers.get("X-Date-Range") == "2025-02-01..2025-04-30"
        if r_narrow.headers.get("content-type", "").startswith("application/json"):
            assert r_narrow.json()["data"]["total_matches"] == 1

    def test_player_growth_date_filter(self, seeded):
        client, _, pa, _ = seeded
        r = client.get(
            f"/api/reports/player_growth?player_id={pa.id}&date_from=2025-02-01&date_to=2025-04-30"
        )
        assert r.status_code == 200, r.text
        assert r.headers.get("X-Date-Range") == "2025-02-01..2025-04-30"
        data = r.json()
        assert data["data"]["total_matches"] == 1
