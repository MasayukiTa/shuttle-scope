"""
武内優幸（player_id=107）の週次コンディション seed。

- 期間: 2025-01-06（月曜）〜 2026-04-13（月曜）＝今日 2026-04-15 の直前の月曜
- 毎週月曜 12:00 に入力想定
- 偏りのあるリアルなデータ:
  * ベースラインは CCS 120 付近（普通〜良好）
  * 大会月（6月、11月、翌3月）前後で疲労・ストレス上昇 → CCS 低下
  * 夏場（7-8月）は睡眠不足傾向
  * 怪我期間（2025-09-15 〜 2025-10-20）は F1 大幅悪化
  * 年末年始（2025-12-22〜2026-01-05）は休養で回復傾向
  * InBody は緩やかな筋肉量増加（65kg → 67kg）、体脂肪率微減（14% → 12.5%）
  * Hooper/RPE も状況に応じて変動
  * 妥当性フラグ: 基本 ok、ごく稀に caution（矛盾回答を意図的に仕込む）

既存の seed 分があれば削除してから再作成する。
"""
from __future__ import annotations
import random
import json
from datetime import date, timedelta

from backend.db.database import SessionLocal
from backend.db.models import Condition, Player
from backend.analysis.condition_questions import (
    WEEKLY_QUESTIONS as WEEKLY_ITEMS,
    REVERSED_ITEMS as REVERSED_ITEM_IDS,
)
VALIDITY_ITEMS = [q for q in WEEKLY_ITEMS if q["factor"] == "V"]
WEEKLY_ITEMS = [q for q in WEEKLY_ITEMS if q["factor"] != "V"]
from backend.analysis.condition_scoring import (
    calc_factor_scores, calc_validity, calc_deviation,
)

PLAYER_ID = 107
START = date(2025, 1, 6)   # 月曜
END = date(2026, 4, 13)    # 月曜（2026-04-15 火曜の直前の月曜）

random.seed(42)  # 再現性


def weekly_mondays(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=7)


def context_for(d: date) -> dict:
    """日付から状況係数を返す。ctx['stress'], ctx['fatigue'], ctx['sleep'],
       ctx['mood'], ctx['motiv'] ∈ [-2, +2]（正=悪化、負=良好）。"""
    ctx = {"stress": 0.0, "fatigue": 0.0, "sleep": 0.0, "mood": 0.0, "motiv": 0.0}

    # 大会月前（5月下旬〜6月、10月下旬〜11月、2月下旬〜3月）
    m, day = d.month, d.day
    if (m == 5 and day >= 20) or m == 6:
        ctx["stress"] += 1.2
        ctx["fatigue"] += 1.0
    if (m == 10 and day >= 20) or m == 11:
        ctx["stress"] += 1.4
        ctx["fatigue"] += 1.1
        ctx["mood"] += 0.5
    if (m == 2 and day >= 20) or m == 3:
        ctx["stress"] += 1.0
        ctx["fatigue"] += 0.9

    # 夏場 睡眠不足
    if m in (7, 8):
        ctx["sleep"] += 1.0
        ctx["fatigue"] += 0.4

    # 怪我期間 2025-09-15 〜 2025-10-20
    injury_start = date(2025, 9, 15)
    injury_end = date(2025, 10, 20)
    if injury_start <= d <= injury_end:
        ctx["fatigue"] += 1.8
        ctx["mood"] += 1.2
        ctx["motiv"] += 0.8
        ctx["stress"] += 0.6

    # 年末年始 休養
    if (m == 12 and day >= 22) or (m == 1 and day <= 5):
        ctx["fatigue"] -= 1.0
        ctx["stress"] -= 0.8
        ctx["mood"] -= 0.5
        ctx["sleep"] -= 0.7

    # トレンド: 全体的に 2025 前半より 2026 の方がモチベ微減、熟練増でストレス耐性上昇
    months_from_start = (d.year - 2025) * 12 + (d.month - 1)
    ctx["stress"] -= months_from_start * 0.015  # 時間と共に慣れ
    ctx["motiv"] += months_from_start * 0.01   # ややマンネリ

    # ランダム揺らぎ
    for k in ctx:
        ctx[k] += random.uniform(-0.4, 0.4)

    return ctx


def response_for_item(item_id: str, factor: str, reversed_: bool, ctx: dict) -> int:
    """係数から 1-5 の回答を生成。reversed な項目は (6-score) が因子スコアになるので
    ctx と逆方向で回答する必要がある。"""
    # 因子キー → ctx キー
    base = {
        "F1": ctx["fatigue"],
        "F2": ctx["stress"],
        "F3": ctx["mood"],
        "F4": ctx["motiv"],
        "F5": ctx["sleep"],
    }.get(factor, 0.0)

    # base が高いほど「悪い」方向。正方向項目は score 高く、逆転項目は score 低く。
    mean = 3.0 + base * 0.6
    if reversed_:
        mean = 6.0 - mean  # 逆転項目は逆方向回答

    # 雑音
    mean += random.uniform(-0.5, 0.5)
    score = round(max(1, min(5, mean)))
    return int(score)


def build_responses(ctx: dict) -> dict:
    res = {}
    for it in WEEKLY_ITEMS:
        iid = it["id"]
        factor = it["factor"]
        reversed_ = iid in REVERSED_ITEM_IDS
        res[iid] = response_for_item(iid, factor, reversed_, ctx)
    # 妥当性項目 V-01..V-04: 基本は 1 or 2（健全）、たまに 4 を混ぜる
    for it in VALIDITY_ITEMS:
        iid = it["id"]
        if random.random() < 0.05:
            res[iid] = 4
        else:
            res[iid] = random.choice([1, 1, 2, 2, 3])
    return res


def inbody_for(d: date) -> dict:
    """緩やかな筋肉量増加、体脂肪率微減のトレンド。"""
    weeks = (d - START).days / 7
    total_weeks = (END - START).days / 7
    progress = weeks / total_weeks  # 0→1

    weight = 65.0 + progress * 2.0 + random.uniform(-0.4, 0.4)
    muscle = 52.0 + progress * 2.0 + random.uniform(-0.3, 0.3)
    bf_pct = 14.0 - progress * 1.5 + random.uniform(-0.6, 0.6)
    bf_mass = weight * bf_pct / 100
    lean = weight - bf_mass
    # 怪我期間中は筋肉量やや減
    if date(2025, 9, 15) <= d <= date(2025, 10, 20):
        muscle -= 0.8
        lean -= 0.5

    return {
        "weight_kg": round(weight, 1),
        "muscle_mass_kg": round(muscle, 1),
        "body_fat_pct": round(bf_pct, 1),
        "body_fat_mass_kg": round(bf_mass, 1),
        "lean_mass_kg": round(lean, 1),
        "ecw_ratio": round(0.380 + random.uniform(-0.008, 0.015), 4),
        "arm_l_muscle_kg": round(muscle * 0.058 + random.uniform(-0.05, 0.05), 2),
        "arm_r_muscle_kg": round(muscle * 0.062 + random.uniform(-0.05, 0.05), 2),
        "leg_l_muscle_kg": round(muscle * 0.165 + random.uniform(-0.1, 0.1), 2),
        "leg_r_muscle_kg": round(muscle * 0.170 + random.uniform(-0.1, 0.1), 2),
        "trunk_muscle_kg": round(muscle * 0.42 + random.uniform(-0.1, 0.1), 2),
        "bmr_kcal": round(1500 + muscle * 8 + random.uniform(-30, 30), 0),
    }


def hooper_rpe_for(ctx: dict) -> dict:
    """Hooper 1-7（高い=悪い）、RPE 0-10、session_duration."""
    def clip7(v):
        return int(max(1, min(7, round(v))))
    return {
        "hooper_sleep": clip7(3 + ctx["sleep"] * 0.9),
        "hooper_soreness": clip7(3 + ctx["fatigue"] * 0.8),
        "hooper_stress": clip7(3 + ctx["stress"] * 0.9),
        "hooper_fatigue": clip7(3 + ctx["fatigue"] * 0.9),
        "session_rpe": int(max(0, min(10, round(6 + ctx["fatigue"] * 0.6 + random.uniform(-1, 1))))),
        "session_duration_min": int(random.choice([60, 75, 90, 90, 105, 120])),
    }


def main():
    db = SessionLocal()

    # 既存の seed を削除（同一 player & weekly）
    deleted = db.query(Condition).filter(
        Condition.player_id == PLAYER_ID,
        Condition.condition_type == "weekly",
    ).delete()
    db.commit()
    print(f"[seed] deleted existing weekly rows: {deleted}")

    # プレイヤー存在チェック
    player = db.query(Player).filter(Player.id == PLAYER_ID).first()
    if not player:
        raise SystemExit(f"player id={PLAYER_ID} not found")

    history_ccs: list[float] = []
    count = 0

    for d in weekly_mondays(START, END):
        ctx = context_for(d)
        responses = build_responses(ctx)

        # 採点
        scores = calc_factor_scores(responses)
        hist_rows = [{"ccs_score": c} for c in history_ccs]
        validity = calc_validity(responses, hist_rows)
        deviation = calc_deviation(scores["ccs_score"], history_ccs)

        inbody = inbody_for(d)
        hooper = hooper_rpe_for(ctx)
        hooper_index = (
            hooper["hooper_sleep"] + hooper["hooper_soreness"]
            + hooper["hooper_stress"] + hooper["hooper_fatigue"]
        )
        session_load = hooper["session_rpe"] * hooper["session_duration_min"]

        row = Condition(
            player_id=PLAYER_ID,
            measured_at=d,
            condition_type="weekly",
            match_id=None,
            **inbody,
            **hooper,
            hooper_index=hooper_index,
            session_load=session_load,
            questionnaire_json=json.dumps(responses, ensure_ascii=False),
            f1_physical=scores["f1_physical"],
            f2_stress=scores["f2_stress"],
            f3_mood=scores["f3_mood"],
            f4_motivation=scores["f4_motivation"],
            f5_sleep_life=scores["f5_sleep_life"],
            total_score=scores["total_score"],
            ccs_score=scores["ccs_score"],
            delta_prev=deviation.get("delta_prev"),
            delta_3ma=deviation.get("delta_3ma"),
            delta_28ma=deviation.get("delta_28ma"),
            z_score=deviation.get("z_score"),
            validity_score=validity["validity_score"],
            validity_flag=validity["validity_flag"],
            validity_flags_json=json.dumps(validity.get("flags_list", []), ensure_ascii=False),
            sleep_hours=round(7.0 - ctx["sleep"] * 0.6 + random.uniform(-0.5, 0.5), 1),
            injury_notes=(
                "右膝テーピング" if date(2025, 9, 15) <= d <= date(2025, 10, 20) else None
            ),
            general_comment=None,
        )
        db.add(row)
        history_ccs.append(scores["ccs_score"])
        count += 1

    db.commit()
    print(f"[seed] inserted {count} weekly conditions for player_id={PLAYER_ID}")
    print(f"[seed] ccs range: {min(history_ccs):.1f} 〜 {max(history_ccs):.1f}, mean={sum(history_ccs)/len(history_ccs):.1f}")


if __name__ == "__main__":
    main()
