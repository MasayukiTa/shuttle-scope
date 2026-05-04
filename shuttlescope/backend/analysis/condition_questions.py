"""体調質問票マスター定数（Phase 2）。

質問文そのものは FE 側 (`src/i18n/ja.json`) に持たせ、backend では ID・因子・
スケール種別・逆転フラグ・i18n キーのみを保持する。仕様書本体の質問文を
backend コードや定数値に直接引用しない方針。

参照: `private_docs/ShuttleScope_CONDITION_SPEC_v2.md`
"""
from __future__ import annotations

from typing import Dict, List, Tuple, TypedDict


# スケール種別（UI 上は頻度/回復/機能/同意/絶対の 5 種）
SCALE_FREQUENCY = "frequency"        # 症状頻度（1=まったく〜5=ほぼ常に）
SCALE_RECOVERY = "recovery"          # 回復・質（1=非常に悪い〜5=非常に良い）
SCALE_FUNCTION = "function"          # 機能性（1=全くできない〜5=十分できた）
SCALE_AGREEMENT = "agreement"        # 同意（妥当性 V 項目: 1=そう思わない〜5=強くそう思う）
SCALE_ABSOLUTE = "absolute_scale"    # 試合直前版 P 項目: 1=非常に悪い〜5=非常に良い


class QuestionDef(TypedDict):
    id: str
    factor: str          # F1..F5 / V / P / A
    scale: str
    reversed: bool
    i18n_key: str


def _q(qid: str, factor: str, scale: str, reversed: bool) -> QuestionDef:
    return {
        "id": qid,
        "factor": factor,
        "scale": scale,
        "reversed": reversed,
        "i18n_key": f"condition.questions.{qid}",
    }


# ─── 逆転項目一覧（仕様書 §6.1） ────────────────────────────────────────────
REVERSED_ITEMS: List[str] = [
    "F1-06", "F1-08",
    "F2-03", "F2-08",
    "F3-01", "F3-04", "F3-06",
    "F4-01", "F4-02", "F4-04", "F4-06", "F4-07",
    "F5-01", "F5-02", "F5-05", "F5-07", "F5-08",
]


# ─── 逆転ペア（仕様書 §6.3 手法B） ──────────────────────────────────────────
# (pos_item, neg_item): pos はポジティブ表現の逆転項目、neg は症状頻度項目
REVERSE_PAIRS: List[Tuple[str, str]] = [
    ("F1-05", "F1-06"),
    ("F2-03", "F2-04"),
    ("F3-01", "F3-03"),
    ("F4-01", "F4-03"),
    ("F4-02", "F4-05"),
    ("F5-01", "F5-06"),
]


def _build_weekly() -> List[QuestionDef]:
    items: List[QuestionDef] = []

    # F1: 身体（8）
    f1 = [
        ("F1-01", SCALE_FREQUENCY), ("F1-02", SCALE_FREQUENCY),
        ("F1-03", SCALE_FREQUENCY), ("F1-04", SCALE_FREQUENCY),
        ("F1-05", SCALE_FREQUENCY), ("F1-06", SCALE_FUNCTION),
        ("F1-07", SCALE_FREQUENCY), ("F1-08", SCALE_FUNCTION),
    ]
    for qid, sc in f1:
        items.append(_q(qid, "F1", sc, qid in REVERSED_ITEMS))

    # F2: ストレス・不安（8）
    f2 = [
        ("F2-01", SCALE_FREQUENCY), ("F2-02", SCALE_FREQUENCY),
        ("F2-03", SCALE_RECOVERY), ("F2-04", SCALE_FREQUENCY),
        ("F2-05", SCALE_FREQUENCY), ("F2-06", SCALE_FREQUENCY),
        ("F2-07", SCALE_FREQUENCY), ("F2-08", SCALE_FUNCTION),
    ]
    for qid, sc in f2:
        items.append(_q(qid, "F2", sc, qid in REVERSED_ITEMS))

    # F3: 気分・感情（8）
    f3 = [
        ("F3-01", SCALE_RECOVERY), ("F3-02", SCALE_FREQUENCY),
        ("F3-03", SCALE_FREQUENCY), ("F3-04", SCALE_RECOVERY),
        ("F3-05", SCALE_FREQUENCY), ("F3-06", SCALE_FREQUENCY),
        ("F3-07", SCALE_FREQUENCY), ("F3-08", SCALE_FREQUENCY),
    ]
    for qid, sc in f3:
        items.append(_q(qid, "F3", sc, qid in REVERSED_ITEMS))

    # F4: 競技モチベーション（8）
    f4 = [
        ("F4-01", SCALE_FUNCTION), ("F4-02", SCALE_FUNCTION),
        ("F4-03", SCALE_FREQUENCY), ("F4-04", SCALE_FUNCTION),
        ("F4-05", SCALE_FREQUENCY), ("F4-06", SCALE_FUNCTION),
        ("F4-07", SCALE_FUNCTION), ("F4-08", SCALE_FREQUENCY),
    ]
    for qid, sc in f4:
        items.append(_q(qid, "F4", sc, qid in REVERSED_ITEMS))

    # F5: 睡眠・生活（8）
    f5 = [
        ("F5-01", SCALE_RECOVERY), ("F5-02", SCALE_RECOVERY),
        ("F5-03", SCALE_FREQUENCY), ("F5-04", SCALE_FREQUENCY),
        ("F5-05", SCALE_RECOVERY), ("F5-06", SCALE_FREQUENCY),
        ("F5-07", SCALE_FUNCTION), ("F5-08", SCALE_RECOVERY),
    ]
    for qid, sc in f5:
        items.append(_q(qid, "F5", sc, qid in REVERSED_ITEMS))

    # 妥当性（4）
    for qid in ["V-01", "V-02", "V-03", "V-04"]:
        items.append(_q(qid, "V", SCALE_AGREEMENT, False))

    return items


def _build_pre_match() -> List[QuestionDef]:
    return [_q(f"P-{i:02d}", "P", SCALE_ABSOLUTE, False) for i in range(1, 11)]


def _build_auxiliary() -> List[QuestionDef]:
    items: List[QuestionDef] = []
    for qid in ["A-01", "A-02", "A-03", "A-04"]:
        items.append(_q(qid, "A", SCALE_FREQUENCY, False))
    # A-05 は自由記述（UI 側は textarea）。scale は参考値。
    items.append({
        "id": "A-05", "factor": "A", "scale": "text",
        "reversed": False, "i18n_key": "condition.questions.A-05",
    })
    return items


WEEKLY_QUESTIONS: List[QuestionDef] = _build_weekly()
PRE_MATCH_QUESTIONS: List[QuestionDef] = _build_pre_match()
AUXILIARY_QUESTIONS: List[QuestionDef] = _build_auxiliary()

# 採点対象 ID（V/A 除外）
WEEKLY_SCORING_IDS: List[str] = [q["id"] for q in WEEKLY_QUESTIONS if q["factor"].startswith("F")]
WEEKLY_REQUIRED_IDS: List[str] = [q["id"] for q in WEEKLY_QUESTIONS]  # V も必須
PRE_MATCH_REQUIRED_IDS: List[str] = [q["id"] for q in PRE_MATCH_QUESTIONS]


# ─── メタ情報 ───────────────────────────────────────────────────────────────
META = {
    "weekly": {
        "reference_period": "past_3_days",
        "estimated_minutes": [5, 7],
        "total_items": len(WEEKLY_QUESTIONS),
        "scoring_items": len(WEEKLY_SCORING_IDS),  # 40
    },
    "pre_match": {
        "reference_period": "today_pre_match",
        "estimated_minutes": [1, 1],
        "total_items": len(PRE_MATCH_QUESTIONS),
        "scoring_items": len(PRE_MATCH_QUESTIONS),
    },
    "auxiliary": {
        "reference_period": "variable",
        "total_items": len(AUXILIARY_QUESTIONS),
    },
}


def get_master(condition_type: str) -> Dict:
    """condition_type ごとにマスター辞書を返す。"""
    if condition_type == "weekly":
        return {
            "condition_type": "weekly",
            "meta": META["weekly"],
            "questions": WEEKLY_QUESTIONS,
            "auxiliary": AUXILIARY_QUESTIONS,
            "reversed_items": REVERSED_ITEMS,
            "reverse_pairs": [list(p) for p in REVERSE_PAIRS],
        }
    if condition_type == "pre_match":
        return {
            "condition_type": "pre_match",
            "meta": META["pre_match"],
            "questions": PRE_MATCH_QUESTIONS,
            "auxiliary": [q for q in AUXILIARY_QUESTIONS if q["id"] == "A-04" or q["id"] == "A-05"],
        }
    raise ValueError(f"unknown condition_type: {condition_type}")
