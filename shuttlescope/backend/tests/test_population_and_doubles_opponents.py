"""解析母集団と対戦相手の数え方 (監査 #324 / #181)。値はすべて架空。

- #324: 絞り込み付きの bundle 文脈 (rs_matches) にも、0 ラリーの未実施試合を入れない。
- #181: ダブルスの対戦相手統計は、相手ペアの 2 人とも対戦相手に数える。
"""
from datetime import date

from backend.analysis.bundle_context import load_context
from backend.tests.test_stats_n0_guards_b import (  # noqa: F401
    _headers,
    _match,
    _player,
    client,
)


def test_filtered_bundle_context_excludes_zero_rally_matches(db_session):
    a = _player(db_session, "A")
    b = _player(db_session, "B")
    m_ok = _match(db_session, a, b, date(2026, 2, 1), 5, 10, result="win")
    m_zero = _match(db_session, a, b, date(2026, 2, 2), 0, 0, result="win")
    db_session.commit()

    ctx = load_context(db_session, a.id, {"date_from": date(2026, 1, 1)})
    rs_ids = [m.id for m in ctx.rs_matches]
    assert m_ok.id in rs_ids
    assert m_zero.id not in rs_ids
    # 絞り込み側 (matches) と同じ母集団になる
    assert sorted(rs_ids) == sorted(m.id for m in ctx.matches)


def test_opponent_stats_counts_both_members_of_the_opposing_pair(client, db_session):
    a = _player(db_session, "A")
    c = _player(db_session, "C")
    b = _player(db_session, "B")
    d = _player(db_session, "D")
    _match(
        db_session, a, b, date(2026, 3, 1), 6, 10, fmt="doubles", result="win",
        partner_a=c, partner_b=d,
    )
    db_session.commit()
    body = client.get(f"/api/analysis/opponent_stats?player_id={a.id}", headers=_headers()).json()
    rows = {r["opponent_id"]: r for r in body["data"]["opponents"]}
    assert set(rows) == {b.id, d.id}
    for oid in (b.id, d.id):
        assert rows[oid]["match_count"] == 1
        assert rows[oid]["win_rate"] == 1.0
        assert rows[oid]["sample_size"] == 10
    # 全体の標本数は一意なラリー数 (相手ペア 2 人に二重に数えない)
    assert body["meta"]["sample_size"] == 10
