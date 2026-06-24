"""
hier_bayes_loader.py — 階層的 Bradley-Terry モデル用 DB データローダー

hier_bayes_engine.fit_bradley_terry() が受け取る
  (player_id_list, pairs)
を DB から組み立てる。

試合勝者の判定規則 (Match.result は player_a 視点):
  Match.result == 'win'  → player_a が勝者
  Match.result == 'loss' → player_b が勝者
  それ以外 ('walkover'/'unfinished'/'unknown') → スキップ
  (これは bayes_matchup.py の compute_bayes_matchup と同じ規則)

セキュリティ:
  allowed_player_ids が None でない場合、その集合に含まれない選手が
  関与する試合を除外する。親ルーターがチームアクセス制御済み選手 ID を
  渡す想定であり、このローダーは決してその集合を拡大しない。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from backend.db.models import Match
from backend.analysis.router_helpers import _get_player_matches


def load_match_pairs(
    db: Session,
    player_id: int,
    *,
    allowed_player_ids: Optional[set[int]] = None,
) -> tuple[list[int], list[tuple[int, int]]]:
    """player_id が関与する試合から Bradley-Terry 用ペアリストを構築する。

    cohort の選手: player_id 自身 + 対戦相手全員。
    allowed_player_ids が渡された場合は、その集合に含まれる選手のみを cohort に含む。

    Parameters
    ----------
    db : SQLAlchemy Session
    player_id : int
        解析対象選手の ID。
    allowed_player_ids : set[int] | None
        アクセス許可済み選手 ID 集合。None = 制限なし。
        player_id 自身は常にアクセス対象とみなす (呼び出し元がすでに認可済み)。

    Returns
    -------
    player_ids : list[int]
        コホート内の選手 ID リスト (安定した順序; インデックスがモデルの選手番号に対応)。
    pairs : list[tuple[int, int]]
        (winner_player_id, loser_player_id) のリスト。
        ここでは player_id ではなくモデルインデックスではなく生の player_id を返す。
        呼び出し元 (エンジンラッパー) がインデックス変換を行う。

    Notes
    -----
    返すペアは生の player_id で表現する。呼び出し元がインデックスを割り当てること:
        pid_to_idx = {pid: i for i, pid in enumerate(player_ids)}
        indexed_pairs = [(pid_to_idx[w], pid_to_idx[l]) for w, l in pairs]
    """
    # player_id が関与する全試合を取得 (フィルタ無し)
    matches: list[Match] = _get_player_matches(db, player_id)

    # 試合から勝者・敗者ペアを抽出し、cohort を収集する
    raw_pairs: list[tuple[int, int]] = []
    cohort_pids: set[int] = {player_id}

    for m in matches:
        res = getattr(m, "result", None)
        if res not in ("win", "loss"):
            # walkover/unfinished/unknown は勝者が確定しないためスキップ
            continue

        a_id: int = m.player_a_id
        b_id: int = m.player_b_id

        # allowed_player_ids による security チェック
        # 双方が許可済みでない試合は除外 (どちらかが圏外なら汚染される)
        if allowed_player_ids is not None:
            if a_id not in allowed_player_ids or b_id not in allowed_player_ids:
                continue

        if res == "win":
            # player_a が勝者
            winner_id, loser_id = a_id, b_id
        else:
            # res == "loss": player_b が勝者
            winner_id, loser_id = b_id, a_id

        raw_pairs.append((winner_id, loser_id))
        cohort_pids.add(a_id)
        cohort_pids.add(b_id)

    # allowed_player_ids で cohort を最終絞り込み (二重チェック)
    if allowed_player_ids is not None:
        cohort_pids &= allowed_player_ids
        # player_id は必ず含める (上述の認可済み前提)
        cohort_pids.add(player_id)

    # 安定した順序で選手リストを作成 (player_id を先頭に固定して予測しやすくする)
    sorted_others = sorted(cohort_pids - {player_id})
    player_ids: list[int] = [player_id] + sorted_others

    # cohort に属さない選手が絡むペアを排除 (cohort 絞り込み後に必要)
    cohort_set = set(player_ids)
    filtered_pairs = [
        (w, l) for w, l in raw_pairs
        if w in cohort_set and l in cohort_set
    ]

    return player_ids, filtered_pairs
