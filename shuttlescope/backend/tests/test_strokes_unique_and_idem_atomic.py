"""strokes (rally_id, stroke_num) の部分一意制約と、/api/strokes/batch の
冒等キーが業務行と同じ commit で永続化されることを検証する。

対応する穴:
  (2) strokes に (rally_id, stroke_num) の一意制約が無かった
      → migration 0062 + models の部分一意インデックス。
         create_all (テストの test_engine) でも張られるので、同一
         (rally_id, stroke_num) の active 行を 2 つ入れようとすると
         IntegrityError になる。論理削除済み (deleted_at) とは衝突しない。
  (1) 冒等キーの保存が commit 成功後にしか行われず、commit 前に
      失敗した再送が本処理を再実行する
      → store_in_session で業務行と同じトランザクションに積む。
         commit 後は AnalysisCache に idem レコードが残り、in-memory
         cache を落としても DB から replay できる。
"""
from __future__ import annotations

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from backend.db.database import get_db
from backend.db.models import AnalysisCache, GameSet, Match, Player, Rally, Stroke, User
from backend.main import app
from backend.utils.jwt_utils import create_access_token


@pytest.fixture()
def game_set(db_session) -> GameSet:
    a = Player(name="UQ-A", dominant_hand="R")
    b = Player(name="UQ-B", dominant_hand="R")
    db_session.add_all([a, b])
    db_session.flush()
    m = Match(
        tournament="uqtest", tournament_level="practice", round="R1",
        date=date(2026, 11, 1), format="singles",
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
def client(db_session, game_set):
    app.dependency_overrides[get_db] = lambda: db_session
    match = db_session.get(Match, game_set.match_id)
    user = User(
        username=f"uq-player-{match.player_a_id}", role="player",
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


def _rally(db_session, game_set) -> Rally:
    r = Rally(
        set_id=game_set.id, rally_num=1, server="player_a", winner="player_a",
        end_type="ace", rally_length=1,
        score_a_before=0, score_b_before=0, score_a_after=1, score_b_after=0,
    )
    db_session.add(r)
    db_session.flush()
    db_session.commit()
    return r


def test_duplicate_active_stroke_num_rejected_by_unique_index(db_session, game_set):
    r = _rally(db_session, game_set)
    db_session.add(Stroke(rally_id=r.id, stroke_num=1, player="player_a", shot_type="clear"))
    db_session.commit()
    # 同じ (rally_id, stroke_num) の active 行をもう一つ → 一意制約違反。
    db_session.add(Stroke(rally_id=r.id, stroke_num=1, player="player_b", shot_type="drop"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_soft_deleted_stroke_does_not_block_same_stroke_num(db_session, game_set):
    r = _rally(db_session, game_set)
    dead = Stroke(rally_id=r.id, stroke_num=1, player="player_a", shot_type="clear")
    db_session.add(dead)
    db_session.flush()
    dead.deleted_at = datetime.utcnow()
    db_session.commit()
    # deleted_at が立っているので、同じ番号の active 行は通る。
    db_session.add(Stroke(rally_id=r.id, stroke_num=1, player="player_b", shot_type="drop"))
    db_session.commit()  # raises しなければ OK
    active = (
        db_session.query(Stroke)
        .filter(Stroke.rally_id == r.id, Stroke.stroke_num == 1, Stroke.deleted_at.is_(None))
        .all()
    )
    assert len(active) == 1


def test_batch_persists_idem_key_in_same_commit(client, db_session, game_set):
    body = {
        "rally": {
            "set_id": game_set.id, "rally_num": 1, "server": "player_a",
            "winner": "player_a", "end_type": "ace", "rally_length": 1,
            "score_a_after": 1, "score_b_after": 0,
        },
        "strokes": [
            {"stroke_num": 1, "player": "player_a", "shot_type": "short_service"},
        ],
    }
    key = "idemkey-batch-0001"
    res = client.post("/api/strokes/batch", json=body,
                      headers={"X-Idempotency-Key": key})
    assert res.status_code in (200, 201), res.text

    # idem レコードが AnalysisCache に DB 永続化されている
    # (= 業務行と同じ commit で書かれた)。
    rec = (
        db_session.query(AnalysisCache)
        .filter(AnalysisCache.cache_key == "idem:" + key)
        .first()
    )
    assert rec is not None
    assert rec.analysis_type == "idempotency"

    # in-memory cache を落としても DB から replay され、再送でラリーが
    # 二重には入らない。
    from backend.utils import idempotency as _idem
    _idem._records.clear()
    res2 = client.post("/api/strokes/batch", json=body,
                       headers={"X-Idempotency-Key": key})
    assert res2.status_code in (200, 201), res2.text
    rallies = (
        db_session.query(Rally)
        .filter(Rally.set_id == game_set.id, Rally.rally_num == 1)
        .all()
    )
    assert len(rallies) == 1
