"""ダブルスの視点が変わっても、同じ試合の分析結果は変わらない (左右対称テスト)。

同じダブルスの試合内容を、対象選手が違う「個人の枠」にいる形で作り直し、
全分析エンドポイントを「player_id だけ」で呼んで結果を比べる。

  X                : 対象選手 T が player_a (基準)
  Y partner_b      : 鏡写し。T は B 側の相方 (partner_b)
  Y player_b       : 鏡写し。T は B 側の選手 (player_b)
  Y partner_a      : 同じ側で入れ替え。T は A 側の相方 (partner_a)

選手・相方・相手の入れ替え、勝敗とサーブ側の反転、打球の枠の対応以外は同一なので、
分析が視点に依存しなければ結果は一致する。以前は相方の試合が分析に入らず、
入っても相方の打球を取れず、相方を対戦相手や自分自身に数えていた。
"""
import inspect
import random
from datetime import date

import pytest

from backend.db.models import GameSet, Match, Player, Rally, Stroke
from backend.routers import (
    analysis_advanced, analysis_bundle, analysis_research, analysis_spine, analysis_stable,
)

SHOTS = ["clear", "smash", "drop", "net", "drive", "lob", "push", "lift", "hairpin", "defensive"]
ZONES = ["BL", "BC", "BR", "ML", "MC", "MR", "NL", "NC", "NR"]
END_TYPES = ["forced_error", "unforced_error", "winner", "net"]

FLIP_SIDE = {"player_a": "player_b", "player_b": "player_a"}

# X の個人の枠 → Y の個人の枠、と、A/B 側を入れ替えるか
CONFIGS = {
    "partner_b": ({"player_a": "partner_b", "partner_a": "player_b", "player_b": "player_a", "partner_b": "partner_a"}, True),
    "player_b": ({"player_a": "player_b", "partner_a": "partner_b", "player_b": "player_a", "partner_b": "partner_a"}, True),
    "partner_a": ({"player_a": "partner_a", "partner_a": "player_a", "player_b": "player_b", "partner_b": "partner_b"}, False),
}


def _plan(seed=7, n_sets=2, n_rallies=24):
    """X 側の試合内容 (中立な形)。Y は同じ内容を写して作る。"""
    rnd = random.Random(seed)  # DevSkim: ignore DS148264 -- deterministic fixture data for a test, not a security use
    sets = []
    for _ in range(n_sets):
        rallies = []
        for _ in range(n_rallies):
            server = rnd.choice(["player_a", "player_b"])
            winner = rnd.choice(["player_a", "player_b"])
            length = rnd.randint(2, 9)
            side = server
            strokes = []
            for _ in range(length):
                slot = side if rnd.random() < 0.5 else ("partner_a" if side == "player_a" else "partner_b")
                strokes.append(dict(slot=slot, shot=rnd.choice(SHOTS), land=rnd.choice(ZONES), hit=rnd.choice(ZONES)))
                side = FLIP_SIDE[side]
            rallies.append(dict(server=server, winner=winner, end=rnd.choice(END_TYPES), strokes=strokes))
        sets.append(rallies)
    return sets


def _build(db, plan, slotmap=None, flip=False):
    """plan を、slotmap で枠を読み替え、flip なら A/B 側も入れ替えて DB に作る。対象選手 T を返す。"""
    slotmap = slotmap or {s: s for s in ("player_a", "partner_a", "player_b", "partner_b")}
    names = {"player_a": "T", "partner_a": "P", "player_b": "O1", "partner_b": "O2"}
    ply = {}
    for slot, nm in names.items():
        p = Player(name=nm, dominant_hand="R", is_target=(slot == "player_a"))
        db.add(p)
        db.flush()
        ply[slot] = p
    by_slot = {slotmap[s]: ply[s] for s in ply}
    side_of = (lambda s: FLIP_SIDE[s]) if flip else (lambda s: s)
    m = Match(
        tournament="t", tournament_level="IC", round="1", date=date(2025, 1, 1), format="mixed_doubles",
        player_a_id=by_slot["player_a"].id, player_b_id=by_slot["player_b"].id,
        partner_a_id=by_slot["partner_a"].id, partner_b_id=by_slot["partner_b"].id,
        result="loss" if flip else "win",
        annotation_status="complete", annotation_progress=1.0,
    )
    db.add(m)
    db.flush()
    for si, rallies in enumerate(plan, start=1):
        sa = sb = 0
        g = GameSet(match_id=m.id, set_num=si, winner=side_of("player_a"), score_a=0, score_b=0)
        db.add(g)
        db.flush()
        for ri, rd in enumerate(rallies, start=1):
            w = side_of(rd["winner"])
            if w == "player_a":
                sa += 1
            else:
                sb += 1
            r = Rally(set_id=g.id, rally_num=ri, server=side_of(rd["server"]), winner=w, end_type=rd["end"],
                      rally_length=len(rd["strokes"]), score_a_after=sa, score_b_after=sb,
                      annotation_mode="manual_record")
            db.add(r)
            db.flush()
            for k, st in enumerate(rd["strokes"], start=1):
                db.add(Stroke(rally_id=r.id, stroke_num=k, player=slotmap[st["slot"]], shot_type=st["shot"],
                              land_zone=st["land"], hit_zone=st["hit"]))
        g.score_a, g.score_b = sa, sb
        db.flush()
    return ply["player_a"]   # 対象選手 T


def _norm(x):
    if isinstance(x, dict):
        return {k: _norm(v) for k, v in sorted(x.items())
                if k not in ("id", "ids") and not k.endswith("_id") and not k.endswith("_ids")}
    if isinstance(x, (list, tuple)):
        return [_norm(v) for v in x]
    if isinstance(x, float):
        return round(x, 6)
    return x


def _endpoints():
    out = []
    for mod in (analysis_stable, analysis_advanced, analysis_research, analysis_spine, analysis_bundle):
        for r in mod.router.routes:
            if "GET" not in getattr(r, "methods", set()):
                continue
            sig = inspect.signature(r.endpoint)
            if "player_id" not in sig.parameters:
                continue
            kwargs, ok = {}, True
            for p in sig.parameters.values():
                if p.name in ("player_id", "db"):
                    continue
                if p.default is inspect._empty:
                    ok = False
                    break
                # FastAPI の Query(None) 等は素の呼び出しでは Query オブジェクトのまま入るので既定値を取り出す
                val = getattr(p.default, "default", p.default)
                if val is Ellipsis or type(val).__name__ == "PydanticUndefinedType":
                    ok = False   # Query(...) = 必須。既定値がないので呼べない
                    break
                kwargs[p.name] = val
            if ok:
                out.append((f"{mod.__name__.rsplit('.', 1)[-1]}:{r.path}", r.endpoint, kwargs))
    return out


ENDPOINTS = _endpoints()


def _call(fn, kwargs, db, pid):
    random.seed(20260930)   # ブートストラップ CI (shot_influence_v2 等) は乱数を使う。同じデータなら同じ値にする
    try:
        res = fn(player_id=pid, db=db, **kwargs)
    except Exception as e:  # noqa: BLE001 — 両視点で同じ例外なら対称とみなす
        return ("EXC", type(e).__name__)
    if isinstance(res, dict) and "data" in res:
        return _norm({"success": res.get("success"), "data": res["data"]})
    return _norm(res) if isinstance(res, (dict, list)) else res


def _has_content(x):
    """空の結果 (0 / 空のリスト・辞書 / None だけ) ではないか。"""
    if isinstance(x, dict):
        return any(_has_content(v) for v in x.values())
    if isinstance(x, (list, tuple)):
        return any(_has_content(v) for v in x)
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return x != 0
    return bool(x)


@pytest.fixture()
def world(db_session):
    plan = _plan()
    tx = _build(db_session, plan)
    ys = {name: _build(db_session, plan, sm, flip) for name, (sm, flip) in CONFIGS.items()}
    return db_session, tx, ys


def test_the_fixture_puts_the_target_in_the_intended_slots(world):
    db, tx, ys = world
    slot_col = {"partner_b": Match.partner_b_id, "player_b": Match.player_b_id, "partner_a": Match.partner_a_id}
    for name, ty in ys.items():
        assert db.query(Match).filter(slot_col[name] == ty.id).count() == 1, name


def test_there_are_endpoints_to_compare():
    assert len(ENDPOINTS) >= 40, [e[0] for e in ENDPOINTS]


def test_the_comparison_is_not_vacuous(world):
    """両方とも空だから一致した、を防ぐ。基準 X で中身のある結果が十分あること。"""
    db, tx, _ = world
    filled = [name for name, fn, kw in ENDPOINTS if _has_content(_call(fn, kw, db, tx.id))]
    assert len(filled) >= 30, f"only {len(filled)} endpoints returned content for the baseline"


@pytest.mark.parametrize("config", list(CONFIGS))
@pytest.mark.parametrize("name,fn,kwargs", ENDPOINTS, ids=[e[0] for e in ENDPOINTS])
def test_endpoint_is_symmetric(world, config, name, fn, kwargs):
    db, tx, ys = world
    x = _call(fn, kwargs, db, tx.id)
    y = _call(fn, kwargs, db, ys[config].id)
    assert x == y, f"{name} [{config}]: X(player_a)={str(x)[:300]}  Y={str(y)[:300]}"
