"""ストローク整合性チェック（SPEC.md §6.4）"""
from typing import Optional

# 物理的に不可能なショット種別×着地ゾーン組み合わせ
INVALID_COMBINATIONS: list[tuple[str, Optional[list[str]]]] = [
    ("short_service", ["BL", "BC", "BR"]),   # ショートサーブがバックへ届かない
    ("net_shot", ["BL", "BC", "BR"]),        # ネットショットがバックへ届かない
    ("cant_reach", None),                     # 届かずは着地点なし（着地ゾーンは不要）
]

# 「まれだが競技上は成立する」組み合わせ。保存は拒否せず、警告として返す。
# スマッシュは急角度でネット寄りの前方ゾーンへ落ちることがあり (甘く上がった
# ネット際の球を高い打点から叩く場面)、物理的不可能ではない。以前は
# INVALID_COMBINATIONS に入れていたため、正しい実測が全保存経路で 422 になった。
UNUSUAL_COMBINATIONS: list[tuple[str, list[str]]] = [
    ("smash", ["NL", "NC", "NR"]),
]

# サーブ種別（ラリー1球目のみ有効）
SERVICE_TYPES = ["short_service", "long_service"]

# ── ゾーン語彙 ───────────────────────────────────────────────────────────────
# `src/types/index.ts` の Zone9 / ZoneOOB / ZoneNet と 1 対 1 で対応する。
# 二重定義なので `backend/tests/test_zone_vocabulary.py` が TS 側を読んで突き合わせる。
#
# ここまで検証が無く、`land_zone` は 5 文字以内なら何でも保存できた。
# ゾーンはヒートマップと空間分析の集計キーなので、綴り違いが 1 つ混ざると
# **誰も選んでいないマスが集計に現れる**。落ちるのではなく静かに増える。
try:
    from backend.config import ZONES_9 as _ZONES_9
except Exception:  # pragma: no cover - config が読めない環境
    _ZONES_9 = ["BL", "BC", "BR", "ML", "MC", "MR", "NL", "NC", "NR"]

COURT_ZONES = frozenset(_ZONES_9)
# コート外 (ZoneOOB)
OOB_ZONES = frozenset({
    "OB_BL", "OB_BC", "OB_BR",      # バックライン外
    "OB_LL", "OB_LM", "OB_LN",      # 左サイドライン外
    "OB_RL", "OB_RM", "OB_RN",      # 右サイドライン外
    "OB_FL", "OB_FR",               # ネット前
})
# ネット接触 (ZoneNet)
NET_ZONES = frozenset({"NET_L", "NET_C", "NET_R"})

# 着地点はコート内・コート外・ネット接触のすべてを取りうる
VALID_LAND_ZONES = COURT_ZONES | OOB_ZONES | NET_ZONES
# 打点は «打った位置» なのでコート内のみ
VALID_HIT_ZONES = COURT_ZONES

# ── 打球の高さ語彙（要望8 / SD-08）────────────────────────────────────────────
# hit_zone（打者の床面位置）とは別概念。ネットを基準にした相対的な打球の高さを
# 4 段階で表す。任意入力なので NULL を許す。ダブルスの簡易分析では、この 4 段階を
# 0〜3 の整数に写像して「打った側」と「受けた側」の高さ差を取る。
#   above_net      = ネットより上  → 0
#   slightly_above = やや上        → 1
#   slightly_below = やや下        → 2
#   below          = 下            → 3
# 整数はネットから下へ向かって単調増加する。差の絶対値が «高さのずれ» を表す。
HIT_HEIGHT_ORDER: tuple[str, ...] = (
    "above_net",
    "slightly_above",
    "slightly_below",
    "below",
)
HIT_HEIGHT_LEVEL: dict[str, int] = {name: i for i, name in enumerate(HIT_HEIGHT_ORDER)}
VALID_HIT_HEIGHTS = frozenset(HIT_HEIGHT_ORDER)


def hit_height_level(value: Optional[str]) -> Optional[int]:
    """4 段階の高さラベルを 0〜3 の整数に写す。未知・NULL は None。"""
    if value is None:
        return None
    return HIT_HEIGHT_LEVEL.get(value)


def validate_stroke(stroke_data: dict) -> tuple[bool, Optional[str]]:
    """
    ストロークの整合性チェック。
    問題があれば (False, エラーメッセージ) を返す。
    警告レベルは弾かずに (True, 警告メッセージ) を返す。
    """
    shot_type = stroke_data.get("shot_type", "")
    land_zone = stroke_data.get("land_zone")
    stroke_num = stroke_data.get("stroke_num", 1)

    # 物理的不可能チェック
    for invalid_shot, invalid_zones in INVALID_COMBINATIONS:
        if shot_type == invalid_shot:
            if invalid_zones is None:
                # 着地点が設定されている場合はエラー
                if land_zone is not None:
                    return False, f"{shot_type}（届かず）は着地点を設定できません"
            elif land_zone in invalid_zones:
                return False, f"{shot_type} が {land_zone} ゾーンに着地するのは物理的に不可能です"

    # まれな組み合わせは弾かず警告にする (保存は続行)
    warning: Optional[str] = None
    for unusual_shot, unusual_zones in UNUSUAL_COMBINATIONS:
        if shot_type == unusual_shot and land_zone in unusual_zones:
            warning = f"{shot_type} が {land_zone} ゾーンに着地するのはまれです（入力内容の確認を推奨）"

    # サーブは1球目のみ
    if shot_type in SERVICE_TYPES and stroke_num != 1:
        return False, f"サーブ（{shot_type}）はラリーの1球目のみ有効です"

    # ゾーン語彙。知らない綴りを通すと、集計のときだけ «誰も選んでいないマス»
    # として現れる。入口で弾く。
    if land_zone is not None and land_zone not in VALID_LAND_ZONES:
        return False, f"着地ゾーン '{land_zone}' は定義されていません"
    hit_zone = stroke_data.get("hit_zone")
    if hit_zone is not None and hit_zone not in VALID_HIT_ZONES:
        return False, f"打点ゾーン '{hit_zone}' は定義されていません"
    hit_height = stroke_data.get("hit_height")
    if hit_height is not None and hit_height not in VALID_HIT_HEIGHTS:
        return False, f"打球の高さ '{hit_height}' は定義されていません"

    return True, warning


def validate_rally(rally_data: dict, strokes: list[dict]) -> tuple[bool, Optional[str]]:
    """
    ラリー全体の整合性チェック。
    is_skipped=True の見逃しラリーはストローク空を許容する。
    """
    if not strokes:
        if rally_data.get("is_skipped"):
            return True, None  # 見逃しラリーはストロークなしでOK
        return False, "ストロークが1球もありません"

    # 1球目がサーブかどうかの確認（警告レベル）
    first_stroke = strokes[0]
    if first_stroke.get("shot_type") not in SERVICE_TYPES:
        # 警告のみ（サーブ不明のデータも受け入れる）
        pass

    # ストローク番号の連続性チェック
    for i, stroke in enumerate(strokes):
        if stroke.get("stroke_num") != i + 1:
            return False, f"ストローク番号が連続していません (期待: {i+1}, 実際: {stroke.get('stroke_num')})"

    # ラリー長の整合性
    expected_length = len(strokes)
    if rally_data.get("rally_length") != expected_length:
        return False, f"ラリー長が不一致 (宣言: {rally_data.get('rally_length')}, 実際: {expected_length})"

    return True, None
