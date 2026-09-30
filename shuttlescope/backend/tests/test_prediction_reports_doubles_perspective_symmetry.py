"""prediction と reports も、ダブルスの視点が変わっても同じ試合なら同じ結果になる。

test_analysis_doubles_perspective_symmetry と同じ 4 通りの世界 (対象選手 T が player_a /
鏡写しの partner_b / 鏡写しの player_b / 入れ替えの partner_a) を作り、
- prediction_engine の、選手 ID を取る計算関数
- get_matches_for_player (選手として・相方として、対戦相手で絞る)
- reports のスカウティング / 成長 / 予測レポート (reportlab を使わない JSON の形)
を、それぞれの視点で呼んで比べる。以前は相方の試合が集まらず、集まっても
チーム側を `m.player_a_id == pid` で決めていたので、相方は B 側と誤判定された。
"""
import json
import sys
from types import SimpleNamespace

import pytest

from backend.analysis import prediction_engine as PE
from backend.tests.test_analysis_doubles_perspective_symmetry import (
    CONFIGS, _build, _norm, _plan,
)


@pytest.fixture()
def world(db_session):
    plan = _plan(seed=11, n_sets=3, n_rallies=25)
    tx = _build(db_session, plan)
    ys = {name: _build(db_session, plan, sm, flip) for name, (sm, flip) in CONFIGS.items()}
    db_session.commit()
    return db_session, tx, ys


def _engine_outputs(db, pid):
    ms = PE.get_matches_for_player(db, pid)
    wp = PE.compute_win_probability(ms, pid)
    out = {
        "n_matches": len(ms),
        "win_probability": wp,
        "set_distribution": PE.compute_set_distribution(ms, pid, wp[0] if isinstance(wp, tuple) else wp),
        "score_bands": PE.compute_score_bands(ms, pid),
        "calibrated_scorelines": PE.compute_calibrated_scorelines(ms, pid),
        "recent_form": PE.compute_recent_form(ms, pid),
        "growth_trend": PE.compute_growth_trend(ms, pid),
        "score_volatility": PE.compute_score_volatility(ms, pid),
        "nearest": PE.find_nearest_matches(ms, pid, "IC"),
        "fatigue": PE.compute_fatigue_risk(db, pid),
    }
    return _norm(json.loads(json.dumps(out, default=str)))


def test_engine_results_do_not_depend_on_the_slot(world):
    db, tx, ys = world
    base = _engine_outputs(db, tx.id)
    assert base["n_matches"] == 1
    for name, ty in ys.items():
        got = _engine_outputs(db, ty.id)
        for key in base:
            assert got[key] == base[key], f"[{name}] {key}: X={str(base[key])[:200]} Y={str(got[key])[:200]}"


def test_head_to_head_finds_the_match_from_every_slot(world):
    """対戦相手で絞る。相手も相方として出ている場合を含め、どの枠からでも同じ試合が見つかる。"""
    db, tx, ys = world
    from backend.db.models import Match

    def opp_of(pid):
        m = db.query(Match).filter(
            (Match.player_a_id == pid) | (Match.player_b_id == pid)
            | (Match.partner_a_id == pid) | (Match.partner_b_id == pid)).one()
        side_a = pid in (m.player_a_id, m.partner_a_id)
        return (m.player_b_id, m.partner_b_id) if side_a else (m.player_a_id, m.partner_a_id)

    for pid in [tx.id] + [t.id for t in ys.values()]:
        for opp in opp_of(pid):                      # 相手の 2 人のどちらで絞っても
            assert len(PE.get_matches_for_player(db, pid, opponent_id=opp)) == 1
        # 自分の相方は相手ではない
    m = db.query(Match).filter(Match.player_a_id == tx.id).one()
    assert PE.get_matches_for_player(db, tx.id, opponent_id=m.partner_a_id) == []


# ── reports (reportlab を使わない JSON の形) ───────────────────────────

REPORTS = ["get_scouting_report", "get_player_growth_report", "get_prediction_report"]


@pytest.fixture()
def reports_module(monkeypatch):
    from backend.routers import reports
    from backend.utils.auth import AuthCtx

    admin = AuthCtx(role="admin", player_id=None, user_id=1, team_name=None, team_id=None)
    monkeypatch.setattr(reports, "get_auth", lambda request: admin)
    monkeypatch.setattr(reports, "check_export_player_scope", lambda *a, **k: None)
    # reportlab があると PDF が返り比較できない。import を失敗させて JSON のフォールバックに入れる
    for name in ("reportlab", "reportlab.lib", "reportlab.lib.pagesizes", "reportlab.lib.units",
                 "reportlab.lib.styles", "reportlab.lib.colors", "reportlab.platypus",
                 "reportlab.pdfbase", "reportlab.pdfbase.pdfmetrics", "reportlab.pdfbase.ttfonts"):
        monkeypatch.setitem(sys.modules, name, None)
    return reports


def _report(reports, fn_name, db, pid):
    fn = getattr(reports, fn_name)
    resp = fn(player_id=pid, request=SimpleNamespace(headers={}, client=None, state=SimpleNamespace()),
              date_from=None, date_to=None, db=db)
    body = getattr(resp, "body", None)
    if body is not None:
        assert "json" in (resp.media_type or "json"), f"{fn_name} returned {resp.media_type}, not JSON"
        resp = json.loads(body)
    return _norm(resp)


@pytest.mark.parametrize("fn_name", REPORTS)
def test_report_does_not_depend_on_the_slot(world, reports_module, fn_name):
    db, tx, ys = world
    x = _report(reports_module, fn_name, db, tx.id)
    assert x.get("success", True) is not False, x
    for name, ty in ys.items():
        y = _report(reports_module, fn_name, db, ty.id)
        assert x == y, f"{fn_name} [{name}]: X={str(x)[:300]}  Y={str(y)[:300]}"


def test_reports_are_not_empty_for_the_baseline(world, reports_module):
    db, tx, _ = world
    d = _report(reports_module, "get_scouting_report", db, tx.id)["data"]
    assert d["total_matches"] == 1 and d["total_rallies"] > 0 and d["top_shots"]
