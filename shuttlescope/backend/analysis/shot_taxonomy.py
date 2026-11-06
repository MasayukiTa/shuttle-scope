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


# ── 大分類（簡易入力モード）─────────────────────────────────────────────────
#
# 仙台大学との打合せ (2026-11-05) で、研究者・アナリストから
# 「同じスマッシュでもそこまで細かく分類できない」という要望が出た。
# 18 canonical 小分類は、現場での素早い入力には細かすぎる場面がある。
#
# そこで「大分類（簡易モード）」を用意する:
#   - 入力は 9 大分類（MAJOR_SHOTS）の粒度で行える。
#   - ただし保存は従来どおり 18 canonical 小分類で行う。大分類は「入力の束ね」
#     にすぎず、選ぶと代表 canonical 小分類（MAJOR_REPRESENTATIVE）へ写像して
#     保存する。これにより遷移行列・EPV など 18 分類前提の解析はそのまま動く。
#   - 小分類 → 大分類は MAJOR_OF_CANONICAL（18→9 の逆写像）。解析側で 18 分類を
#     大分類へ畳んで集計したい場合に使う。
#
# フロント側ミラー: src/constants/shotMajorCategories.ts。両者がずれると、
# 簡易モードで選んだ大分類がサーバで別の小分類に落ち、画面と解析が食い違う。
# frontend のテスト (shotMajorCategories.test.ts) と backend のテスト
# (test_shot_major_categories.py) で両者の一致を検査している。

MAJOR_SHOTS: list[str] = [
    "serve",
    "net",
    "drop",
    "clear",
    "smash",
    "drive",
    "lob",
    "defensive",
    "other",
]

MAJOR_SET: frozenset[str] = frozenset(MAJOR_SHOTS)

MAJOR_SHOT_JA: dict[str, str] = {
    "serve":     "サーブ",
    "net":       "ネット前",
    "drop":      "ドロップ",
    "clear":     "クリア",
    "smash":     "スマッシュ",
    "drive":     "ドライブ",
    "lob":       "ロブ",
    "defensive": "守備",
    "other":     "その他",
}

# 大分類 → 代表 canonical 小分類（簡易モードでの既定保存値）。
MAJOR_REPRESENTATIVE: dict[str, str] = {
    "serve":     "short_service",
    "net":       "net_shot",
    "drop":      "drop",
    "clear":     "clear",
    "smash":     "smash",
    "drive":     "drive",
    "lob":       "lob",
    "defensive": "defensive",
    "other":     "other",
}

# canonical 小分類 → 大分類（18→9 の逆写像）。CANONICAL_SHOTS を全て覆う。
MAJOR_OF_CANONICAL: dict[str, str] = {
    "short_service": "serve",
    "long_service":  "serve",
    "net_shot":      "net",
    "cross_net":     "net",
    "push_rush":     "net",
    "flick":         "net",
    "block":         "net",
    "drop":          "drop",
    "clear":         "clear",
    "slice":         "clear",
    "smash":         "smash",
    "half_smash":    "smash",
    "around_head":   "smash",
    "drive":         "drive",
    "lob":           "lob",
    "defensive":     "defensive",
    "cant_reach":    "other",
    "other":         "other",
}


def major_of(shot_type: str) -> str:
    """canonical / 表記ゆれの小分類を大分類へ畳む。未知は 'other'。

    >>> major_of("half_smash")
    'smash'
    >>> major_of("Jump Smash")
    'smash'
    >>> major_of("unknown")
    'other'
    """
    return MAJOR_OF_CANONICAL.get(canonicalize(shot_type), "other")


def representative_of(major: str) -> str:
    """大分類の代表 canonical 小分類を返す。未知は 'other'。

    >>> representative_of("serve")
    'short_service'
    >>> representative_of("NET")
    'net_shot'
    >>> representative_of("bogus")
    'other'
    """
    return MAJOR_REPRESENTATIVE.get(major.strip().lower(), "other")


def major_ja_label(major: str) -> str:
    """大分類コードから日本語ラベルを返す。"""
    return MAJOR_SHOT_JA.get(major.strip().lower(), "その他")
