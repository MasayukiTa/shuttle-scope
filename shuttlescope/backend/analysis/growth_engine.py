"""
growth_engine.py — 成長解析エンジン (Stage 2-B)

改善点:
  - 全試合を等重み → 相手強度で重み付けした成長率を計算
  - 「弱い相手に勝った成長」と「強い相手に粘った成長」を区別できる
  - prediction の recent_form にも後から接続できる設計

相手強度の算出方針:
  1. Player.world_ranking が入っていれば使用（低ランク=強い）
  2. ない場合は DB 内の全試合勝率で推定
  3. 両方なければ強度は不明（None）。加重計算だけが中立重み NEUTRAL_STRENGTH を使い、
     画面・API には 0.5 を「強度」として出さない（n<3 の偽の中立値は統計ではない）

設計原則:
  - 全関数は純粋関数（副作用なし）
  - 非同期 DB 呼び出しなし（同期 SQLAlchemy セッション使用）
  - 既存レスポンスに strength_weighted_* フィールドを追加する形で後方互換
"""
from __future__ import annotations
from typing import Optional
from sqlalchemy.orm import Session

from backend.analysis.role_view import team_side
from backend.analysis.player_context import involves_player, opponent_player_id
from backend.analysis.analysis_population import is_decided_result
from backend.db.models import Match, GameSet, Rally, Player


# 相手強度が不明（world_ranking なし かつ 過去 3 試合未満）のとき、加重平均の「重み」にだけ
# 使う中立値。強度そのものとしては返さない（API には strength_weight=None で出る）。
NEUTRAL_STRENGTH = 0.5
# 勝率から相手強度を推定するのに必要な最小試合数
MIN_MATCHES_FOR_STRENGTH = 3


def _weight_of(strength: Optional[float]) -> float:
    """加重計算用の重み。強度不明（None）は中立重み。"""
    return NEUTRAL_STRENGTH if strength is None else strength


# ── 相手強度計算 ─────────────────────────────────────────────────────────────

def compute_opponent_strength(db: Session, opponent_id: int) -> Optional[float]:
    """
    相手選手の強度スコアを 0.0-1.0 の範囲で計算する。
    1.0 = 最強、0.0 = 最弱。算出できない（標本不足）ときは None。

    算出ロジック:
      1. world_ranking が 1-500 の範囲にある場合:
         strength = 1 - (rank - 1) / 499  （1位=1.0, 500位=0.0）
      2. ranking がない場合:
         DB 内の全試合勝率を使用（全試合 win/loss のみ）
      3. いずれもデータなしの場合: None（0.5 を強度として返さない）
    """
    player = db.get(Player, opponent_id)
    if player and player.world_ranking and 1 <= player.world_ranking <= 500:
        return round(1.0 - (player.world_ranking - 1) / 499, 4)

    # world_ranking なし → 過去試合の勝率から推定
    matches = (
        db.query(Match)
        .filter(
            involves_player(opponent_id),
            Match.result.in_(["win", "loss"]),
        )
        .all()
    )
    if len(matches) < MIN_MATCHES_FOR_STRENGTH:
        return None  # サンプル不足: 偽の中立値 0.5 を強度として返さない

    wins = sum(
        1 for m in matches
        if (m.player_a_id == opponent_id and m.result == "win")
        or (m.player_b_id == opponent_id and m.result == "loss")
    )
    return round(wins / len(matches), 4)


def build_strength_cache(
    db: Session,
    matches: list[Match],
    player_id: int,
) -> dict[int, Optional[float]]:
    """
    対戦相手 ID ごとの強度スコアをまとめて計算してキャッシュ dict を返す。
    N+1 を防ぐために一度に処理する。
    """
    opp_ids: set[int] = set()
    for m in matches:
        opp = opponent_player_id(m, player_id)
        if opp is not None:
            opp_ids.add(opp)

    return {opp_id: compute_opponent_strength(db, opp_id) for opp_id in opp_ids}


# ── 重み付き指標計算 ─────────────────────────────────────────────────────────

def weighted_win_rate(
    matches: list[Match],
    player_id: int,
    strength_cache: dict[int, Optional[float]],
) -> Optional[float]:
    """
    相手強度で重み付けした勝率を計算する。

    weighted_wins = Σ(strength_i × won_i)
    weighted_total = Σ(strength_i)
    weighted_wr = weighted_wins / weighted_total

    強い相手への勝利: 高重みで勝利に貢献
    弱い相手への敗戦: 低重みで影響小

    Returns:
        重み付き勝率 (0.0-1.0)、計算不能な場合は None
    """
    total_weight = 0.0
    weighted_wins = 0.0

    for m in matches:
        if m.result not in ("win", "loss"):
            continue
        # result は A 側 (player_a と partner_a) から見た勝敗。相方も同じチームの側で判定する
        opp_id = opponent_player_id(m, player_id)
        won = (m.result == "win") == (team_side(m, player_id) == "player_a")

        strength = _weight_of(strength_cache.get(opp_id))
        total_weight += strength
        if won:
            weighted_wins += strength

    if total_weight < 0.01:
        return None
    return round(weighted_wins / total_weight, 4)


def growth_points_weighted(
    matches: list[Match],
    player_id: int,
    db: Session,
    metric: str = "win_rate",
    provenance_rows: Optional[dict[str, list]] = None,
) -> list[dict]:
    """
    時系列の各試合について、通常指標と相手強度補正済み指標の両方を計算する。

    Parameters:
        matches:   試合一覧（日付昇順推奨）
        player_id: 対象選手 ID
        db:        DB セッション
        metric:    'win_rate' / 'serve_win_rate' / 'avg_rally_length'

    Returns:
        [
          {
            "match_id": int,
            "date": str,
            "value": float,              # 通常指標
            "rally_count": int,          # value の母数（この試合で集計したラリー数）
            "strength_weight": float|None,  # 相手強度 (0-1)。標本不足は None
            "opponent_id": int,
            "strength_insufficient": True,  # 強度が None のときだけ付く
          }, ...
        ]
    """
    strength_cache = build_strength_cache(db, matches, player_id)
    points: list[dict] = []
    if provenance_rows is not None:
        provenance_rows.setdefault("rallies", [])

    # バルクロード: 全試合ぶんの GameSet / Rally を1クエリずつで取得（N+1 排除）
    match_ids = [m.id for m in matches]
    sets_by_match: dict[int, list[int]] = {}
    if match_ids:
        for s in db.query(GameSet.id, GameSet.match_id).filter(GameSet.match_id.in_(match_ids)).all():
            sets_by_match.setdefault(s.match_id, []).append(s.id)
    all_set_ids = [sid for sids in sets_by_match.values() for sid in sids]
    rallies_by_set: dict[int, list] = {}
    if all_set_ids:
        for r in db.query(Rally).filter(Rally.set_id.in_(all_set_ids)).all():
            rallies_by_set.setdefault(r.set_id, []).append(r)

    for m in matches:
        # 勝敗未確定の試合 (unfinished / walkover) は成長の点にしない (analysis_population)
        if not is_decided_result(m.result):
            continue
        role = team_side(m, player_id)
        opp_id = opponent_player_id(m, player_id)

        set_ids = sets_by_match.get(m.id, [])
        if not set_ids:
            continue
        rallies = [r for sid in set_ids for r in rallies_by_set.get(sid, [])]
        if not rallies:
            continue

        if metric == "win_rate":
            wins = sum(1 for r in rallies if r.winner == role)
            value = round(wins / len(rallies), 4)
            used_rallies = rallies

        elif metric == "serve_win_rate":
            serve_rallies = [r for r in rallies if r.server == role]
            if not serve_rallies:
                continue
            value = round(
                sum(1 for r in serve_rallies if r.winner == role) / len(serve_rallies), 4
            )
            used_rallies = serve_rallies

        elif metric == "avg_rally_length":
            value = round(sum(r.rally_length for r in rallies) / len(rallies), 2)
            used_rallies = rallies

        else:
            continue

        if provenance_rows is not None:
            provenance_rows["rallies"].extend(used_rallies)

        strength = strength_cache.get(opp_id)
        point = {
            "match_id": m.id,
            "date": str(m.date),
            "value": value,
            "rally_count": len(used_rallies),
            "strength_weight": strength,
            "opponent_id": opp_id,
        }
        if strength is None:
            point["strength_insufficient"] = True
        points.append(point)

    return points


def strength_weighted_moving_avg(
    points: list[dict],
    window_size: int = 3,
) -> list[dict]:
    """
    各ポイントについて strength_weight を加味した移動平均を計算する。

    通常の移動平均に加え、相手強度重み付き移動平均も付与する。

    Returns:
        points に "moving_avg" と "weighted_moving_avg" を追加したリスト
    """
    result = [dict(p) for p in points]
    n = len(result)

    for i in range(n):
        if i + 1 >= window_size:
            window = result[i + 1 - window_size : i + 1]
            # 通常移動平均
            result[i]["moving_avg"] = round(
                sum(p["value"] for p in window) / window_size, 4
            )
            # 強度重み付き移動平均
            total_w = sum(_weight_of(p.get("strength_weight")) for p in window)
            if total_w > 0.01:
                result[i]["weighted_moving_avg"] = round(
                    sum(p["value"] * _weight_of(p.get("strength_weight")) for p in window) / total_w, 4
                )
            else:
                result[i]["weighted_moving_avg"] = result[i]["moving_avg"]
        else:
            result[i]["moving_avg"] = None
            result[i]["weighted_moving_avg"] = None

    return result


def compute_growth_trend(
    points: list[dict],
    window_size: int,
    metric: str,
    trend_delta: float = 0.03,
) -> dict:
    """
    time series points からトレンドを判定する。
    通常値と強度補正値の両方について trend を返す。

    Returns:
        {
          "trend": "improving"|"stable"|"declining"|"pending",
          "trend_delta": float,
          "weighted_trend": "improving"|"stable"|"declining"|"pending",
          "weighted_trend_delta": float,
        }
    """
    base = {
        "trend": "pending",
        "trend_delta": 0.0,
        "weighted_trend": "pending",
        "weighted_trend_delta": 0.0,
    }

    if len(points) < window_size * 2:
        return base

    def _trend(values: list[float]) -> tuple[str, float]:
        if not values or len(values) < window_size * 2:
            return "pending", 0.0
        early = sum(values[:window_size]) / window_size
        recent = sum(values[-window_size:]) / window_size
        delta = round(recent - early, 4)
        if metric == "avg_rally_length":
            return "stable", delta
        if delta >= trend_delta:
            return "improving", delta
        if delta <= -trend_delta:
            return "declining", delta
        return "stable", delta

    normal_values = [p["value"] for p in points]
    wt, wd = _trend(normal_values)
    base["trend"] = wt
    base["trend_delta"] = wd

    weighted_values = [
        p.get("weighted_moving_avg") or p["value"]
        for p in points
    ]
    wwt, wwd = _trend(weighted_values)
    base["weighted_trend"] = wwt
    base["weighted_trend_delta"] = wwd

    return base


def compute_metric_growth_trend(
    raw_points: list[dict],
    min_matches: int,
    trend_delta: float,
    metric: str,
) -> dict:
    """成長判定カードと成長推移グラフが共有する「トレンド算出」の唯一の入口。

    以前は /analysis/growth_judgment が窓 = max(2, 件数//3) でトレンドを算出し、
    /analysis/growth_timeline は窓 = クライアント指定 (既定3) で別個に算出していた。
    同一画面で同じ指標が +4.8% と +6.9% のように食い違う原因はこの窓の不一致なので、
    トレンドの窓と判定可否 (件数不足 → pending) はここだけで決める。
    移動平均の描画用の窓 (window_size) はグラフの平滑化専用で、トレンドには使わない。
    """
    annotated = len(raw_points)
    window = max(2, annotated // 3)
    # 算出法を画面に出すための付帯情報。trend_delta は
    #   (最後の window 試合の平均) − (最初の window 試合の平均)   [率の差 = ポイント]
    # であり、回帰傾きでも相対変化率でもない。期間 (early / recent) は比較に使った試合の日付範囲。
    # 判定保留 (件数不足) のときは窓・期間を null にする (比較していないものを比較したように見せない)。
    info = {
        "n_points": annotated,
        "window": None,
        "early_period": None,
        "recent_period": None,
    }
    if annotated < max(window * 2, min_matches):
        return {
            "trend": "pending",
            "trend_delta": 0.0,
            "weighted_trend": "pending",
            "weighted_trend_delta": 0.0,
            **info,
        }
    pts_with_avg = strength_weighted_moving_avg(raw_points, window_size=window)
    result = compute_growth_trend(
        pts_with_avg, window_size=window, metric=metric, trend_delta=trend_delta,
    )
    info["window"] = window
    info["early_period"] = _period_of(raw_points[:window])
    info["recent_period"] = _period_of(raw_points[-window:])
    return {**result, **info}


def _period_of(points: list[dict]) -> Optional[dict]:
    """点の列の日付範囲 {"from", "to"}。点が無い、または日付が無ければ None。"""
    dates = [str(p["date"]) for p in points if p.get("date")]
    if not dates:
        return None
    return {"from": min(dates), "to": max(dates)}


def summarize_growth_population(
    matches: list,
    used_points: list[dict],
    excluded_before: Optional[dict] = None,
) -> dict:
    """成長判定の母集団内訳: 対象 / 使用 / 除外 (理由別)。

    対象 = 利用者の絞り込み (日付 / 結果 / 大会) を通った全試合、
    使用 = 成長の点になった試合 (勝敗確定かつラリーあり)。
    matches は解析母集団 (analysis_population) を通した試合。母集団の段階で
    外した試合は excluded_before ({"unfinished": n, "zero_rally": n}) で受け取り、
    対象と除外に足し戻す (さもないと除外が常に 0 になる)。
    除外理由は analysis_population と同じ語彙 (unfinished / zero_rally) で数える。
    unfinished と zero_rally が重なる試合は unfinished に数える (1 試合 1 回)。
    """
    pre = excluded_before or {}
    pre_unfinished = int(pre.get("unfinished", 0))
    pre_zero_rally = int(pre.get("zero_rally", 0))
    total = len(matches) + pre_unfinished + pre_zero_rally
    used = len(used_points)
    undecided_here = sum(1 for m in matches if not is_decided_result(m.result))
    unfinished = pre_unfinished + undecided_here
    zero_rally = pre_zero_rally + max(0, len(matches) - used - undecided_here)
    return {
        "total": total,
        "used": used,
        "excluded": {"unfinished": unfinished, "zero_rally": zero_rally},
    }


def decide_overall_growth(metrics: dict[str, dict]) -> tuple[str, str]:
    """複数指標を横断した総合判定 (judgment, judgment_ja) を返す。

    投票規則 (2026-10-15 オーナー承認の統計修正):
      - 1 指標 = 1 票。票は指標自身の trend (improving / stable / declining)。
      - weighted_trend (相手強度補正) は 2 票目ではなく「補正」: 通常の trend と補正後の
        trend が逆向き (improving と declining) のとき、その指標は根拠が割れているので
        stable (票なし) として数える。補正が同方向・stable・pending のときは trend のまま。
        (旧実装は trend と weighted_trend を別々に数えたため、改善 2 票以上という条件を
         指標 1 つだけで満たせた。)
      - 必須指標 (metrics の全指標) のどれかが pending なら、残りの指標だけで
        「改善傾向」などと言い切らず「判定保留」にする。
      - 改善 2 指標以上かつ悪化 0 → 改善傾向、悪化 2 指標以上かつ改善 0 → 悪化傾向、それ以外は横ばい。
    """
    votes: list[str] = []
    any_pending = False
    for v in metrics.values():
        trend = v.get("trend", "pending")
        if trend == "pending":
            any_pending = True
            continue
        weighted = v.get("weighted_trend", "pending")
        if {trend, weighted} == {"improving", "declining"}:
            trend = "stable"
        votes.append(trend)
    improving_count = votes.count("improving")
    declining_count = votes.count("declining")

    if not votes or any_pending:
        return "pending", "判定保留"
    if improving_count >= 2 and declining_count == 0:
        return "improving", "改善傾向"
    if declining_count >= 2 and improving_count == 0:
        return "declining", "悪化傾向"
    return "stable", "横ばい"
