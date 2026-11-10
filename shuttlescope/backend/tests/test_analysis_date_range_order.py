"""分析の期間は開始日 <= 終了日 (監査 #797)。

防ぐ事象: 開始日 > 終了日を送ると backend が 400/422 にせず「正常な 0 件」を返し、
期間指定ミスが「データなし / サンプル不足」に見えた。
"""
from datetime import date

import pytest

from backend.tests.test_stats_n0_guards_b import (  # noqa: F401
    _headers,
    _match,
    _player,
    client,
)

# match_filter_params 経由 / _get_player_matches 直 / 独自クエリ の 3 経路
URLS = [
    "/api/analysis/exploitability?player_id={pid}",
    "/api/analysis/rally_length_vs_winrate?player_id={pid}",
    "/api/analysis/opponent_type_affinity?player_id={pid}",
]


def _seed(db):
    a = _player(db, "A")
    b = _player(db, "B")
    _match(db, a, b, date(2026, 2, 10), wins_a=1, n=2)
    db.commit()
    return a


@pytest.mark.parametrize("url", URLS)
def test_reversed_range_is_rejected_with_422(client, db_session, url):
    a = _seed(db_session)
    r = client.get(url.format(pid=a.id) + "&date_from=2026-03-01&date_to=2026-01-01", headers=_headers())
    assert r.status_code == 422, r.text


@pytest.mark.parametrize("url", URLS)
def test_same_day_and_ordered_ranges_still_work(client, db_session, url):
    a = _seed(db_session)
    for q in ("&date_from=2026-02-10&date_to=2026-02-10", "&date_from=2026-01-01&date_to=2026-03-01", "&date_from=2026-01-01"):
        r = client.get(url.format(pid=a.id) + q, headers=_headers())
        assert r.status_code == 200, (q, r.text)
