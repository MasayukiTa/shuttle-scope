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



# ── 表示名 (display_name) の長さルール ───────────────────────────────────────
# 表示名の文字数ルールを **バックエンドで唯一化** する。各エントリポイント
# (admin create / admin update / 公開登録 / 招待受諾) がこの関数を
# 呼ぶことで、長さルールが一箇所でしか定義されない。
#
# 文字数は前後の空白を除いた後の Unicode コードポイント数で数える。
# 全角文字も 1 文字として数える (len() がコードポイント数)。
DISPLAY_NAME_MIN_LENGTH = 6
DISPLAY_NAME_MAX_LENGTH = 24

# 前後の trim は ASCII whitespace に加えて一般的な Unicode whitespace
# (U+3000 表意空白等) も前後から除く。内部の空白は残す。
_DISPLAY_NAME_TRIM_WS = frozenset(
    [chr(i) for i in range(0x21)] + [  # 0x00-0x20 (ASCII whitespace/control incl. space)
        "\x7f", "\u0085", "\u00a0", "\u1680",
        "\u2000", "\u2001", "\u2002", "\u2003", "\u2004", "\u2005",
        "\u2006", "\u2007", "\u2008", "\u2009", "\u200a",
        "\u2028", "\u2029", "\u202f", "\u205f", "\u3000", "\ufeff",
    ]
)


def trim_display_name(value: str) -> str:
    """表示名の前後の空白 (ASCII + 主要な Unicode whitespace) を除く。"""
    chars = list(value)
    start = 0
    end = len(chars)
    while start < end and chars[start] in _DISPLAY_NAME_TRIM_WS:
        start += 1
    while end > start and chars[end - 1] in _DISPLAY_NAME_TRIM_WS:
        end -= 1
    return "".join(chars[start:end])


def display_name_length(value: str) -> int:
    """trim 後の Unicode コードポイント数 (全角 = 1)。"""
    return len(trim_display_name(value))


def display_name_conforms(value: Optional[str]) -> bool:
    """表示名が 6〜24 文字ルールを満たすか (制御文字等は含まない)。

    レガシーユーザーの非適合名を一覧でマーカー表示するための判定。
    例外を送出せず bool を返す (ログインや表示をブロックしない)。
    None / 空 / 長さ外 / 不可視文字混入はすべて False。
    """
    if value is None:
        return False
    trimmed = trim_display_name(value)
    if not (DISPLAY_NAME_MIN_LENGTH <= len(trimmed) <= DISPLAY_NAME_MAX_LENGTH):
        return False
    for ch in trimmed:
        if ch in _C0_ALL or is_invisible_format_char(ch):
            return False
    return True


def validate_display_name(value: Optional[str], field_name: str = "display_name") -> str:
    """表示名を検証し、trim 済みの値を返す。違反時は 422。

    - 制御文字 / BIDI / ゼロ幅文字を拒否 (reject_ctrl_and_bidi と同じ文字集合)。
    - 前後の空白を trim した上で Unicode コードポイント数で 6〜24 を強制 (全角 = 1)。
    - メッセージは日本語 + 英語で許容長を明示する。
    """
    if value is None or not isinstance(value, str):
        raise HTTPException(
            status_code=422,
            detail=(
                f"{field_name} は必須です。"
                f"{DISPLAY_NAME_MIN_LENGTH}〜{DISPLAY_NAME_MAX_LENGTH}文字で入力してください。 / "
                f"{field_name} is required and must be "
                f"{DISPLAY_NAME_MIN_LENGTH}-{DISPLAY_NAME_MAX_LENGTH} characters."
            ),
        )
    # 制御 / BIDI / ゼロ幅文字は trim 前に全体を検査して拒否する。
    for ch in value:
        if ch in _C0_ALL or is_invisible_format_char(ch):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{field_name} contains disallowed control/format "
                    f"character (U+{ord(ch):04X})"
                ),
            )
    trimmed = trim_display_name(value)
    n = len(trimmed)
    if not (DISPLAY_NAME_MIN_LENGTH <= n <= DISPLAY_NAME_MAX_LENGTH):
        raise HTTPException(
            status_code=422,
            detail=(
                f"{field_name} は{DISPLAY_NAME_MIN_LENGTH}〜{DISPLAY_NAME_MAX_LENGTH}文字で入力してください"
                f"（前後の空白を除き、全角文字も1文字として数えます。現在 {n} 文字）。 / "
                f"{field_name} must be {DISPLAY_NAME_MIN_LENGTH}-{DISPLAY_NAME_MAX_LENGTH} characters "
                f"(after trimming surrounding whitespace; full-width characters count as 1; got {n})."
            ),
        )
    return trimmed
