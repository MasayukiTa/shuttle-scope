"""test_conformal_engine.py — conformal_engine の数値検証

テスト設計:
- 既知の勝率を持つグループで合成データを生成し、
  split-conformal の被覆保証 (empirical_coverage >= 1 - alpha - tolerance) を検証する。
- 大量サンプル (2000 点) で alpha=0.1, 0.2 の両方を確認する。
- prediction_set が q の大小に応じて {win,loss} または singleton を返すことを検証する。
"""
import numpy as np

from backend.analysis.conformal_engine import (
    fit_group_winrates,
    predict_p_win,
    split_conformal,
    prediction_set,
    evaluate_coverage,
)


# ── ヘルパー: 合成データ生成 ────────────────────────────────────────────────────

def _make_synthetic_data(n: int, rng: np.random.Generator) -> tuple[list[str], list[int]]:
    """
    2 グループ (A: p_win=0.7, B: p_win=0.3) を均等に生成する。
    グループキーと勝敗ラベルのリストを返す。
    """
    groups: list[str] = []
    wins: list[int] = []
    for i in range(n):
        if i % 2 == 0:
            g = "A"
            p = 0.7
        else:
            g = "B"
            p = 0.3
        w = int(rng.random() < p)
        groups.append(g)
        wins.append(w)
    return groups, wins


# ── テスト ──────────────────────────────────────────────────────────────────────

class TestSplitConformalCoverage:
    """split_conformal + evaluate_coverage の保証検証。"""

    def _run_coverage_check(self, alpha: float, n: int = 2000, tolerance: float = 0.02):
        """
        n 点合成データを校正/テスト 50/50 に分割し、
        経験的被覆率 >= 1 - alpha - tolerance を確認する。
        """
        rng = np.random.default_rng(42)
        groups, wins = _make_synthetic_data(n, rng)

        # 校正/テスト分割
        cal_idx = [i for i in range(n) if i % 2 == 0]
        test_idx = [i for i in range(n) if i % 2 == 1]

        cal_groups = [groups[i] for i in cal_idx]
        cal_wins = [wins[i] for i in cal_idx]
        test_groups = [groups[i] for i in test_idx]
        test_wins = [wins[i] for i in test_idx]

        # ベーススコアラー
        winrate_map = fit_group_winrates(cal_groups, cal_wins)

        p_hat_cal = np.array([predict_p_win(g, winrate_map) for g in cal_groups])
        y_cal = np.array(cal_wins, dtype=float)

        # コンフォーマル分位点
        q = split_conformal(p_hat_cal, y_cal, alpha)

        # テスト被覆率
        p_hat_test = np.array([predict_p_win(g, winrate_map) for g in test_groups])
        y_test = np.array(test_wins, dtype=float)
        result = evaluate_coverage(p_hat_test, y_test, q)

        empirical = result["empirical_coverage"]
        target = 1.0 - alpha
        assert empirical is not None
        assert empirical >= target - tolerance, (
            f"被覆率保証未達: empirical={empirical:.4f} < target={target:.4f} - tol={tolerance:.4f}"
            f" (alpha={alpha})"
        )
        return result

    def test_coverage_alpha_0_10(self):
        """alpha=0.1 → 90% 被覆率保証の検証。"""
        self._run_coverage_check(alpha=0.1, n=2000, tolerance=0.02)

    def test_coverage_alpha_0_20(self):
        """alpha=0.2 → 80% 被覆率保証の検証。"""
        self._run_coverage_check(alpha=0.2, n=2000, tolerance=0.02)

    def test_avg_set_size_reasonable(self):
        """平均集合サイズが 1 以上 2 以下であること (abstain が過剰でない)。"""
        result = self._run_coverage_check(alpha=0.1, n=2000, tolerance=0.02)
        avg = result["avg_set_size"]
        assert avg is not None
        assert 1.0 <= avg <= 2.0


class TestPredictionSet:
    """prediction_set の挙動検証。"""

    def test_abstain_when_q_large(self):
        """q=1.0 のとき全点を abstain ({win,loss}) にする。"""
        pset = prediction_set(0.5, q=1.0)
        assert "win" in pset
        assert "loss" in pset

    def test_singleton_win_when_q_small(self):
        """q がほぼ 0 かつ p_win が高いとき、{win} のみを返す。"""
        pset = prediction_set(0.99, q=0.01)
        assert "win" in pset
        assert "loss" not in pset

    def test_singleton_loss_when_q_small_and_p_win_low(self):
        """q がほぼ 0 かつ p_win が低いとき、{loss} のみを返す。"""
        pset = prediction_set(0.01, q=0.01)
        assert "loss" in pset
        assert "win" not in pset

    def test_empty_only_when_q_negative(self):
        """q < 0 (理論上発生しないが) のとき空集合。"""
        pset = prediction_set(0.5, q=-0.1)
        assert len(pset) == 0

    def test_both_when_p_win_mid_and_q_large(self):
        """p_win=0.5 かつ q=0.6 のとき {loss, win} 両方を含む。"""
        pset = prediction_set(0.5, q=0.6)
        assert "win" in pset
        assert "loss" in pset


class TestFitGroupWinrates:
    """fit_group_winrates の Laplace 平滑化検証。"""

    def test_known_group_winrate(self):
        """全勝グループの P(win) が Laplace 補正後も高いこと。"""
        groups = ["X"] * 10
        wins = [1] * 10
        wr = fit_group_winrates(groups, wins)
        # (10 + 1) / (10 + 2) = 11/12 ≈ 0.917
        assert abs(wr["X"] - 11 / 12) < 1e-9

    def test_unknown_group_returns_0_5(self):
        """未知グループには 0.5 を返すこと。"""
        wr = fit_group_winrates(["A"], [1])
        p = predict_p_win("Z", wr)
        assert p == 0.5

    def test_zero_sample_single_group(self):
        """単一サンプルのグループで Laplace 平滑化が効くこと。"""
        wr = fit_group_winrates(["G"], [0])
        # (0 + 1) / (1 + 2) = 1/3 ≈ 0.333
        assert abs(wr["G"] - 1 / 3) < 1e-9


class TestSplitConformalFormula:
    """split_conformal の分位点計算式の検証。"""

    def test_empty_calibration_returns_one(self):
        """校正集合が空のとき q=1.0 (常に abstain) を返すこと。"""
        q = split_conformal(np.array([]), np.array([]), alpha=0.1)
        assert q == 1.0

    def test_all_correct_scores_are_zero(self):
        """予測が完全に正確なとき非適合スコアは全て 0。
        q=ceil((n+1)(1-alpha))/n 番目の分位点 = 0 となり、
        予測集合は singleton になること。
        """
        # p_win=1.0 かつ y=1 のとき s = 1 - p̂(win) = 0
        n = 50
        p_hat_cal = np.ones(n)
        y_cal = np.ones(n)
        q = split_conformal(p_hat_cal, y_cal, alpha=0.1)
        assert q < 0.1  # 非適合スコアが全て 0 → q ≈ 0

    def test_quantile_clips_at_one(self):
        """n=1 かつ alpha=0.1 のとき ceil((1+1)*0.9)/1 = 2 → クリップで 1.0。"""
        q = split_conformal(np.array([0.5]), np.array([1.0]), alpha=0.1)
        assert q <= 1.0

    def test_evaluate_coverage_empty(self):
        """テスト集合が空のとき None を返すこと。"""
        result = evaluate_coverage(np.array([]), np.array([]), q=0.5)
        assert result["empirical_coverage"] is None
        assert result["avg_set_size"] is None
        assert result["n"] == 0
