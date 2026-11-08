"""(rally_id, stroke_num) の一意性のテスト。

一意性が無かったため、Pass2 の再実行・再送・複数端末で同じ stroke_num が二重に
入り、rally_length と下流のカウントが静かにずれていた。migration 0064 /
Stroke.__table_args__ の部分一意インデックス
(uq_strokes_rally_id_stroke_num_active) を固定する。

部分インデックスにしているのは、論理削除 (deleted_at) 済みの行と衝突させない
ため。rallies の 0053 と同じ思想・同じ形。
"""
from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from backend.db.models import Player, Match, GameSet, Rally, Stroke


@pytest.fixture()
def rally(db_session) -> Rally:
    a = Player(name="打球一意A", dominant_hand="R")
    b = Player(name="打球一意B", dominant_hand="R")
    db_session.add_all([a, b])
    db_session.flush()
    m = Match(
        tournament="打球一意テスト",
        tournament_level="practice",
        round="R1",
        date=date(2026, 11, 5),
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
    r = Rally(
        set_id=gs.id,
        rally_num=1,
        server="player_a",
        winner="player_a",
        end_type="ace",
        rally_length=3,
        score_a_after=1,
        score_b_after=0,
    )
    db_session.add(r)
    db_session.flush()
    db_session.commit()
    return r


def _stroke(rally_id: int, stroke_num: int) -> Stroke:
    return Stroke(
        rally_id=rally_id,
        stroke_num=stroke_num,
        player="player_a",
        shot_type="clear",
    )


class TestStrokeUniqueIndex:
    def test_index_exists(self, db_session):
        names = {ix["name"] for ix in inspect(db_session.get_bind()).get_indexes("strokes")}
        assert "uq_strokes_rally_id_stroke_num_active" in names

    def test_duplicate_stroke_num_is_rejected(self, db_session, rally):
        db_session.add(_stroke(rally.id, 1))
        db_session.commit()
        db_session.add(_stroke(rally.id, 1))
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_soft_deleted_row_does_not_block_reuse(self, db_session, rally):
        first = _stroke(rally.id, 1)
        db_session.add(first)
        db_session.commit()
        first.deleted_at = datetime.utcnow()
        db_session.commit()
        # 部分インデックスなので、論理削除済みの #1 と新しい #1 は衝突しない。
        db_session.add(_stroke(rally.id, 1))
        db_session.commit()

    def test_same_number_in_another_rally_is_fine(self, db_session, rally):
        other = Rally(
            set_id=rally.set_id,
            rally_num=2,
            server="player_a",
            winner="player_a",
            end_type="ace",
            rally_length=1,
            score_a_after=2,
            score_b_after=0,
        )
        db_session.add(other)
        db_session.flush()
        db_session.add(_stroke(rally.id, 1))
        db_session.add(_stroke(other.id, 1))
        db_session.commit()  # 別ラリーの同じ番号は通る
