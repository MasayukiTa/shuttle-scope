"""画面上の「上/下」を、その試合の player_a / player_b に対応づける。

**CV の `player_a` は人ではない。** `backend/yolo/inference.py` の
`_assign_player_labels` は、そのフレームで検出された人の y 平均より上にいる方から
順に `player_a`, `player_b` を振る。つまり `player_a` は「画面の上側」という
意味しか持たない。一方 `Stroke.player` の `player_a` は **その試合の
`Match.player_a_id` 本人**を指す。同じ綴りで別の意味なので、翻訳せずに繋ぐと
自選手が下側に映っている試合では打者が全部入れ替わる。

翻訳に要るのは「set N のこのラリー時点で、match の player_a は画面のどちら側か」
だけで、それは `Match.player_a_start_side`（セット1開始時の位置）とコートチェンジの
規則から決まる:

  - 各ゲームの終了ごとにエンドを替える → set_num - 1 回入れ替わる
  - 最終ゲームは **どちらかが 11 点** に達した時点でもう一度替える

3ゲームマッチしか規則を持っていないので、4 ゲーム目以降や開始サイド未設定は
**推測せず None を返す**。呼び出し側は従来どおり «画面上の位置» のまま扱い、
人には対応づけない。
"""
from __future__ import annotations

from typing import Optional

TOP = "top"
BOTTOM = "bottom"

# 3ゲームマッチの最終ゲーム。ここだけ試合中にもエンドを替える。
FINAL_SET_NUM = 3
MID_SET_CHANGE_POINT = 11

# CV ラベルが意味する画面上の位置 (inference.py の割り当て順に対応)
_CV_LABEL_SIDE = {"player_a": TOP, "player_b": BOTTOM}


def _other(side: str) -> str:
    return BOTTOM if side == TOP else TOP


def side_of_player_a(
    start_side: Optional[str],
    set_num: Optional[int],
    score_a_before: Optional[int] = None,
    score_b_before: Optional[int] = None,
) -> Optional[str]:
    """そのラリー時点で match.player_a が画面のどちら側にいるか。

    決められなければ None（分からないことを分からないまま返す）。
    """
    if start_side not in (TOP, BOTTOM):
        return None
    if not isinstance(set_num, int) or isinstance(set_num, bool) or set_num < 1:
        return None
    if set_num > FINAL_SET_NUM:
        # 4・5 ゲーム目を持つ形式のエンド交替規則を持っていない。
        return None

    swaps = set_num - 1
    if set_num == FINAL_SET_NUM:
        if score_a_before is None or score_b_before is None:
            # 11 点の前か後かが判定できない = 半分の確率で逆。答えない。
            return None
        if max(score_a_before, score_b_before) >= MID_SET_CHANGE_POINT:
            swaps += 1

    return start_side if swaps % 2 == 0 else _other(start_side)


def resolve_cv_player(
    cv_label: Optional[str],
    start_side: Optional[str],
    set_num: Optional[int],
    score_a_before: Optional[int] = None,
    score_b_before: Optional[int] = None,
) -> Optional[str]:
    """CV ラベル（画面上の位置）を試合の player_a / player_b に翻訳する。

    翻訳できなければ None。`player_c` / `player_d` / `player_other` は
    ダブルスのパートナー区別であって本人特定ではないので対象外。
    """
    cv_side = _CV_LABEL_SIDE.get(cv_label or "")
    if cv_side is None:
        return None
    side_a = side_of_player_a(start_side, set_num, score_a_before, score_b_before)
    if side_a is None:
        return None
    return "player_a" if cv_side == side_a else "player_b"
