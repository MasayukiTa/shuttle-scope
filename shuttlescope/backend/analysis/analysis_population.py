"""analysis_population.py — 「解析に入れてよい試合」の定義 (1 か所)

Match.result の語彙は win / loss / walkover / unfinished (db/models.py)。
勝敗が確定している (win / loss) 試合で、かつ有効なラリーが 1 本以上ある試合だけを
解析母集団に入れる。それ以外を勝率の分母に入れると、未完了の試合が「負け」に
数えられる。

除外した試合は黙って捨てず、理由別の件数 (unfinished / zero_rally) を返す。
unfinished と zero_rally が重なる試合は unfinished に数える (1 試合 1 回だけ)。

audit #178: 検証用 fixture (BIAS_SEED 等の合成データ) は matches.is_synthetic で
明示タグ付けされる。通常の母集団はこれを既定で除外する。管理ツールだけが
include_synthetic=True で取り込める。synthetic は母集団に入る前の段階で外すため、
excluded 件数 dict (unfinished / zero_rally の 2 キー) の形は変えない。この除外判定は
ここ 1 か所 (split_analysis_population) に集約し、母集団を数える全ての解析
(opponent_stats / tournament_level_comparison / pair_synergy / router_helpers 経由の
各エンドポイント) が同じ定義を使う。
"""
from typing import Iterable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.db.models import GameSet, Match, Rally

DECIDED_RESULTS = ("win", "loss")

EXCLUDED_UNFINISHED = "unfinished"
EXCLUDED_ZERO_RALLY = "zero_rally"

# 途中保存 (mid-rally autosave) ラリーの end_type。POST /api/strokes/batch を
# final=false で送ると、まだ確定していないラリーが end_type="in_progress" /
# winner=仮 (player_a) で保存される。これは確定ラリーではないので、解析母集団・
# 有効ラリー数・各種集計から一貫して除外する。識別は end_type 列だけで足りる
# (専用フラグ列は増やさない = スキーマ変更なし)。
IN_PROGRESS_END_TYPE = "in_progress"


def active_rally_predicates(include_skipped: bool = False) -> list:
    """確定ラリーだけを引くための SQLAlchemy フィルタ条件のリスト。

    query(Rally)... に *args 展開して使う。全集計で同じ定義を使うためここに集約する。
    除外するもの:
      - 論理削除済み (deleted_at IS NOT NULL)
      - 途中保存 (end_type == IN_PROGRESS_END_TYPE)
      - 見逃しラリー (is_skipped) ※ include_skipped=True のときは残す
    """
    # 遅延 import 回避のためモジュール先頭の Rally を使う
    preds = [
        Rally.deleted_at.is_(None),
        Rally.end_type != IN_PROGRESS_END_TYPE,
    ]
    if not include_skipped:
        preds.append(Rally.is_skipped == False)  # noqa: E712
    return preds


def is_decided_result(result: Optional[str]) -> bool:
    """勝敗が確定した結果 (win / loss) か。walkover / unfinished / None は False。"""
    return result in DECIDED_RESULTS


def empty_excluded() -> dict[str, int]:
    return {EXCLUDED_UNFINISHED: 0, EXCLUDED_ZERO_RALLY: 0}


def is_synthetic_match(match: Match) -> bool:
    """検証用 fixture (合成データ) か。matches.is_synthetic が True のときだけ True。
    False / NULL / 属性なし (旧データ) は実データ扱い (fail closed)。"""
    return getattr(match, "is_synthetic", False) is True


def exclusion_reason(result: Optional[str], rally_count: int) -> Optional[str]:
    """解析母集団から外す理由 (unfinished / zero_rally)。入れてよい試合は None。
    synthetic (検証用 fixture) の除外は split_analysis_population 側で母集団に入る前に
    行うため、ここには含めない (excluded 件数 dict の形を変えないため)。"""
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
        .filter(
            GameSet.match_id.in_(ids),
            Rally.end_type != IN_PROGRESS_END_TYPE,
            Rally.is_skipped == False,  # noqa: E712
            Rally.deleted_at.is_(None),
        )
        .group_by(GameSet.match_id)
        .all()
    )
    return {mid: int(n) for mid, n in rows}


def split_analysis_population(
    db: Session, matches: list[Match], include_synthetic: bool = False,
) -> tuple[list[Match], dict[str, int]]:
    """試合一覧を (解析母集団に入る試合, 理由別の除外件数) に分ける。順序は保つ。

    include_synthetic=False (既定): 検証用 fixture (is_synthetic) を母集団から外す。
    include_synthetic=True: 管理ツール向け。synthetic も取り込む (他の除外理由は従来通り)。
    """
    excluded = empty_excluded()
    if not matches:
        return [], excluded
    # synthetic (検証用 fixture) は既定で母集団に入れない。include_synthetic=True の
    # ときだけ取り込む。synthetic は excluded 件数 (unfinished / zero_rally) には数えない。
    if not include_synthetic:
        matches = [m for m in matches if not is_synthetic_match(m)]
    counts = rally_counts_by_match(db, (m.id for m in matches))
    included: list[Match] = []
    for m in matches:
        reason = exclusion_reason(m.result, counts.get(m.id, 0))
        if reason is None:
            included.append(m)
        else:
            excluded[reason] += 1
    return included, excluded
