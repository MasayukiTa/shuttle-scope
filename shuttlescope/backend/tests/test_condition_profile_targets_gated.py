"""ベストプロフィールの目標レンジ・ギャップは標本が足りるときだけ出す (監査 #74 / #75)。

上位群が 1 件だと min = max = 生値で、1 試合分の値が「目標値」に見える。
標本不足では target_* / gap を None にし、targets_withheld=True で理由を伝える。
"""
from __future__ import annotations

from datetime import date, timedelta

from backend.analysis.condition_analytics import (
    PROFILE_TARGET_MIN_TOTAL,
    best_performance_profile,
)


def _cond(pid: int, dt: date, cid: int, ccs: float, sleep: float) -> dict:
    return {
        "id": cid,
        "player_id": pid,
        "measured_at": dt,
        "recorded_at": dt.isoformat(),
        "ccs_score": ccs,
        "sleep_hours": sleep,
        "condition_type": "weekly",
    }


def _match(mid: int, dt: date, pid: int, result: str) -> dict:
    return {
        "id": mid, "date": dt, "result": result,
        "player_a_id": pid, "player_b_id": 999,
        "partner_a_id": None, "partner_b_id": None,
    }


def _build(n: int):
    pid = 501
    base = date(2026, 3, 1)
    conds, matches = [], []
    for i in range(n):
        d = base + timedelta(days=i * 7)
        # 後半ほど勝ち・睡眠が長い (値は架空)
        conds.append(_cond(pid, d, i + 1, ccs=70.0 + i * 3, sleep=5.0 + i * 0.4))
        matches.append(_match(100 + i, d, pid, "win" if i >= n // 2 else "loss"))
    return conds, matches


def test_small_sample_withholds_targets_and_gap():
    conds, matches = _build(3)
    out = best_performance_profile(conds, matches)
    assert out["key_factors"], "小標本でも関連の方向そのものは返る"
    assert out["targets_withheld"] is True
    for f in out["key_factors"]:
        assert f["target_min"] is None
        assert f["target_max"] is None
        assert f["target_mean"] is None
        assert f["gap"] is None


def test_enough_sample_returns_targets():
    conds, matches = _build(PROFILE_TARGET_MIN_TOTAL + 2)
    out = best_performance_profile(conds, matches)
    assert out["targets_withheld"] is False
    assert out["n_top"] >= 3
    assert any(f["target_min"] is not None for f in out["key_factors"])
