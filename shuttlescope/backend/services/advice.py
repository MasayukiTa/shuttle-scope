"""アドバイス (示唆) の生成サービス。

信頼性の絶対原則:
  1. 推測やテンプレ文を出さない。必ず実データから計算した数値・観測のみ。
  2. 各 advice は basis (source / sample_size / period) を明示で持つ。
  3. サンプル不足なら advice 自体を返さない (「計測中」を出す)。
       — 「それっぽいことを書く」のが最も信用を毀損する。
  4. player ロールは数値そのまま + 伸びしろ表現 (CLAUDE.md 非交渉)。

各 context 関数は AdviceCard | None を返す。None なら「データ不足、計測中」を
フロント側で表示する。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, date as DateType, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.utils.auth import AuthCtx


@dataclass
class AdviceCard:
    """1 件のアドバイス。

    text は必ず実データから組み立てた文字列。
    basis に source / sample_size / period を入れて、ユーザが根拠を辿れるようにする。
    confidence は "high" / "medium" / "low" の 3 段階のみ (insufficient は別途扱い)。
    """
    text: str
    basis: dict[str, Any] = field(default_factory=dict)
    confidence: str = "medium"  # "high" | "medium" | "low"
    severity: str = "info"      # "info" | "positive" | "warning"
    # フロント描画のヒント (任意): 「詳細を見る」リンクの遷移先など
    cta: Optional[dict[str, str]] = None


def _empty_response(reason: str, period: Optional[str] = None) -> dict:
    """サンプル不足等で advice が出せない場合の素直な応答。

    text を 「それっぽい示唆」 で埋めず、「計測中」と明言する。
    """
    return {
        "success": True,
        "advice": None,
        "status": "insufficient_data",
        "reason": reason,
        "period": period,
    }


def _ok_response(card: AdviceCard) -> dict:
    return {
        "success": True,
        "advice": asdict(card),
        "status": "ok",
    }


# ─────────────────────────────────────────────────────────────────────
# ヘルパー: 直近期間の試合 + ラリー集計
# ─────────────────────────────────────────────────────────────────────

def _gather_window(db: Session, player_id: int, days: int) -> dict:
    """指定日数の試合・ラリーを集計して返す。

    返り値:
      {
        "match_count": int,
        "rally_count": int,
        "wins": int,
        "losses": int,
        "win_rate": float | None,  # None なら計算不能
        "primary_shot": (shot_type, count, ratio) | None,
        "from_date": date,
        "to_date": date,
      }
    """
    from backend.db.models import Match, GameSet, Rally, Stroke
    today = DateType.today()
    from_d = today - timedelta(days=days)

    matches = (
        db.query(Match)
        .filter(
            (Match.player_a_id == player_id) | (Match.player_b_id == player_id),
            Match.date >= from_d,
            Match.date <= today,
            Match.deleted_at.is_(None),
        )
        .all()
    )
    if not matches:
        return {
            "match_count": 0, "rally_count": 0,
            "wins": 0, "losses": 0, "win_rate": None,
            "primary_shot": None, "from_date": from_d, "to_date": today,
        }

    # ロール判定 (player_a or player_b)
    def _role(m: Match) -> str:
        return "player_a" if m.player_a_id == player_id else "player_b"

    role_by_mid = {m.id: _role(m) for m in matches}
    mids = [m.id for m in matches]
    sets = db.query(GameSet).filter(GameSet.match_id.in_(mids)).all()
    sid_to_mid = {s.id: s.match_id for s in sets}
    sids = [s.id for s in sets]
    rallies = db.query(Rally).filter(Rally.set_id.in_(sids)).all() if sids else []

    wins = sum(1 for r in rallies if r.winner == role_by_mid.get(sid_to_mid.get(r.set_id)))
    rcount = len(rallies)
    losses = rcount - wins
    win_rate = (wins / rcount) if rcount else None

    # ショット集計 (自分の打った)
    primary_shot = None
    if rallies:
        rids = [r.id for r in rallies]
        rid_to_role = {r.id: role_by_mid.get(sid_to_mid.get(r.set_id)) for r in rallies}
        strokes = db.query(Stroke).filter(Stroke.rally_id.in_(rids)).all() if rids else []
        from collections import Counter
        c: Counter[str] = Counter()
        for s in strokes:
            if s.shot_type and s.player == rid_to_role.get(s.rally_id):
                c[s.shot_type] += 1
        if c:
            most, cnt = c.most_common(1)[0]
            total = sum(c.values())
            primary_shot = (most, cnt, cnt / total if total else 0.0)

    return {
        "match_count": len(matches), "rally_count": rcount,
        "wins": wins, "losses": losses,
        "win_rate": win_rate, "primary_shot": primary_shot,
        "from_date": from_d, "to_date": today,
    }


# ─────────────────────────────────────────────────────────────────────
# Context 1: dashboard.overview
# ─────────────────────────────────────────────────────────────────────

# 最低必要試合数。これ未満は advice を出さない (= 計測中扱い)。
MIN_MATCHES = 3
MIN_RALLIES = 60


def advice_dashboard_overview(db: Session, player_id: int, ctx: AuthCtx) -> dict:
    """直近 30 日 + その前 30 日の事実観測のみ。

    判断はしない (「強化すべき」「期待できる」等の主観表現を避ける)。
    数字をそのまま提示し、ユーザに判断材料を渡す。
    """
    cur = _gather_window(db, player_id, days=30)
    prev = _gather_window(db, player_id, days=60)
    # prev は直近 30〜60 日を取り出す
    prev_only_match = prev["match_count"] - cur["match_count"]
    prev_only_rally = prev["rally_count"] - cur["rally_count"]

    if cur["match_count"] < MIN_MATCHES or cur["rally_count"] < MIN_RALLIES:
        return _empty_response(
            f"直近 30 日の試合数が {cur['match_count']} 件、ラリー数が {cur['rally_count']} 件です。"
            f"傾向判定には最低 {MIN_MATCHES} 試合 / {MIN_RALLIES} ラリーが必要です。",
            period=f"{cur['from_date']} ~ {cur['to_date']}",
        )

    parts = []
    # 1. ラリー勝率の事実
    if cur["win_rate"] is not None:
        wr_pct = round(cur["win_rate"] * 100, 1)
        parts.append(f"直近 30 日のラリー勝率は {wr_pct}% (試合 {cur['match_count']} / ラリー {cur['rally_count']})")
    # 2. 前 30 日比 (両期間とも閾値を満たす場合のみ)
    delta_str = None
    if prev_only_match >= MIN_MATCHES and prev_only_rally >= MIN_RALLIES:
        # 直近 30 日とその前 30 日のラリー勝率を分けて再計算
        prev_wr = (prev["wins"] - cur["wins"]) / prev_only_rally if prev_only_rally else None
        if prev_wr is not None and cur["win_rate"] is not None:
            delta_pp = (cur["win_rate"] - prev_wr) * 100
            sign = "+" if delta_pp >= 0 else ""
            delta_str = f"その前 30 日比 {sign}{delta_pp:.1f}pp"
            parts.append(delta_str)
    # 3. 最頻使用ショット (確定事実)
    if cur["primary_shot"]:
        st, cnt, ratio = cur["primary_shot"]
        parts.append(f"最頻ショットは {st} ({cnt} 本 / 全体の {round(ratio * 100, 1)}%)")

    # player ロールは「弱点」「不足」を出さない方針
    if ctx.role == "player":
        # 自分目線の中立的観測のみ。改善の方向性は数字から自分で気づける程度に。
        text = " / ".join(parts) + "。直近の試合を振り返るとき、これらの数字を起点にしてみてください。"
    else:
        text = " / ".join(parts) + "。"

    confidence = "high" if cur["match_count"] >= 10 and cur["rally_count"] >= 300 else "medium"
    return _ok_response(AdviceCard(
        text=text,
        basis={
            "source": "rally_aggregate_30d",
            "period": f"{cur['from_date']} ~ {cur['to_date']}",
            "sample_size": {"matches": cur["match_count"], "rallies": cur["rally_count"]},
            "delta_basis": "対直前 30 日" if delta_str else None,
        },
        confidence=confidence,
        severity="info",
    ))


# ─────────────────────────────────────────────────────────────────────
# Context 2: post_match_save (試合保存直後)
# ─────────────────────────────────────────────────────────────────────

def advice_post_match_save(db: Session, player_id: int, match_id: int, ctx: AuthCtx) -> dict:
    """保存直後の試合に対する事実観測。

    生成する数字は本試合のものだけ + ベースライン (player の直近 30 日平均) との
    対比。判断 (「もっと攻めるべき」など) は一切しない。
    """
    from backend.db.models import Match, GameSet, Rally, Stroke
    m = db.get(Match, match_id)
    if not m or (m.player_a_id != player_id and m.player_b_id != player_id):
        return _empty_response("対象試合が見つかりません。")

    role = "player_a" if m.player_a_id == player_id else "player_b"
    sets = db.query(GameSet).filter(GameSet.match_id == match_id).all()
    sids = [s.id for s in sets]
    rallies = db.query(Rally).filter(Rally.set_id.in_(sids)).all() if sids else []
    if len(rallies) < 10:
        return _empty_response(
            f"本試合のラリー数が {len(rallies)} と少ないため、観測値は省略します。"
        )
    wins = sum(1 for r in rallies if r.winner == role)
    wr = wins / len(rallies)

    # 自分のショット集計
    rids = [r.id for r in rallies]
    strokes = db.query(Stroke).filter(Stroke.rally_id.in_(rids)).all() if rids else []
    from collections import Counter
    own = Counter()
    for s in strokes:
        if s.shot_type and s.player == role:
            own[s.shot_type] += 1
    primary = None
    if own:
        st, cnt = own.most_common(1)[0]
        total = sum(own.values())
        primary = (st, cnt, cnt / total if total else 0.0)

    # ベースライン: 直近 30 日平均 (本試合除外)
    base = _gather_window(db, player_id, days=30)
    base_wr = None
    if base["rally_count"] >= MIN_RALLIES:
        # 本試合分を差し引く
        base_rallies = max(0, base["rally_count"] - len(rallies))
        base_wins = max(0, base["wins"] - wins)
        if base_rallies > 0:
            base_wr = base_wins / base_rallies

    parts = [
        f"本試合のラリー勝率: {round(wr * 100, 1)}% ({wins}/{len(rallies)})",
    ]
    if base_wr is not None:
        diff = (wr - base_wr) * 100
        sign = "+" if diff >= 0 else ""
        parts.append(
            f"直近 30 日平均 {round(base_wr * 100, 1)}% との差 {sign}{diff:.1f}pp"
        )
    if primary:
        st, cnt, ratio = primary
        parts.append(f"最頻ショット: {st} ({cnt} 本 / {round(ratio * 100, 1)}%)")

    severity = "positive" if (base_wr is not None and wr > base_wr) else "info"
    text = " / ".join(parts) + "。"
    return _ok_response(AdviceCard(
        text=text,
        basis={
            "source": "post_match_save",
            "match_id": match_id,
            "sample_size": {"rallies": len(rallies)},
            "baseline": "player_30d_excluding_this" if base_wr is not None else None,
        },
        confidence="high" if len(rallies) >= 100 else "medium",
        severity=severity,
    ))


# ─────────────────────────────────────────────────────────────────────
# Context 3: condition.header
# ─────────────────────────────────────────────────────────────────────

def advice_condition_header(db: Session, player_id: int, ctx: AuthCtx) -> dict:
    """直近の体調入力から、事実観測のみを返す。

    判断 (「練習強度を落とすべき」等) は出さない。
    観測した値が「注意領域」かは閾値判定ではなく自然な数字提示。
    """
    from sqlalchemy import text as _sql_text
    # condition_master が無い環境では skip
    try:
        # 直近 7 日の DailyCondition を取得 (構造は条件付き)
        from backend.db.models import DailyCondition
    except ImportError:
        return _empty_response("体調モデルが利用できません。")

    cutoff = DateType.today() - timedelta(days=14)
    rows = (
        db.query(DailyCondition)
        .filter(
            DailyCondition.player_id == player_id,
            DailyCondition.target_date >= cutoff,
        )
        .order_by(DailyCondition.target_date.desc())
        .all()
    )
    if len(rows) < 3:
        return _empty_response(
            f"直近 14 日の体調入力が {len(rows)} 件です (傾向判定には 3 件以上必要)。"
        )

    # Hooper-like 集計 (fatigue / stress / mood / sleep 1-5)
    # responses_json または個別フィールドがある前提で安全に取り出す
    def _safe_get(r, key, default=None):
        v = getattr(r, key, None)
        if v is not None: return v
        # responses dict から
        rd = getattr(r, "responses", None) or getattr(r, "responses_json", None)
        if isinstance(rd, dict):
            return rd.get(key, default)
        return default

    latest = rows[0]
    sleep = _safe_get(latest, "sleep_score", None)
    fatigue = _safe_get(latest, "fatigue_score", None)
    parts = [f"直近 {len(rows)} 件の体調入力を取得 (最終: {latest.target_date.isoformat() if getattr(latest, 'target_date', None) else 'N/A'})"]
    if sleep is not None:
        parts.append(f"最新 sleep スコア {sleep}")
    if fatigue is not None:
        parts.append(f"最新 fatigue スコア {fatigue}")
    text = " / ".join(parts) + "。"
    return _ok_response(AdviceCard(
        text=text,
        basis={
            "source": "daily_condition_14d",
            "sample_size": {"entries": len(rows)},
        },
        confidence="medium" if len(rows) >= 5 else "low",
        severity="info",
    ))


# ─────────────────────────────────────────────────────────────────────
# Context 4: prediction.tab
# ─────────────────────────────────────────────────────────────────────

def advice_prediction_tab(db: Session, player_id: int, opponent_id: Optional[int], ctx: AuthCtx) -> dict:
    """対戦相手指定があれば head-to-head 勝率、無ければ直近の予測根拠サマリ。

    Player ロールには予測勝率の生数値は出さない (CLAUDE.md 規約)。
    """
    # Player ロールには予測タブそのものが原則出ないが、もし呼ばれた場合は安全に応答
    if ctx.role == "player":
        return _empty_response(
            "選手ロールでは予測タブの数値は表示しません (CLAUDE.md 規約)。"
        )

    if not opponent_id:
        # 対戦相手未指定 → 一般的な過去戦績の事実のみ
        cur = _gather_window(db, player_id, days=90)
        if cur["match_count"] < MIN_MATCHES:
            return _empty_response(
                f"直近 90 日の試合数が {cur['match_count']} 件です (予測根拠に 3 件以上必要)。"
            )
        text = (
            f"直近 90 日: 試合 {cur['match_count']} / ラリー {cur['rally_count']} を蓄積。"
            f"対戦相手を選択すると head-to-head 予測が出ます。"
        )
        return _ok_response(AdviceCard(
            text=text,
            basis={"source": "rally_aggregate_90d", "sample_size": cur["match_count"]},
            confidence="medium",
            severity="info",
            cta={"label": "対戦相手を選択", "action": "select_opponent"},
        ))

    # opponent_id 指定: head-to-head 実績のみ集計 (予測モデル呼び出しはエラー耐性が必要)
    from backend.db.models import Match, GameSet, Rally
    h2h = (
        db.query(Match)
        .filter(
            (
                ((Match.player_a_id == player_id) & (Match.player_b_id == opponent_id)) |
                ((Match.player_a_id == opponent_id) & (Match.player_b_id == player_id))
            ),
            Match.deleted_at.is_(None),
        )
        .all()
    )
    if len(h2h) == 0:
        return _empty_response(f"対戦相手 #{opponent_id} との対戦履歴がありません。")

    mids = [m.id for m in h2h]
    sets = db.query(GameSet).filter(GameSet.match_id.in_(mids)).all()
    sids = [s.id for s in sets]
    sid_to_mid = {s.id: s.match_id for s in sets}
    rallies = db.query(Rally).filter(Rally.set_id.in_(sids)).all() if sids else []
    role_by_mid = {m.id: ("player_a" if m.player_a_id == player_id else "player_b") for m in h2h}
    wins = sum(1 for r in rallies if r.winner == role_by_mid.get(sid_to_mid.get(r.set_id)))
    rcount = len(rallies)
    if rcount < 30:
        return _empty_response(
            f"対戦相手 #{opponent_id} との head-to-head ラリー数 {rcount} は予測根拠に不足 (30 以上必要)。"
        )
    h2h_wr = wins / rcount
    # 95% Wilson 区間
    from math import sqrt
    n, p = rcount, h2h_wr
    z = 1.96
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
    lo = max(0.0, center - half)
    hi = min(1.0, center + half)

    text = (
        f"対戦相手 #{opponent_id} との過去 {len(h2h)} 試合 ({rcount} ラリー) の"
        f"ラリー勝率: {round(h2h_wr * 100, 1)}% "
        f"(95% 信頼区間 [{round(lo * 100, 1)}%, {round(hi * 100, 1)}%])"
    )
    return _ok_response(AdviceCard(
        text=text,
        basis={
            "source": "head_to_head_wilson_ci",
            "match_count": len(h2h),
            "rally_count": rcount,
        },
        confidence="high" if rcount >= 200 else "medium",
        severity="info",
    ))


# ─────────────────────────────────────────────────────────────────────
# Context 5: growth.timeline
# ─────────────────────────────────────────────────────────────────────

def advice_growth_timeline(db: Session, player_id: int, ctx: AuthCtx) -> dict:
    """直近 8 週間 vs その前 8 週間のラリー勝率比較 (両期間が閾値を満たす場合のみ)。

    「成長」「改善」「向上」等の主観語は使わず、数字をそのまま提示する。
    player 向けには「伸びしろ」表現に揃える。
    """
    from backend.db.models import Match, GameSet, Rally
    today = DateType.today()
    a_from = today - timedelta(weeks=8)
    b_from = today - timedelta(weeks=16)
    b_to = a_from

    def _wr_in(from_d: DateType, to_d: DateType) -> tuple[Optional[float], int, int]:
        ms = (
            db.query(Match)
            .filter(
                (Match.player_a_id == player_id) | (Match.player_b_id == player_id),
                Match.date >= from_d, Match.date < to_d,
                Match.deleted_at.is_(None),
            )
            .all()
        )
        if not ms:
            return (None, 0, 0)
        role_by_mid = {m.id: ("player_a" if m.player_a_id == player_id else "player_b") for m in ms}
        mids = [m.id for m in ms]
        sets = db.query(GameSet).filter(GameSet.match_id.in_(mids)).all()
        sids = [s.id for s in sets]
        sid_to_mid = {s.id: s.match_id for s in sets}
        rs = db.query(Rally).filter(Rally.set_id.in_(sids)).all() if sids else []
        if len(rs) < MIN_RALLIES:
            return (None, len(ms), len(rs))
        wins = sum(1 for r in rs if r.winner == role_by_mid.get(sid_to_mid.get(r.set_id)))
        return (wins / len(rs), len(ms), len(rs))

    cur_wr, cur_m, cur_r = _wr_in(a_from, today)
    prev_wr, prev_m, prev_r = _wr_in(b_from, b_to)

    if cur_wr is None or prev_wr is None:
        return _empty_response(
            f"比較に十分なデータがありません (直近 8 週: 試合 {cur_m}/ラリー {cur_r}, "
            f"その前 8 週: 試合 {prev_m}/ラリー {prev_r}, 各期間で最低 {MIN_RALLIES} ラリー必要)。"
        )
    diff_pp = (cur_wr - prev_wr) * 100
    sign = "+" if diff_pp >= 0 else ""
    if ctx.role == "player":
        # 伸びしろ表現
        text = (
            f"直近 8 週のラリー勝率 {round(cur_wr * 100, 1)}% は、その前 8 週 ({round(prev_wr * 100, 1)}%) と"
            f"比較して {sign}{diff_pp:.1f}pp。試合 {cur_m} 件 / ラリー {cur_r} 件が集計対象です。"
        )
    else:
        text = (
            f"直近 8 週 vs その前 8 週: ラリー勝率 {round(cur_wr * 100, 1)}% → "
            f"{round(prev_wr * 100, 1)}% ({sign}{diff_pp:.1f}pp)。"
            f"サンプル: 直近 8 週 試合 {cur_m}/ラリー {cur_r}, その前 8 週 試合 {prev_m}/ラリー {prev_r}。"
        )
    return _ok_response(AdviceCard(
        text=text,
        basis={
            "source": "growth_8w_vs_8w",
            "sample_size": {
                "current": {"matches": cur_m, "rallies": cur_r},
                "previous": {"matches": prev_m, "rallies": prev_r},
            },
        },
        confidence="high" if cur_r >= 300 and prev_r >= 300 else "medium",
        severity="positive" if diff_pp > 0 else "info",
    ))


# ─────────────────────────────────────────────────────────────────────
# Context 6: player.home
# ─────────────────────────────────────────────────────────────────────

def advice_player_home(db: Session, player_id: int, ctx: AuthCtx) -> dict:
    """player ロール用の home strip。dashboard.overview を player 向け表現に。"""
    # dashboard.overview と同じ集計だが player 向けに揃える
    return advice_dashboard_overview(db, player_id, ctx)
