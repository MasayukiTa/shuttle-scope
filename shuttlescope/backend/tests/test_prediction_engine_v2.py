"""
Phase 1 Rebuild — 予測エンジン新関数のユニットテスト
DB不要: list[Match] を直接渡す純粋関数のみをテスト。
"""
import pytest
from datetime import date
from unittest.mock import MagicMock

from backend.db.models import Match
from backend.analysis.prediction_engine import (
    compute_recent_form,
    compute_growth_trend,
    compute_feature_win_prob,
    compute_set_model_v2,
    compute_brier_score,
    compute_brier_score_blended,
    build_caution_flags,
    compute_match_narrative,
    reference_status,
    win_probability_interval,
    find_nearest_matches,
)
from backend.utils.confidence import VERDICT_MIN_SAMPLE


# ── テスト用ヘルパー ────────────────────────────────────────────────────────

def _match(
    player_id: int,
    result: str,
    date_val: date | None = None,
    level: str = 'IC',
    fmt: str = 'singles',
) -> MagicMock:
    """Match モックオブジェクトを作成する"""
    m = MagicMock(spec=Match)
    m.player_a_id = player_id
    m.player_b_id = player_id + 100
    m.result = result
    m.date = date_val or date(2024, 1, 1)
    m.tournament_level = level
    m.format = fmt
    m.final_score = '21-15, 21-18' if result == 'win' else '15-21, 18-21'
    m.sets = []
    return m


def _wins(player_id: int, n: int, level: str = 'IC') -> list[MagicMock]:
    return [_match(player_id, 'win', date(2024, 1, i + 1), level) for i in range(n)]


def _losses(player_id: int, n: int, level: str = 'IC') -> list[MagicMock]:
    return [_match(player_id, 'loss', date(2024, 2, i + 1), level) for i in range(n)]


# ── compute_recent_form ───────────────────────────────────────────────────────

class TestComputeRecentForm:
    def test_empty_returns_no_verdict(self):
        # 試合 0 件: 偽の 50% / 「安定」を返さず null + sample=0
        r = compute_recent_form([], 1)
        assert r['trend'] is None
        assert r['sample'] == 0
        assert r['win_rate'] is None
        assert r['overall_wr'] is None

    def test_all_wins_recent_improving(self):
        # 10試合全体5W5L, 直近5はすべて勝利 → improving
        all_matches = _losses(1, 5) + _wins(1, 5)  # 降順: 最新が先頭
        all_matches.reverse()  # 降順に並べる（最新が先頭）
        r = compute_recent_form(all_matches, 1, n=5)
        assert r['trend'] == 'improving'
        assert r['sample'] == 5
        assert r['win_rate'] > 0.5

    def test_all_losses_recent_declining(self):
        all_matches = _wins(1, 5) + _losses(1, 5)
        all_matches.reverse()
        r = compute_recent_form(all_matches, 1, n=5)
        assert r['trend'] == 'declining'

    def test_fewer_than_n_uses_all(self):
        matches = _wins(1, 3)
        r = compute_recent_form(matches, 1, n=5)
        assert r['sample'] == 3

    def test_results_list_is_chronological(self):
        # 古い順に W, L, W
        matches = [
            _match(1, 'win',  date(2024, 3, 1)),
            _match(1, 'loss', date(2024, 2, 1)),
            _match(1, 'win',  date(2024, 1, 1)),
        ]  # 降順（最新が先頭）
        r = compute_recent_form(matches, 1, n=3)
        assert r['results'] == ['W', 'L', 'W']

    def test_stable_when_recent_and_overall_close(self):
        # 交互 W/L パターン: 直近も全体も 50% 付近 → stable
        from datetime import timedelta
        start = date(2024, 1, 1)
        matches = [
            _match(1, 'win' if i % 2 == 0 else 'loss', start + timedelta(days=i))
            for i in range(12)
        ]
        matches.reverse()  # 降順（最新先頭）
        r = compute_recent_form(matches, 1, n=6)
        # 直近 6 も全体も交互パターン → overall と近い → stable
        assert abs(r['win_rate'] - r['overall_wr']) < 0.10


# ── compute_growth_trend ─────────────────────────────────────────────────────

class TestComputeGrowthTrend:
    def test_empty_returns_flat(self):
        r = compute_growth_trend([], 1)
        assert r['direction'] is None
        assert r['slope'] is None
        assert r['buckets'] == []

    def test_single_match_returns_flat(self):
        r = compute_growth_trend([_match(1, 'win')], 1)
        assert r['direction'] is None
        assert len(r['buckets']) == 1

    def test_improving_trend(self):
        # 古い試合で負け多め → 最近で勝ち多め
        matches = (
            _losses(1, 6, 'IC') +
            [_match(1, 'win', date(2024, 6, i + 1)) for i in range(6)]
        )
        r = compute_growth_trend(matches, 1)
        assert r['direction'] == 'up'
        assert r['slope'] > 0

    def test_declining_trend(self):
        matches = (
            [_match(1, 'win', date(2024, 1, i + 1)) for i in range(6)] +
            _losses(1, 6)
        )
        r = compute_growth_trend(matches, 1)
        assert r['direction'] == 'down'

    def test_at_most_6_buckets(self):
        matches = [_match(1, 'win', date(2024, 1, i + 1)) for i in range(20)]
        r = compute_growth_trend(matches, 1)
        assert len(r['buckets']) <= 6

    def test_bucket_win_rates_in_range(self):
        matches = _wins(1, 4) + _losses(1, 4)
        r = compute_growth_trend(matches, 1)
        for b in r['buckets']:
            assert 0.0 <= b['win_rate'] <= 1.0


# ── compute_feature_win_prob ──────────────────────────────────────────────────

class TestComputeFeatureWinProb:
    def _recent(self, wr=0.5, n=5):
        return {'win_rate': wr, 'sample': n, 'trend': 'stable', 'results': [], 'overall_wr': wr}

    def test_base_only_when_no_h2h_no_recent(self):
        matches = _wins(1, 10)
        form = self._recent(wr=0.5, n=0)
        prob, bd = compute_feature_win_prob(matches, 1, [], form, {})
        assert bd['weights'] == {'base': 1.0}
        assert 0.10 <= prob <= 0.90

    def test_h2h_3_activates_h2h_weights(self):
        all_m = _wins(1, 10)
        h2h = _wins(1, 3)
        form = self._recent(wr=0.7, n=5)
        prob, bd = compute_feature_win_prob(all_m, 1, h2h, form, {})
        assert bd['weights'] == {'base': 0.25, 'recent': 0.35, 'h2h': 0.40}
        assert bd['h2h_wr'] is not None

    def test_obs_modifier_heavy_opp_increases_prob(self):
        matches = _wins(1, 5) + _losses(1, 5)
        form = self._recent(wr=0.5, n=5)
        obs = {'opponent': {'physical_caution': {'value': 'heavy', 'confidence': 'high'}}}
        prob_no_obs, _ = compute_feature_win_prob(matches, 1, [], form, {})
        prob_with_obs, bd = compute_feature_win_prob(matches, 1, [], form, obs)
        assert bd['obs_modifier'] == pytest.approx(0.03)
        assert prob_with_obs > prob_no_obs

    def test_obs_modifier_poor_self_decreases_prob(self):
        matches = _wins(1, 5) + _losses(1, 5)
        form = self._recent(wr=0.5, n=5)
        obs = {'self': {'self_condition': {'value': 'poor', 'confidence': 'high'}}}
        _, bd = compute_feature_win_prob(matches, 1, [], form, obs)
        assert bd['obs_modifier'] == pytest.approx(-0.05)

    def test_cumulative_obs_modifier(self):
        # poor condition + off timing → -0.05 + -0.04 = -0.09
        matches = _wins(1, 5)
        form = self._recent()
        obs = {
            'self': {
                'self_condition': {'value': 'poor', 'confidence': 'high'},
                'self_timing': {'value': 'off', 'confidence': 'high'},
            }
        }
        _, bd = compute_feature_win_prob(matches, 1, [], form, obs)
        assert bd['obs_modifier'] == pytest.approx(-0.09)

    def test_clamp_to_bounds(self):
        # 全勝試合 + very high obs_modifier → 0.90 以下
        matches = _wins(1, 20)
        form = self._recent(wr=0.99, n=5)
        prob, _ = compute_feature_win_prob(matches, 1, [], form, {})
        assert prob <= 0.90

    def test_lower_clamp(self):
        matches = _losses(1, 20)
        form = self._recent(wr=0.01, n=5)
        obs = {'self': {'self_condition': {'value': 'poor', 'confidence': 'high'},
                        'self_timing': {'value': 'off', 'confidence': 'high'}}}
        prob, _ = compute_feature_win_prob(matches, 1, [], form, obs)
        assert prob >= 0.10


# ── compute_set_model_v2 ──────────────────────────────────────────────────────

class TestComputeSetModelV2:
    def test_observed_dist_returned_as_is(self):
        obs = {'2-0': 0.5, '2-1': 0.3, '1-2': 0.1, '0-2': 0.1}
        r = compute_set_model_v2(0.7, obs)
        assert r['model_type'] == 'observed'
        assert r['dist'] == obs

    def test_none_triggers_momentum_model(self):
        r = compute_set_model_v2(0.6, None)
        assert r['model_type'] == 'momentum'

    def test_sums_to_one_at_p05(self):
        r = compute_set_model_v2(0.5, None)
        total = sum(r['dist'].values())
        assert abs(total - 1.0) < 1e-6

    def test_sums_to_one_at_extreme_p09(self):
        r = compute_set_model_v2(0.9, None)
        total = sum(r['dist'].values())
        assert abs(total - 1.0) < 1e-6

    def test_sums_to_one_at_extreme_p01(self):
        r = compute_set_model_v2(0.1, None)
        total = sum(r['dist'].values())
        assert abs(total - 1.0) < 1e-6

    def test_high_prob_skews_toward_20(self):
        r = compute_set_model_v2(0.85, None)
        # 強い選手は 2-0 が最頻
        assert r['dist']['2-0'] > r['dist']['0-2']

    def test_low_prob_skews_toward_02(self):
        r = compute_set_model_v2(0.15, None)
        assert r['dist']['0-2'] > r['dist']['2-0']

    def test_symmetric_at_p05(self):
        r = compute_set_model_v2(0.5, None)
        assert abs(r['dist']['2-0'] - r['dist']['0-2']) < 0.05


# ── compute_brier_score ───────────────────────────────────────────────────────

class TestComputeBrierScore:
    def test_fewer_than_5_returns_none(self):
        matches = _wins(1, 4)
        r = compute_brier_score(matches, 1)
        assert r['score'] is None
        assert r['grade'] is None
        assert r['sample'] == 4

    def test_empty_returns_none(self):
        r = compute_brier_score([], 1)
        assert r['score'] is None

    def test_all_wins_grades_good(self):
        # 10連勝: LOO予測 ≈ 0.83, actual=1.0, MSE ≈ 0.029
        matches = _wins(1, 10)
        r = compute_brier_score(matches, 1)
        assert r['score'] is not None
        assert r['grade'] == 'good'
        assert r['score'] < 0.20

    def test_all_losses_grades_good(self):
        # 全敗: LOO予測 ≈ 0.17, actual=0.0, MSE ≈ 0.029
        matches = _losses(1, 10)
        r = compute_brier_score(matches, 1)
        assert r['grade'] == 'good'

    def test_mixed_results_score_in_range(self):
        matches = _wins(1, 5) + _losses(1, 5)
        r = compute_brier_score(matches, 1)
        assert r['score'] is not None
        assert 0.0 <= r['score'] <= 1.0

    def test_grade_poor_for_random_noise(self):
        # ランダムパターン (WLWLWL...) は予測困難 → スコア高め
        from datetime import timedelta
        start = date(2024, 1, 1)
        matches = [
            _match(1, 'win' if i % 2 == 0 else 'loss', start + timedelta(days=i))
            for i in range(10)
        ]
        r = compute_brier_score(matches, 1)
        # スコアが 0.20 以上になりやすい
        assert r['score'] is not None


# ── find_nearest_matches ──────────────────────────────────────────────────────

class TestFindNearestMatches:
    def test_empty_returns_empty(self):
        assert find_nearest_matches([], 1, 'IC') == []

    def test_returns_at_most_n(self):
        matches = _wins(1, 10)
        result = find_nearest_matches(matches, 1, 'IC', n=5)
        assert len(result) <= 5

    def test_same_level_scores_higher(self):
        ic = _match(1, 'win', date(2024, 1, 1), 'IC')
        sjl = _match(1, 'win', date(2024, 1, 2), 'SJL')
        result = find_nearest_matches([ic, sjl], 1, 'IC', n=5)
        ic_item = next(r for r in result if r['tournament_level'] == 'IC')
        sjl_item = next(r for r in result if r['tournament_level'] == 'SJL')
        assert ic_item['similarity_score'] > sjl_item['similarity_score']

    def test_result_field_present(self):
        matches = _wins(1, 3)
        result = find_nearest_matches(matches, 1, 'IC', n=3)
        for item in result:
            assert item['result'] in ('win', 'loss')
            assert 'date' in item
            assert 'tournament_level' in item
            assert 'similarity_score' in item
            assert 'score_summary' in item

    def test_loss_result_labeled_correctly(self):
        m = _match(1, 'loss', date(2024, 1, 1), 'IC')
        result = find_nearest_matches([m], 1, 'IC', n=1)
        assert result[0]['result'] == 'loss'


# ── 最小標本 VERDICT_MIN_SAMPLE: 方向・注意・成長傾向・勝率の格下げ ───────────────────

class TestVerdictMinSample:
    def test_minimum_is_the_existing_narrative_rule(self):
        assert VERDICT_MIN_SAMPLE == 5

    @pytest.mark.parametrize('n', [1, 2, 4])
    def test_recent_form_has_no_direction_below_minimum(self, n):
        # n=1 の 1 勝は 直近 1.0 / 全体 0.667 で「上向き」になっていた
        r = compute_recent_form(_wins(1, n), 1, n=5)
        assert r['trend'] is None
        # 数値そのものは残す (n と一緒に参考値として出せる)
        assert r['sample'] == n
        assert r['win_rate'] == 1.0

    @pytest.mark.parametrize('n', [1, 2, 4])
    def test_caution_flag_not_raised_from_few_matches(self, n):
        # n=1 の 1 敗は (0+1)/(1+2)=0.333 < 0.35 で「戦術の再検討が必要」になっていた
        assert build_caution_flags(0.333, n, {}) == []
        assert build_caution_flags(0.80, n, {}) == []

    def test_caution_flag_unchanged_at_minimum(self):
        n = VERDICT_MIN_SAMPLE
        assert build_caution_flags(0.30, n, {}) == ['過去の対戦成績が厳しい — 戦術の再検討が必要']
        assert build_caution_flags(0.75, n, {}) == ['過去の勝率が高いが油断に注意']
        assert build_caution_flags(0.50, n, {}) == []

    def test_physical_caution_still_flagged_with_few_matches(self):
        ctx = {'opponent': {'physical_caution': {'value': 'heavy'}}}
        assert len(build_caution_flags(0.5, 1, ctx)) == 1

    @pytest.mark.parametrize('n', [1, 2, 4])
    def test_growth_trend_has_no_direction_below_minimum(self, n):
        matches = [_match(1, 'win' if i == n - 1 else 'loss', date(2024, 1, i + 1)) for i in range(n)]
        r = compute_growth_trend(matches, 1)
        assert r['direction'] is None
        assert r['slope'] is None
        assert r['sample'] == n

    def test_growth_trend_unchanged_at_minimum(self):
        matches = _losses(1, 3) + [_match(1, 'win', date(2024, 6, i + 1)) for i in range(3)]
        r = compute_growth_trend(matches, 1)
        assert r['direction'] == 'up'
        assert r['slope'] > 0

    def test_recent_form_unchanged_at_minimum(self):
        all_matches = (_losses(1, 5) + _wins(1, 5))
        all_matches.reverse()
        r = compute_recent_form(all_matches, 1, n=5)
        assert r['trend'] == 'improving'

    def test_reference_status_by_sample(self):
        assert reference_status(VERDICT_MIN_SAMPLE - 1)['reason'] == 'sample'
        assert reference_status(VERDICT_MIN_SAMPLE)['is_reference'] is False

    def test_wilson_interval_replaces_fixed_margin(self):
        assert win_probability_interval(0.6, VERDICT_MIN_SAMPLE - 1) is None
        assert win_probability_interval(None, 20) is None
        small = win_probability_interval(0.6, 5)
        large = win_probability_interval(0.6, 80)
        assert small['low'] < 0.6 < small['high']
        # 標本が多いほど区間は狭い (固定の ±15/10/7 ではない)
        assert (large['high'] - large['low']) < (small['high'] - small['low'])
        assert small['n'] == 5

    def test_narrative_sentence_does_not_call_blended_value_head_to_head(self):
        out = compute_match_narrative(
            player_name='A', opponent_name='B', win_prob=0.61, sample_size=8,
            set_distribution={'2-0': 0.3, '2-1': 0.3, '1-2': 0.2, '0-2': 0.2},
            most_likely_scorelines=[], score_volatility=None, recent_form=None,
            obs_context={}, h2h_count=4, tournament_level=None,
        )
        text = out['deciding_factor']
        assert '直接対戦での実績' not in text
        assert '直接対戦4試合を加味した推定勝率61%' in text


# ── 表示する予測そのものの Brier ───────────────────────────────────────────────

class TestBlendedBrier:
    def test_below_five_matches_is_none(self):
        r = compute_brier_score_blended(_wins(1, 4), 1, [])
        assert r['score'] is None and r['grade'] is None

    def test_scores_the_blended_prediction_not_the_laplace_one(self):
        # 直近 5 件が全部負け・その前が全部勝ち: 混合 (直近重み 0.6) は Laplace と別の値を出す
        matches = _losses(1, 6) + _wins(1, 6)
        matches.sort(key=lambda m: m.date, reverse=True)
        laplace = compute_brier_score(matches, 1)
        blended = compute_brier_score_blended(matches, 1, [])
        assert laplace['score'] is not None and blended['score'] is not None
        assert laplace['score'] != blended['score']
        assert blended['sample'] == len(matches)

    def test_formula_is_unchanged_for_a_custom_predictor(self):
        # 常に 0.5 と答える予測の Brier は 0.25 ちょうど (コイントス基準)
        matches = _wins(1, 3) + _losses(1, 3)
        r = compute_brier_score(matches, 1, predictor=lambda holdout: 0.5)
        assert r['score'] == 0.25
        assert r['grade'] == 'fair'

    def test_poor_grade_demotes_to_reference(self):
        # 常に外す予測 (勝つのに 0.1 と答える) は 0.25 を超えて poor
        matches = _wins(1, 6)
        brier = compute_brier_score(matches, 1, predictor=lambda holdout: 0.1)
        assert brier['grade'] == 'poor'
        status = reference_status(len(matches), brier)
        assert status['is_reference'] is True and status['reason'] == 'brier'
        assert reference_status(len(matches), {'grade': 'good'})['is_reference'] is False
