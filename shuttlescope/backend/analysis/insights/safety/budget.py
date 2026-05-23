"""ユーザ単位の 1 日トークン予算。プロセス内 in-memory のみ (POC)。"""
from __future__ import annotations

import os
from datetime import date


INSIGHT_BUDGET_DAILY_TOKENS = int(os.getenv("INSIGHT_BUDGET_DAILY_TOKENS", "50000"))

_state: dict[int, dict[str, int]] = {}


def _today_iso() -> str:
    return date.today().isoformat()


def check_and_record_budget(user_id: int | None, tokens: int) -> tuple[bool, int]:
    """予算チェック & 記録。

    Returns:
        (allowed, remaining). 拒否時は False / 残量 (記録しない)。
    """
    if user_id is None:
        return False, 0

    today = _today_iso()
    bucket = _state.setdefault(int(user_id), {})
    used = bucket.get(today, 0)
    proposed = used + max(int(tokens), 0)
    remaining_if_allowed = INSIGHT_BUDGET_DAILY_TOKENS - proposed

    if proposed > INSIGHT_BUDGET_DAILY_TOKENS:
        return False, max(INSIGHT_BUDGET_DAILY_TOKENS - used, 0)

    bucket[today] = proposed
    return True, max(remaining_if_allowed, 0)


def reset_for_test() -> None:
    """テスト用フック。"""
    _state.clear()
