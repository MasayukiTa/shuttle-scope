"""ユーザ入力サニタイズ。

検知のみ。ブロックは呼び出し側の責務。
"""
from __future__ import annotations

import re


_MAX_LEN = 2000

_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+previous\s+instructions", re.IGNORECASE),
    re.compile(r"system\s+prompt", re.IGNORECASE),
    re.compile(r"you\s+are\s+now", re.IGNORECASE),
    re.compile(r"act\s+as\s+if\s+you", re.IGNORECASE),
    re.compile(r"forget\s+your\s+rules", re.IGNORECASE),
    re.compile(r"新しい指示"),
    re.compile(r"システムプロンプト"),
    re.compile(r"前の指示を無視"),
)

# Bounded quantifiers eliminate polynomial backtracking on adversarial
# inputs (CodeQL py/polynomial-redos). Caps are above any legitimate
# value: HTML tags > 200 chars don't appear in real prose; runs > 2000
# chars are already truncated by _MAX_LEN above.
_HTML_TAG_RE = re.compile(r"<[^<>]{1,200}>")
_REPEATED_CHAR_RE = re.compile(r"(.)\1{50,2000}")


def sanitize_user_input(text: str) -> tuple[str, list[str]]:
    """危険パターンを除去し (cleaned, flags) を返す。

    Returns:
        (cleaned text, list of flags). 空 list = 安全。
    """
    flags: list[str] = []
    cleaned = text or ""

    # 1) 長さ
    if len(cleaned) > _MAX_LEN:
        cleaned = cleaned[:_MAX_LEN]
        flags.append("truncated")

    # 2) injection パターン (検知のみ、テキストは残す)
    for pat in _INJECTION_PATTERNS:
        if pat.search(cleaned):
            flags.append("injection_attempt")
            break

    # 3) HTML タグ除去 (subn = 1パスで removal + count)
    cleaned, n_html = _HTML_TAG_RE.subn("", cleaned)
    if n_html:
        flags.append("html_stripped")

    # 4) スパム連続文字 (truncated でない場合のみ collapse、1パスで処理)
    if "truncated" not in flags:
        cleaned, n_spam = _REPEATED_CHAR_RE.subn(lambda m: m.group(1) * 50, cleaned)
        if n_spam:
            flags.append("spam_chars")

    return cleaned, flags
