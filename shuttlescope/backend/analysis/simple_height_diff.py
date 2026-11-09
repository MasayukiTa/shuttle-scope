"""簡易分析: 打球の高さ差（要望8 / SD-08）

ねらい
------
仙台大学との 2026-11-05 の打合せで、ダブルス向けに «簡単な分析» の要望が出た:
打った側の打球の高さと、それを受けた側の打球の高さの «差» を見たい。
例: 打った人が「ネットより上」、受けた人が「やや下」なら差は 2。

このモジュールは «細かい分析»（analysis_stable / advanced / research）とは別物の、
依存の少ない小さな計算だけを持つ。DB モデルも FastAPI も読み込まない。

高さの 0〜3 写像
----------------
4 段階の高さラベルは ``backend.utils.validators.HIT_HEIGHT_ORDER`` で一元定義され、
``hit_height_level`` が 0〜3 の整数へ写す（ネットから下へ向かって単調増加）:

    above_net      ネットより上  → 0
    slightly_above やや上        → 1
    slightly_below やや下        → 2
    below          下            → 3

高さ差の定義
------------
ラリーの中で «連続する 2 球» のうち、打った側（team A）と受けた側（team B）が
別チームになっている組（= 返球関係）について、

    diff = | level(打った球の高さ) - level(受けた球の高さ) |

を取る。差は 0〜3 の整数。どちらかの高さが未入力（None / 未知ラベル）の組は
集計から除く（0 と数えない）。チームの判定は role_view.stroke_side を使うので、
ダブルスでも «自分の相方の球» を相手扱いしない。

シングルスでも連続する 2 球は必ず別チームなので、同じ関数がそのまま使える。
"""
from __future__ import annotations

from typing import Iterable, Optional

from backend.analysis.role_view import stroke_side
from backend.utils.validators import hit_height_level


class _StrokeView:
    """計算に必要な最小限だけを読む薄いラッパ。dict でも ORM オブジェクトでも受ける。"""

    __slots__ = ("player", "hit_height", "stroke_num")

    def __init__(self, src: object) -> None:
        if isinstance(src, dict):
            self.player = src.get("player")
            self.hit_height = src.get("hit_height")
            self.stroke_num = src.get("stroke_num")
        else:
            self.player = getattr(src, "player", None)
            self.hit_height = getattr(src, "hit_height", None)
            self.stroke_num = getattr(src, "stroke_num", None)


def height_diff(hitter_height: Optional[str], receiver_height: Optional[str]) -> Optional[int]:
    """打った側と受けた側の高さの差の絶対値（0〜3）。

    どちらかが未入力・未知ラベルなら None（= この組は測れない）。
    """
    a = hit_height_level(hitter_height)
    b = hit_height_level(receiver_height)
    if a is None or b is None:
        return None
    return abs(a - b)


def rally_height_diffs(strokes: Iterable[object]) -> list[int]:
    """1 ラリー分の打球列から、返球関係（連続する別チームの 2 球）の高さ差を並べる。

    strokes は stroke_num 昇順である必要はない（内部で並べ替える）。
    高さが片方でも欠ける組は飛ばす。
    """
    views = [_StrokeView(s) for s in strokes]
    views.sort(key=lambda v: (v.stroke_num is None, v.stroke_num))
    out: list[int] = []
    for prev, cur in zip(views, views[1:]):
        side_prev = stroke_side(prev.player)
        side_cur = stroke_side(cur.player)
        if side_prev is None or side_cur is None:
            continue
        if side_prev == side_cur:
            # 同じチームの連続球（例: ダブルスでの隊形上のつなぎ）は返球関係ではない
            continue
        d = height_diff(prev.hit_height, cur.hit_height)
        if d is not None:
            out.append(d)
    return out


def summarize_height_diffs(rallies_strokes: Iterable[Iterable[object]]) -> dict:
    """複数ラリー分をまとめた «簡易分析» の結果。

    返す dict:
      pairs          : 測れた返球関係の組数
      mean_diff      : 高さ差の平均（組が無ければ None）
      distribution   : 差の値（0..3）ごとの件数 {\"0\":.., \"1\":.., \"2\":.., \"3\":..}
    """
    diffs: list[int] = []
    for strokes in rallies_strokes:
        diffs.extend(rally_height_diffs(strokes))
    distribution = {str(k): 0 for k in range(4)}
    for d in diffs:
        distribution[str(d)] += 1
    pairs = len(diffs)
    mean_diff = (sum(diffs) / pairs) if pairs else None
    return {
        "pairs": pairs,
        "mean_diff": mean_diff,
        "distribution": distribution,
    }


def rally_max_diff(strokes: Iterable[object]) -> Optional[int]:
    """1 ラリーの «最も大きかった» 高さ差（測れる返球関係が無ければ None）。"""
    diffs = rally_height_diffs(strokes)
    return max(diffs) if diffs else None


def top_height_diff_rallies(
    rallies: Iterable[tuple[object, Iterable[object]]],
    limit: int = 5,
) -> list[dict]:
    """«差が大きかったラリー» の一覧（最大差の降順、上位 ``limit`` 件）。

    引数
    ----
    rallies : (rally_key, strokes) の列。rally_key はラリーの識別子
              （例: rally_num や rally_id）で、そのまま結果に載せる。
    limit   : 返す件数の上限（0 以下なら空。測れるラリーが少なければそれだけ）。

    返す各要素 dict:
      rally      : 渡した rally_key
      max_diff   : そのラリーの最大高さ差（0〜3）
      pairs      : そのラリーで測れた返球関係の組数

    高さ差を 1 組も測れないラリーは一覧に入れない。並びは max_diff 降順、
    同じ max_diff なら pairs の多い順、さらに同じなら渡された順を保つ（安定）。
    """
    rows: list[dict] = []
    for idx, (rally_key, strokes) in enumerate(rallies):
        diffs = rally_height_diffs(strokes)
        if not diffs:
            continue
        rows.append({
            "rally": rally_key,
            "max_diff": max(diffs),
            "pairs": len(diffs),
            "_order": idx,
        })
    rows.sort(key=lambda r: (-r["max_diff"], -r["pairs"], r["_order"]))
    if limit is not None and limit >= 0:
        rows = rows[:limit]
    for r in rows:
        r.pop("_order", None)
    return rows
