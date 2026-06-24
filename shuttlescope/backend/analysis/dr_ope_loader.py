"""
dr_ope_loader.py — DR-OPE 解析用レコードを DB から構築する

DR-OPE エンジン (dr_ope_engine.py) はコンテキスト的バンディット設定を想定:
  - 状態キー: (score_phase, player_role) の粗い 2 次元 (coarse=True デフォルト)
  - 行動 a:   対象選手のショットバケット
  - 報酬 win: そのラリーで対象選手が勝てば 1

exploitability_loader の load_exploitability_records をそのまま再利用し、
各レコードから相手行動 "b" を落として {"a", "win"} の形式に変換する。

注意:
  - チームスコープのフィルタリングは呼び出し元 (ルーター) が担う。
    このローダーは player_id 単位でレコードを返すのみ。
  - load_exploitability_records が既に選手の全試合を対象に集計するため、
    このモジュールでは追加のチームロジックは不要。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.analysis.exploitability_loader import load_exploitability_records


def load_policy_records(
    db: Session,
    player_id: int,
    *,
    coarse: bool = True,
) -> dict[str, list[dict]]:
    """player_id の全試合から DR-OPE 用レコードを状態キー別に返す。

    内部で load_exploitability_records を呼び出し、
    各レコードを {"a": str, "win": 0|1} に変換する (相手行動 "b" を除去)。

    Args:
        db:        SQLAlchemy セッション
        player_id: 対象選手の ID
        coarse:    True (デフォルト) → 状態キー = (score_phase, player_role) 2 次元
                   False → 状態キー = GameState 5 次元 (データ疎密環境では非推奨)

    Returns:
        {state_key: [{"a": str, "win": 0|1}, ...]}
        レコードなし / 試合なしの場合は {} を返す。
    """
    raw = load_exploitability_records(db, player_id, coarse=coarse)

    policy_records: dict[str, list[dict]] = {}
    for state_key, recs in raw.items():
        flattened = [{"a": r["a"], "win": r["win"]} for r in recs if r.get("a") is not None]
        if flattened:
            policy_records[state_key] = flattened

    return policy_records
