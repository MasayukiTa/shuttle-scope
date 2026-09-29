"""
test_analysis_foundation.py — 解析基盤モジュールのテスト

対象:
  - backend.analysis.player_context
  - backend.analysis.shot_taxonomy
  - backend.analysis.sequence_helper
  - backend.analysis.analysis_tiers
  - backend.utils.confidence (拡張部分)
"""
import pytest
from unittest.mock import MagicMock


# ── player_context テスト ────────────────────────────────────────────────────

class TestPlayerContext:
    """player_context.py のユニットテスト"""

    def _make_match(self, player_a_id, player_b_id, result,
                    partner_a_id=None, partner_b_id=None):
        m = MagicMock()
        m.player_a_id = player_a_id
        m.player_b_id = player_b_id
        m.partner_a_id = partner_a_id
        m.partner_b_id = partner_b_id
        m.result = result
        return m

    def test_target_role_player_a(self):
        from backend.analysis.player_context import target_role
        m = self._make_match(1, 2, 'win')
        assert target_role(m, 1) == 'player_a'

    def test_target_role_player_b(self):
        from backend.analysis.player_context import target_role
        m = self._make_match(1, 2, 'win')
        assert target_role(m, 2) == 'player_b'

    def test_target_role_not_in_match(self):
        from backend.analysis.player_context import target_role
        m = self._make_match(1, 2, 'win')
        assert target_role(m, 99) is None

    def test_player_wins_match_as_a(self):
        from backend.analysis.player_context import player_wins_match
        m = self._make_match(1, 2, 'win')
        assert player_wins_match(m, 1) is True

    def test_player_wins_match_as_b(self):
        from backend.analysis.player_context import player_wins_match
        # result='loss' from player_a perspective means player_b won
        m = self._make_match(1, 2, 'loss')
        assert player_wins_match(m, 2) is True

    def test_player_loses_match_as_a(self):
        from backend.analysis.player_context import player_wins_match
        m = self._make_match(1, 2, 'loss')
        assert player_wins_match(m, 1) is False

    def test_opponent_player_id_from_a(self):
        from backend.analysis.player_context import opponent_player_id
        m = self._make_match(1, 2, 'win')
        assert opponent_player_id(m, 1) == 2

    def test_opponent_player_id_from_b(self):
        from backend.analysis.player_context import opponent_player_id
        m = self._make_match(1, 2, 'win')
        assert opponent_player_id(m, 2) == 1

    def test_partner_player_id_doubles(self):
        from backend.analysis.player_context import partner_player_id
        m = self._make_match(1, 2, 'win', partner_a_id=3, partner_b_id=4)
        assert partner_player_id(m, 1) == 3
        assert partner_player_id(m, 2) == 4

    def test_partner_player_id_singles(self):
        from backend.analysis.player_context import partner_player_id
        m = self._make_match(1, 2, 'win')
        assert partner_player_id(m, 1) is None

    def test_resolve_doubles_roles(self):
        from backend.analysis.player_context import resolve_doubles_roles
        m = self._make_match(1, 2, 'win', partner_a_id=3, partner_b_id=4)
        d = resolve_doubles_roles(m, 1)
        assert d['team_side'] == 'player_a'
        assert d['individual_slot'] == 'player_a'
        assert d['partner_slot'] == 'partner_a'
        assert d['opponent_slot'] == 'player_b'
        assert d['partner_id'] == 3

    def test_opponent_role(self):
        from backend.analysis.player_context import opponent_role
        m = self._make_match(1, 2, 'win')
        assert opponent_role(m, 1) == 'player_b'
        assert opponent_role(m, 2) == 'player_a'


# ── shot_taxonomy テスト ─────────────────────────────────────────────────────

class TestShotTaxonomy:
    """shot_taxonomy.py のユニットテスト"""

    def test_canonical_passthrough(self):
        from backend.analysis.shot_taxonomy import canonicalize
        assert canonicalize('smash') == 'smash'
        assert canonicalize('net_shot') == 'net_shot'
        assert canonicalize('clear') == 'clear'

    def test_case_insensitive(self):
        from backend.analysis.shot_taxonomy import canonicalize
        assert canonicalize('Smash') == 'smash'
        assert canonicalize('CLEAR') == 'clear'

    def test_alias_resolution(self):
        from backend.analysis.shot_taxonomy import canonicalize
        assert canonicalize('jump smash') == 'smash'
        assert canonicalize('hairpin') == 'net_shot'
        assert canonicalize('lift') == 'lob'
        assert canonicalize('push') == 'push_rush'
        assert canonicalize("can't reach") == 'cant_reach'

    def test_unknown_fallback(self):
        from backend.analysis.shot_taxonomy import canonicalize
        assert canonicalize('totally_unknown') == 'other'

    def test_all_canonical_pass_through(self):
        from backend.analysis.shot_taxonomy import canonicalize, CANONICAL_SHOTS
        for shot in CANONICAL_SHOTS:
            assert canonicalize(shot) == shot

    def test_ja_label(self):
        from backend.analysis.shot_taxonomy import ja_label
        assert ja_label('smash') == 'スマッシュ'
        assert ja_label('jump smash') == 'スマッシュ'

    def test_18_canonical_shots(self):
        from backend.analysis.shot_taxonomy import CANONICAL_SHOTS
        assert len(CANONICAL_SHOTS) == 18

    def test_shot_type_ja_covers_all_canonical(self):
        from backend.analysis.shot_taxonomy import CANONICAL_SHOTS, SHOT_TYPE_JA
        for shot in CANONICAL_SHOTS:
            assert shot in SHOT_TYPE_JA, f"{shot} missing from SHOT_TYPE_JA"


# ── sequence_helper テスト ───────────────────────────────────────────────────

class TestSequenceHelper:
    """sequence_helper.py のユニットテスト"""

    def _make_stroke(self, stroke_num, player, shot_type):
        s = MagicMock()
        s.stroke_num = stroke_num
        s.player = player
        s.shot_type = shot_type
        return s

    def _make_rally(self, rally_id, winner='player_a'):
        r = MagicMock()
        r.id = rally_id
        r.winner = winner
        r.score_a_after = 5
        r.score_b_after = 3
        return r

    def test_player_stroke_sequence(self):
        from backend.analysis.sequence_helper import player_stroke_sequence
        r = self._make_rally(1)
        strokes = {
            1: [
                self._make_stroke(1, 'player_a', 'smash'),
                self._make_stroke(2, 'player_b', 'defensive'),
                self._make_stroke(3, 'player_a', 'drop'),
            ]
        }
        seq = player_stroke_sequence([r], strokes, 'player_a')
        assert seq == ['smash', 'drop']

    def test_last_n_shots(self):
        from backend.analysis.sequence_helper import last_n_shots
        seq = ['a', 'b', 'c', 'd', 'e']
        assert last_n_shots(seq, 3) == ['c', 'd', 'e']
        assert last_n_shots(seq, 10) == seq

    def test_stroke_ngrams(self):
        from backend.analysis.sequence_helper import stroke_ngrams
        seq = ['A', 'B', 'C', 'D']
        assert stroke_ngrams(seq, 2) == [('A', 'B'), ('B', 'C'), ('C', 'D')]
        assert stroke_ngrams(seq, 3) == [('A', 'B', 'C'), ('B', 'C', 'D')]

    def test_transition_pairs(self):
        from backend.analysis.sequence_helper import transition_pairs
        seq = ['smash', 'defensive', 'drop']
        assert transition_pairs(seq) == [('smash', 'defensive'), ('defensive', 'drop')]

    def test_context_response_pairs(self):
        from backend.analysis.sequence_helper import context_response_pairs
        seq = ['A', 'B', 'C', 'D']
        pairs = context_response_pairs(seq, context_len=2)
        assert pairs == [(('A', 'B'), 'C'), (('B', 'C'), 'D')]

    def test_ngram_frequency(self):
        from backend.analysis.sequence_helper import ngram_frequency
        seq = ['A', 'B', 'A', 'B', 'C']
        freq = ngram_frequency(seq, 2)
        assert freq[('A', 'B')] == 2
        assert freq[('B', 'C')] == 1

    def test_pre_outcome_sequences(self):
        from backend.analysis.sequence_helper import pre_outcome_sequences
        r_win = self._make_rally(1, winner='player_a')
        r_loss = self._make_rally(2, winner='player_b')
        strokes = {
            1: [self._make_stroke(1, 'player_a', 'smash'),
                self._make_stroke(2, 'player_a', 'drop')],
            2: [self._make_stroke(1, 'player_a', 'clear')],
        }
        win_seqs = pre_outcome_sequences([r_win, r_loss], strokes, 'player_a', 'win')
        assert win_seqs == [['smash', 'drop']]
        loss_seqs = pre_outcome_sequences([r_win, r_loss], strokes, 'player_a', 'loss')
        assert loss_seqs == [['clear']]

    def test_empty_sequence(self):
        from backend.analysis.sequence_helper import stroke_ngrams, transition_pairs
        assert stroke_ngrams([], 2) == []
        assert transition_pairs([]) == []


# ── analysis_tiers テスト ────────────────────────────────────────────────────

class TestAnalysisTiers:
    """analysis_tiers.py のユニットテスト"""

    def test_known_stable(self):
        from backend.analysis.analysis_tiers import get_tier
        assert get_tier('descriptive') == 'stable'
        assert get_tier('heatmap') == 'stable'

    def test_known_advanced(self):
        from backend.analysis.analysis_tiers import get_tier
        assert get_tier('pressure') == 'advanced'
        assert get_tier('temporal') == 'advanced'

    def test_known_research(self):
        from backend.analysis.analysis_tiers import get_tier
        assert get_tier('counterfactual') == 'research'
        assert get_tier('epv') == 'research'

    def test_unknown_fallback_to_research(self):
        from backend.analysis.analysis_tiers import get_tier
        assert get_tier('nonexistent_analysis') == 'research'

    def test_min_samples_ordering(self):
        from backend.analysis.analysis_tiers import TIER_MIN_SAMPLES
        assert TIER_MIN_SAMPLES['stable'] < TIER_MIN_SAMPLES['advanced']
        assert TIER_MIN_SAMPLES['advanced'] < TIER_MIN_SAMPLES['research']

    def test_all_tiers_meta_structure(self):
        from backend.analysis.analysis_tiers import all_tiers_meta
        meta = all_tiers_meta()
        assert 'tiers' in meta
        assert 'stable' in meta['tiers']
        assert 'advanced' in meta['tiers']
        assert 'research' in meta['tiers']
        assert len(meta['tiers']['stable']) > 0

    def test_output_policy_research_no_conclusion(self):
        from backend.analysis.analysis_tiers import get_output_policy
        policy = get_output_policy('counterfactual')
        assert policy['show_conclusion'] is False
        assert policy['show_suggestion'] is False


# ── confidence output control テスト ────────────────────────────────────────

class TestConfidenceOutputControl:
    """confidence.py 拡張部分のテスト"""

    def test_output_flags_high(self):
        from backend.utils.confidence import output_flags
        flags = output_flags('high')
        assert flags['show_conclusion'] is True
        assert flags['show_suggestion'] is True
        assert flags['show_trend'] is True

    def test_output_flags_low(self):
        from backend.utils.confidence import output_flags
        flags = output_flags('low')
        assert flags['show_conclusion'] is False
        assert flags['show_trend'] is True

    def test_output_flags_insufficient(self):
        from backend.utils.confidence import output_flags
        flags = output_flags('insufficient')
        assert flags['show_conclusion'] is False
        assert flags['show_trend'] is False

    def test_gate_field_allowed(self):
        from backend.utils.confidence import gate_field
        result = gate_field('top_smash', 'high', 'show_conclusion')
        assert result == 'top_smash'

    def test_gate_field_blocked(self):
        from backend.utils.confidence import gate_field
        result = gate_field('top_smash', 'low', 'show_conclusion')
        assert result is None

    def test_gate_field_custom_placeholder(self):
        from backend.utils.confidence import gate_field
        result = gate_field('value', 'insufficient', 'show_trend', placeholder='—')
        assert result == '—'

    def test_build_confidence_aware_response(self):
        from backend.utils.confidence import build_confidence_aware_response
        data = {
            'trend': 'improving',
            'top_shot': 'smash',
            'suggestion': 'use more drops',
        }
        result = build_confidence_aware_response(
            data, 'low',
            conclusion_keys=['top_shot'],
            suggestion_keys=['suggestion'],
        )
        assert result['trend'] == 'improving'      # trend_key でないので保持
        assert result['top_shot'] is None           # conclusion → blocked
        assert result['suggestion'] is None         # suggestion → blocked

    def test_insufficient_response_structure(self):
        from backend.utils.confidence import insufficient_response
        resp = insufficient_response('pressure', 5)
        assert resp['success'] is True
        assert resp['data'] is None
        assert resp['confidence']['level'] == 'insufficient'
