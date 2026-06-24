"""
test_dr_ope_engine.py — dr_ope_engine.py のユニットテスト (純粋関数, numpy のみ)

テストシナリオ:
  1. 合成状態: 'good' 行動が win ≈ 0.9, 'bad' が win ≈ 0.1, 行動方策は 50/50
     → ターゲット方策 (ソフトマックス) が 'good' にマスを集中させる
     → value_target > value_behavior, uplift > 0
     → CI: ci_low < ci_high (非縮退)

  2. 行動方策が既に貪欲 (softmax と同一) のとき uplift ≈ 0

  3. 報酬が q と完全一致するとき IPS 残差項がゼロ → dr_value = direct_value

  4. 各関数のエッジケース (空辞書, 最小サンプル未達 → None)
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from backend.analysis.dr_ope_engine import (
    MIN_STATE_SAMPLES,
    bootstrap_ci,
    direct_value,
    dr_value,
    empirical_policy,
    evaluate_state,
    q_hat,
    softmax_target_policy,
)


# ── ヘルパー ─────────────────────────────────────────────────────────────────

def _make_records(n_good: int, n_bad: int, good_win_prob: float = 0.9, bad_win_prob: float = 0.1, seed: int = 42) -> list[dict]:
    """合成レコードを生成する。"""
    rng = np.random.default_rng(seed)
    recs: list[dict] = []
    for _ in range(n_good):
        recs.append({"a": "good", "win": int(rng.random() < good_win_prob)})
    for _ in range(n_bad):
        recs.append({"a": "bad", "win": int(rng.random() < bad_win_prob)})
    return recs


# ── empirical_policy ─────────────────────────────────────────────────────────

class TestEmpiricalPolicy:
    def test_normalized(self):
        counts = {"smash": 60, "net": 40}
        pi = empirical_policy(counts)
        assert math.isclose(pi["smash"], 0.6, abs_tol=1e-9)
        assert math.isclose(pi["net"], 0.4, abs_tol=1e-9)
        assert math.isclose(sum(pi.values()), 1.0, abs_tol=1e-9)

    def test_single_action(self):
        counts = {"smash": 10}
        pi = empirical_policy(counts)
        assert math.isclose(pi["smash"], 1.0, abs_tol=1e-9)

    def test_all_zero_returns_uniform(self):
        counts = {"a": 0, "b": 0}
        pi = empirical_policy(counts)
        assert math.isclose(pi["a"], 0.5, abs_tol=1e-9)
        assert math.isclose(pi["b"], 0.5, abs_tol=1e-9)


# ── q_hat ────────────────────────────────────────────────────────────────────

class TestQHat:
    def test_laplace_smoothing(self):
        """全勝の場合でも Laplace 平滑化で 1.0 未満になる。"""
        recs = [{"a": "good", "win": 1}] * 10
        q = q_hat(recs)
        assert q["good"] < 1.0
        assert q["good"] > 0.9  # (10+1)/(10+2) = 11/12 ≈ 0.917

    def test_zero_wins(self):
        """全敗の場合でも 0 より大きい (Laplace 平滑化)。"""
        recs = [{"a": "bad", "win": 0}] * 10
        q = q_hat(recs)
        assert q["bad"] > 0.0
        assert q["bad"] < 0.1  # (0+1)/(10+2) = 1/12 ≈ 0.083

    def test_high_low_split(self):
        """高勝率行動と低勝率行動が正しく分かれる。"""
        recs = _make_records(100, 100)
        q = q_hat(recs)
        assert q["good"] > q["bad"]
        assert q["good"] > 0.7
        assert q["bad"] < 0.3

    def test_none_action_skipped(self):
        recs = [{"a": None, "win": 1}, {"a": "good", "win": 1}]
        q = q_hat(recs)
        assert "good" in q
        assert None not in q


# ── softmax_target_policy ────────────────────────────────────────────────────

class TestSoftmaxTargetPolicy:
    def test_sums_to_one(self):
        q = {"good": 0.9, "bad": 0.1}
        pi = softmax_target_policy(q, temp=0.25)
        assert math.isclose(sum(pi.values()), 1.0, abs_tol=1e-9)

    def test_favors_high_q_action(self):
        q = {"good": 0.9, "bad": 0.1}
        pi = softmax_target_policy(q, temp=0.25)
        assert pi["good"] > pi["bad"]

    def test_low_temp_approaches_greedy(self):
        """低温ではほぼ最良行動に集中する。"""
        q = {"good": 0.9, "bad": 0.1}
        pi = softmax_target_policy(q, temp=0.01)
        assert pi["good"] > 0.99

    def test_high_temp_approaches_uniform(self):
        """高温では一様分布に近づく。"""
        q = {"good": 0.9, "bad": 0.1}
        pi = softmax_target_policy(q, temp=100.0)
        assert abs(pi["good"] - pi["bad"]) < 0.1

    def test_empty_q(self):
        assert softmax_target_policy({}) == {}


# ── direct_value ─────────────────────────────────────────────────────────────

class TestDirectValue:
    def test_basic(self):
        pi = {"good": 0.6, "bad": 0.4}
        q = {"good": 0.9, "bad": 0.1}
        v = direct_value(pi, q)
        expected = 0.6 * 0.9 + 0.4 * 0.1
        assert math.isclose(v, expected, abs_tol=1e-9)

    def test_missing_action_in_q(self):
        """q に存在しない行動は 0 扱い。"""
        pi = {"a": 0.5, "b": 0.5}
        q = {"a": 0.8}
        v = direct_value(pi, q)
        assert math.isclose(v, 0.5 * 0.8, abs_tol=1e-9)


# ── dr_value ─────────────────────────────────────────────────────────────────

class TestDrValue:
    def test_ips_zero_when_reward_equals_q(self):
        """報酬が q と完全一致するとき IPS 残差項はゼロ → dr_value = direct_value(π_e, q)。"""
        q = {"good": 0.8, "bad": 0.2}
        pi_b = {"good": 0.5, "bad": 0.5}
        pi_e = softmax_target_policy(q, temp=0.25)

        # 報酬 = q 値そのもの (整数にするため round して 0 or 1 は不可、
        # 代わりに報酬を浮動小数点 q 値に設定して残差 r - q(a) = 0 を作る)
        # ただし win は 0/1 なので r と q は完全一致不可→代わりに人工合成:
        # good のみ 10 件、全て win=round(q["good"])=1 として近似する代わりに
        # 残差がゼロになる特殊ケースを直接テスト:
        # r_i = q(a_i) のとき (r_i - q(a_i)) = 0

        # 特殊合成: good=10件 win=0.8(float) は整数制約上無理。
        # 代わりに IPS 残差が数値的にゼロになる条件で確認:
        # good: win=1, q=1 → 1-1=0 (1.0 に丸める代わりに q=Laplace smoothed)
        # ここでは q を手動設定して残差ゼロを保証する人工ケースを使う

        # r_i = q(a_i) を直接設定した人工レコード
        recs_exact: list[dict] = []
        for _ in range(20):
            recs_exact.append({"a": "good", "win": q["good"]})  # type: ignore[arg-type]
        for _ in range(20):
            recs_exact.append({"a": "bad", "win": q["bad"]})  # type: ignore[arg-type]

        v_dr = dr_value(recs_exact, pi_b, pi_e, q)
        v_dm = direct_value(pi_e, q)
        assert math.isclose(v_dr, v_dm, abs_tol=1e-6), (
            f"IPS 残差がゼロのとき dr_value={v_dr:.6f} は direct_value={v_dm:.6f} に一致すべき"
        )

    def test_dr_value_sign(self):
        """π_e が 'good' に寄っているとき dr_value > direct_value(π_b, q)。"""
        recs = _make_records(100, 100, seed=7)
        q = q_hat(recs)
        action_counts = {"good": 100, "bad": 100}
        pi_b = empirical_policy(action_counts)
        pi_e = softmax_target_policy(q, temp=0.25)

        v_behavior = direct_value(pi_b, q)
        v_target = dr_value(recs, pi_b, pi_e, q)
        # ターゲット方策は高 Q 行動に寄るため通常は uplift > 0
        assert v_target > v_behavior

    def test_uncovered_action_clipped(self):
        """π_b がカバーしない行動 (prob=0) は IPS 残差をゼロクリップ。"""
        q = {"good": 0.8, "bad": 0.2, "rare": 0.5}
        pi_b = {"good": 0.6, "bad": 0.4, "rare": 0.0}  # rare はカバーなし
        pi_e = {"good": 0.5, "bad": 0.3, "rare": 0.2}
        recs = [{"a": "rare", "win": 1}] * 10
        # rare 行動のみ → IPS 残差がクリップされて dr ≈ dm_term (= direct_value(π_e, q))
        v_dr = dr_value(recs, pi_b, pi_e, q)
        v_dm = direct_value(pi_e, q)
        assert math.isclose(v_dr, v_dm, abs_tol=1e-9)


# ── bootstrap_ci ─────────────────────────────────────────────────────────────

class TestBootstrapCI:
    def test_ci_ordered(self):
        """CI 下限 < CI 上限。"""
        recs = _make_records(100, 100)
        q = q_hat(recs)
        pi_b = empirical_policy({"good": 100, "bad": 100})
        pi_e = softmax_target_policy(q, temp=0.25)
        low, high = bootstrap_ci(recs, pi_b, pi_e, q, n_boot=500, seed=0)
        assert low < high

    def test_ci_reproducible(self):
        """同一シードで同一 CI を返す。"""
        recs = _make_records(80, 80)
        q = q_hat(recs)
        pi_b = empirical_policy({"good": 80, "bad": 80})
        pi_e = softmax_target_policy(q, temp=0.25)
        ci1 = bootstrap_ci(recs, pi_b, pi_e, q, n_boot=200, seed=42)
        ci2 = bootstrap_ci(recs, pi_b, pi_e, q, n_boot=200, seed=42)
        assert ci1 == ci2

    def test_ci_different_seeds(self):
        """異なるシードでは結果が異なる (ほぼ確実)。"""
        recs = _make_records(80, 80)
        q = q_hat(recs)
        pi_b = empirical_policy({"good": 80, "bad": 80})
        pi_e = softmax_target_policy(q, temp=0.25)
        ci1 = bootstrap_ci(recs, pi_b, pi_e, q, n_boot=200, seed=0)
        ci2 = bootstrap_ci(recs, pi_b, pi_e, q, n_boot=200, seed=99)
        # 微妙に差があるはず (厳密に等しくなる確率はほぼゼロ)
        assert ci1 != ci2


# ── evaluate_state (統合テスト) ───────────────────────────────────────────────

class TestEvaluateState:
    def test_insufficient_samples_returns_none(self):
        """最小サンプル未達のとき None を返す。"""
        recs = _make_records(5, 5)  # 合計 10 < MIN_STATE_SAMPLES=20
        result = evaluate_state(recs, temp=0.25, n_boot=200, seed=0)
        assert result is None

    def test_uplift_positive_when_behavior_is_random(self):
        """行動方策が 50/50 のとき、ターゲット (高 Q 偏重) の uplift > 0。"""
        # good: win ≈ 0.9, bad: win ≈ 0.1, 50/50 の行動方策
        recs = _make_records(200, 200, seed=0)
        result = evaluate_state(recs, temp=0.25, n_boot=500, seed=0)
        assert result is not None
        assert result["uplift"] > 0, f"uplift={result['uplift']:.4f} は正であるべき"
        assert result["value_target"] > result["value_behavior"], (
            f"value_target={result['value_target']:.4f} > value_behavior={result['value_behavior']:.4f} であるべき"
        )

    def test_ci_contains_point_estimate(self):
        """CI は point estimate (value_target) を概ね含む。"""
        recs = _make_records(200, 200, seed=1)
        result = evaluate_state(recs, temp=0.25, n_boot=500, seed=0)
        assert result is not None
        # ブートストラップ CI は中心の推定値を内包するはず (90% CI)
        assert result["ci_low"] < result["value_target"] < result["ci_high"], (
            f"CI=[{result['ci_low']:.4f}, {result['ci_high']:.4f}] は "
            f"value_target={result['value_target']:.4f} を含むべき"
        )

    def test_uplift_near_zero_when_behavior_equals_greedy(self):
        """行動方策が既に貪欲なとき uplift ≈ 0。"""
        # good のみ選択する貪欲方策 (bad をほぼ使わない)
        # good: 190 件, bad: 10 件 → π_b は good に強く偏る
        recs = _make_records(190, 10, good_win_prob=0.9, bad_win_prob=0.1, seed=2)
        # ソフトマックス温度を非常に低く (≈ 貪欲) してターゲットも good 集中
        result = evaluate_state(recs, temp=0.01, n_boot=200, seed=0)
        assert result is not None
        # π_b が既に good 集中 (≈ π_e) のため uplift ≈ 0
        assert abs(result["uplift"]) < 0.1, (
            f"uplift={result['uplift']:.4f} は貪欲方策では ≈0 であるべき"
        )

    def test_result_keys(self):
        """返り値に必須キーがすべて含まれる。"""
        recs = _make_records(100, 100, seed=3)
        result = evaluate_state(recs, temp=0.25, n_boot=100, seed=0)
        assert result is not None
        expected_keys = {
            "n", "value_behavior", "value_target", "uplift",
            "ci_low", "ci_high", "behavior_policy", "target_policy",
        }
        assert expected_keys.issubset(result.keys())

    def test_policy_sums_to_one(self):
        """behavior_policy と target_policy の確率の和 ≈ 1。"""
        recs = _make_records(100, 100, seed=4)
        result = evaluate_state(recs, temp=0.25, n_boot=100, seed=0)
        assert result is not None
        assert math.isclose(sum(result["behavior_policy"].values()), 1.0, abs_tol=1e-3)
        assert math.isclose(sum(result["target_policy"].values()), 1.0, abs_tol=1e-3)

    def test_ci_low_less_than_high(self):
        """CI 下限 < CI 上限。"""
        recs = _make_records(100, 100, seed=5)
        result = evaluate_state(recs, temp=0.25, n_boot=300, seed=0)
        assert result is not None
        assert result["ci_low"] < result["ci_high"]
