"""match_filter.py — 解析ダッシュボードの絞り込み (結果・大会レベル・期間) の共通部品

防ぐ事象: 絞り込みを受け取る解析と受け取らない解析が混ざり、同じ画面で N が指標ごとに
違った (監査 #152)。受け取り方・母集団の決め方・応答への書き方をここ 1 か所に置く。

使い方 (エンドポイント):
    @router.get("/analysis/xxx")
    @stamps_population("xxx")
    def get_xxx(player_id: int, mf: MatchFilter = Depends(match_filter_params), db=Depends(get_db)):
        matches, excluded = select_population(db, player_id, mf)

  - 母集団の定義は analysis_population (勝敗確定 かつ ラリー有り) + 絞り込み。
  - `stamps_population` が応答の meta に次を書く:
        meta.population   = {n_matches, n_rallies, filter_applied}
        meta.filter_scope = registry の filter_scope
    n_matches / n_rallies は select_population が返す試合の件数で、解析本体の母集団と
    同じ関数で数える。
  - 絞り込みを使わない解析は registry で filter_scope="global_only" と宣言し、
    declare_filter_scope で meta に書く。MatchFilter は受け取らない。
"""
from __future__ import annotations

import functools
from dataclasses import dataclass
from datetime import date as DateType
from typing import Any, Callable, Optional

from fastapi import Query
from sqlalchemy.orm import Session

from backend.analysis.analysis_population import rally_counts_by_match
from backend.analysis.analysis_registry import FILTER_SCOPE_FILTERED, get_filter_scope
from backend.analysis.router_helpers import _get_player_matches_with_excluded, validate_date_range
from backend.db.models import Match


@dataclass(frozen=True)
class MatchFilter:
    """ダッシュボードの絞り込み。query 名はフロントと同じ
    (result / tournament_level / date_from / date_to)。result は "win" / "loss" のときだけ効く
    (フロントは "all" のとき result を送らない)。"""

    result: Optional[str] = None
    tournament_level: Optional[str] = None
    date_from: Optional[DateType] = None
    date_to: Optional[DateType] = None

    @property
    def applied(self) -> bool:
        return bool(
            self.result in ("win", "loss")
            or self.tournament_level
            or self.date_from
            or self.date_to
        )

    def kwargs(self) -> dict[str, Any]:
        """_get_player_matches / _get_player_matches_with_excluded へ渡す引数。"""
        return {
            "result": self.result,
            "tournament_level": self.tournament_level,
            "date_from": self.date_from,
            "date_to": self.date_to,
        }


NO_FILTER = MatchFilter()


def match_filter_params(
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
) -> MatchFilter:
    """FastAPI 依存。解析エンドポイントはこれ 1 つで絞り込みを受け取る。
    開始日 > 終了日は 422 (監査 #797)。"""
    validate_date_range(date_from, date_to)
    return MatchFilter(
        result=result if result in ("win", "loss") else None,
        tournament_level=tournament_level or None,
        date_from=date_from,
        date_to=date_to,
    )


def select_population(
    db: Session, player_id: int, mf: Optional[MatchFilter] = None,
) -> tuple[list[Match], dict[str, int]]:
    """解析母集団 (analysis_population) に絞り込みを掛けた試合と、理由別の除外件数。"""
    return _get_player_matches_with_excluded(db, player_id, **(mf or NO_FILTER).kwargs())


def population_summary(
    db: Session, matches: list[Match], mf: Optional[MatchFilter] = None,
) -> dict[str, Any]:
    """meta.population。n_rallies は有効ラリー (is_skipped でないもの) の本数。"""
    counts = rally_counts_by_match(db, (m.id for m in matches))
    return {
        "n_matches": len(matches),
        "n_rallies": int(sum(counts.get(m.id, 0) for m in matches)),
        "filter_applied": bool((mf or NO_FILTER).applied),
    }


def stamps_population(analysis_type: str) -> Callable:
    """エンドポイントの応答 meta に population と filter_scope を書き足すデコレータ。

    エンドポイントは player_id / db / mf をキーワード引数で受け取ること
    (FastAPI は常にキーワードで渡す)。応答が dict で meta が dict のときだけ書く。
    """

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            resp = fn(*args, **kwargs)
            meta = resp.get("meta") if isinstance(resp, dict) else None
            if not isinstance(meta, dict):
                return resp
            db = kwargs["db"]
            mf = kwargs.get("mf")
            matches, _excluded = select_population(db, kwargs["player_id"], mf)
            meta["population"] = population_summary(db, matches, mf)
            meta["filter_scope"] = get_filter_scope(analysis_type)
            return resp

        return wrapper

    return decorator


def declare_filter_scope(meta: dict, analysis_type: str) -> dict:
    """絞り込みを使わない解析 (global_only) の meta に filter_scope と population を書く。
    population.filter_applied は常に False。母集団は別に数えないので n は None。"""
    scope = get_filter_scope(analysis_type)
    meta["filter_scope"] = scope
    if scope != FILTER_SCOPE_FILTERED:
        meta["population"] = {"n_matches": None, "n_rallies": None, "filter_applied": False}
    return meta
