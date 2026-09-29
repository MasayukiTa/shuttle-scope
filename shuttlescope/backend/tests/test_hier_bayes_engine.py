"""
test_hier_bayes_engine.py — 階層的 Bradley-Terry エンジンの単体テスト

依存: numpy のみ (venv 不要)
実行: python -m pytest backend/tests/test_hier_bayes_engine.py -v
"""
from __future__ import annotations

import numpy as np
import pytest

from backend.analysis.hier_bayes_engine import fit_bradley_terry, predict_matchup


# ── ヘルパー ──────────────────────────────────────────────────────────────────

def _generate_pairs(
    n_games: int,
    prob_matrix: list[list[float]],
    rng: np.random.Generator,
) -> list[tuple[int, int]]:
    """prob_matrix[i][j] = P(player i beats player j) で合成対戦ペアを生成する。"""
    n = len(prob_matrix)
    pairs = []
    for _ in range(n_games):
        i = int(rng.integers(0, n))
        j = int(rng.integers(0, n))
        while j == i:
            j = int(rng.integers(0, n))
        if rng.random() < prob_matrix[i][j]:
            pairs.append((i, j))
        else:
            pairs.append((j, i))
    return pairs


# ── テスト ────────────────────────────────────────────────────────────────────

class TestFitBradleyTerry:
    """fit_bradley_terry の動作確認。"""

    def test_strength_order_recovered(self):
        """強弱関係が明確な 3 選手モデルで θ の順序が復元されること。

        設定: player 0 > player 1 > player 2
        P(0 beats 1) = 0.75, P(1 beats 2) = 0.75, P(0 beats 2) = 0.90
        十分な対戦数 (各 100 試合) があれば順序 θ_0 > θ_1 > θ_2 が回復されるはず。
        """
        rng = np.random.default_rng(42)
        prob = [
            [0.5, 0.75, 0.90],
            [0.25, 0.5, 0.75],
            [0.10, 0.25, 0.5],
        ]
        pairs = _generate_pairs(300, prob, rng)

        result = fit_bradley_terry(pairs, n_players=3, prior_tau=2.0, iters=200)
        theta = result["theta"]

        assert theta.shape == (3,), f"expected shape (3,), got {theta.shape}"
        assert theta[0] > theta[1], (
            f"θ[0]={theta[0]:.4f} should be > θ[1]={theta[1]:.4f}"
        )
        assert theta[1] > theta[2], (
            f"θ[1]={theta[1]:.4f} should be > θ[2]={theta[2]:.4f}"
        )

    def test_sparse_player_shrunk_toward_mean(self):
        """データが少ない選手は |θ| が小さく (平均 0 に引き寄せられ) 分散が大きいこと。

        設定:
          player 0 (強) : 100 試合
          player 1 (中) : 100 試合
          player 2 (疎) :   2 試合のみ
        階層事前の縮小効果で |θ_2| < |θ_0| かつ var_2 > var_0 が期待される。
        """
        rng = np.random.default_rng(99)
        # player 0 >> player 1 >> player 2 の真の強度設定
        prob = [
            [0.5, 0.80, 0.90],
            [0.20, 0.5, 0.70],
            [0.10, 0.30, 0.5],
        ]

        # player 0 と 1 の対戦を多数生成
        pairs: list[tuple[int, int]] = []
        for _ in range(100):
            if rng.random() < prob[0][1]:
                pairs.append((0, 1))
            else:
                pairs.append((1, 0))

        # player 2 の対戦はわずか 2 試合
        for _ in range(2):
            if rng.random() < prob[1][2]:
                pairs.append((1, 2))
            else:
                pairs.append((2, 1))

        result = fit_bradley_terry(pairs, n_players=3, prior_tau=1.0, iters=200)
        theta = result["theta"]
        var   = result["theta_var"]

        # player 2 は疎なので |θ_2| < |θ_0| (平均0への縮小)
        assert abs(theta[2]) <= abs(theta[0]) + 0.1, (
            f"|θ[2]|={abs(theta[2]):.4f} should be <= |θ[0]|={abs(theta[0]):.4f} "
            f"(sparse player should shrink toward 0)"
        )

        # player 2 の分散は player 0 より大きい (情報が少ない)
        assert var[2] > var[0], (
            f"var[2]={var[2]:.4f} should be > var[0]={var[0]:.4f} "
            f"(sparse player should have wider uncertainty)"
        )

    def test_returns_correct_keys(self):
        """返り値が必要なキーを全て含むこと。"""
        pairs = [(0, 1), (1, 2), (0, 2)]
        result = fit_bradley_terry(pairs, n_players=3)
        assert "theta" in result
        assert "theta_var" in result
        assert "tau" in result
        assert "n_obs_per_player" in result

    def test_zero_players_degenerate(self):
        """選手数 0 またはペア空でも例外を起こさないこと。"""
        result = fit_bradley_terry([], n_players=0)
        assert result["theta"].shape == (0,)

        result2 = fit_bradley_terry([], n_players=3)
        assert result2["theta"].shape == (3,)
        assert np.allclose(result2["theta"], 0.0)

    def test_single_player_degenerate(self):
        """選手 1 人 (対戦なし) でも例外を起こさないこと。"""
        result = fit_bradley_terry([], n_players=1)
        assert result["theta"].shape == (1,)

    def test_theta_mean_near_zero(self):
        """推定後の θ の平均が 0 付近に中心化されていること。"""
        rng = np.random.default_rng(7)
        prob = [[0.5, 0.6, 0.7], [0.4, 0.5, 0.6], [0.3, 0.4, 0.5]]
        pairs = _generate_pairs(200, prob, rng)
        result = fit_bradley_terry(pairs, n_players=3, prior_tau=1.5, iters=150)
        assert abs(result["theta"].mean()) < 0.05, (
            f"theta mean={result['theta'].mean():.4f} should be near 0"
        )

    def test_n_obs_per_player_correct(self):
        """n_obs_per_player が各選手の登場試合数を正しく集計すること。"""
        # player 0 は 3 試合, player 1 は 3 試合, player 2 は 2 試合
        pairs = [(0, 1), (0, 2), (1, 2), (0, 1), (1, 0)]
        result = fit_bradley_terry(pairs, n_players=3)
        n_obs = result["n_obs_per_player"]
        assert int(n_obs[0]) == 4  # (0,1),(0,2),(0,1),(1,0) に player 0 が登場
        assert int(n_obs[1]) == 4  # (0,1),(1,2),(0,1),(1,0) に player 1 が登場
        assert int(n_obs[2]) == 2  # (0,2),(1,2) に player 2 が登場

    def test_theta_var_positive(self):
        """Laplace 後分散が全て正であること。"""
        rng = np.random.default_rng(3)
        prob = [[0.5, 0.65], [0.35, 0.5]]
        pairs = _generate_pairs(50, prob, rng)
        result = fit_bradley_terry(pairs, n_players=2)
        assert np.all(result["theta_var"] > 0), (
            f"All variances should be positive, got {result['theta_var']}"
        )


class TestPredictMatchup:
    """predict_matchup の動作確認。"""

    def test_p_win_in_unit_interval(self):
        """p_win が (0, 1) に収まること。"""
        result = predict_matchup(1.0, 0.1, 0.0, 0.1)
        assert 0.0 < result["p_win"] < 1.0, f"p_win={result['p_win']}"

    def test_ci_ordering(self):
        """ci_low <= p_win <= ci_high であること。"""
        result = predict_matchup(0.5, 0.2, -0.3, 0.3)
        assert result["ci_low"] <= result["p_win"] <= result["ci_high"], (
            f"CI ordering violated: [{result['ci_low']}, {result['ci_high']}] "
            f"does not contain p_win={result['p_win']}"
        )

    def test_equal_strength_gives_half(self):
        """等強度 (θ_i = θ_j) なら p_win ≈ 0.5。"""
        result = predict_matchup(0.0, 0.1, 0.0, 0.1)
        assert abs(result["p_win"] - 0.5) < 1e-6, (
            f"Equal strength should give p_win=0.5, got {result['p_win']}"
        )

    def test_higher_strength_means_higher_p_win(self):
        """θ_i > θ_j なら p_win > 0.5。"""
        result = predict_matchup(2.0, 0.1, 0.0, 0.1)
        assert result["p_win"] > 0.5

    def test_sparse_player_wider_ci(self):
        """分散が大きい (データ疎) 選手ペアほど CI 幅が広いこと。

        対戦: データ豊富なペア (var=0.05) vs データ疎なペア (var=1.0)。
        疎なペアの CI 幅が広いはず。
        """
        # データ豊富
        r_dense = predict_matchup(0.5, 0.05, 0.0, 0.05)
        ci_dense = r_dense["ci_high"] - r_dense["ci_low"]

        # データ疎 (var 大)
        r_sparse = predict_matchup(0.5, 1.0, 0.0, 1.0)
        ci_sparse = r_sparse["ci_high"] - r_sparse["ci_low"]

        assert ci_sparse > ci_dense, (
            f"Sparse CI width={ci_sparse:.4f} should be > dense CI width={ci_dense:.4f}"
        )

    def test_symmetric_opponents(self):
        """predict_matchup(i, j) と predict_matchup(j, i) の p_win が補完的。"""
        r_ij = predict_matchup(1.0, 0.2, -1.0, 0.3)
        r_ji = predict_matchup(-1.0, 0.3, 1.0, 0.2)
        assert abs(r_ij["p_win"] + r_ji["p_win"] - 1.0) < 1e-3, (
            f"p_win(i,j) + p_win(j,i) should be 1.0, "
            f"got {r_ij['p_win']} + {r_ji['p_win']}"
        )

    def test_deterministic_with_seed(self):
        """同じシードで結果が再現されること。"""
        r1 = predict_matchup(0.3, 0.5, -0.2, 0.4, seed=42)
        r2 = predict_matchup(0.3, 0.5, -0.2, 0.4, seed=42)
        assert r1 == r2

    def test_different_seed_gives_different_ci(self):
        """異なるシードで CI が変わること (n_mc が小さいとき)。"""
        r1 = predict_matchup(0.3, 1.0, -0.2, 1.0, n_mc=50, seed=0)
        r2 = predict_matchup(0.3, 1.0, -0.2, 1.0, n_mc=50, seed=99)
        # 点推定 (p_win) は同じ、CI はシードで異なる
        assert r1["p_win"] == r2["p_win"]
        # CI が完全一致することはほぼない (n_mc=50)
        # ただしこれは確率的なので警告のみ (assert ではなく緩いチェック)
        ci_differs = (r1["ci_low"] != r2["ci_low"]) or (r1["ci_high"] != r2["ci_high"])
        assert ci_differs, "CI should differ across seeds (stochastic)"

    def test_returns_required_keys(self):
        """返り値が p_win / ci_low / ci_high を含むこと。"""
        result = predict_matchup(0.0, 0.1, 0.0, 0.1)
        assert "p_win" in result
        assert "ci_low" in result
        assert "ci_high" in result


class TestEndToEndWorkflow:
    """エンジン全体の統合動作確認。"""

    def test_full_pipeline_order_and_uncertainty(self):
        """fit + predict の組み合わせで強弱順序と疎プレイヤーの広 CI を確認する。

        設定:
          player 0 (強): θ_true ≈ +1.5
          player 1 (中): θ_true ≈  0
          player 2 (弱): θ_true ≈ -1.5
          player 3 (疎): データ 2 試合のみ

        期待:
          - θ_0 > θ_1 > θ_2
          - player 3 の |θ| は小さく CI が広い
          - predict_matchup(0, 2) の p_win > 0.5
        """
        rng = np.random.default_rng(2024)

        # 真の強度を Bradley-Terry 確率に変換
        theta_true = np.array([1.5, 0.0, -1.5])
        prob = np.zeros((3, 3))
        for i in range(3):
            for j in range(3):
                if i != j:
                    prob[i, j] = 1.0 / (1.0 + np.exp(-(theta_true[i] - theta_true[j])))

        # player 0,1,2 の対戦を各 80 試合
        pairs: list[tuple[int, int]] = []
        for _ in range(80):
            for i in range(3):
                for j in range(i + 1, 3):
                    if rng.random() < prob[i, j]:
                        pairs.append((i, j))
                    else:
                        pairs.append((j, i))

        # player 3 (疎): 2 試合だけ追加
        pairs.append((3, 2))  # 疎な選手が弱い選手に勝つ
        pairs.append((1, 3))  # 疎な選手が中間選手に負ける

        result = fit_bradley_terry(pairs, n_players=4, prior_tau=2.0, iters=200)
        theta = result["theta"]
        var   = result["theta_var"]

        # 強弱順序の確認
        assert theta[0] > theta[1], f"θ[0]={theta[0]:.3f} > θ[1]={theta[1]:.3f} 失敗"
        assert theta[1] > theta[2], f"θ[1]={theta[1]:.3f} > θ[2]={theta[2]:.3f} 失敗"

        # 疎選手の縮小確認
        assert abs(theta[3]) <= abs(theta[0]) + 0.3, (
            f"疎選手 |θ[3]|={abs(theta[3]):.3f} は豊富選手 |θ[0]|={abs(theta[0]):.3f} "
            f"以下のはず (部分プーリング)"
        )

        # 疎選手の分散が豊富選手より大きい
        assert var[3] > var[0], (
            f"疎選手 var[3]={var[3]:.3f} > 豊富選手 var[0]={var[0]:.3f} 失敗"
        )

        # predict_matchup: 強 vs 弱
        pred = predict_matchup(
            float(theta[0]), float(var[0]),
            float(theta[2]), float(var[2]),
            n_mc=5000, seed=42,
        )
        assert pred["p_win"] > 0.5, (
            f"強選手の勝率は 0.5 超えるはず: p_win={pred['p_win']:.4f}"
        )
        assert pred["ci_low"] < pred["p_win"] < pred["ci_high"], (
            f"CI 順序違反: [{pred['ci_low']}, {pred['ci_high']}]"
        )

        # predict_matchup: 疎選手は CI 幅が豊富選手ペアより広い
        pred_dense = predict_matchup(
            float(theta[0]), float(var[0]),
            float(theta[1]), float(var[1]),
            n_mc=5000, seed=42,
        )
        pred_sparse = predict_matchup(
            float(theta[0]), float(var[0]),
            float(theta[3]), float(var[3]),
            n_mc=5000, seed=42,
        )
        ci_dense  = pred_dense["ci_high"]  - pred_dense["ci_low"]
        ci_sparse = pred_sparse["ci_high"] - pred_sparse["ci_low"]
        assert ci_sparse > ci_dense, (
            f"疎選手を含む CI 幅={ci_sparse:.4f} は豊富ペア CI 幅={ci_dense:.4f} より広いはず"
        )
