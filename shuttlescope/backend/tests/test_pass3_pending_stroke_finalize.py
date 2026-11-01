"""Pass 3 完了時の未確定 sentinel stroke 確定・409拒否と、解析クエリからの除外 (監査 #475)。

- Pass 2 は最終打を stroke_num=9999 / shot_type='__final_pending' で挿入する。
- Pass 3 完了 (review_status=completed) 時に:
    * shot_type が確定済で stroke_num が 9999 のままなら通常番号へ再採番する。
    * shot_type が '__final_pending' のままなら 409 で拒否する (fail closed)。
- 解析共通ローダ (bundle_context) は pending sentinel 行を読まない。
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import GameSet, Match, Player, Rally, Stroke
from backend.main import app
from backend.analysis.pending_strokes import (
    PENDING_FINAL_SHOT_TYPE,
    PENDING_FINAL_STROKE_NUM,
    exclude_pending_strokes,
    filter_non_pending,
    is_pending_stroke,
)


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    c = TestClient(app, headers={"X-Role": "admin"})
    yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def rally(db_session):
    a = Player(name="P475A", dominant_hand="R")
    b = Player(name="P475B", dominant_hand="R")
    db_session.add_all([a, b])
    db_session.flush()
    m = Match(
        tournament="#475",
        tournament_level="practice",
        round="R1",
        date=date(2026, 10, 22),
        format="singles",
        player_a_id=a.id,
        player_b_id=b.id,
        result="unknown",
    )
    db_session.add(m)
    db_session.flush()
    gs = GameSet(match_id=m.id, set_num=1)
    db_session.add(gs)
    db_session.flush()
    r = Rally(set_id=gs.id, rally_num=1, review_status="pending")
    db_session.add(r)
    db_session.flush()
    db_session.commit()
    return r


def _add_stroke(db, rally_id, num, shot_type, player="player_a"):
    s = Stroke(rally_id=rally_id, stroke_num=num, player=player, shot_type=shot_type)
    db.add(s)
    db.flush()
    return s


def _review(client, rally_id, status):
    return client.put(
        f"/api/cv-candidates/review/{rally_id}",
        json={"review_status": status},
    )


class TestPass3Finalize:
    def test_classified_sentinel_is_renumbered_on_complete(self, client, db_session, rally):
        _add_stroke(db_session, rally.id, 1, "serve")
        _add_stroke(db_session, rally.id, 2, "clear")
        # shot_type は確定済だが stroke_num が sentinel(9999) のまま
        _add_stroke(db_session, rally.id, PENDING_FINAL_STROKE_NUM, "smash")
        db_session.commit()

        resp = _review(client, rally.id, "completed")
        assert resp.status_code == 200, resp.text

        rows = (
            db_session.query(Stroke)
            .filter(Stroke.rally_id == rally.id)
            .order_by(Stroke.stroke_num)
            .all()
        )
        nums = [s.stroke_num for s in rows]
        assert PENDING_FINAL_STROKE_NUM not in nums
        assert nums == [1, 2, 3]
        assert rows[-1].shot_type == "smash"
        db_session.refresh(rally)
        assert rally.review_status == "completed"

    def test_unclassified_pending_is_rejected_with_409(self, client, db_session, rally):
        _add_stroke(db_session, rally.id, 1, "serve")
        _add_stroke(
            db_session, rally.id, PENDING_FINAL_STROKE_NUM, PENDING_FINAL_SHOT_TYPE
        )
        db_session.commit()

        resp = _review(client, rally.id, "completed")
        assert resp.status_code == 409, resp.text

        # 拒否時は何も確定させず、review_status も pending のまま
        db_session.refresh(rally)
        assert rally.review_status == "pending"
        row = (
            db_session.query(Stroke)
            .filter(
                Stroke.rally_id == rally.id,
                Stroke.stroke_num == PENDING_FINAL_STROKE_NUM,
            )
            .one()
        )
        assert row.shot_type == PENDING_FINAL_SHOT_TYPE

    def test_pending_to_pending_does_not_finalize(self, client, db_session, rally):
        _add_stroke(db_session, rally.id, 1, "serve")
        _add_stroke(
            db_session, rally.id, PENDING_FINAL_STROKE_NUM, PENDING_FINAL_SHOT_TYPE
        )
        db_session.commit()
        # completed 以外への更新では確定処理を走らせない
        resp = _review(client, rally.id, "pending")
        assert resp.status_code == 200, resp.text


class TestPendingStrokeHelper:
    def test_is_pending_detects_either_sentinel(self, db_session, rally):
        full = _add_stroke(
            db_session, rally.id, PENDING_FINAL_STROKE_NUM, PENDING_FINAL_SHOT_TYPE
        )
        only_num = _add_stroke(db_session, rally.id, PENDING_FINAL_STROKE_NUM, "smash")
        only_type = _add_stroke(db_session, rally.id, 2, PENDING_FINAL_SHOT_TYPE)
        normal = _add_stroke(db_session, rally.id, 1, "serve")
        db_session.commit()
        assert is_pending_stroke(full)
        assert is_pending_stroke(only_num)
        assert is_pending_stroke(only_type)
        assert not is_pending_stroke(normal)
        assert filter_non_pending(
            [full, only_num, only_type, normal]
        ) == [normal]

    def test_exclude_pending_strokes_query(self, db_session, rally):
        _add_stroke(db_session, rally.id, 1, "serve")
        _add_stroke(
            db_session, rally.id, PENDING_FINAL_STROKE_NUM, PENDING_FINAL_SHOT_TYPE
        )
        db_session.commit()
        q = db_session.query(Stroke).filter(Stroke.rally_id == rally.id)
        kept = exclude_pending_strokes(q).all()
        assert [s.stroke_num for s in kept] == [1]
