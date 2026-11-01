"""#522 回帰テスト: スコア補正の擬似ラリー (is_skipped) が research spine の
状態 / 系列 / 反事実解析の母集団へ混入しないことを固定する。

spine 系の共通入力層 _load_ctx_or_query は、ctx 経由・直接クエリの両経路で
Rally.is_skipped == False を強制する。epv_state_table は data.total_rallies に
母集団サイズを返すので、擬似ラリーを足しても増えないことを確認する。
"""
from __future__ import annotations

from datetime import date

from backend.db.models import GameSet, Rally
from backend.tests.test_stats_n0_guards_b import (  # noqa: F401
    _headers,
    _match,
    _player,
    client,
)


def _add_skipped(db, match, n):
    """スコア補正で機械生成される擬似ラリー (server=winner, is_skipped=True) を足す。"""
    gs = db.query(GameSet).filter(GameSet.match_id == match.id).first()
    for i in range(n):
        db.add(Rally(
            set_id=gs.id, rally_num=200 + i, server="player_a", winner="player_a",
            end_type="unknown", rally_length=0, score_a_after=0, score_b_after=0,
            annotation_mode="manual_record", is_skipped=True,
        ))
    db.commit()


def test_epv_state_table_ignores_score_correction_rallies(client, db_session):
    a = _player(db_session, "spine補正A")
    b = _player(db_session, "spine補正B")
    m = _match(db_session, a, b, date(2026, 9, 7), 2, 4)  # 実ラリー 4 本
    db_session.commit()
    _add_skipped(db_session, m, 6)  # 補正で機械生成された 6 本
    r = client.get(
        f"/api/analysis/epv_state_table?player_id={a.id}", headers=_headers()
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    # 機械生成の 6 本は母集団から除かれ、実ラリー 4 本だけが残る。
    assert data["total_rallies"] == 4


def test_epv_state_table_all_skipped_is_empty_population(client, db_session):
    a = _player(db_session, "spine補正C")
    b = _player(db_session, "spine補正D")
    m = _match(db_session, a, b, date(2026, 9, 8), 0, 0)  # 実ラリー 0 本
    db_session.commit()
    _add_skipped(db_session, m, 5)  # 補正点だけ
    r = client.get(
        f"/api/analysis/epv_state_table?player_id={a.id}", headers=_headers()
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    # 補正点だけの試合は実質 0 ラリー。機械生成点を水増ししない。
    assert data["total_rallies"] == 0
    assert data["global_win_rate"] is None
