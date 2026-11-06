"""G6 #524 (option A): 完了セットが試合を決したら end_set が match の result / final_score を
自動入力する。手入力値 (result_source='manual' の実結果) は絶対に上書きしない。

検証: 2-0 / 2-1 / 未決着 / early finish / walkover / manual 優先 / 再実行(冪等) / 並行。
値はすべて架空。
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import GameSet, Match, Player
from backend.main import app
from backend.routers.sets import _autofill_match_result_from_sets


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    c = TestClient(app, headers={"X-Role": "admin"})
    yield c
    app.dependency_overrides.clear()


def _make_match(db_session, *, result="unfinished", result_source="manual",
                final_score=None, n_sets=1):
    a = Player(name="自動A", dominant_hand="R")
    b = Player(name="自動B", dominant_hand="R")
    db_session.add_all([a, b])
    db_session.flush()
    m = Match(
        tournament="自動入力テスト",
        tournament_level="practice",
        round="R1",
        date=date(2026, 9, 20),
        format="singles",
        player_a_id=a.id,
        player_b_id=b.id,
        result=result,
        final_score=final_score,
        result_source=result_source,
    )
    db_session.add(m)
    db_session.flush()
    sets = []
    for i in range(1, n_sets + 1):
        gs = GameSet(match_id=m.id, set_num=i)
        db_session.add(gs)
        sets.append(gs)
    db_session.flush()
    db_session.commit()
    return m, sets


def _end(client, gs, winner, a, b, incomplete=False):
    return client.put(
        f"/api/sets/{gs.id}/end",
        json={"winner": winner, "score_a": a, "score_b": b, "incomplete": incomplete},
    )


def _reload(db_session, match_id):
    db_session.expire_all()
    return db_session.get(Match, match_id)


def test_two_nil_fills_result_and_score(client, db_session):
    m, sets = _make_match(db_session, n_sets=2)
    assert _end(client, sets[0], "player_a", 21, 15).status_code == 200
    assert _end(client, sets[1], "player_a", 21, 18).status_code == 200
    got = _reload(db_session, m.id)
    assert got.result == "win"
    assert got.final_score == "21-15, 21-18"
    assert got.result_source == "auto"


def test_two_one_includes_three_sets(client, db_session):
    m, sets = _make_match(db_session, n_sets=3)
    assert _end(client, sets[0], "player_a", 21, 15).status_code == 200
    assert _end(client, sets[1], "player_b", 18, 21).status_code == 200
    assert _end(client, sets[2], "player_a", 21, 19).status_code == 200
    got = _reload(db_session, m.id)
    assert got.result == "win"
    assert got.final_score == "21-15, 18-21, 21-19"
    assert got.result_source == "auto"


def test_player_b_wins_is_loss(client, db_session):
    m, sets = _make_match(db_session, n_sets=2)
    assert _end(client, sets[0], "player_b", 15, 21).status_code == 200
    assert _end(client, sets[1], "player_b", 18, 21).status_code == 200
    got = _reload(db_session, m.id)
    assert got.result == "loss"
    assert got.final_score == "15-21, 18-21"
    assert got.result_source == "auto"


def test_undecided_leaves_match_untouched(client, db_session):
    m, sets = _make_match(db_session, n_sets=3)
    # 1-0 のまま。まだ決着していないので自動入力しない。
    assert _end(client, sets[0], "player_a", 21, 15).status_code == 200
    got = _reload(db_session, m.id)
    assert got.result == "unfinished"
    assert got.final_score is None
    assert got.result_source == "manual"


def test_manual_result_is_never_overwritten(client, db_session):
    # 人が先に win / スコアを確定させている (manual)。セットが B の 2-0 でも上書きしない。
    m, sets = _make_match(
        db_session, result="win", result_source="manual",
        final_score="21-10, 21-12", n_sets=2,
    )
    assert _end(client, sets[0], "player_b", 15, 21).status_code == 200
    assert _end(client, sets[1], "player_b", 18, 21).status_code == 200
    got = _reload(db_session, m.id)
    assert got.result == "win"
    assert got.final_score == "21-10, 21-12"
    assert got.result_source == "manual"


def test_walkover_stays_manual(client, db_session):
    # 人が walkover (不戦勝) を確定させた match。walkover は result が非空の manual なので
    # 以降セットが決着しても自動入力は踏まず、walkover のまま残る。
    m, sets = _make_match(
        db_session, result="walkover", result_source="manual",
        final_score=None, n_sets=2,
    )
    assert _end(client, sets[0], "player_a", 21, 15).status_code == 200
    assert _end(client, sets[1], "player_a", 21, 18).status_code == 200
    got = _reload(db_session, m.id)
    assert got.result == "walkover"
    assert got.final_score is None
    assert got.result_source == "manual"


def test_early_finish_incomplete_stays_manual(client, db_session):
    # incomplete=True (棄権・中断) は自動入力経路を通らず manual のまま。
    m, sets = _make_match(db_session, n_sets=2)
    assert _end(client, sets[0], "player_a", 21, 15).status_code == 200
    # 2 セット目を途中で閉じる
    assert _end(client, sets[1], "player_a", 5, 3, incomplete=True).status_code == 200
    got = _reload(db_session, m.id)
    # 1 セットしか決着しておらず 2 勝に達していない → 未入力
    assert got.result == "unfinished"
    assert got.result_source == "manual"


def test_rerun_is_idempotent(client, db_session):
    # auto で入った後、最終セットを同じ値で再度 end しても同値。
    m, sets = _make_match(db_session, n_sets=2)
    assert _end(client, sets[0], "player_a", 21, 15).status_code == 200
    assert _end(client, sets[1], "player_a", 21, 18).status_code == 200
    first = _reload(db_session, m.id)
    assert first.result == "win" and first.result_source == "auto"
    # 同じセットを再度確定 (auto なので再計算・同値上書き)
    assert _end(client, sets[1], "player_a", 21, 18).status_code == 200
    again = _reload(db_session, m.id)
    assert again.result == "win"
    assert again.final_score == "21-15, 21-18"
    assert again.result_source == "auto"


def test_concurrent_autofill_is_safe_and_idempotent(client, db_session):
    """並行する複数の end_set が同じ match に対して自動入力を走らせても安全か。

    DB レベルの真の並行は SQLite テストでは再現しにくいため、セット保存後の
    `_autofill_match_result_from_sets` を同一 match に対して連続で複数回呼ぶ
    (= 逐次化された並行書き込み) ことで、auto 行が manual を踏まず同値で
    安定することを確かめる。どの呼び出しも同じ完了セットを見るので結果は不変。
    """
    m, sets = _make_match(db_session, n_sets=2)
    assert _end(client, sets[0], "player_a", 21, 15).status_code == 200
    assert _end(client, sets[1], "player_a", 21, 18).status_code == 200
    after_end = _reload(db_session, m.id)
    assert after_end.result == "win" and after_end.result_source == "auto"

    # 同一 match を指す 2 つのセッションが、それぞれ自動入力を実行するを模す。
    for _ in range(3):
        match_obj = db_session.get(Match, m.id)
        _autofill_match_result_from_sets(db_session, match_obj)
        db_session.commit()
    final = _reload(db_session, m.id)
    assert final.result == "win"
    assert final.final_score == "21-15, 21-18"
    assert final.result_source == "auto"


def test_concurrent_autofill_never_clobbers_manual(client, db_session):
    """manual で確定された match に対して並行で自動入力が走っても、一切踏まない。"""
    m, sets = _make_match(
        db_session, result="win", result_source="manual",
        final_score="21-10, 21-12", n_sets=2,
    )
    # B が 2-0 で決着しているセットを書くが、manual なので結果は変わらない。
    sets[0].score_a, sets[0].score_b, sets[0].winner = 15, 21, "player_b"
    sets[1].score_a, sets[1].score_b, sets[1].winner = 18, 21, "player_b"
    db_session.commit()
    for _ in range(3):
        match_obj = db_session.get(Match, m.id)
        _autofill_match_result_from_sets(db_session, match_obj)
        db_session.commit()
    final = _reload(db_session, m.id)
    assert final.result == "win"
    assert final.final_score == "21-10, 21-12"
    assert final.result_source == "manual"
