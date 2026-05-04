"""アノテーション記録方式フィールドのテスト

migration 0002 で追加されたフィールド:
- Rally.annotation_mode  (manual_record / assisted_record)
- Rally.review_status    (pending / completed)
- Stroke.source_method   (manual / assisted / corrected)
"""
import pytest
from datetime import date
from fastapi.testclient import TestClient

from backend.main import app
from backend.db.database import get_db
from backend.db.models import Player, Match, GameSet, Rally, Stroke


# ─── ヘルパー ─────────────────────────────────────────────────────────────────

def _make_player(db, name="テスト選手"):
    p = Player(name=name)
    db.add(p)
    db.flush()
    return p


def _make_match(db, pa, pb):
    m = Match(
        tournament="テスト大会",
        tournament_level="IC",
        round="1回戦",
        date=date(2026, 4, 8),
        format="singles",
        player_a_id=pa.id,
        player_b_id=pb.id,
        result="win",
    )
    db.add(m)
    db.flush()
    return m


def _make_set(db, match):
    s = GameSet(match_id=match.id, set_num=1)
    db.add(s)
    db.flush()
    return s


@pytest.fixture
def mode_client(db_session):
    """annotation_mode テスト用クライアント"""
    pa = _make_player(db_session, "選手A")
    pb = _make_player(db_session, "選手B")
    match = _make_match(db_session, pa, pb)
    game_set = _make_set(db_session, match)

    app.dependency_overrides[get_db] = lambda: db_session
    # analyst 権限でテスト (新しい team scope ガードを通すため X-Role 付与)
    client = TestClient(app, headers={"X-Role": "analyst"})
    yield client, game_set.id
    app.dependency_overrides.clear()


# ─── ORM レベルテスト ─────────────────────────────────────────────────────────

class TestAnnotationModeORM:
    """Rally / Stroke モデルの新フィールドが機能する"""

    def test_rally_annotation_mode_manual(self, db_session):
        """Rally.annotation_mode = 'manual_record' で保存できる"""
        pa = _make_player(db_session, "ORM選手A")
        pb = _make_player(db_session, "ORM選手B")
        match = _make_match(db_session, pa, pb)
        game_set = _make_set(db_session, match)

        rally = Rally(
            set_id=game_set.id,
            rally_num=1,
            server="player_a",
            winner="player_a",
            end_type="ace",
            rally_length=0,
            score_a_after=1,
            score_b_after=0,
            annotation_mode="manual_record",
        )
        db_session.add(rally)
        db_session.flush()

        fetched = db_session.get(Rally, rally.id)
        assert fetched is not None
        assert fetched.annotation_mode == "manual_record"

    def test_rally_annotation_mode_assisted(self, db_session):
        """Rally.annotation_mode = 'assisted_record' で保存できる"""
        pa = _make_player(db_session, "ORM選手C")
        pb = _make_player(db_session, "ORM選手D")
        match = _make_match(db_session, pa, pb)
        game_set = _make_set(db_session, match)

        rally = Rally(
            set_id=game_set.id,
            rally_num=1,
            server="player_a",
            winner="player_b",
            end_type="unforced_error",
            rally_length=0,
            score_a_after=0,
            score_b_after=1,
            annotation_mode="assisted_record",
        )
        db_session.add(rally)
        db_session.flush()

        fetched = db_session.get(Rally, rally.id)
        assert fetched.annotation_mode == "assisted_record"

    def test_rally_review_status_pending(self, db_session):
        """Rally.review_status = 'pending' で保存できる"""
        pa = _make_player(db_session, "ORM選手E")
        pb = _make_player(db_session, "ORM選手F")
        match = _make_match(db_session, pa, pb)
        game_set = _make_set(db_session, match)

        rally = Rally(
            set_id=game_set.id,
            rally_num=1,
            server="player_a",
            winner="player_a",
            end_type="ace",
            rally_length=0,
            score_a_after=1,
            score_b_after=0,
            review_status="pending",
        )
        db_session.add(rally)
        db_session.flush()

        fetched = db_session.get(Rally, rally.id)
        assert fetched.review_status == "pending"

    def test_stroke_source_method_manual(self, db_session):
        """Stroke.source_method = 'manual' で保存できる"""
        pa = _make_player(db_session, "ORM選手G")
        pb = _make_player(db_session, "ORM選手H")
        match = _make_match(db_session, pa, pb)
        game_set = _make_set(db_session, match)

        rally = Rally(
            set_id=game_set.id, rally_num=1, server="player_a",
            winner="player_a", end_type="ace", rally_length=1,
            score_a_after=1, score_b_after=0,
        )
        db_session.add(rally)
        db_session.flush()

        stroke = Stroke(
            rally_id=rally.id,
            stroke_num=1,
            player="player_a",
            shot_type="short_service",
            source_method="manual",
        )
        db_session.add(stroke)
        db_session.flush()

        fetched = db_session.get(Stroke, stroke.id)
        assert fetched.source_method == "manual"

    def test_stroke_source_method_assisted(self, db_session):
        """Stroke.source_method = 'assisted' で保存できる"""
        pa = _make_player(db_session, "ORM選手I")
        pb = _make_player(db_session, "ORM選手J")
        match = _make_match(db_session, pa, pb)
        game_set = _make_set(db_session, match)

        rally = Rally(
            set_id=game_set.id, rally_num=1, server="player_a",
            winner="player_a", end_type="ace", rally_length=1,
            score_a_after=1, score_b_after=0,
        )
        db_session.add(rally)
        db_session.flush()

        stroke = Stroke(
            rally_id=rally.id,
            stroke_num=1,
            player="player_a",
            shot_type="short_service",
            source_method="assisted",
        )
        db_session.add(stroke)
        db_session.flush()

        fetched = db_session.get(Stroke, stroke.id)
        assert fetched.source_method == "assisted"

    def test_fields_nullable_by_default(self, db_session):
        """annotation_mode / review_status / source_method は省略可能（既存互換）"""
        pa = _make_player(db_session, "ORM選手K")
        pb = _make_player(db_session, "ORM選手L")
        match = _make_match(db_session, pa, pb)
        game_set = _make_set(db_session, match)

        rally = Rally(
            set_id=game_set.id, rally_num=1, server="player_a",
            winner="player_a", end_type="ace", rally_length=1,
            score_a_after=1, score_b_after=0,
        )
        db_session.add(rally)
        db_session.flush()

        stroke = Stroke(
            rally_id=rally.id, stroke_num=1,
            player="player_a", shot_type="short_service",
        )
        db_session.add(stroke)
        db_session.flush()

        r = db_session.get(Rally, rally.id)
        s = db_session.get(Stroke, stroke.id)
        assert r.annotation_mode is None
        assert r.review_status is None
        assert s.source_method is None


# ─── API レベルテスト ─────────────────────────────────────────────────────────

class TestAnnotationModeBatchAPI:
    """POST /strokes/batch で annotation_mode / source_method が保存される"""

    def _batch_payload(self, set_id: int, annotation_mode: str, source_method: str) -> dict:
        return {
            "rally": {
                "set_id": set_id,
                "rally_num": 1,
                "server": "player_a",
                "winner": "player_a",
                "end_type": "ace",
                "rally_length": 1,
                "score_a_after": 1,
                "score_b_after": 0,
                "is_deuce": False,
                "annotation_mode": annotation_mode,
            },
            "strokes": [
                {
                    "stroke_num": 1,
                    "player": "player_a",
                    "shot_type": "short_service",
                    "source_method": source_method,
                }
            ],
        }

    def test_batch_saves_manual_record(self, mode_client):
        """annotation_mode='manual_record' でラリーが保存される"""
        client, set_id = mode_client
        resp = client.post(
            "/api/strokes/batch",
            json=self._batch_payload(set_id, "manual_record", "manual"),
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["rally_id"] is not None

    def test_batch_saves_assisted_record(self, mode_client):
        """annotation_mode='assisted_record' でラリーが保存される"""
        client, set_id = mode_client
        resp = client.post(
            "/api/strokes/batch",
            json=self._batch_payload(set_id, "assisted_record", "assisted"),
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["success"] is True

    def test_batch_without_annotation_mode(self, mode_client):
        """annotation_mode なしでも保存できる（既存互換）"""
        client, set_id = mode_client
        payload = {
            "rally": {
                "set_id": set_id,
                "rally_num": 1,
                "server": "player_a",
                "winner": "player_a",
                "end_type": "ace",
                "rally_length": 1,
                "score_a_after": 1,
                "score_b_after": 0,
                "is_deuce": False,
            },
            "strokes": [
                {
                    "stroke_num": 1,
                    "player": "player_a",
                    "shot_type": "short_service",
                }
            ],
        }
        resp = client.post("/api/strokes/batch", json=payload)
        assert resp.status_code == 201
        assert resp.json()["success"] is True
