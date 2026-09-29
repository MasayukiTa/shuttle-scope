"""Zone9 の「相手半面を自半面に重ねる」畳み込み（可視化専用）。

A-1b (2026-09-22) で座標系を **画面基準** に統一したときに書き直した。

## Zone9 の 2 つの軸は基準が違う

人手入力の正本は `src/components/court/CourtDiagram.tsx` の
`OPPONENT_ZONES` / `OWN_ZONES`（300x400 の俯瞰図、ネットは y=200）。
そこから読み取れる規則は:

- **行 (B / M / N) はネット基準。** どちらの半面でも N がネット際、B が
  ベースライン側。相手半面は上端が B、自半面は下端が B。
- **列 (L / C / R) は画面基準。** どちらの半面でも画面左が L
  （x=0..100 が L、200..300 が R）。**鏡映しない。**

## だから畳み込みは恒等写像になる

相手半面を自半面に重ねるのは、ネット線 (y=200) での鏡映。

- 鏡映は「ネットからの距離」を保つ → 行ラベルは変わらない
- 鏡映は x を動かさない → 列ラベルも変わらない

つまり相手半面の `BL` は自半面の `BL` の位置に重なる。

## 以前の `ZONE_ROTATION_MAP` が何を仮定していたか

旧実装は `BL→NR` / `ML→MR` / `NL→BR` という **180 度の点対称**だった。
これは「各選手が自分から見た左右で L/R を呼ぶ」= **選手基準の列**を前提に
した表で、その前提なら相手の BL は世界座標で自分の BR の対角にあたるので
行と列の両方を反転させる必要がある。

しかしこのアプリの入力 UI は選手基準ではない。列は画面基準である。
前提が違う変換を掛けていたので、**相手のベースライン際に落ちた球が、
自コートのネット際に描かれていた**（クリアがネット前に見える）。

旧テスト `test_heatmap_composite.py` は変換表をテスト側に書き写して
自分自身と突合していただけなので、実装を一度も読んでおらず、
この誤りでは絶対に落ちなかった。
"""
from __future__ import annotations

#: 行ラベル: ネット際から遠い順ではなく「ネット基準」であることだけが重要。
ROW_LABELS = ("N", "M", "B")
#: 列ラベル: 画面左から右。
COL_LABELS = ("L", "C", "R")

ZONES_9 = tuple(f"{r}{c}" for r in ("B", "M", "N") for c in COL_LABELS)


def split_zone9(zone: str) -> tuple[str, str]:
    """`"BL"` → `("B", "L")`。語彙外は ValueError。"""
    if not isinstance(zone, str) or len(zone) != 2:
        raise ValueError(f"Zone9 ではない: {zone!r}")
    row, col = zone[0], zone[1]
    if row not in ROW_LABELS or col not in COL_LABELS:
        raise ValueError(f"Zone9 ではない: {zone!r}")
    return row, col


def fold_land_zone_onto_own_court(zone: str) -> str:
    """相手半面の Zone9 を、自半面に重ねたときのラベルに変換する。

    行はネット基準・列は画面基準なので、ネット線での鏡映はどちらのラベルも
    変えない。**恒等写像である**ことをここで明示的に述べておくために関数に
    してある（「変換が要るはず」という直感で点対称を書き戻さないため）。

    語彙検査は行う。Zone9 以外が来たら黙って通さない。
    """
    split_zone9(zone)
    return zone
