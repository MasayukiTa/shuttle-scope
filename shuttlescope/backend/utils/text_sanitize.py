"""文字列フィールドのコントロール文字 / Unicode BIDI override 拒否。

UI 表示偽装 (RTLO による拡張子偽装、ZWSP による host 偽装等) と CRLF
injection / null byte 系の処理バグを防ぐ。

短い識別子フィールドは `reject_ctrl_and_bidi` (改行も拒否)、
長い自由記述フィールドは `reject_bidi_only` (改行 / タブは許可) を使う。

それぞれ Pydantic validator やルータ内で呼び出すだけで強制できる軽量 util。
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException


# Unicode BIDI / 不可視 format character セット (admin 文書の表示偽装防止)
_BIDI_FORMAT_CHARS = frozenset({
    "​", "‌", "‍",          # ZWSP / ZWNJ / ZWJ
    " ", " ",                     # Line / Paragraph separators
    "‪", "‫", "‬", "‭", "‮",  # LRE/RLE/PDF/LRO/RLO
    "⁦", "⁧", "⁨", "⁩", "﻿",  # LRI/RLI/FSI/PDI/BOM
})

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
    disallowed = _C0_ALL | _BIDI_FORMAT_CHARS
    for ch in value:
        if ch in disallowed:
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
    disallowed = _C0_DANGEROUS | _BIDI_FORMAT_CHARS
    for ch in value:
        if ch in disallowed:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{field_name} contains disallowed control/format "
                    f"character (U+{ord(ch):04X})"
                ),
            )
    return value
