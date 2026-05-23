"""live_coach.py — ライブコーチダッシュボード強化エンドポイント

提供エンドポイント:
- GET /api/analysis/live_anomaly       — 直近 N ラリーの "ふだんと違う" 検知
- GET /api/analysis/live_suggestions   — インターバル戦術提案 Top 3

設計方針:
- coach / analyst / admin のみ。player には絶対に公開しない（弱点露出になり得るため）。
- "弱点 / weakness" 表現は禁止。中立的な「研究されている可能性」「試す価値あり」表現に統一。
- 全レスポンスに confidence (0..1) を載せる。
- データ不足時は anomaly=false / suggestions=[] を返し、UI 側で banner / strip を隠す。
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Match, GameSet, Rally, Stroke
from backend.utils.auth import AuthCtx, get_auth
from backend.analysis.router_helpers import (
    _fetch_matches_sets_rallies,
    _player_role_in_match,
)

router = APIRouter()


# ─────────────────────────── 権限ガード ───────────────────────────────────

_ALLOWED_ROLES = {"coach", "analyst", "admin"}


def _require_coach_or_higher(ctx: AuthCtx) -> None:
    """player / demo / 未認証は 403。"""
    if ctx.role is None:
        raise HTTPException(status_code=401, detail="auth required")
    if ctx.role not in _ALLOWED_ROLES:
        raise HTTPException(status_code=403, detail="forbidden")


# ─────────────────────────── ヘルパ ───────────────────────────────────────

def _shot_distribution(strokes: list[Stroke], target_role: Optional[str]) -> Counter:
    """対象選手のショット種別ヒストグラム。"""
    c: Counter = Counter()
    for s in strokes:
        if target_role is not None and s.player != target_role:
            continue
        st = (s.shot_type or "unknown").lower()
        c[st] += 1
    return c


def _kl_divergence(p: dict[str, float], q: dict[str, float]) -> float:
    """KL(p || q). ラプラス平滑で 0 割回避。"""
    keys = set(p) | set(q)
    eps = 1e-6
    total_p = sum(p.values()) + eps * len(keys)
    total_q = sum(q.values()) + eps * len(keys)
    div = 0.0
    for k in keys:
        pk = (p.get(k, 0.0) + eps) / total_p
        qk = (q.get(k, 0.0) + eps) / total_q
        div += pk * math.log(pk / qk)
    return div


# ─────────────────────────── Feature 1: live_anomaly ─────────────────────

@router.get("/analysis/live_anomaly")
def get_live_anomaly(
    player_id: int = Query(..., ge=1, le=2_147_483_647),
    match_id: int = Query(..., ge=1, le=2_147_483_647),
    window: int = Query(5, ge=1, le=50),
    db: Session = Depends(get_db),
    ctx: AuthCtx = Depends(get_auth),
) -> dict:
    """直近 `window` ラリーが季節ベースラインから乖離していたら anomaly=true を返す。

    - chi-square / KL 発散をベースに判定（KL を採用）
    - 各セル N >= 3 かつ window 内ラリー >= 3 が最低条件
    - threshold: KL >= 0.25 で anomaly
    """
    _require_coach_or_higher(ctx)

    # ── 対象試合 + 直近 N ラリー
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="match not found")
    role_in_match = _player_role_in_match(match, player_id)
    if role_in_match is None:
        return {"anomaly": False, "reason": "player_not_in_match",
                "confidence": 0.0, "evidence": {}}

    sets = db.query(GameSet).filter(GameSet.match_id == match_id).all()
    set_ids = [s.id for s in sets]
    if not set_ids:
        return {"anomaly": False, "reason": "no_sets", "confidence": 0.0, "evidence": {}}

    recent_rallies = (
        db.query(Rally)
        .filter(Rally.set_id.in_(set_ids), Rally.is_skipped == False)  # noqa: E712
        .order_by(Rally.set_id.desc(), Rally.rally_num.desc())
        .limit(window)
        .all()
    )
    if len(recent_rallies) < 3:
        return {"anomaly": False, "reason": "insufficient_window",
                "confidence": 0.0, "evidence": {"window_rallies": len(recent_rallies)}}

    recent_rally_ids = [r.id for r in recent_rallies]
    recent_strokes = db.query(Stroke).filter(Stroke.rally_id.in_(recent_rally_ids)).all()
    recent_dist = _shot_distribution(recent_strokes, role_in_match)

    if sum(recent_dist.values()) < 3:
        return {"anomaly": False, "reason": "insufficient_strokes",
                "confidence": 0.0, "evidence": {"recent_strokes": sum(recent_dist.values())}}

    # ── 季節ベースライン: この選手の全試合ストローク
    _, role_by_match, _, _, base_rallies, _ = _fetch_matches_sets_rallies(player_id, db)
    base_rally_ids = [r.id for r in base_rallies]
    base_strokes_all = (
        db.query(Stroke).filter(Stroke.rally_id.in_(base_rally_ids)).all()
        if base_rally_ids else []
    )

    # rally → role mapping (across matches)
    rally_to_role: dict[int, Optional[str]] = {}
    set_to_match_local = {gs.id: gs.match_id for gs in
                          db.query(GameSet).filter(
                              GameSet.match_id.in_(list(role_by_match.keys()))
                          ).all()}
    for r in base_rallies:
        rally_to_role[r.id] = role_by_match.get(set_to_match_local.get(r.set_id))

    baseline_dist: Counter = Counter()
    for s in base_strokes_all:
        role = rally_to_role.get(s.rally_id)
        if role is None or s.player != role:
            continue
        st = (s.shot_type or "unknown").lower()
        baseline_dist[st] += 1

    if sum(baseline_dist.values()) < 20:
        # ベースライン不十分
        return {"anomaly": False, "reason": "insufficient_baseline",
                "confidence": 0.0,
                "evidence": {"baseline_strokes": sum(baseline_dist.values())}}

    # cell-min: 直近 dist の最大カテゴリだけ評価
    top_recent_shot, top_recent_n = recent_dist.most_common(1)[0]
    if top_recent_n < 3:
        return {"anomaly": False, "reason": "insufficient_cell",
                "confidence": 0.0, "evidence": {"top_recent": top_recent_n}}

    # ── KL divergence
    p = dict(recent_dist)
    q = dict(baseline_dist)
    kl = _kl_divergence(p, q)

    threshold = 0.25
    if kl < threshold:
        return {"anomaly": False, "reason": "no_divergence",
                "confidence": round(min(kl / threshold, 1.0), 3),
                "evidence": {"kl": round(kl, 4), "threshold": threshold}}

    # ── 主因ショットの比率変化
    recent_total = sum(recent_dist.values())
    base_total = sum(baseline_dist.values())
    diffs = []
    for st in set(p) | set(q):
        pr = recent_dist.get(st, 0) / recent_total
        br = baseline_dist.get(st, 0) / base_total
        diffs.append((st, round((pr - br) * 100, 1), recent_dist.get(st, 0)))
    diffs.sort(key=lambda x: -abs(x[1]))
    primary = diffs[0]
    pct_label = f"{'+' if primary[1] >= 0 else ''}{primary[1]}pp"

    headline_ja = (
        f"直近{len(recent_rallies)}ラリーで {primary[0]} 比率が普段の {pct_label}。"
        "相手に研究されている可能性があります。"
    )
    headline_en = (
        f"In last {len(recent_rallies)} rallies, {primary[0]} share shifted {pct_label} vs season baseline. "
        "The opponent may be reading this pattern."
    )

    # confidence: KL / 上限 * 観測量での減衰
    raw_conf = min(kl / (threshold * 4), 1.0)
    n_factor = min(recent_total / 30.0, 1.0)
    confidence = round(raw_conf * (0.6 + 0.4 * n_factor), 3)

    return {
        "anomaly": True,
        "headline_ja": headline_ja,
        "headline_en": headline_en,
        "confidence": confidence,
        "evidence": {
            "kl": round(kl, 4),
            "threshold": threshold,
            "window_rallies": len(recent_rallies),
            "recent_strokes": recent_total,
            "baseline_strokes": base_total,
            "shot_diffs_pp": [
                {"shot_type": st, "delta_pp": dp, "recent_n": n}
                for st, dp, n in diffs[:5]
            ],
            "primary_shot": primary[0],
        },
    }


# ─────────────────────────── Feature 2: live_suggestions ─────────────────

_BANNED_TERMS = ("弱点", "weakness")


def _safe(text: str) -> str:
    """player 安全用語ガード (coach 向けでも一応排除)。"""
    out = text
    for w in _BANNED_TERMS:
        out = out.replace(w, "研究されやすい点")
    return out


@router.get("/analysis/live_suggestions")
def get_live_suggestions(
    player_id: int = Query(..., ge=1, le=2_147_483_647),
    match_id: int = Query(..., ge=1, le=2_147_483_647),
    db: Session = Depends(get_db),
    ctx: AuthCtx = Depends(get_auth),
) -> dict:
    """インターバル戦術提案 (Top 3)。

    現状: counterfactual lift と直近 anomaly を簡易に合成し、ヒューリスティック
    で 1..3 個の提案を返す。confidence>=0.5 のみ。
    """
    _require_coach_or_higher(ctx)

    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="match not found")
    target_role = _player_role_in_match(match, player_id)
    if target_role is None:
        return {"items": [], "reason": "player_not_in_match", "meta": {"min_confidence": 0.5}}

    sets = db.query(GameSet).filter(GameSet.match_id == match_id).all()
    set_ids = [s.id for s in sets]
    rallies = (
        db.query(Rally)
        .filter(Rally.set_id.in_(set_ids), Rally.is_skipped == False)  # noqa: E712
        .all()
        if set_ids else []
    )

    items: list[dict] = []

    if rallies:
        rally_ids = [r.id for r in rallies]
        strokes = db.query(Stroke).filter(Stroke.rally_id.in_(rally_ids)).all()
        # rally outcome
        rally_won = {r.id: (r.winner == target_role) for r in rallies}

        # shot -> (rallies, wins)
        agg: dict[str, dict[str, set]] = defaultdict(lambda: {"rallies": set(), "wins": set()})
        for s in strokes:
            if s.player != target_role:
                continue
            st = (s.shot_type or "unknown").lower()
            agg[st]["rallies"].add(s.rally_id)
            if rally_won.get(s.rally_id):
                agg[st]["wins"].add(s.rally_id)

        # 全体勝率
        total_rallies = len(rallies)
        total_wins = sum(1 for r in rallies if rally_won.get(r.id))
        overall_wr = total_wins / total_rallies if total_rallies else 0.0

        # 各 shot の lift: 個別勝率 - 全体勝率
        shot_stats = []
        for st, d in agg.items():
            n = len(d["rallies"])
            if n < 5:
                continue
            wr = len(d["wins"]) / n
            lift_pp = (wr - overall_wr) * 100
            shot_stats.append((st, wr, lift_pp, n))

        # 高 lift ショット → 推奨「もっと使う」
        shot_stats.sort(key=lambda x: -x[2])
        for st, wr, lift_pp, n in shot_stats[:3]:
            if lift_pp < 5.0:
                continue
            conf = min(0.5 + min(n, 30) / 60.0, 0.95)
            if conf < 0.5:
                continue
            items.append({
                "id": f"use_more_{st}",
                "headline_ja": _safe(
                    f"{st} を積極的に使う価値あり (lift +{lift_pp:.1f}pp / N={n})"
                ),
                "headline_en": _safe(
                    f"Consider leaning on {st} (lift +{lift_pp:.1f}pp, N={n})"
                ),
                "confidence": round(conf, 3),
                "evidence_path": f"counterfactual_shots#shot={st}",
            })

        # 低 lift ショット → 「代わりに別の手」
        shot_stats.sort(key=lambda x: x[2])
        for st, wr, lift_pp, n in shot_stats[:2]:
            if lift_pp > -5.0:
                continue
            # 代替候補: lift 最大ショット
            alt_list = [s for s in shot_stats if s[2] > 0 and s[0] != st]
            alt = alt_list[-1] if alt_list else None
            alt_label = alt[0] if alt else "別のショット"
            conf = min(0.5 + min(n, 30) / 60.0, 0.9)
            if conf < 0.5:
                continue
            items.append({
                "id": f"swap_{st}",
                "headline_ja": _safe(
                    f"{st} の代わりに {alt_label} を試す価値あり (lift {lift_pp:.1f}pp)"
                ),
                "headline_en": _safe(
                    f"Consider {alt_label} instead of {st} (lift {lift_pp:.1f}pp)"
                ),
                "confidence": round(conf, 3),
                "evidence_path": f"counterfactual_shots#shot={st}",
            })

    # confidence 順 + Top 3
    items.sort(key=lambda x: -x["confidence"])
    items = items[:3]

    return {
        "items": items,
        "meta": {
            "min_confidence": 0.5,
            "match_id": match_id,
            "player_id": player_id,
            "disclaimer": "coach-facing tactical suggestions; not for player display",
        },
    }
