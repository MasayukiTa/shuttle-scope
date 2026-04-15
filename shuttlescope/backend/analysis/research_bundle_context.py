"""research_bundle_context.py — 研究タブ bundle 用の共有データコンテキスト

研究タブ 10 カード (epv / epv_state_table / state_action_values /
counterfactual_shots / counterfactual_v2 / bayes_matchup / opponent_policy /
doubles_role / shot_influence_v2 / hazard_fatigue) が Match/Set/Rally/Stroke を
各自再ロードしていたため、1 回だけロードして共有する。

設計メモ:
- spine / research 系の大半は `_get_player_matches(filters)` → sets → rallies →
  strokes という同じ形状で、`set_num_map` と `strokes_by_rally` (rally_id -> list)
  を追加で要求する。振り返りと同じ基礎データに派生マップを足すだけで足りる。
- `counterfactual_shots` のみ `_fetch_matches_sets_rallies` 由来で
  「フィルタなし + is_skipped=False」のビューを使うため、振り返り側と同じく
  `rs_*` 派生を持つ。
- `bayes_matchup` は matches だけあれば足りる。`format` は endpoint 固有パラメータ
  (ctx フィルタの一部ではない) として endpoint 側で処理する。
- `doubles_role` は filtered matches を `format in doubles` でさらに絞るので
  `doubles_matches` を事前計算しておく。
"""
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from backend.analysis.bundle_context import AnalysisContext, load_context
from backend.db.models import GameSet, Match, Rally, Stroke


@dataclass
class ResearchAnalysisContext:
    """研究タブ bundle 用に1回だけ DB を叩いて共有するためのコンテナ。

    振り返り版 `AnalysisContext` をベースに、spine 系 endpoint が要求する
    `set_num_map` と `strokes_by_rally` (dict 形式) を追加で保持する。
    """

    base: AnalysisContext

    # spine / research 固有の派生
    set_num_map: dict             # set_id -> set_num
    strokes_by_rally: dict        # rally_id -> list[Stroke] (filtered view)

    # counterfactual_shots 用 (フィルタなし + is_skipped=False)
    rs_strokes_by_rally: dict     # rally_id -> list[Stroke]

    # doubles_role 用
    doubles_matches: list         # format in ('womens_doubles', 'mixed_doubles')

    # 直通アクセス用のショートカット
    @property
    def player_id(self) -> int:
        return self.base.player_id

    @property
    def filters(self) -> dict:
        return self.base.filters

    @property
    def matches(self) -> list:
        return self.base.matches

    @property
    def role_by_match(self) -> dict:
        return self.base.role_by_match

    @property
    def sets(self) -> list:
        return self.base.sets

    @property
    def set_to_match(self) -> dict:
        return self.base.set_to_match

    @property
    def rallies(self) -> list:
        return self.base.rallies

    @property
    def strokes(self) -> list:
        return self.base.strokes

    @property
    def rs_matches(self) -> list:
        return self.base.rs_matches

    @property
    def rs_role_by_match(self) -> dict:
        return self.base.rs_role_by_match

    @property
    def rs_set_to_match(self) -> dict:
        return self.base.rs_set_to_match

    @property
    def rs_rallies(self) -> list:
        return self.base.rs_rallies

    @property
    def rs_strokes(self) -> list:
        return self.base.rs_strokes


def _group_by_rally(strokes: list) -> dict:
    out: dict = {}
    for s in strokes:
        out.setdefault(s.rally_id, []).append(s)
    return out


def load_research_context(
    db: Session, player_id: int, filters: dict
) -> ResearchAnalysisContext:
    """研究タブ 10 カード分の共有データを 1 回のバルクロードで構築する。"""

    # 振り返り版の基盤をそのまま再利用 (Match/Set/Rally/Stroke)
    base = load_context(db, player_id, filters)

    # set_num は base.sets に既に載っているため再クエリせず派生させる
    set_num_map = {s.id: s.set_num for s in base.sets}

    # spine 系は stable ビュー (filtered) の strokes を rally ごとに並べ替えて使う
    strokes_by_rally = _group_by_rally(base.strokes)

    # counterfactual_shots は rs_* ビューを使うため、こちらも同様に組み立てる
    rs_strokes_by_rally = _group_by_rally(base.rs_strokes)

    # doubles_role: filtered matches から doubles format のみを抽出
    doubles_matches = [
        m for m in base.matches
        if getattr(m, "format", None) in ("womens_doubles", "mixed_doubles")
    ]

    return ResearchAnalysisContext(
        base=base,
        set_num_map=set_num_map,
        strokes_by_rally=strokes_by_rally,
        rs_strokes_by_rally=rs_strokes_by_rally,
        doubles_matches=doubles_matches,
    )
