"""包括レポートと期間エクスポートは、ダブルスの相方として出た試合も対象にする。

どちらも「選手の試合」を player_a / player_b だけで集めていたので、相方として出た試合は
黙って抜けていた。試合単位のデータなので、役割の解決は要らず、集め方だけの問題。
"""
from datetime import date
from types import SimpleNamespace

import pytest

from backend.db.models import Match, Player
from backend.utils.auth import AuthCtx


def _admin():
    return AuthCtx(role="admin", player_id=None, user_id=1, team_name=None, team_id=None)


@pytest.fixture()
def world(db_session):
    ply = {}
    for nm in ["T", "P", "O1", "O2", "S1", "S2"]:
        p = Player(name=nm, dominant_hand="R")
        db_session.add(p)
        db_session.flush()
        ply[nm] = p

    def match(a, b, pa=None, pb=None, fmt="mixed_doubles"):
        m = Match(tournament="t", tournament_level="IC", round="1", date=date(2025, 1, 1), format=fmt,
                  player_a_id=ply[a].id, player_b_id=ply[b].id,
                  partner_a_id=ply[pa].id if pa else None, partner_b_id=ply[pb].id if pb else None,
                  result="win", annotation_status="complete", annotation_progress=1.0)
        db_session.add(m)
        db_session.flush()
        return m

    doubles = match("T", "O1", pa="P", pb="O2")
    singles = match("S1", "S2", fmt="singles")
    db_session.commit()
    return db_session, ply, doubles, singles


def _per_match_ids(db, pid):
    from backend.services.comprehensive_report import gather_player_report
    rep = gather_player_report(db, pid, _admin(), include_per_match=True)
    return {m["id"] for m in rep["matches"]}


def test_comprehensive_report_lists_the_partner_match(world):
    db, ply, doubles, singles = world
    assert _per_match_ids(db, ply["P"].id) == {doubles.id}      # A 側の相方 (旧: 空)
    assert _per_match_ids(db, ply["O2"].id) == {doubles.id}     # B 側の相方
    assert _per_match_ids(db, ply["T"].id) == {doubles.id}
    assert _per_match_ids(db, ply["S1"].id) == {singles.id}


def _period_count(db, monkeypatch, pid):
    from backend.routers import export_period as ep
    monkeypatch.setattr(ep, "get_auth", lambda request: _admin())
    monkeypatch.setattr(ep, "check_export_match_scope", lambda *a, **k: None)
    resp = ep.export_period(
        request=SimpleNamespace(headers={}, client=None, state=SimpleNamespace()),
        player_id=pid, date_from=None, date_to=None, format="json", sections=None, db=db)
    return int(resp.headers["X-Period-Match-Count"])


def test_period_export_counts_the_partner_match(world, monkeypatch):
    db, ply, doubles, singles = world
    assert _period_count(db, monkeypatch, ply["P"].id) == 1     # 旧: 0
    assert _period_count(db, monkeypatch, ply["O2"].id) == 1
    assert _period_count(db, monkeypatch, ply["T"].id) == 1
    assert _period_count(db, monkeypatch, ply["S1"].id) == 1
