"""advice と live_coach も、ダブルスの視点が変わっても同じ試合なら同じ結果になる。

test_analysis_doubles_perspective_symmetry と同じ 4 通りの世界 (対象選手 T が player_a /
鏡写しの partner_b / 鏡写しの player_b / 入れ替えの partner_a) を作り、
- advice の各集計 (直近の窓、ホーム、試合直後の観測、予測タブ、成長)
- live_coach の異常検知と提案
を、それぞれの視点で呼んで比べる。live_coach は router_helpers の共通関数から
視点 (TeamSide) を受け取るが、自分の打球を選ぶ比較が個人の枠でなかったため、
相方の視点では別の選手 (player_a) の打球を自分のものとして数えていた。
"""
import json
import re
from dataclasses import asdict, is_dataclass

import pytest

from backend.db.models import Match
from backend.services import advice
from backend.tests.test_analysis_doubles_perspective_symmetry import (
    CONFIGS, _build, _norm, _plan,
)
from backend.utils.auth import AuthCtx


def _ctx():
    return AuthCtx(role="admin", player_id=None, user_id=1, team_name=None, team_id=None)


def _strip_ids(x):
    """文言に埋まった「#3」のような選手 ID は世界ごとに違うので、数字を落とす。"""
    if isinstance(x, str):
        return re.sub(r"#\d+", "#", x)
    if isinstance(x, dict):
        return {k: _strip_ids(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_strip_ids(v) for v in x]
    return x


def _plain(x):
    def default(o):
        if is_dataclass(o):
            return asdict(o)
        return str(o)
    return _strip_ids(_norm(json.loads(json.dumps(x, default=default))))


@pytest.fixture()
def world(db_session):
    plan = _plan(seed=5, n_sets=3, n_rallies=30)
    tx = _build(db_session, plan)
    ys = {name: _build(db_session, plan, sm, flip) for name, (sm, flip) in CONFIGS.items()}
    db_session.commit()
    return db_session, tx, ys


def _match_of(db, pid):
    return db.query(Match).filter(
        (Match.player_a_id == pid) | (Match.player_b_id == pid)
        | (Match.partner_a_id == pid) | (Match.partner_b_id == pid)).one()


def _opponent_named(db, pid, name):
    from backend.db.models import Player
    from backend.analysis.role_view import opposing_ids
    m = _match_of(db, pid)
    for oid in opposing_ids(m, pid):
        if db.get(Player, oid).name == name:
            return oid
    raise AssertionError("no such opponent")


def _outputs(db, pid):
    m = _match_of(db, pid)
    ctx = _ctx()
    out = {
        "window": advice._gather_window(db, pid, 100000),
        "overview": advice.advice_dashboard_overview(db, pid, ctx),
        "post_match": advice.advice_post_match_save(db, pid, m.id, ctx),
        "prediction_tab": advice.advice_prediction_tab(db, pid, _opponent_named(db, pid, "O1"), ctx),
        "growth": advice.advice_growth_timeline(db, pid, ctx),
        "home": advice.advice_player_home(db, pid, ctx),
    }
    return {k: _plain(v) for k, v in out.items()}


def _has_content(x):
    if isinstance(x, dict):
        return any(_has_content(v) for v in x.values())
    if isinstance(x, (list, tuple)):
        return any(_has_content(v) for v in x)
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return x != 0
    return bool(x)


def test_advice_does_not_depend_on_the_slot(world):
    db, tx, ys = world
    base = _outputs(db, tx.id)
    filled = [k for k, v in base.items() if _has_content(v)]
    assert len(filled) >= 3, f"baseline too empty to compare: {filled}"
    for name, ty in ys.items():
        got = _outputs(db, ty.id)
        for key in base:
            assert got[key] == base[key], f"[{name}] {key}: X={str(base[key])[:250]} Y={str(got[key])[:250]}"


def test_advice_head_to_head_with_either_opponent(world):
    """予測タブの対戦履歴は、相手チームのどちらの選手を指定しても見つかる。"""
    db, tx, ys = world
    for ty in [tx] + list(ys.values()):
        for nm in ("O1", "O2"):
            r = _plain(advice.advice_prediction_tab(db, ty.id, _opponent_named(db, ty.id, nm), _ctx()))
            assert "対戦履歴がありません" not in json.dumps(r, ensure_ascii=False), (ty.id, nm)


# ── live_coach ────────────────────────────────────────────────

def _live(db, pid):
    from backend.routers import live_coach as lc
    m = _match_of(db, pid)
    ctx = _ctx()
    return {
        "anomaly": _plain(lc.get_live_anomaly(player_id=pid, match_id=m.id, window=20, db=db, ctx=ctx)),
        "suggestions": _plain(lc.get_live_suggestions(player_id=pid, match_id=m.id, db=db, ctx=ctx)),
    }


def test_live_coach_does_not_depend_on_the_slot(world):
    db, tx, ys = world
    base = _live(db, tx.id)
    assert base["anomaly"].get("reason") != "player_not_in_match"
    for name, ty in ys.items():
        got = _live(db, ty.id)
        for key in base:
            assert got[key] == base[key], f"[{name}] {key}: X={str(base[key])[:250]} Y={str(got[key])[:250]}"
