"""analysis_population.py — 「解析に入れてよい試合」の定義 (1 か所)

Match.result の語彙は win / loss / walkover / unfinished (db/models.py)。
勝敗が確定している (win / loss) 試合で、かつ有効なラリーが 1 本以上ある試合だけを
解析母集団に入れる。それ以外を勝率の分母に入れると、未完了の試合が「負け」に
数えられる。

除外した試合は黙って捨てず、理由別の件数 (unfinished / zero_rally) を返す。
unfinished と zero_rally が重なる試合は unfinished に数える (1 試合 1 回だけ)。
"""
from typing import Iterable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.db.models import GameSet, Match, Rally

DECIDED_RESULTS = ("win", "loss")

EXCLUDED_UNFINISHED = "unfinished"
EXCLUDED_ZERO_RALLY = "zero_rally"


def is_decided_result(result: Optional[str]) -> bool:
    """勝敗が確定した結果 (win / loss) か。walkover / unfinished / None は False。"""
    return result in DECIDED_RESULTS


def empty_excluded() -> dict[str, int]:
    return {EXCLUDED_UNFINISHED: 0, EXCLUDED_ZERO_RALLY: 0}


def exclusion_reason(result: Optional[str], rally_count: int) -> Optional[str]:
    """解析母集団から外す理由。入れてよい試合は None。"""
    if not is_decided_result(result):
        return EXCLUDED_UNFINISHED
    if rally_count <= 0:
        return EXCLUDED_ZERO_RALLY
    return None


def rally_counts_by_match(db: Session, match_ids: Iterable[int]) -> dict[int, int]:
    """試合ごとの有効ラリー数 (is_skipped でないもの)。ラリーが無い試合は含まれない。"""
    ids = list(match_ids)
    if not ids:
        return {}
    rows = (
        db.query(GameSet.match_id, func.count(Rally.id))
        .join(Rally, Rally.set_id == GameSet.id)
        .filter(GameSet.match_id.in_(ids), Rally.is_skipped == False)  # noqa: E712
        .group_by(GameSet.match_id)
        .all()
    )
    return {mid: int(n) for mid, n in rows}


def split_analysis_population(
    db: Session, matches: list[Match],
) -> tuple[list[Match], dict[str, int]]:
    """試合一覧を (解析母集団に入る試合, 理由別の除外件数) に分ける。順序は保つ。"""
    excluded = empty_excluded()
    if not matches:
        return [], excluded
    counts = rally_counts_by_match(db, (m.id for m in matches))
    included: list[Match] = []
    for m in matches:
        reason = exclusion_reason(m.result, counts.get(m.id, 0))
        if reason is None:
            included.append(m)
        else:
            excluded[reason] += 1
    return included, excluded
