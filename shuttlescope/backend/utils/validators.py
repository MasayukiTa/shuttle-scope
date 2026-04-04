"""ストローク整合性チェック（SPEC.md §6.4）"""
from typing import Optional

# 物理的に不可能なショット種別×着地ゾーン組み合わせ
INVALID_COMBINATIONS: list[tuple[str, Optional[list[str]]]] = [
    ("smash", ["NL", "NC", "NR"]),           # スマッシュがネット前に落ちない
    ("short_service", ["BL", "BC", "BR"]),   # ショートサーブがバックへ届かない
    ("net_shot", ["BL", "BC", "BR"]),        # ネットショットがバックへ届かない
    ("cant_reach", None),                     # 届かずは着地点なし（着地ゾーンは不要）
]

# サーブ種別（ラリー1球目のみ有効）
SERVICE_TYPES = ["short_service", "long_service"]


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

    # サーブは1球目のみ
    if shot_type in SERVICE_TYPES and stroke_num != 1:
        return False, f"サーブ（{shot_type}）はラリーの1球目のみ有効です"

    return True, None


def validate_rally(rally_data: dict, strokes: list[dict]) -> tuple[bool, Optional[str]]:
    """
    ラリー全体の整合性チェック。
    """
    if not strokes:
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
