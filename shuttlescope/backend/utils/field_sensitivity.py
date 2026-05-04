"""フィールド感度分類（A-3）

Tier 0: 公開可
Tier 1: 基本統計（役職者に開示可）
Tier 2: パフォーマンス指標（coach 以上）
Tier 3: 身体組成（coach 以上）
Tier 4: 医療・自由記述（analyst/admin のみ）
"""
from typing import Optional

# --- ConditionRecord フィールド感度 ---

CONDITION_FIELD_TIERS: dict[str, int] = {
    # Tier 0 — 識別子
    "id": 0,
    "player_id": 0,
    "measured_at": 0,
    "condition_type": 0,
    "match_id": 0,
    # Tier 2 — パフォーマンス指標
    "hooper_sleep": 2,
    "hooper_soreness": 2,
    "hooper_stress": 2,
    "hooper_fatigue": 2,
    "hooper_index": 2,
    "session_rpe": 2,
    "session_duration_min": 2,
    "session_load": 2,
    "f1_physical": 2,
    "f2_stress": 2,
    "f3_mood": 2,
    "f4_motivation": 2,
    "f5_sleep_life": 2,
    "total_score": 2,
    "ccs_score": 2,
    "delta_prev": 2,
    "delta_3ma": 2,
    "delta_28ma": 2,
    "z_score": 2,
    "sleep_hours": 2,
    "validity_score": 2,
    "validity_flag": 2,
    "validity_flags_json": 2,
    # Tier 3 — 身体組成
    "weight_kg": 3,
    "muscle_mass_kg": 3,
    "body_fat_pct": 3,
    "body_fat_mass_kg": 3,
    "lean_mass_kg": 3,
    "ecw_ratio": 3,
    "arm_l_muscle_kg": 3,
    "arm_r_muscle_kg": 3,
    "leg_l_muscle_kg": 3,
    "leg_r_muscle_kg": 3,
    "trunk_muscle_kg": 3,
    "bmr_kcal": 3,
    # Tier 4 — 医療・自由記述
    "injury_notes": 4,
    "general_comment": 4,
    "questionnaire_json": 4,
}

# ロール → 許可最大ティア
ROLE_MAX_TIER: dict[str, int] = {
    "admin": 4,
    "analyst": 4,
    "coach": 3,
    "player": 2,
}


def get_max_tier(role: Optional[str]) -> int:
    if not role:
        return 0
    return ROLE_MAX_TIER.get(role, 0)


def filter_condition_fields(data: dict, role: Optional[str]) -> dict:
    """ロールに応じてコンディションデータのフィールドをフィルタ。"""
    max_tier = get_max_tier(role)
    return {
        k: v for k, v in data.items()
        if CONDITION_FIELD_TIERS.get(k, 0) <= max_tier
    }
