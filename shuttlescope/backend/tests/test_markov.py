"""マルコフEPV計算エンジンのテスト"""
import pytest
import numpy as np

from backend.analysis.markov import MarkovAnalyzer, SHOT_KEYS


# テスト用ラリーデータを生成するヘルパー
def make_strokes(shots: list[str], won: bool) -> list[dict]:
    """ショット種別リストからストロークリストを生成する"""
    return [
        {"shot_type": shot, "player_won": won, "stroke_num": i + 1}
        for i, shot in enumerate(shots)
    ]


def make_strokes_list(n: int = 50) -> list[list[dict]]:
    """テスト用のラリーデータを生成する"""
    import random
    random.seed(42)
    strokes_list = []
    for _ in range(n):
        length = random.randint(2, 8)
        shots = [random.choice(SHOT_KEYS) for _ in range(length)]
        won = random.random() < 0.5
        strokes_list.append(make_strokes(shots, won))
    return strokes_list


class TestMarkovAnalyzer:
    """MarkovAnalyzerの単体テスト"""

    def setup_method(self):
        self.analyzer = MarkovAnalyzer()
        self.strokes_list = make_strokes_list(100)

    def test_epv_values_in_range(self):
        """EPV値が適切な範囲内にあること（基本的にベースライン差分は-1〜+1）"""
        epv = self.analyzer.calc_epv(self.strokes_list)
        for shot_type, value in epv.items():
            assert -1.0 <= value <= 1.0, f"EPV out of range for {shot_type}: {value}"

    def test_no_zero_division_with_minimal_data(self):
        """最小データ（1ラリー）でもゼロ除算が発生しないこと"""
        single_rally = [make_strokes(["smash", "defensive"], won=True)]
        try:
            epv = self.analyzer.calc_epv(single_rally)
            matrix = self.analyzer.build_transition_matrix(single_rally)
            patterns = self.analyzer.get_top_patterns(single_rally)
        except ZeroDivisionError:
            pytest.fail("ZeroDivisionError が発生しました")

    def test_no_zero_division_with_empty_data(self):
        """空データでもゼロ除算が発生しないこと"""
        try:
            epv = self.analyzer.calc_epv([])
            matrix = self.analyzer.build_transition_matrix([])
            patterns = self.analyzer.get_top_patterns([])
            ci = self.analyzer.bootstrap_ci([])
        except ZeroDivisionError:
            pytest.fail("ZeroDivisionError が発生しました（空データ）")

    def test_transition_matrix_rows_sum_to_one(self):
        """遷移行列の各行の和が1に近いこと（ラプラス平滑化込み）"""
        matrix = self.analyzer.build_transition_matrix(self.strokes_list, laplace_alpha=1.0)
        n = len(SHOT_KEYS)
        assert matrix.shape == (n, n), f"行列サイズが不正: {matrix.shape}"

        for i in range(n):
            row_sum = matrix[i].sum()
            assert abs(row_sum - 1.0) < 1e-9, f"行 {i} の和が1でない: {row_sum}"

    def test_bootstrap_ci_covers_point_estimate(self):
        """ブートストラップCIが点推定値を含む確率が高いこと（統計的テスト）"""
        strokes_list = make_strokes_list(200)
        epv = self.analyzer.calc_epv(strokes_list)
        ci = self.analyzer.bootstrap_ci(strokes_list, n_bootstrap=200)

        # 少なくとも主要なショットについてCIをチェック
        covered = 0
        total = 0
        for shot_type, ci_data in ci.items():
            point_est = epv.get(shot_type, 0.0)
            # CIが点推定値を含むかチェック（CIは概算なので緩いチェック）
            if ci_data["ci_low"] - 0.1 <= point_est <= ci_data["ci_high"] + 0.1:
                covered += 1
            total += 1

        if total > 0:
            coverage_rate = covered / total
            assert coverage_rate >= 0.7, f"CI カバレッジが低すぎる: {coverage_rate:.2f}"

    def test_get_top_patterns_returns_list(self):
        """get_top_patterns が正しいリストを返すこと"""
        patterns = self.analyzer.get_top_patterns(self.strokes_list, top_k=10)
        assert isinstance(patterns, list)
        assert len(patterns) <= 10
        for p in patterns:
            assert "pattern" in p
            assert "shots" in p
            assert "epv" in p
            assert "count" in p

    def test_extract_triplets(self):
        """triplet抽出が正常に動作すること"""
        strokes_list = [
            make_strokes(["smash", "defensive", "clear", "lob"], won=True)
        ]
        triplets = self.analyzer.extract_triplets(strokes_list)
        assert len(triplets) == 2  # 4ショット→2トリプレット
        assert triplets[0] == ("smash", "defensive", "clear")
        assert triplets[1] == ("defensive", "clear", "lob")
