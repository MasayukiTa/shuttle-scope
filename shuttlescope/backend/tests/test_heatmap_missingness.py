"""項目161: 打点ヒートマップと着地点ヒートマップの標本数が食い違うとき、
その欠損数・欠損率を `data.missingness` で明示することを検証する。

旧実装は hit_zone 集計と land_zone 集計を別々に数えるだけで、
「どの球が打点欠損なのか」「欠損率が何 %か」を UI に渡していなかった。
ここでは実際にルータを呼び、欠損が数値として表に出ることを確かめる。
"""
from __future__ import annotations

import datetime

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from backend.db.models import Base, GameSet, Match, Player, Rally, Stroke
from backend.routers.analysis_stable import get_heatmap_composite


def _make(model, **kw):
    """NOT NULL かつ既定値なしの列を機械的に埋めてインスタンスを作る。"""
    for col in model.__table__.columns:
        if col.nullable or col.primary_key or col.name in kw:
            continue
        if col.default is not None or col.server_default is not None:
            continue
        try:
            py = col.type.python_type
        except NotImplementedError:
            py = str
        kw[col.name] = (
            datetime.date(2026, 9, 22) if py is datetime.date
            else datetime.datetime(2026, 9, 22) if py is datetime.datetime
            else 1 if py is int
            else 1.0 if py is float
            else False if py is bool
            else "t"
        )
    return model(**kw)


def _seed_and_call(strokes):
    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        a = _make(Player, name="A")
        b = _make(Player, name="B")
        db.add_all([a, b])
        db.flush()
        m = _make(Match, player_a_id=a.id, player_b_id=b.id, result="win")
        db.add(m)
        db.flush()
        gs = _make(GameSet, match_id=m.id, set_num=1)
        db.add(gs)
        db.flush()
        rally = _make(Rally, set_id=gs.id, rally_num=1)
        db.add(rally)
        db.flush()
        for i, (hz, lz) in enumerate(strokes):
            db.add(_make(Stroke, rally_id=rally.id, stroke_num=i + 1,
                         player="player_a", hit_zone=hz, land_zone=lz))
        db.commit()
        res = get_heatmap_composite(
            player_id=a.id, result=None, tournament_level=None,
            date_from=None, date_to=None, match_id=None, match_ids=None, db=db,
        )
    finally:
        db.close()
    return res


def test_missingness_counts_hit_points_absent_from_landings():
    """着地点はあるが打点が未入力の球を missing_hit で数える。"""
    # 3 球は hit+land 両方、 2 球は land のみ (hit_zone 欠損)。
    res = _seed_and_call(
        [("MC", "BL"), ("MC", "BL"), ("MC", "BL"), (None, "BL"), (None, "NR")]
    )
    miss = res["data"]["missingness"]
    assert miss["hit_n"] == 3
    assert miss["land_n"] == 5
    assert miss["missing_hit"] == 2
    assert miss["missing_hit_rate"] == round(2 / 5, 4)
    # 逆方向 (land 欠損) はない。
    assert miss["missing_land"] == 0
    assert miss["missing_land_rate"] == 0.0


def test_missingness_is_zero_when_hit_and_land_match():
    """すべての球が hit も land も持つなら欠損は 0。"""
    res = _seed_and_call([("MC", "BL"), ("ML", "BC")])
    miss = res["data"]["missingness"]
    assert miss["hit_n"] == 2 and miss["land_n"] == 2
    assert miss["missing_hit"] == 0 and miss["missing_land"] == 0
    assert miss["missing_hit_rate"] == 0.0 and miss["missing_land_rate"] == 0.0


def test_missingness_rate_is_none_when_no_landings():
    """land が 0 件なら欠損率は 0.0 ではなく None (分母 0 は未定義)。"""
    res = _seed_and_call([("MC", None), ("ML", None)])
    miss = res["data"]["missingness"]
    assert miss["hit_n"] == 2 and miss["land_n"] == 0
    assert miss["missing_hit"] == 0
    assert miss["missing_hit_rate"] is None
    # hit はあるので land 欠損は 2、率は hit を分母に持てる。
    assert miss["missing_land"] == 2
    assert miss["missing_land_rate"] == 1.0
