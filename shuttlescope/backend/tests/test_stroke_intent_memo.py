"""ショットの意図メモ (customer request #6, 2026-11-05) のテスト。

対象:
- Stroke.intent_tag / intent_note カラム (ORM 保存)
- POST /api/strokes/batch / POST /api/strokes / PUT /api/strokes/{id} での保存と正規化
- 固定語彙への正規化 (未知タグ -> 'other'、空 -> NULL、自由記述の前後空白除去)
- stroke_to_dict / data_package エクスポートに含まれる
- migration 0061 が additive (既存 NULL を保つ) で、downgrade で列が消える
"""
import pathlib
import pytest
from datetime import date
from fastapi.testclient import TestClient

from backend.main import app
from backend.db.database import get_db
from backend.db.models import Player, Match, GameSet, Rally, Stroke
from backend.routers.strokes import _canonicalize_intent_tag, _clean_intent_note


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
        date=date(2026, 11, 5),
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


def _make_rally(db, game_set):
    r = Rally(
        set_id=game_set.id,
        rally_num=1,
        server="player_a",
        winner="player_b",
        end_type="error",
        rally_length=3,
        score_a_after=0,
        score_b_after=1,
    )
    db.add(r)
    db.flush()
    return r


@pytest.fixture
def intent_client(db_session):
    pa = _make_player(db_session, "選手A")
    pb = _make_player(db_session, "選手B")
    match = _make_match(db_session, pa, pb)
    game_set = _make_set(db_session, match)
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app, headers={"X-Role": "analyst"})
    yield client, game_set.id
    app.dependency_overrides.clear()


# ─── 正規化ユニット ───────────────────────────────────────────────────────────

class TestIntentNormalization:
    def test_known_tags_pass_through(self):
        for tag in ["deep", "net", "body", "sideline", "cross", "deception", "clear_safe", "other"]:
            assert _canonicalize_intent_tag(tag) == tag

    def test_unknown_tag_becomes_other(self):
        assert _canonicalize_intent_tag("somethingelse") == "other"
        assert _canonicalize_intent_tag("DEEP") == "other"  # 綴り/大小違いは素通ししない

    def test_empty_tag_is_null(self):
        assert _canonicalize_intent_tag(None) is None
        assert _canonicalize_intent_tag("") is None
        assert _canonicalize_intent_tag("   ") is None

    def test_note_trims_and_nulls_empty(self):
        assert _clean_intent_note("  奥を狙った  ") == "奥を狙った"
        assert _clean_intent_note("") is None
        assert _clean_intent_note("   ") is None
        assert _clean_intent_note(None) is None


# ─── ORM レベル ───────────────────────────────────────────────────────────────

class TestIntentMemoORM:
    def test_stroke_saves_intent_fields(self, db_session):
        pa = _make_player(db_session, "A")
        pb = _make_player(db_session, "B")
        match = _make_match(db_session, pa, pb)
        gs = _make_set(db_session, match)
        rally = _make_rally(db_session, gs)
        s = Stroke(
            rally_id=rally.id,
            stroke_num=1,
            player="player_a",
            shot_type="clear",
            intent_tag="deep",
            intent_note="奥に打とうとしてネットにかけた",
        )
        db_session.add(s)
        db_session.flush()
        fetched = db_session.get(Stroke, s.id)
        assert fetched.intent_tag == "deep"
        assert fetched.intent_note == "奥に打とうとしてネットにかけた"

    def test_intent_fields_optional(self, db_session):
        pa = _make_player(db_session, "A")
        pb = _make_player(db_session, "B")
        match = _make_match(db_session, pa, pb)
        gs = _make_set(db_session, match)
        rally = _make_rally(db_session, gs)
        s = Stroke(rally_id=rally.id, stroke_num=1, player="player_a", shot_type="drive")
        db_session.add(s)
        db_session.flush()
        fetched = db_session.get(Stroke, s.id)
        assert fetched.intent_tag is None
        assert fetched.intent_note is None


# ─── API レベル ───────────────────────────────────────────────────────────────

class TestIntentMemoAPI:
    def _batch_payload(self, set_id, intent_tag=None, intent_note=None):
        stroke = {"stroke_num": 1, "player": "player_a", "shot_type": "clear"}
        if intent_tag is not None:
            stroke["intent_tag"] = intent_tag
        if intent_note is not None:
            stroke["intent_note"] = intent_note
        return {
            "rally": {
                "set_id": set_id, "rally_num": 1, "server": "player_a",
                "winner": "player_b", "end_type": "error", "rally_length": 1,
                "score_a_after": 0, "score_b_after": 1, "is_deuce": False,
            },
            "strokes": [stroke],
        }

    def test_batch_saves_intent(self, intent_client, db_session):
        client, set_id = intent_client
        resp = client.post(
            "/api/strokes/batch",
            json=self._batch_payload(set_id, "net", "  ネット前に落とすつもりだった  "),
        )
        assert resp.status_code == 201
        rally_id = resp.json()["data"]["rally_id"]
        s = db_session.query(Stroke).filter(Stroke.rally_id == rally_id).first()
        assert s.intent_tag == "net"
        assert s.intent_note == "ネット前に落とすつもりだった"

    def test_batch_unknown_tag_normalized(self, intent_client, db_session):
        client, set_id = intent_client
        resp = client.post(
            "/api/strokes/batch",
            json=self._batch_payload(set_id, "totally_made_up"),
        )
        assert resp.status_code == 201
        rally_id = resp.json()["data"]["rally_id"]
        s = db_session.query(Stroke).filter(Stroke.rally_id == rally_id).first()
        assert s.intent_tag == "other"

    def test_batch_without_intent_is_null(self, intent_client, db_session):
        client, set_id = intent_client
        resp = client.post("/api/strokes/batch", json=self._batch_payload(set_id))
        assert resp.status_code == 201
        rally_id = resp.json()["data"]["rally_id"]
        s = db_session.query(Stroke).filter(Stroke.rally_id == rally_id).first()
        assert s.intent_tag is None
        assert s.intent_note is None

    def test_create_single_stroke_saves_intent(self, intent_client, db_session):
        client, set_id = intent_client
        rally = _make_rally(db_session, db_session.get(GameSet, set_id))
        resp = client.post(
            f"/api/strokes?rally_id={rally.id}",
            json={
                "stroke_num": 1, "player": "player_a", "shot_type": "smash",
                "intent_tag": "body", "intent_note": "体を狙った",
            },
        )
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["intent_tag"] == "body"
        assert data["intent_note"] == "体を狙った"

    def test_update_stroke_sets_intent_without_clobbering(self, intent_client, db_session):
        client, set_id = intent_client
        rally = _make_rally(db_session, db_session.get(GameSet, set_id))
        s = Stroke(rally_id=rally.id, stroke_num=1, player="player_a", shot_type="drop")
        db_session.add(s)
        db_session.commit()
        # intent だけを送る更新 (他項目は未送信=保持される)
        resp = client.put(
            f"/api/strokes/{s.id}",
            json={"stroke_num": 1, "player": "player_a", "shot_type": "drop",
                  "intent_tag": "deception", "intent_note": "崩しにいった"},
        )
        assert resp.status_code == 200
        db_session.refresh(s)
        assert s.intent_tag == "deception"
        assert s.intent_note == "崩しにいった"


# ─── エクスポート ─────────────────────────────────────────────────────────────

class TestIntentMemoExport:
    def test_stroke_to_dict_includes_intent(self, db_session):
        from backend.routers.strokes import stroke_to_dict
        pa = _make_player(db_session, "A")
        pb = _make_player(db_session, "B")
        match = _make_match(db_session, pa, pb)
        gs = _make_set(db_session, match)
        rally = _make_rally(db_session, gs)
        s = Stroke(rally_id=rally.id, stroke_num=1, player="player_a",
                   shot_type="clear", intent_tag="deep", intent_note="奥狙い")
        db_session.add(s)
        db_session.flush()
        d = stroke_to_dict(s)
        assert d["intent_tag"] == "deep"
        assert d["intent_note"] == "奥狙い"

    def test_data_package_stroke_dict_includes_intent(self, db_session):
        from backend.routers.data_package import _stroke_dict
        pa = _make_player(db_session, "A")
        pb = _make_player(db_session, "B")
        match = _make_match(db_session, pa, pb)
        gs = _make_set(db_session, match)
        rally = _make_rally(db_session, gs)
        s = Stroke(rally_id=rally.id, stroke_num=1, player="player_a",
                   shot_type="clear", intent_tag="sideline", intent_note="サイド")
        db_session.add(s)
        db_session.flush()
        d = _stroke_dict(s)
        assert d["intent_tag"] == "sideline"
        assert d["intent_note"] == "サイド"


# ─── マイグレーション ─────────────────────────────────────────────────────────

def _load_migration():
    import importlib.util
    path = (
        pathlib.Path(__file__).resolve().parents[1]
        / "db" / "migrations" / "versions" / "0061_stroke_intent_memo.py"
    )
    spec = importlib.util.spec_from_file_location("mig0061", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestMigration0061:
    def test_revision_chain(self):
        mod = _load_migration()
        assert mod.revision == "0061"
        assert mod.down_revision == "0060"

    def test_upgrade_adds_columns_and_downgrade_removes(self):
        import sqlalchemy as sa
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        mod = _load_migration()
        engine = sa.create_engine("sqlite:///:memory:")
        with engine.connect() as conn:
            conn.execute(sa.text("CREATE TABLE strokes (id INTEGER PRIMARY KEY, land_zone TEXT)"))
            ctx = MigrationContext.configure(conn)
            op = Operations(ctx)
            import backend.db.migrations.versions  # noqa: F401
            # alembic op はグローバル proxy なので明示 bind
            from alembic import op as alembic_op_module  # noqa: F401
            # upgrade: モジュール内 op を使うため、op を一時的に差し替える
            mod.op = op
            mod.upgrade()
            cols = {c["name"] for c in sa.inspect(conn).get_columns("strokes")}
            assert "intent_tag" in cols
            assert "intent_note" in cols
            # 既存行があっても NULL を保つ (additive)
            conn.execute(sa.text("INSERT INTO strokes (id, land_zone) VALUES (1, 'BR')"))
            row = conn.execute(sa.text("SELECT intent_tag, intent_note FROM strokes WHERE id=1")).first()
            assert row == (None, None)
            mod.downgrade()
            cols2 = {c["name"] for c in sa.inspect(conn).get_columns("strokes")}
            assert "intent_tag" not in cols2
            assert "intent_note" not in cols2
