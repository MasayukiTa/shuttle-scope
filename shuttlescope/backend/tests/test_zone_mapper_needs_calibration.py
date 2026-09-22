"""A-1b: Zone9 はキャリブレーション無しには決まらない、を成果物で守る。

旧 `coords_to_zone` は画像の生の正規化座標を固定の閾値
(`y>0.50→B` / `y<=0.25→N` / `x<=0.33→L`) で切って Zone9 を返していた。
全景カメラでは画面の下半分が手前の半面なので、そこを丸ごと `B` と呼び、
奥の半面ではベースライン側を `N`、ネット側を `M` と呼んでいた
（**奥側半面で行が逆**、しかも半面の区別が無い）。

その値は `cv/candidate_builder.py` を通って `land_zone` 候補として
人のレビューに出ていた。

`backend.main` を import しないので Python 3.10 でも走る。
"""
from __future__ import annotations

import pytest

from backend.routers.court_calibration import _compute_homography, pixel_to_court_zone
from backend.tracknet.zone_mapper import (
    batch_heatmap_argmax,
    coords_to_zone,
    court_to_zone9,
    heatmap_to_zone,
)

UNIT_SQUARE = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]


@pytest.fixture(scope="module")
def flat_H():
    """恒等写像（画像座標 = コート座標）。"""
    return _compute_homography(UNIT_SQUARE, UNIT_SQUARE)


# ─── 画像座標からは Zone9 を出さない ──────────────────────────────────────────

def test_image_coordinates_never_produce_a_zone():
    """旧実装ならここで "B"/"N"/"M" が返っていた。

    特に `(0.5, 0.9)` は「画面下＝手前の半面」なのに旧実装は `BC` を返した。
    """
    for x, y in ((0.5, 0.9), (0.5, 0.1), (0.1, 0.4), (0.9, 0.6), (0.5, 0.5)):
        assert coords_to_zone(x, y) is None, (x, y)


def test_heatmap_peak_is_reported_without_inventing_a_zone():
    np = pytest.importorskip("numpy")
    hm = np.zeros((16, 16), dtype="float32")
    hm[13, 2] = 0.9  # 画面下寄り・左
    zone, conf, coords = heatmap_to_zone(hm)
    assert zone is None
    assert conf == pytest.approx(0.9, abs=1e-6)
    assert coords is not None  # 位置そのものは失わない
    assert coords[0] == pytest.approx(2 / 16)
    assert coords[1] == pytest.approx(13 / 16)


def test_heatmap_below_threshold_reports_nothing():
    np = pytest.importorskip("numpy")
    hm = np.full((8, 8), 0.1, dtype="float32")
    assert heatmap_to_zone(hm, threshold=0.5) == (None, pytest.approx(0.1, abs=1e-6), None)


def test_batch_argmax_matches_the_single_frame_path():
    np = pytest.importorskip("numpy")
    hms = np.zeros((3, 8, 8), dtype="float32")
    hms[0, 1, 1] = 0.8
    hms[1, 6, 6] = 0.7
    # hms[2] は全部 0 → 閾値未満
    batch = batch_heatmap_argmax(hms)
    single = [heatmap_to_zone(hms[i]) for i in range(3)]
    assert len(batch) == 3
    for b, s in zip(batch, single):
        assert b[0] is s[0] is None
        assert b[1] == pytest.approx(s[1], abs=1e-6)
        assert b[2] == s[2]


# ─── コート座標からは決まる ───────────────────────────────────────────────────

def test_net_row_is_nearest_the_net_on_both_sides():
    """N はネット際、B はベースライン側。どちらの半面でも同じ意味。"""
    assert court_to_zone9(0.5, 0.49) == ("A", "NC")   # ネットの A 側すぐ
    assert court_to_zone9(0.5, 0.51) == ("B", "NC")   # ネットの B 側すぐ
    assert court_to_zone9(0.5, 0.01) == ("A", "BC")   # A のベースライン
    assert court_to_zone9(0.5, 0.99) == ("B", "BC")   # B のベースライン


def test_columns_are_screen_based_not_mirrored():
    """画面左は両半面とも L。鏡映しない（ユーザ判断: 画面基準）。"""
    assert court_to_zone9(0.05, 0.05)[1][1] == "L"
    assert court_to_zone9(0.05, 0.95)[1][1] == "L"
    assert court_to_zone9(0.95, 0.05)[1][1] == "R"
    assert court_to_zone9(0.95, 0.95)[1][1] == "R"


def test_rows_split_each_half_into_equal_thirds():
    """半面の長さを 3 等分する。旧 zone_mapper は B だけがコートの半分だった。"""
    # B 側 (court_y 0.5..1.0) を等分すると N=0.5..0.667 / M=..0.833 / B=..1.0
    assert court_to_zone9(0.5, 0.60)[1][0] == "N"
    assert court_to_zone9(0.5, 0.75)[1][0] == "M"
    assert court_to_zone9(0.5, 0.90)[1][0] == "B"
    # A 側は鏡写し
    assert court_to_zone9(0.5, 0.40)[1][0] == "N"
    assert court_to_zone9(0.5, 0.25)[1][0] == "M"
    assert court_to_zone9(0.5, 0.10)[1][0] == "B"


def test_outside_the_normalised_court_returns_nothing():
    for x, y in ((-0.1, 0.5), (1.1, 0.5), (0.5, -0.01), (0.5, 1.01)):
        assert court_to_zone9(x, y) is None, (x, y)


# ─── 18 ゾーン側と食い違わないこと ────────────────────────────────────────────

def test_agrees_with_pixel_to_court_zone(flat_H):
    """`court_to_zone9` と `pixel_to_court_zone` が同じ点を同じように呼ぶ。

    18 ゾーン式と Zone9 式は別々に書かれていて、実際に食い違っていた
    （A-1b）。同じ点に対する side / depth / col が一致することを繋いでおく。
    """
    depth_to_row = {"front": "N", "mid": "M", "back": "B"}
    col_to_letter = {"left": "L", "center": "C", "right": "R"}
    for x in (0.1, 0.4, 0.6, 0.9):
        for y in (0.05, 0.2, 0.45, 0.55, 0.8, 0.95):
            info = pixel_to_court_zone(x, y, flat_H)
            got = court_to_zone9(info["court_x"], info["court_y"])
            assert got is not None, (x, y, info)
            side, zone = got
            assert side == info["side"], (x, y, side, info)
            assert zone[0] == depth_to_row[info["depth"]], (x, y, zone, info)
            assert zone[1] == col_to_letter[info["col"]], (x, y, zone, info)
