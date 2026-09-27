"""ユーザ入力サニタイズ。

検知のみ。ブロックは呼び出し側の責務。
"""
from __future__ import annotations

import base64
import binascii
import re
import unicodedata


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
    re.compile(
        r"(?:repeat|print|quote|show|reveal)[^\n]{0,24}"
        r"(?:above|previous)[^\n]{0,16}(?:text|instructions?)",
        re.IGNORECASE,
    ),
    # Chinese: ignore prior instructions / reveal the system prompt.
    re.compile(
        r"(?:\u5ffd\u7565|\u7121\u8996)[^\n]{0,12}"
        r"(?:\u4e4b\u524d|\u4ee5\u524d|\u4e0a\u9762|\u6240\u6709)[^\n]{0,12}"
        r"(?:\u6307\u4ee4|\u6307\u793a|\u89c4\u5219|\u7cfb\u7edf\u63d0\u793a)"
    ),
    re.compile(
        r"(?:\u663e\u793a|\u8f93\u51fa|\u91cd\u590d|\u6cc4\u9732)[^\n]{0,16}"
        r"(?:\u7cfb\u7edf\u63d0\u793a|\u9690\u85cf\u6307\u4ee4)"
    ),
    # German.
    re.compile(
        r"ignorier(?:e|en)?[^\n]{0,28}(?:vorherigen|früheren|obigen|alle)[^\n]{0,20}"
        r"(?:anweisungen|instruktionen|regeln)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:zeige|wiederhole|verrate)[^\n]{0,28}"
        r"(?:system[- ]?prompt|versteckte\s+anweisungen|obige\s+anweisungen)",
        re.IGNORECASE,
    ),
)

# Bounded quantifiers eliminate polynomial backtracking on adversarial
# inputs (CodeQL py/polynomial-redos). Caps are above any legitimate
# value: HTML tags > 200 chars don't appear in real prose; runs > 2000
# chars are already truncated by _MAX_LEN above.
_HTML_TAG_RE = re.compile(r"<[^<>]{1,200}>")
_REPEATED_CHAR_RE = re.compile(r"(.)\1{50,2000}")
_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u2060\ufeff]")
_BASE64_CANDIDATE_RE = re.compile(
    r"(?<![A-Za-z0-9+/_-])([A-Za-z0-9+/_-]{20,512}={0,2})(?![A-Za-z0-9+/_-])"
)


def _normalize_for_detection(text: str) -> str:
    return _ZERO_WIDTH_RE.sub("", unicodedata.normalize("NFKC", text))


def _matches_injection(text: str) -> bool:
    return any(pat.search(text) for pat in _INJECTION_PATTERNS)


def _decoded_base64_injection(text: str) -> bool:
    for match in _BASE64_CANDIDATE_RE.finditer(text):
        token = match.group(1)
        padded = token + ("=" * ((4 - len(token) % 4) % 4))
        try:
            raw = base64.b64decode(
                padded.encode("ascii"), altchars=b"-_", validate=True
            )
        except (binascii.Error, ValueError, UnicodeEncodeError):
            continue
        if not raw or len(raw) > 1024:
            continue
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if _matches_injection(_normalize_for_detection(decoded)):
            return True
    return False


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

    # 2) injection patterns (detection only; keep the original text).
    # NFKC + zero-width removal prevents trivial visual obfuscation. Base64 is
    # inspected only when the decoded UTF-8 itself matches an injection pattern.
    detection_text = _normalize_for_detection(cleaned)
    if _matches_injection(detection_text):
        flags.append("injection_attempt")
    elif _decoded_base64_injection(detection_text):
        flags.extend(("injection_attempt", "encoded_instruction"))

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
