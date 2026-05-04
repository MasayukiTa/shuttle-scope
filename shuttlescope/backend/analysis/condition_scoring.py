"""体調質問票の採点・妥当性・本人内変動の純関数群（Phase 2）。

仕様書 §6・§7 に基づく。いかなる質問文字列もここには含めない。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from backend.analysis.condition_questions import (
    REVERSE_PAIRS,
    REVERSED_ITEMS,
    WEEKLY_SCORING_IDS,
    PRE_MATCH_REQUIRED_IDS,
)


# ─── 基本 ──────────────────────────────────────────────────────────────────

def reverse_item(score: int) -> int:
    """逆転処理: 6 - score（1⇔5, 2⇔4, 3→3）。"""
    return 6 - int(score)


def _item_score(qid: str, raw: int) -> int:
    """採点方向に揃えた 1..5（高値=不良）。逆転項目は reverse を適用。"""
    raw_i = int(raw)
    if qid in REVERSED_ITEMS:
        return reverse_item(raw_i)
    return raw_i


# ─── 因子スコア ─────────────────────────────────────────────────────────────

def calc_factor_scores(responses: Dict[str, int]) -> Dict[str, float]:
    """F1〜F5 / total / ccs を算出。

    responses は生回答（1..5）を ID→int で含む dict。
    F? は合計 8〜40（高値=不良）、total=40..200、ccs=200-total（0..160、高値=良好）。
    """
    factors = {"F1": 0, "F2": 0, "F3": 0, "F4": 0, "F5": 0}
    for qid in WEEKLY_SCORING_IDS:
        raw = responses.get(qid)
        if raw is None:
            raise KeyError(qid)
        s = _item_score(qid, raw)
        factors[qid.split("-")[0]] += s

    total = sum(factors.values())
    ccs = 200 - total

    return {
        "f1_physical": float(factors["F1"]),
        "f2_stress": float(factors["F2"]),
        "f3_mood": float(factors["F3"]),
        "f4_motivation": float(factors["F4"]),
        "f5_sleep_life": float(factors["F5"]),
        "total_score": float(total),
        "ccs_score": float(ccs),
    }


def calc_pre_match_score(responses: Dict[str, int]) -> Dict[str, float]:
    """試合直前版 10 項目の単純合計（10〜50、高値=良好）。"""
    total = 0
    for qid in PRE_MATCH_REQUIRED_IDS:
        v = responses.get(qid)
        if v is None:
            raise KeyError(qid)
        total += int(v)
    return {"pre_match_total": float(total)}


# ─── 妥当性スコア（仕様書 §6.3） ────────────────────────────────────────────

def calc_validity(
    responses: Dict[str, int],
    history_ccs: Optional[List[float]] = None,
    current_ccs: Optional[float] = None,
) -> Dict:
    """妥当性スコアを返す。0..100、<20 ok / <50 caution / else unreliable。"""
    score = 0
    flags: List[str] = []

    # A: V-01〜V-03 の高値
    for vid in ("V-01", "V-02", "V-03"):
        v = responses.get(vid)
        if v is not None and int(v) >= 4:
            score += 15
            flags.append(f"{vid}_high")

    # B: 逆転ペア矛盾
    for pos_id, neg_id in REVERSE_PAIRS:
        pos = responses.get(pos_id)
        neg = responses.get(neg_id)
        if pos is None or neg is None:
            continue
        if abs(int(pos) - (6 - int(neg))) >= 3:
            score += 10
            flags.append(f"reverse_pair_mismatch:{pos_id}/{neg_id}")

    # C: 直線回答（V 以外のセットサイズ <=2）
    all_scores = [
        int(v) for k, v in responses.items()
        if not k.startswith("V") and not k.startswith("A")
    ]
    if all_scores and len(set(all_scores)) <= 2:
        score += 20
        flags.append("straight_line_response")

    # D: 前回比急変（|ΔCCS| >= 40）
    if history_ccs and current_ccs is not None:
        prev = history_ccs[-1]
        delta = current_ccs - prev
        if abs(delta) >= 40:
            score += 10
            flags.append(f"ccs_sudden_change:{delta:+.0f}")

    capped = min(score, 100)
    if capped < 20:
        flag_level = "ok"
    elif capped < 50:
        flag_level = "caution"
    else:
        flag_level = "unreliable"

    return {
        "validity_score": float(capped),
        "validity_flag": flag_level,
        "flags_list": flags,
    }


# ─── 本人内変動（仕様書 §7.1） ──────────────────────────────────────────────

def calc_deviation(current_ccs: float, history_ccs_list: List[float]) -> Dict:
    """前回差・3MA・28日平均/SD・zスコアを算出。欠損は None。"""
    result: Dict = {
        "delta_prev": None,
        "delta_3ma": None,
        "delta_28ma": None,
        "z_score": None,
        "mean_28": None,
        "sd_28": None,
    }
    h = list(history_ccs_list)

    if len(h) >= 1:
        result["delta_prev"] = float(current_ccs - h[-1])

    if len(h) >= 3:
        mean_3 = sum(h[-3:]) / 3.0
        result["delta_3ma"] = float(current_ccs - mean_3)

    if len(h) >= 7:
        recent = h[-28:]
        n = len(recent)
        mean_28 = sum(recent) / n
        var_28 = sum((x - mean_28) ** 2 for x in recent) / n
        sd_28 = var_28 ** 0.5
        result["mean_28"] = float(mean_28)
        result["sd_28"] = float(sd_28)
        result["delta_28ma"] = float(current_ccs - mean_28)
        result["z_score"] = float((current_ccs - mean_28) / sd_28) if sd_28 > 0 else 0.0

    return result


# ─── プレイヤー向け因子ラベル（z 絶対値） ────────────────────────────────

def factor_label_from_z(z: Optional[float]) -> str:
    """|z| <0.5 良好 / <1.0 少し注意 / else 注意。"""
    if z is None:
        return "insufficient_data"
    az = abs(z)
    if az < 0.5:
        return "good"
    if az < 1.0:
        return "caution_mild"
    return "caution"
