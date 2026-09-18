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
    # Tier 1 — 派生サマリ（運営/コーチ/アナリストに開示可・選手本人は除外）
    # 同意書 第5条: 妥当性フラグは admin/coach/analyst=○、本人=×
    # 注: 選手本人除外は呼び出し側で別途実装する必要あり（tier 単独では表現不可）
    "validity_flag": 1,
    # Tier 2 — パフォーマンス指標（生スコア。同意書では本人と admin のみ）
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
# 同意書 第5条 アライメント:
# - admin (開発者): 全件 ○ → Tier 4
# - analyst: コンディション生スコア ×, 体組成 ×, 医療自由記述 × → Tier 1 (識別子+派生のみ)
# - coach:   コンディション生スコア ×, 体組成 ×, 医療自由記述 × → Tier 1
# - player:  自身のデータは全 Tier 可（owner check は呼び出し側で行う）
#            他選手の生スコア/体組成/医療記述は不可。デフォルト cap は Tier 2 に置き、
#            owner であれば routers が個別に Tier 4 まで開示する設計。
# Round 258: analyst=4 / coach=3 から大幅縮小（医療自由記述・体組成の漏洩を遮断）。
# 既存 UI で coach/analyst が hooper/F-スコア raw を期待していた箇所は壊れる可能性があるため
# docs/validation/ 配下の MD で残存差分を P1 として追跡する。
ROLE_MAX_TIER: dict[str, int] = {
    "admin": 4,
    "analyst": 1,
    "coach": 1,
    "player": 2,
}


def get_max_tier(role: Optional[str]) -> int:
    if not role:
        return 0
    return ROLE_MAX_TIER.get(role, 0)


# --- 外部処理系（社外の LLM API 等）への送出 ---

# ROLE_MAX_TIER は「社内の誰に見せるか」の表であって、社外の事業者は載っていない。
# 載せられない: 同意書 (consents/BODY_DISCLOSURE_TO_*.md §1) が定めているのは
# Coach / Analyst という**役割**への開示であり、第三者への送信を許す条項は無い。
# したがって外部宛には、どのロールにも紐づけず、識別子と健康データを落とす。
#
# 落とす対象:
#   - player_name / player_id : 個人の識別。統計を作るのに不要
#   - conditions              : avg_rpe / avg_hooper は Tier 2 の生スコア
#
# 残すもの (試合中のプレーの統計。これが insight の題材そのもの):
#   sample / outcomes / shot_mix / zones / recent_trend / date_from / date_to
_EXTERNAL_DROP_KEYS = frozenset({"player_name", "player_id", "conditions"})


def redact_for_external_processor(payload: Optional[dict]) -> dict:
    """社外の処理系へ渡す直前に、識別子と健康データを落とす。

    **allow-list ではなく drop-list にしていない理由**: サマリの構造は今後も
    増える。増えたキーが黙って外へ出るより、増えたキーが黙って落ちるほうが安全。
    よって「残すキー」を明示する allow-list にしてある。

    知らないキーは落とす。呼び出し側はここを通ったものだけを送ること。
    """
    if not payload:
        return {}
    keep = {
        "date_from",
        "date_to",
        "sample",
        "outcomes",
        "shot_mix",
        "zones",
        "recent_trend",
    }
    return {k: v for k, v in payload.items() if k in keep and k not in _EXTERNAL_DROP_KEYS}


def get_effective_max_tier(
    role: Optional[str],
    owner_consents: Optional[dict[str, bool]] = None,
) -> int:
    """ロール + 当該 player 本人の同意状態から実効最大ティアを返す。

    - admin: 常に Tier 4
    - player: ROLE_MAX_TIER 通り (owner check は呼び出し側)
    - analyst: 通常 Tier 1。owner の 'body_disclose_to_analyst' が True なら
      Tier 3 まで開放 (= 体組成データ閲覧可)。
    - coach: 通常 Tier 1。owner の 'body_disclose_to_coach' が True なら
      Tier 3 まで開放。default OFF。
    """
    base = get_max_tier(role)
    if not owner_consents:
        return base
    if role == "analyst" and owner_consents.get("body_disclose_to_analyst"):
        return max(base, 3)
    if role == "coach" and owner_consents.get("body_disclose_to_coach"):
        return max(base, 3)
    return base


def filter_condition_fields(
    data: dict,
    role: Optional[str],
    owner_consents: Optional[dict[str, bool]] = None,
) -> dict:
    """ロール + owner consent に応じてコンディションデータのフィールドをフィルタ。

    owner_consents は当該データの "本人" (= player) が submit した consent の
    {consent_type: consent_given} dict。後方互換のため省略可能 (None = 旧挙動)。
    """
    max_tier = get_effective_max_tier(role, owner_consents)
    return {
        k: v for k, v in data.items()
        if CONDITION_FIELD_TIERS.get(k, 0) <= max_tier
    }
