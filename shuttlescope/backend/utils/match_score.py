"""match_score.py -- final_score と result の整合性検査 (監査 #155 / #179 / #180)。

防ぐ事象: final_score は自由文字列 ("21-15, 18-21, 21-19") なので、
- result=loss なのにスコア上は player_a の勝ち (結果とスコアの勝者が逆)
- 2 セット先取で終わっているのに 3 セット目があるスコア (21-18, 21-16, 21-17)
が保存でき、解析の勝敗がスコアと食い違った (監査の実測: 確定スコア 50 試合中 11 試合が逆、3-0 が 3 件)。

ここは「新しい書き込み」だけを対象にする純粋関数で、既存のデータは書き換えない。
解釈できない書式 (自由記述など) は判定せず通す。判定できるときだけ矛盾を返す。
スコアは player_a から見た A-B。result も player_a から見た win / loss。
"""
from __future__ import annotations

import re
from typing import Optional

_SET_RE = re.compile(r"^\s*(\d{1,2})\s*[-–:]\s*(\d{1,2})\s*$")
_SPLIT_RE = re.compile(r"[,、;]")
_SETS_TO_WIN = 2  # best-of-3


def parse_set_scores(final_score: Optional[str]) -> Optional[list[tuple[int, int]]]:
    """'21-15, 18-21, 21-19' を [(21,15),(18,21),(21,19)] にする。解釈できなければ None。"""
    if final_score is None or not final_score.strip():
        return None
    out: list[tuple[int, int]] = []
    for part in _SPLIT_RE.split(final_score):
        m = _SET_RE.match(part)
        if not m:
            return None
        out.append((int(m.group(1)), int(m.group(2))))
    return out or None


def score_consistency_error(final_score: Optional[str], result: Optional[str]) -> Optional[str]:
    """矛盾があれば理由 (日本語) を、なければ None を返す。判定できない入力は None。"""
    sets = parse_set_scores(final_score)
    if sets is None:
        return None
    a_sets = b_sets = 0
    for a, b in sets:
        if a == b:
            return "final_score に引き分けのセットがあります"
        if a_sets >= _SETS_TO_WIN or b_sets >= _SETS_TO_WIN:
            return "final_score は 2 セット先取で決着した後にセットが続いています (3 セットマッチとして成立しません)"
        if a > b:
            a_sets += 1
        else:
            b_sets += 1
    if result == "win" and a_sets <= b_sets:
        return "result=win ですが final_score の勝者は player_a ではありません"
    if result == "loss" and b_sets <= a_sets:
        return "result=loss ですが final_score の勝者は player_b ではありません"
    return None
