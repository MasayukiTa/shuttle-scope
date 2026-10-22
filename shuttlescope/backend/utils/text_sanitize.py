"""文字列フィールドのコントロール文字 / Unicode BIDI override 拒否。

UI 表示偽装 (RTLO による拡張子偽装、ZWSP による host 偽装等) と CRLF
injection / null byte 系の処理バグを防ぐ。

短い識別子フィールドは `reject_ctrl_and_bidi` (改行も拒否)、
長い自由記述フィールドは `reject_bidi_only` (改行 / タブは許可) を使う。

それぞれ Pydantic validator やルータ内で呼び出すだけで強制できる軽量 util。
"""
from __future__ import annotations

import unicodedata
from typing import Optional

from fastapi import HTTPException


# 不可視 / 双方向制御 (format) 文字セット。表示偽装 (RTLO・ZWSP・LRM 等) の防止。
# 名前系フィールドの検証はすべてこのモジュールの関数を使うこと (別実装を作らない)。
# 2026-10: LRM/RLM/ALM/WJ/SHY を追加 (従来は欠けていた)。
_BIDI_FORMAT_CHARS = frozenset({
    "\u00ad",                          # SHY (soft hyphen)
    "\u061c",                          # ALM (Arabic letter mark)
    "\u200b", "\u200c", "\u200d",      # ZWSP / ZWNJ / ZWJ
    "\u200e", "\u200f",                # LRM / RLM
    "\u2028", "\u2029",                # Line / Paragraph separators
    "\u202a", "\u202b", "\u202c", "\u202d", "\u202e",  # LRE/RLE/PDF/LRO/RLO
    "\u2060",                          # WJ (word joiner)
    "\u2066", "\u2067", "\u2068", "\u2069",  # LRI/RLI/FSI/PDI
    "\ufeff",                          # BOM / ZWNBSP
})

# 列挙漏れを防ぐため、Unicode の一般カテゴリでも判定する (監査 #10)。
#   Cf = 書式制御 (不可視の数式演算子 U+2061-2064、廃止済み書式 U+206A-206F、
#        言語タグ U+E0000 台、ALM など)
#   Zl / Zp = 行・段落区切り
# 幅を持たないのに文字として扱われ、見た目が同じで内部文字列が違う名前を作れる
# ハングル・フィラー等は Cf ではないので別に列挙する。
_INVISIBLE_FILLERS = frozenset({
    "͏",                  # CGJ
    "ᅟ", "ᅠ",        # Hangul choseong / jungseong filler
    "឴", "឵",        # Khmer inherent vowel (不可視)
    "ㅤ", "ﾠ",        # Hangul filler / halfwidth Hangul filler
})
_INVISIBLE_CATEGORIES = frozenset({"Cf", "Zl", "Zp"})


def is_invisible_format_char(ch: str) -> bool:
    """不可視 / 双方向制御 / 書式制御の 1 文字か (名前・表示名には入れさせない文字)。"""
    return (
        ch in _BIDI_FORMAT_CHARS
        or ch in _INVISIBLE_FILLERS
        or unicodedata.category(ch) in _INVISIBLE_CATEGORIES
    )


def strip_invisible_format_chars(value: Optional[str]) -> Optional[str]:
    """表示用: 不可視・双方向制御文字と C0 制御文字を取り除き、NFC に正規化して返す。

    防ぐ事象 (監査 #10): 検証を入れる前に保存された名前に不可視文字が残っていると、
    一覧にそのまま出て、見た目が同じなのに別の文字列になる (なりすまし・重複)。
    保存値は書き換えず、応答に載せる時だけ整える (非破壊)。None はそのまま返す。
    """
    if value is None:
        return None
    cleaned = "".join(
        ch for ch in value
        if not is_invisible_format_char(ch) and ch not in _C0_ALL
    )
    return unicodedata.normalize("NFC", cleaned)


# C0 制御文字のうち改行・タブも拒否するセット (識別子向け)
_C0_ALL = frozenset(chr(i) for i in range(0x20)) | {"\x7f"}

# C0 制御文字から改行・タブを除いたセット (自由記述向け)
# free-text でも null byte / vertical tab / form feed 等は処理バグの元になるので拒否。
_C0_DANGEROUS = frozenset(
    chr(i) for i in range(0x20) if chr(i) not in ("\t", "\n", "\r")
) | {"\x7f"}


def reject_ctrl_and_bidi(
    value: Optional[str], field_name: str, max_len: int = 200
) -> Optional[str]:
    """短い識別子向け: C0 制御文字 (改行含む) + BIDI を全拒否し、長さ上限を check。

    None はそのまま透過する (任意フィールド向け)。
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise HTTPException(
            status_code=422, detail=f"{field_name} must be a string"
        )
    if len(value) > max_len:
        raise HTTPException(
            status_code=422, detail=f"{field_name} too long (max {max_len})"
        )
    disallowed = _C0_ALL
    for ch in value:
        if ch in disallowed or is_invisible_format_char(ch):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{field_name} contains disallowed control/format "
                    f"character (U+{ord(ch):04X})"
                ),
            )
    return value


def reject_bidi_only(
    value: Optional[str], field_name: str, max_len: int = 5000
) -> Optional[str]:
    """長い自由記述向け: 改行・タブは許可、それ以外の C0 + BIDI を拒否。

    free-text な statement_text や scope_description で改行を許容しつつ、
    UI 表示偽装に使われる format char は許さない。
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise HTTPException(
            status_code=422, detail=f"{field_name} must be a string"
        )
    if len(value) > max_len:
        raise HTTPException(
            status_code=422, detail=f"{field_name} too long (max {max_len})"
        )
    disallowed = _C0_DANGEROUS
    for ch in value:
        if ch in disallowed or is_invisible_format_char(ch):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{field_name} contains disallowed control/format "
                    f"character (U+{ord(ch):04X})"
                ),
            )
    return value
