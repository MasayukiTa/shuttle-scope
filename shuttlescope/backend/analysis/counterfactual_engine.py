"""
counterfactual_engine.py — 反事実的ショット比較エンジン (Stage 3-A)

改善点:
  - 文脈 = prev_shot のみ → 多次元文脈に拡張
  - 文脈変数: (prev_shot, score_pressure, rally_phase, zone)
  - 文脈ごとに代替ショット選択肢の勝率を比較し、最善手との差分（lift）を算出
  - 後方互換: comparisons の従来構造を維持しつつ context_features を追加

文脈変数:
  1. prev_shot     : 直前の相手ショット種別（従来互換）
  2. score_pressure: "neutral" / "pressure" / "behind"
     - pressure: 自分17+ or 相手17+
     - behind: 自分スコア < 相手スコア - 3
     - neutral: それ以外
  3. rally_phase   : "early"(1-3打) / "mid"(4-7打) / "late"(8+打)
  4. zone          : 相手ショットの落下ゾーン（land_zone）— ある場合のみ

設計原則:
  - 全関数は純粋関数（副作用なし）
  - DB 呼び出しなし（呼び出し元で取得したデータを受け取る）
"""
from __future__ import annotations
from collections import defaultdict
from typing import Optional

from backend.analysis.analysis_config import AnalysisConfig


# ── 文脈分類 ─────────────────────────────────────────────────────────────────

def classify_score_pressure(
    score_a: int,
    score_b: int,
    player_is_a: bool,
) -> str:
    """スコア状態から圧力分類を返す。"""
    my_score = score_a if player_is_a else score_b
    opp_score = score_b if player_is_a else score_a

    if my_score >= AnalysisConfig.PRESSURE_SCORE_THRESHOLD or opp_score >= AnalysisConfig.PRESSURE_SCORE_THRESHOLD:
        return "pressure"
    if my_score < opp_score - 3:
        return "behind"
    return "neutral"


def classify_rally_phase(stroke_num: int) -> str:
    """ラリー内の打球番号からフェーズを返す。"""
    if stroke_num <= 3:
        return "early"
    if stroke_num <= 7:
        return "mid"
    return "late"


# ── 文脈キー構築 ─────────────────────────────────────────────────────────────

def build_context_key(
    prev_shot: str,
    score_pressure: str,
    rally_phase: str,
    zone: Optional[str] = None,
) -> tuple:
    """多次元文脈キーを生成する。"""
    return (prev_shot, score_pressure, rally_phase, zone or "unknown")


def build_simple_context_key(prev_shot: str) -> tuple:
    """従来互換の1次元文脈キー。"""
    return (prev_shot,)


# ── 文脈統計の集計 ────────────────────────────────────────────────────────────

def collect_context_stats(
    rallies: list,
    strokes_by_rally: dict[int, list],
    role_by_match: dict[int, str],
    set_to_match: dict[int, int],
    use_extended_context: bool = True,
) -> tuple[dict[tuple, dict[str, dict]], dict[tuple, dict[str, dict]]]:
    """
    全ラリー・ストロークを走査して文脈ごとの統計を集める。

    Parameters:
        rallies:           ラリー一覧
        strokes_by_rally:  rally_id → [stroke, ...] マッピング
        role_by_match:     match_id → role マッピング
        set_to_match:      set_id → match_id マッピング
        use_extended_context: True なら多次元文脈、False なら prev_shot のみ

    Returns:
        (extended_stats, simple_stats) の2つ
        各 stats: context_key → {response_shot → {"count": N, "wins": N}}
    """
    extended: dict[tuple, dict[str, dict]] = defaultdict(lambda: defaultdict(lambda: {"count": 0, "wins": 0}))
    simple: dict[tuple, dict[str, dict]] = defaultdict(lambda: defaultdict(lambda: {"count": 0, "wins": 0}))

    for rally in rallies:
        mid = set_to_match.get(rally.set_id)
        if mid is None:
            continue
        role = role_by_match.get(mid)
        if not role:
            continue
        player_is_a = role == "player_a"
        opponent_role = "player_b" if player_is_a else "player_a"
        is_win = rally.winner == role

        stks = sorted(strokes_by_rally.get(rally.id, []), key=lambda x: x.stroke_num)

        for i, s in enumerate(stks):
            if s.player != role or not s.shot_type:
                continue

            # 直前の相手ショットを探す
            prev_shot = None
            prev_land_zone = None
            for j in range(i - 1, -1, -1):
                if stks[j].player == opponent_role and stks[j].shot_type:
                    prev_shot = stks[j].shot_type
                    prev_land_zone = getattr(stks[j], "land_zone", None)
                    break
            if not prev_shot:
                continue

            # 従来互換: simple context
            skey = build_simple_context_key(prev_shot)
            simple[skey][s.shot_type]["count"] += 1
            if is_win:
                simple[skey][s.shot_type]["wins"] += 1

            # 拡張文脈
            if use_extended_context:
                pressure = classify_score_pressure(
                    rally.score_a_before, rally.score_b_before, player_is_a
                )
                phase = classify_rally_phase(s.stroke_num)
                ekey = build_context_key(prev_shot, pressure, phase, prev_land_zone)
                extended[ekey][s.shot_type]["count"] += 1
                if is_win:
                    extended[ekey][s.shot_type]["wins"] += 1

    return dict(extended), dict(simple)


# ── 比較候補の構築 ────────────────────────────────────────────────────────────

def build_comparisons(
    ctx_stats: dict[tuple, dict[str, dict]],
    shot_labels: dict[str, str],
    min_obs: int = 5,
    min_lift: float = 0.05,
    top_n: int = 5,
    include_context_features: bool = False,
) -> list[dict]:
    """
    文脈統計から比較候補を構築する。

    Parameters:
        ctx_stats:              文脈キー → {shot → {count, wins}}
        shot_labels:            shot_type → 日本語ラベル
        min_obs:                最低サンプル数
        min_lift:               最低 lift（最善手 - 次善手）
        top_n:                  返す件数上限
        include_context_features: True なら文脈変数の内訳を含める

    Returns:
        comparisons リスト（lift 降順、top_n 件）
    """
    context_label_ja = {
        "smash": "スマッシュへの返球",
        "clear": "クリアへの返球",
        "drop": "ドロップへの返球",
        "net_shot": "ネットショットへの返球",
        "drive": "ドライブへの返球",
        "defensive": "ディフェンスへの返球",
        "lob": "ロブへの返球",
        "push_rush": "プッシュ/ラッシュへの返球",
    }

    comparisons = []

    for ctx_key, resp_map in ctx_stats.items():
        prev_shot = ctx_key[0]

        choices = []
        for resp_shot, v in resp_map.items():
            if v["count"] < min_obs:
                continue
            wr = round(v["wins"] / v["count"], 3)
            choices.append({
                "shot_type": resp_shot,
                "label": shot_labels.get(resp_shot, resp_shot),
                "count": v["count"],
                "win_rate": wr,
            })

        if len(choices) < 2:
            continue

        choices.sort(key=lambda x: -x["win_rate"])
        best_wr = choices[0]["win_rate"]
        second_wr = choices[1]["win_rate"]
        lift = round(best_wr - second_wr, 3)
        if lift < min_lift:
            continue

        ctx_label = context_label_ja.get(
            prev_shot,
            f"{shot_labels.get(prev_shot, prev_shot)}への返球",
        )

        entry = {
            "context_label": ctx_label,
            "prev_shot": prev_shot,
            "choices": choices,
            "recommended": choices[0]["shot_type"],
            "lift": lift,
            "interpretation": (
                f"{ctx_label}では{choices[0]['label']}が"
                f"{choices[1]['label']}より{round(lift * 100)}%高い勝率"
            ),
        }

        # 拡張文脈の場合、文脈変数の内訳を含める
        if include_context_features and len(ctx_key) >= 4:
            entry["context_features"] = {
                "prev_shot": ctx_key[0],
                "score_pressure": ctx_key[1],
                "rally_phase": ctx_key[2],
                "zone": ctx_key[3],
            }

        comparisons.append(entry)

    comparisons.sort(key=lambda x: -x["lift"])
    return comparisons[:top_n]


# ── 文脈別サマリ ─────────────────────────────────────────────────────────────

def summarize_by_dimension(
    extended_stats: dict[tuple, dict[str, dict]],
) -> dict[str, dict]:
    """
    拡張文脈の各次元ごとに集計サマリを生成する。

    Returns:
        {
          "by_pressure": {"neutral": {...}, "pressure": {...}, "behind": {...}},
          "by_phase":    {"early": {...}, "mid": {...}, "late": {...}},
        }
    """
    pressure_agg: dict[str, dict] = defaultdict(lambda: {"total": 0, "wins": 0})
    phase_agg: dict[str, dict] = defaultdict(lambda: {"total": 0, "wins": 0})

    for ctx_key, resp_map in extended_stats.items():
        if len(ctx_key) < 4:
            continue
        pressure = ctx_key[1]
        phase = ctx_key[2]
        for shot, v in resp_map.items():
            pressure_agg[pressure]["total"] += v["count"]
            pressure_agg[pressure]["wins"] += v["wins"]
            phase_agg[phase]["total"] += v["count"]
            phase_agg[phase]["wins"] += v["wins"]

    def _wr(d: dict) -> Optional[float]:
        if d["total"] == 0:
            return None
        return round(d["wins"] / d["total"], 4)

    return {
        "by_pressure": {k: {"win_rate": _wr(v), **v} for k, v in pressure_agg.items()},
        "by_phase": {k: {"win_rate": _wr(v), **v} for k, v in phase_agg.items()},
    }
