"""
shot_taxonomy.py — canonical shot type 定義

方針:
  - CANONICAL_SHOTS が唯一の正規ショット種別リスト
  - SHOT_ALIASES で表記ゆれ・旧表記を canonical に変換する
  - SHOT_TYPE_JA は UI 表示用の日本語ラベル（analysis.py から移植）
  - canonicalize() を保存・解析の入口に挟むことで、
    ストローク記録の表記ゆれを早期に止める

保存時: strokes.py / batch_save_rally で canonicalize() を適用する
解析時: analysis.py / prediction_engine.py は CANONICAL_SHOTS を前提に動く
"""
from __future__ import annotations

# ── 正規ショット種別（18分類）───────────────────────────────────────────────

CANONICAL_SHOTS: list[str] = [
    "short_service",
    "long_service",
    "net_shot",
    "clear",
    "push_rush",
    "smash",
    "defensive",
    "drive",
    "lob",
    "drop",
    "cross_net",
    "slice",
    "around_head",
    "cant_reach",
    "flick",
    "half_smash",
    "block",
    "other",
]

CANONICAL_SET: frozenset[str] = frozenset(CANONICAL_SHOTS)

# ── 日本語表示ラベル ─────────────────────────────────────────────────────────

SHOT_TYPE_JA: dict[str, str] = {
    "short_service": "ショートサーブ",
    "long_service":  "ロングサーブ",
    "net_shot":      "ネットショット",
    "clear":         "クリア",
    "push_rush":     "プッシュ/ラッシュ",
    "smash":         "スマッシュ",
    "defensive":     "ディフェンス",
    "drive":         "ドライブ",
    "lob":           "ロブ",
    "drop":          "ドロップ",
    "cross_net":     "クロスネット",
    "slice":         "スライス",
    "around_head":   "ラウンドヘッド",
    "cant_reach":    "届かず",
    "flick":         "フリック",
    "half_smash":    "ハーフスマッシュ",
    "block":         "ブロック",
    "other":         "その他",
}

# ── エイリアスマップ（表記ゆれ → canonical）────────────────────────────────
# 追加ルール: 小文字・スペースなし・アンダースコアで記載

SHOT_ALIASES: dict[str, str] = {
    # サーブ系
    "service":          "short_service",
    "short service":    "short_service",
    "long service":     "long_service",
    "flick_service":    "long_service",
    "flick service":    "long_service",
    # ネット系
    "net":              "net_shot",
    "netshot":          "net_shot",
    "hairpin":          "net_shot",
    "cross net":        "cross_net",
    "crossnet":         "cross_net",
    # スマッシュ系
    "half smash":       "half_smash",
    "halfsmash":        "half_smash",
    "jump smash":       "smash",
    "jumpsmash":        "smash",
    # プッシュ
    "push":             "push_rush",
    "rush":             "push_rush",
    "push/rush":        "push_rush",
    # ドライブ
    "drive shot":       "drive",
    # ディフェンス
    "defense":          "defensive",
    "defend":           "defensive",
    # クリア
    "attacking clear":  "clear",
    "high clear":       "clear",
    # ドロップ
    "drop shot":        "drop",
    "fast drop":        "drop",
    "sliced drop":      "drop",
    # ロブ
    "lift":             "lob",
    "lobbing":          "lob",
    # アラウンドヘッド
    "around head":      "around_head",
    "aroundhead":       "around_head",
    # ブロック
    "block shot":       "block",
    # フリック
    "flick shot":       "flick",
    # 届かず
    "cant reach":       "cant_reach",
    "can't reach":      "cant_reach",
    "unreachable":      "cant_reach",
    "out of reach":     "cant_reach",
}


def canonicalize(shot_type: str) -> str:
    """
    shot_type 文字列を canonical 形式に変換する。
    大文字小文字・前後スペース無視。
    認識できない場合は 'other' にフォールバック。

    >>> canonicalize("Smash")
    'smash'
    >>> canonicalize("jump smash")
    'smash'
    >>> canonicalize("unknown_shot")
    'other'
    """
    normalized = shot_type.strip().lower()
    if normalized in CANONICAL_SET:
        return normalized
    if normalized in SHOT_ALIASES:
        return SHOT_ALIASES[normalized]
    # アンダースコアをスペースに変換して再トライ
    spaced = normalized.replace("_", " ")
    if spaced in SHOT_ALIASES:
        return SHOT_ALIASES[spaced]
    return "other"


def ja_label(shot_type: str) -> str:
    """canonical shot_type から日本語ラベルを返す"""
    return SHOT_TYPE_JA.get(canonicalize(shot_type), "その他")
