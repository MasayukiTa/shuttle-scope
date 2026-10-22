"""live_coach.py — ライブコーチダッシュボード強化エンドポイント

提供エンドポイント:
- GET /api/analysis/live_anomaly       — 直近 N ラリーの "ふだんと違う" 検知
- GET /api/analysis/live_suggestions   — インターバル戦術提案 Top 3

設計方針:
- coach / analyst / admin のみ。player には絶対に公開しない（弱点露出になり得るため）。
- "弱点 / weakness" 表現は禁止。観測事実 (何がどちらへ何ポイント動いたか・N) だけを中立に書く。原因や相手の意図は書かない。
- 全レスポンスに confidence (0..1) を載せる。
- データ不足時は anomaly=false / suggestions=[] を返し、UI 側で banner / strip を隠す。
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.analysis.role_view import own_slot
from backend.analysis.shot_taxonomy import canonicalize, ja_label
from backend.db.database import get_db
from backend.db.models import Match, GameSet, Rally, Stroke
from backend.utils.auth import AuthCtx, get_auth
from backend.utils.confidence import VERDICT_MIN_SAMPLE
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
        if target_role is not None and s.player != own_slot(target_role):
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
        if role is None or s.player != own_slot(role):
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
    n_rallies = len(recent_rallies)
    delta_abs = abs(primary[1])
    went_up = primary[1] >= 0
    # 表示名は shot_taxonomy の既存対応表 (SHOT_TYPE_JA) を使う。内部キーは文面に出さない。
    shot_ja = ja_label(primary[0])
    shot_en = canonicalize(primary[0]).replace("_", " ")

    # 観測した事実だけを書く (向き・大きさ・直近ラリー数 N)。
    # 原因や相手の意図は、検定の裏づけが無いので書かない。
    headline_ja = (
        f"直近{n_rallies}ラリー(N={n_rallies})で、{shot_ja}の比率が"
        f"普段より{delta_abs}ポイント{'高く' if went_up else '低く'}なっています。"
    )
    headline_en = (
        f"In the last {n_rallies} rallies (N={n_rallies}), the share of {shot_en} "
        f"was {delta_abs} points {'higher' if went_up else 'lower'} than usual."
    )

    # confidence: 手置きの式 (KL / 上限 * 観測量での減衰)。確率ではないので
    # 画面には出さない (UI は evidence の標本数 N を表示する)。互換のため値は残す。
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
                {"shot_type": st, "shot_key": canonicalize(st), "delta_pp": dp, "recent_n": n}
                for st, dp, n in diffs[:5]
            ],
            "primary_shot": primary[0],
            "primary_direction": "up" if went_up else "down",
        },
    }


# ─────────────────────────── Feature 2: live_suggestions ─────────────────

_BANNED_TERMS = ("弱点", "weakness")

# 提案の対象にできないショット。
#   other / cant_reach : 打ち手が選べる行為ではない (分類外・届かなかった球)。
#   short_service / long_service : 選べるのは自分のサーブ権があるときだけで、
#     この提案は直前の状態 (誰のサーブか) を持たない。lift も「サーブ権を持つ
#     ラリー」に偏るので、そのまま並べると実行できない助言になる。
_NOT_SUGGESTIBLE_SHOTS = frozenset({"other", "cant_reach", "short_service", "long_service"})


def _safe(text: str) -> str:
    """player 安全用語ガード (coach 向けでも一応排除)。"""
    out = text
    for w in _BANNED_TERMS:
        out = out.replace(w, "研究されやすい点")
    return out


def _sufficiency_score(n: int, *, cap: float) -> float:
    """データ量の単調増加スコア (0〜cap)。**確率ではない。**

    n が VERDICT_MIN_SAMPLE 未満なら 0.5 未満、ちょうど VERDICT_MIN_SAMPLE で 0.5、
    n=30 で cap。以前は下限が 0.5 で、呼び出し側の `conf < 0.5` の足切りが一度も効かなかった。

    D-5: 旧来この値は `confidence` という名前で返り、画面では
    「信頼度 NN%」として描かれていた。中身は N を 0.5〜0.95 に写す
    手置きの式で、**NN という数に対応する事象が存在しない**。

    並べ替え・足切りのように単調性だけが要る用途に留めること。
    画面に出す信頼度が要るなら `backend/utils/confidence.py` の
    `check_confidence` (閾値が文書化されていて星と警告文を返す) を使う。
    """
    n = max(n, 0)
    if n < VERDICT_MIN_SAMPLE:
        return round(0.5 * n / VERDICT_MIN_SAMPLE, 3)
    return round(min(0.5 + min(n - VERDICT_MIN_SAMPLE, 25) / 50.0, cap), 3)


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
            if s.player != own_slot(target_role):
                continue
            # 表記ゆれは canonical に寄せ、提案できないショットは集計から外す。
            st = canonicalize(s.shot_type or "")
            if st in _NOT_SUGGESTIBLE_SHOTS:
                continue
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
            if n < VERDICT_MIN_SAMPLE:
                continue
            wr = len(d["wins"]) / n
            lift_pp = (wr - overall_wr) * 100
            shot_stats.append((st, wr, lift_pp, n, len(d["wins"])))

        # 高 lift ショット → 推奨「もっと使う」
        shot_stats.sort(key=lambda x: -x[2])
        for st, wr, lift_pp, n, n_won in shot_stats[:3]:
            if lift_pp < 5.0:
                continue
            # D-5: これは **確率ではない**。N の単調増加関数で、0.5〜0.95 に
            # 収まるよう手で置いた式。「信頼度 NN%」として画面に出してはいけない
            # (IntervalSuggestionsStrip の % 表示は撤去済み)。
            # 並べ替えと足切りにだけ使う。標本数は headline の N=... が持つ。
            conf = _sufficiency_score(n, cap=0.95)
            if conf < 0.5:
                continue
            items.append({
                "id": f"use_more_{st}",
                "headline_ja": _safe(
                    f"{ja_label(st)}を使った{n}ラリー中{n_won}ラリーで得点"
                    f"（全体より{lift_pp:.1f}ポイント高い）。使う場面を増やす余地があります。"
                ),
                "headline_en": _safe(
                    f"Rallies with {st.replace('_', ' ')}: points won in {n_won} of {n} "
                    f"({lift_pp:.1f} points above the overall rate). Room to use it more."
                ),
                "confidence": round(conf, 3),
                "evidence_path": f"counterfactual_shots#shot={st}",
            })

        # 低 lift ショット → 「代わりに別の手」
        shot_stats.sort(key=lambda x: x[2])
        for st, wr, lift_pp, n, n_won in shot_stats[:2]:
            if lift_pp > -5.0:
                continue
            # 代替候補: lift 最大ショット (shot_stats は提案できるショットだけ)
            alt_list = [s for s in shot_stats if s[2] > 0 and s[0] != st]
            alt = alt_list[-1] if alt_list else None
            alt_label_ja = ja_label(alt[0]) if alt else "別のショット"
            alt_label_en = alt[0].replace("_", " ") if alt else "another shot"
            conf = _sufficiency_score(n, cap=0.9)  # 確率ではない。上のコメント参照
            if conf < 0.5:
                continue
            items.append({
                "id": f"swap_{st}",
                "headline_ja": _safe(
                    f"{ja_label(st)}を使った{n}ラリー中{n_won}ラリーで得点"
                    f"（全体より{abs(lift_pp):.1f}ポイント低い）。{alt_label_ja}を試す余地があります。"
                ),
                "headline_en": _safe(
                    f"Rallies with {st.replace('_', ' ')}: points won in {n_won} of {n} "
                    f"({abs(lift_pp):.1f} points below the overall rate). "
                    f"Room to try {alt_label_en} instead."
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
