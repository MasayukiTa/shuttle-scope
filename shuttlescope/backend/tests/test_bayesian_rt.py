"""ベイズリアルタイム解析エンジンのテスト"""
import time
import pytest

from backend.analysis.bayesian_rt import BayesianRealTimeAnalyzer


class TestBayesianRealTimeAnalyzer:
    """BayesianRealTimeAnalyzerの単体テスト"""

    def setup_method(self):
        self.analyzer = BayesianRealTimeAnalyzer()

    def test_posterior_mean_between_0_and_1(self):
        """事後分布の平均値が0〜1の範囲内にあること"""
        # 様々なalpha/betaパラメータでテスト
        test_cases = [
            (1.0, 1.0),       # 無情報事前分布
            (10.0, 5.0),      # 勝率高め
            (3.0, 15.0),      # 勝率低め
            (0.5, 0.5),       # Jeffreys prior
            (100.0, 100.0),   # 大サンプル
        ]
        for alpha, beta in test_cases:
            result = self.analyzer.posterior_mean_and_ci(alpha, beta)
            assert 0.0 <= result["mean"] <= 1.0, f"mean out of range: {result['mean']} (alpha={alpha}, beta={beta})"
            assert 0.0 <= result["ci_low"] <= 1.0, f"ci_low out of range: {result['ci_low']}"
            assert 0.0 <= result["ci_high"] <= 1.0, f"ci_high out of range: {result['ci_high']}"
            assert result["ci_low"] <= result["mean"] <= result["ci_high"], \
                f"mean {result['mean']} not in CI [{result['ci_low']}, {result['ci_high']}]"

    def test_update_posterior_correctness(self):
        """posteriorの更新が正しく計算されること"""
        prior_alpha = 2.0
        prior_beta = 3.0
        wins = 7
        total = 10
        losses = total - wins

        result = self.analyzer.update_posterior(prior_alpha, prior_beta, wins, total)
        expected_alpha = prior_alpha + wins
        expected_beta = prior_beta + losses

        assert result["alpha"] == expected_alpha, f"alpha mismatch: {result['alpha']} != {expected_alpha}"
        assert result["beta"] == expected_beta, f"beta mismatch: {result['beta']} != {expected_beta}"

    def test_compute_prior_with_no_data_returns_fallback(self):
        """データがない場合にフォールバックのpriorが返されること"""
        prior = self.analyzer.compute_prior(player_id=9999, opponent_id=None, db=None)
        assert "alpha" in prior
        assert "beta" in prior
        assert prior["alpha"] > 0
        assert prior["beta"] > 0

    def test_interval_report_returns_quickly(self):
        """interval_report の応答時間が30秒未満であること"""
        start = time.time()
        # DB接続なしでのフォールバック動作をテスト
        result = self.analyzer.generate_interval_report(
            match_id=99999, completed_set_num=1, db=None
        )
        elapsed = time.time() - start
        assert elapsed < 30.0, f"interval_report が遅すぎる: {elapsed:.2f}秒"
        # エラーが返ることは許容（DBなしなので）
        assert isinstance(result, dict)

    def test_posterior_ci_width_decreases_with_more_data(self):
        """データが増えるとCI幅が狭くなること"""
        # 少ないデータ
        small_result = self.analyzer.posterior_mean_and_ci(2.0, 2.0)
        small_width = small_result["ci_high"] - small_result["ci_low"]

        # 多いデータ（同じ割合で）
        large_result = self.analyzer.posterior_mean_and_ci(200.0, 200.0)
        large_width = large_result["ci_high"] - large_result["ci_low"]

        assert large_width < small_width, \
            f"大サンプルのCI幅 ({large_width:.4f}) が小サンプル ({small_width:.4f}) より大きい"

    def test_interval_report_with_db(self, db_session):
        """DBセッションを使ったinterval_reportのテスト（空DBで動作確認）"""
        start = time.time()
        result = self.analyzer.generate_interval_report(
            match_id=1, completed_set_num=1, db=db_session
        )
        elapsed = time.time() - start
        assert elapsed < 30.0, f"DB付きinterval_report が遅すぎる: {elapsed:.2f}秒"
        # 試合なしの場合はエラーまたは空データが返る
        assert isinstance(result, dict)
        assert "success" in result
