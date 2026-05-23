"""LLM 出力バリデータ。

順に検査し最初の失敗で打ち切り:
1. 短すぎ / 長すぎ
2. 禁止語
3. リフューザル分類トピック
4. JSON 混入
5. 数値整合性
6. AI self-reference (警告のみ)
"""
from __future__ import annotations

import re
from typing import TypedDict

from backend.analysis.insights.safety.system_prompts import (
    BANNED_TERMS_EN,
    BANNED_TERMS_JA,
    REFUSAL_CATEGORIES,
)


class ValidationResult(TypedDict):
    ok: bool
    reason: str | None


_JSON_RE = re.compile(r"\{[^}]*:[^}]*\}")
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?%?")
_N_EQ_RE = re.compile(r"N\s*=\s*(\d+)", re.IGNORECASE)

# 普遍的に安全な数値 (回数 / 一般的な %)
_UNIVERSAL_SAFE = {0.0, 1.0, 2.0, 3.0, 5.0, 10.0, 100.0}

_AI_SELF_REF = (
    "as an ai",
    "私はaiとして",
    "私は ai として",
    "i am an ai",
)


def _flatten_metric_numbers(d: dict | list | float | int | str) -> set[float]:
    """metric dict を再帰的に走査し数値の set を返す。"""
    out: set[float] = set()
    if isinstance(d, dict):
        for v in d.values():
            out |= _flatten_metric_numbers(v)
    elif isinstance(d, list):
        for v in d:
            out |= _flatten_metric_numbers(v)
    elif isinstance(d, (int, float)) and not isinstance(d, bool):
        out.add(float(d))
    return out


def _number_explained(num_str: str, allowed: set[float]) -> bool:
    """num_str (e.g. "73%", "0.52") が allowed のいずれかと一致するか。"""
    is_pct = num_str.endswith("%")
    raw = num_str[:-1] if is_pct else num_str
    try:
        n = float(raw)
    except ValueError:
        return True  # parse 不能なら見逃す

    if is_pct:
        # % 表記: allowed 側が 0..1 比率なら *100 と比較、または直接 % としても比較
        candidates_pct = set()
        for a in allowed:
            if 0.0 <= a <= 1.0:
                candidates_pct.add(a * 100.0)
            candidates_pct.add(a)
        for c in candidates_pct:
            if abs(n - c) <= 2.0:
                return True
        return n in {v * 100.0 for v in _UNIVERSAL_SAFE} or n in _UNIVERSAL_SAFE
    else:
        # 整数 ±0.5、比率 (≤1) は ±0.02
        for a in allowed:
            if abs(n) > 1.0 or abs(a) > 1.0:
                if abs(n - a) <= 0.5:
                    return True
            else:
                if abs(n - a) <= 0.02:
                    return True
        if n in _UNIVERSAL_SAFE:
            return True
        return False


def validate_response(
    text: str,
    lang: str,
    allowed_metrics: dict | None,
) -> ValidationResult:
    """LLM 出力を多段バリデーション。"""
    if text is None:
        return {"ok": False, "reason": "too_short"}

    stripped = text.strip()
    # 1) 短すぎ
    if len(stripped) < 5:
        return {"ok": False, "reason": "too_short"}

    # 2) 長すぎ
    if lang == "ja":
        if len(text) > 220:
            return {"ok": False, "reason": "too_long"}
    else:
        if len(text.split()) > 110:
            return {"ok": False, "reason": "too_long"}

    lower = text.lower()

    # 3) 禁止語
    for term in BANNED_TERMS_JA:
        if term in text:
            return {"ok": False, "reason": f"banned_term:{term}"}
    for term in BANNED_TERMS_EN:
        if term.lower() in lower:
            return {"ok": False, "reason": f"banned_term:{term}"}

    # 4) リフューザル分類トピック
    for cat, kws in REFUSAL_CATEGORIES.items():
        for kw in kws:
            if kw.lower() in lower or kw in text:
                return {"ok": False, "reason": f"refusal_topic:{cat}"}

    # 5) JSON 混入
    if _JSON_RE.search(text):
        return {"ok": False, "reason": "leaked_json"}

    # 6) 数値整合性
    if allowed_metrics is not None:
        allowed_nums = _flatten_metric_numbers(allowed_metrics) | _UNIVERSAL_SAFE
        # N=X パターンは X が metrics に存在すれば許可
        n_eq_values = {float(m.group(1)) for m in _N_EQ_RE.finditer(text)}
        allowed_nums |= {v for v in n_eq_values if v in allowed_nums}

        unexplained: list[str] = []
        for m in _NUMBER_RE.finditer(text):
            num_str = m.group(0)
            if not _number_explained(num_str, allowed_nums):
                unexplained.append(num_str)
        if len(unexplained) > 1:
            return {
                "ok": True if False else False,
                "reason": f"hallucinated_numbers:{','.join(unexplained)}",
            }

    # 7) AI self-reference (警告のみ)
    for marker in _AI_SELF_REF:
        if marker in lower:
            return {"ok": True, "reason": "ai_self_reference_warn"}

    return {"ok": True, "reason": None}
