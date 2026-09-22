"""コートヒートマップ合成ビュー — 畳み込みが**入力 UI の幾何と一致する**ことを見る。

## このテストが以前どうなっていたか

旧 `test_heatmap_composite.py` は `ZONE_ROTATION_MAP` を **テスト側に書き写して**、
その写しに対して「BL の点対称は NR」と assert していた。実装を一度も import して
おらず、対合性のような写し自身の性質しか見ていない。
座標系が間違っていても**絶対に落ちない**テストだった。

## いま何を見るか

人手入力の正本は `src/components/court/CourtDiagram.tsx` の矩形定義。
テストはその TSX を読んで実際の座標を取り出し、

- 列 (L/C/R) が両半面で同じ x か（= 画面基準・鏡映していない）
- 行 (B/M/N) がネット線 y=200 からの距離で対応しているか（= ネット基準）

を確かめたうえで、`fold_land_zone_onto_own_court` が
**ネット線での鏡映と一致する**ことを幾何から検証する。
表を書き写すのではなく、UI の座標から導く。
"""
from __future__ import annotations

import pathlib
import re

import pytest

from backend.utils.zone9_fold import (
    ZONES_9,
    fold_land_zone_onto_own_court,
    split_zone9,
)

#: `CourtDiagram` のネット線 (SVG viewBox "0 0 300 400" の中央)
NET_Y = 200.0

_TSX = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src" / "components" / "court" / "CourtDiagram.tsx"
)

_RECT_RE = re.compile(
    r"\{\s*zone:\s*'(?P<zone>[A-Z_]+)'\s*,\s*"
    r"x:\s*(?P<x>-?\d+)\s*,\s*y:\s*(?P<y>-?\d+)\s*,\s*"
    r"w:\s*(?P<w>-?\d+)\s*,\s*h:\s*(?P<h>-?\d+)"
)


def _parse_zone_table(name: str) -> dict[str, tuple[float, float, float, float]]:
    """TSX の `const <name>: ZoneRect[] = [...]` を読み取る。"""
    src = _TSX.read_text(encoding="utf-8")
    header = f"const {name}: ZoneRect[] = ["
    # `ZoneRect[]` の `]` を掴まないよう、配列が開いた **後ろ** から閉じ括弧を探す。
    start = src.index(header) + len(header)
    end = src.index("]", start)
    body = src[start:end]
    table = {
        m.group("zone"): (
            float(m.group("x")), float(m.group("y")),
            float(m.group("w")), float(m.group("h")),
        )
        for m in _RECT_RE.finditer(body)
    }
    assert len(table) == 9, f"{name} から 9 ゾーン読めなかった: {sorted(table)}"
    return table


@pytest.fixture(scope="module")
def opponent_rects():
    return _parse_zone_table("OPPONENT_ZONES")


@pytest.fixture(scope="module")
def own_rects():
    return _parse_zone_table("OWN_ZONES")


def _x_center(rect) -> float:
    x, _y, w, _h = rect
    return x + w / 2


def _distance_from_net(rect, half: str) -> float:
    """矩形の中心がネット線からどれだけ離れているか。"""
    _x, y, _w, h = rect
    cy = y + h / 2
    return (NET_Y - cy) if half == "opponent" else (cy - NET_Y)


# ─── 入力 UI が本当に「行=ネット基準 / 列=画面基準」なのか ────────────────────

def test_columns_are_screen_based_not_mirrored(opponent_rects, own_rects):
    """同じ列ラベルは両半面で同じ x にある（= 画面左が両方とも L）。

    ここが崩れていたら「画面基準」という前提そのものが違うので、
    畳み込みの結論も作り直しになる。
    """
    for zone in ZONES_9:
        assert _x_center(opponent_rects[zone]) == _x_center(own_rects[zone]), (
            f"{zone}: 相手半面 x={_x_center(opponent_rects[zone])} / "
            f"自半面 x={_x_center(own_rects[zone])} — 列が鏡映されている"
        )


def test_rows_are_net_relative(opponent_rects, own_rects):
    """同じ行ラベルは両半面でネットから同じ距離にある。"""
    for zone in ZONES_9:
        d_opp = _distance_from_net(opponent_rects[zone], "opponent")
        d_own = _distance_from_net(own_rects[zone], "own")
        assert abs(d_opp - d_own) < 1.0, (
            f"{zone}: ネットからの距離が 相手={d_opp} / 自={d_own}"
        )


def test_net_row_is_nearest_the_net_and_back_row_is_farthest(opponent_rects):
    """N がネット際、B がベースライン側であること（行ラベルの意味）。"""
    for col in ("L", "C", "R"):
        d_n = _distance_from_net(opponent_rects[f"N{col}"], "opponent")
        d_m = _distance_from_net(opponent_rects[f"M{col}"], "opponent")
        d_b = _distance_from_net(opponent_rects[f"B{col}"], "opponent")
        assert d_n < d_m < d_b, f"列 {col}: N={d_n} M={d_m} B={d_b}"


# ─── 畳み込みが幾何と一致するか ───────────────────────────────────────────────

def _mirror_across_net(rect) -> tuple[float, float]:
    """矩形の中心をネット線 y=200 で鏡映した座標。"""
    x, y, w, h = rect
    cx, cy = x + w / 2, y + h / 2
    return cx, 2 * NET_Y - cy


def _rect_contains(rect, pt) -> bool:
    x, y, w, h = rect
    px, py = pt
    return x <= px <= x + w and y <= py <= y + h


def test_fold_matches_the_mirror_image_of_the_ui_rectangles(opponent_rects, own_rects):
    """相手半面のゾーンをネット線で折り返すと、畳み込み先の自半面ゾーンに落ちる。

    これが A-1b の本体。旧実装の点対称 (`BL→NR` 等) はここで落ちる。
    """
    for zone in ZONES_9:
        mirrored = _mirror_across_net(opponent_rects[zone])
        dst = fold_land_zone_onto_own_court(zone)
        assert _rect_contains(own_rects[dst], mirrored), (
            f"{zone} をネットで折り返すと {mirrored} だが、"
            f"畳み込み先とされた {dst} の矩形 {own_rects[dst]} に入らない"
        )


def test_the_old_point_symmetry_table_does_not_match_the_ui(opponent_rects, own_rects):
    """旧 `ZONE_ROTATION_MAP` が UI の幾何と一致しないことを明示する。

    「直感的には変換が要るはず」で点対称を書き戻さないための杭。
    旧表は列も反転させるので、**相手のベースライン際がネット際に描かれていた**。
    """
    old_point_symmetry = {
        "BL": "NR", "BC": "NC", "BR": "NL",
        "ML": "MR", "MC": "MC", "MR": "ML",
        "NL": "BR", "NC": "BC", "NR": "BL",
    }
    mismatches = [
        zone for zone in ZONES_9
        if not _rect_contains(
            own_rects[old_point_symmetry[zone]], _mirror_across_net(opponent_rects[zone])
        )
    ]
    # 中央 (MC) だけは点対称でも一致してしまうので、それ以外が全部ずれる。
    assert set(mismatches) == set(ZONES_9) - {"MC"}, mismatches


def test_fold_rejects_vocabulary_outside_zone9():
    for bad in ("A_front_left", "OB_LL", "NET_L", "", "X", None, 5):
        with pytest.raises((ValueError, TypeError)):
            fold_land_zone_onto_own_court(bad)  # type: ignore[arg-type]


def test_split_zone9_round_trips():
    for zone in ZONES_9:
        row, col = split_zone9(zone)
        assert row + col == zone


# ─── ルータの出力が畳み込みを通っているか ─────────────────────────────────────

def _make(model, **kw):
    """NOT NULL かつ既定値なしの列を機械的に埋めてインスタンスを作る。

    モデルに列が増えるたびにテストが壊れるのを避ける。値そのものは
    このテストの主張に関係しない（見ているのは land_zone の畳み込みだけ）。
    """
    import datetime

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


def test_router_maps_land_counts_through_the_fold():
    """`get_heatmap_composite` の `land_rotated` が畳み込みどおりに並ぶ。

    表をテスト側に写して満足しないよう、**実際にルータを呼ぶ**。
    """
    import sqlalchemy as sa
    from sqlalchemy.orm import sessionmaker

    from backend.db.models import Base, GameSet, Match, Player, Rally, Stroke
    from backend.routers.analysis_stable import get_heatmap_composite

    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        a = _make(Player, name="A")
        b = _make(Player, name="B")
        db.add_all([a, b])
        db.flush()
        m = _make(Match, player_a_id=a.id, player_b_id=b.id)
        db.add(m)
        db.flush()
        gs = _make(GameSet, match_id=m.id, set_num=1)
        db.add(gs)
        db.flush()
        rally = _make(Rally, set_id=gs.id, rally_num=1)
        db.add(rally)
        db.flush()
        # 相手コートのベースライン左 (BL) に 3 本落としている。
        for i in range(3):
            db.add(_make(Stroke, rally_id=rally.id, stroke_num=i + 1,
                         player="player_a", hit_zone="MC", land_zone="BL"))
        db.commit()

        # FastAPI の `Query(None)` 既定値は直接呼び出しでは None にならないので、
        # 絞り込み条件は全部明示的に None を渡す。
        res = get_heatmap_composite(
            player_id=a.id, result=None, tournament_level=None,
            date_from=None, date_to=None, match_id=None, match_ids=None, db=db,
        )
        land = res["data"]["land_rotated"]
    finally:
        db.close()

    # ベースライン際に落ちた球は、自コートでもベースライン際に描かれる。
    assert land["BL"]["count"] == 3, land
    # 旧実装ならここ (ネット際・右) に 3 本入っていた。
    assert land["NR"]["count"] == 0, land
