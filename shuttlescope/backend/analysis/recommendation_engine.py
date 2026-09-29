"""
recommendation_engine.py — 推奨ランキング計算エンジン (Stage 2-A)

改善点:
  - BASELINE=0.5 固定 → 選手固有の全体勝率をベースラインとして使用
  - context_baseline: 大会レベル等の文脈に応じた補正ベースライン
  - 将来拡張: opponent-adjusted / pair-adjusted baseline は Stage 3 以降

設計原則:
  - 全関数は純粋関数（副作用なし）
  - 既存のエンドポイント引数・レスポンス形式と後方互換
"""
from __future__ import annotations
import math
from collections import defaultdict
from typing import Optional


# ── ベースライン計算 ─────────────────────────────────────────────────────────

def compute_player_baseline(
    rallies: list,
    role_by_match: dict,
    set_to_match: dict,
) -> float:
    """
    選手固有の全体ラリー勝率をベースラインとして計算する。

    固定 0.5 ではなく実際の成績を反映することで、
    強い選手（勝率 0.65）がショットを強化すべき場合と
    弱い選手（勝率 0.40）が改善すべき場合を適切に区別する。

    Parameters:
        rallies:       対象ラリー一覧
        role_by_match: match_id → player_role マッピング
        set_to_match:  set_id → match_id マッピング

    Returns:
        全体ラリー勝率 (0.0-1.0)。データなし時は 0.5 にフォールバック。
    """
    if not rallies:
        return 0.5
    wins = 0
    total = 0
    for r in rallies:
        mid = set_to_match.get(r.set_id)
        if mid is None:
            continue
        role = role_by_match.get(mid)
        if role is None:
            continue
        total += 1
        if r.winner == role:
            wins += 1
    return round(wins / total, 4) if total > 0 else 0.5


def compute_context_baselines(
    rallies: list,
    role_by_match: dict,
    set_to_match: dict,
    matches: list,
) -> dict[str, float]:
    """
    文脈別のベースライン勝率を計算する。

    将来の opponent-adjusted / pair-adjusted baseline の土台。
    現 Stage 2 では大会レベル別と日付半期別のコンテキストを提供する。

    Returns:
        {
          'overall': float,                          # 全体
          'by_level': {tournament_level: float},     # 大会レベル別
        }
    """
    match_by_id = {m.id: m for m in matches}

    overall = compute_player_baseline(rallies, role_by_match, set_to_match)

    # 大会レベル別
    level_stats: dict[str, dict] = defaultdict(lambda: {"wins": 0, "total": 0})
    for r in rallies:
        mid = set_to_match.get(r.set_id)
        if mid is None:
            continue
        role = role_by_match.get(mid)
        m = match_by_id.get(mid)
        if role is None or m is None:
            continue
        level = m.tournament_level or "other"
        level_stats[level]["total"] += 1
        if r.winner == role:
            level_stats[level]["wins"] += 1

    by_level: dict[str, float] = {}
    for level, s in level_stats.items():
        if s["total"] >= 20:  # 最低 20 ラリーないと信頼性が低い
            by_level[level] = round(s["wins"] / s["total"], 4)
        else:
            by_level[level] = overall  # サンプル不足はデフォルト

    return {
        "overall": overall,
        "by_level": by_level,
    }


# ── スコアリング ─────────────────────────────────────────────────────────────

def score_recommendation_item(
    count: int,
    wins: int,
    baseline: float,
    norm_n: float = 300.0,
) -> float:
    """
    推奨アドバイスの優先度スコアを計算する。

    スコア = log(n+1) / log(norm_n+1) × |win_rate - baseline|

    - サンプル数が多いほど高スコア（対数スケール）
    - ベースラインからの乖離が大きいほど高スコア
    - 勝率が高い（強み）も低い（伸びしろ）も同等に評価

    Returns:
        優先度スコア (float, 通常 0.0-1.0 の範囲)
    """
    if count == 0:
        return 0.0
    wr = wins / count
    effect = abs(wr - baseline)
    return round(math.log(count + 1) / math.log(norm_n + 1) * effect, 4)


def build_recommendation_item(
    category: str,
    key: str,
    label: str,
    count: int,
    wins: int,
    baseline: float,
    norm_n: float = 300.0,
    min_samples: int = 5,
) -> Optional[dict]:
    """
    推奨アドバイス1件を構築する。
    min_samples 未満の場合は None を返す。

    Parameters:
        category:    'shot' / 'zone'
        key:         shot_type / zone コード
        label:       表示名（日本語）
        count:       該当ストローク/エリア数
        wins:        勝利ラリー数
        baseline:    ベースライン勝率（player_baseline 等）
        norm_n:      スコア正規化定数
        min_samples: 最低サンプル数

    Returns:
        推奨アドバイス dict または None
    """
    if count < min_samples:
        return None

    wr = wins / count
    score = score_recommendation_item(count, wins, baseline, norm_n)
    confidence_level = "★★★" if count >= 100 else "★★" if count >= 30 else "★"

    if wr >= baseline:
        title = f"{label}の継続強化"
        body = (
            f"{label}時の勝率{round(wr*100)}%"
            f"（全体比{'+' if wr > baseline else ''}{round((wr - baseline) * 100)}%）。優先度高。"
        )
    else:
        title = f"{label}の改善余地"
        body = f"{label}時の勝率{round(wr*100)}%。伸びしろあり。"

    return {
        "category": category,
        "key": key,
        "title": title,
        "body": body,
        "priority_score": score,
        "sample_size": count,
        "confidence_level": confidence_level,
        "win_rate": round(wr, 3),
        "baseline": round(baseline, 3),
        "delta_from_baseline": round(wr - baseline, 3),
    }


def rank_recommendations(items: list[dict], top_n: int = 7) -> list[dict]:
    """
    推奨アドバイスを優先度スコア降順でソートし、rank を付与する。

    Parameters:
        items:  build_recommendation_item() の結果リスト (None 除外済み)
        top_n:  返す件数上限

    Returns:
        [{rank: 1, ...}, {rank: 2, ...}, ...]
    """
    sorted_items = sorted(items, key=lambda x: -x["priority_score"])
    return [{"rank": i + 1, **item} for i, item in enumerate(sorted_items[:top_n])]
