"""Fix the ONE official attack/defence height rule (coach + university request).

The rule is body-relative and lives in a single place
(backend.analysis.attack_defence):

    wrist at or above racket height -> attack
    wrist below racket height       -> defence

These tests pin the mapping, the unknown/None behaviour (we never guess from a
different concept) and the aggregation shape.
"""
from __future__ import annotations

from backend.analysis.attack_defence import (
    ATTACK,
    DEFENCE,
    VALID_WRIST_VS_RACKET,
    classify_attack_defence,
    stroke_attack_defence,
    summarize_attack_defence,
)
from backend.utils.validators import VALID_WRIST_VS_RACKET as VALIDATORS_VOCAB


class _Stroke:
    def __init__(self, wrist_vs_racket):
        self.wrist_vs_racket = wrist_vs_racket


class TestClassifyRule:
    def test_at_or_above_is_attack(self):
        assert classify_attack_defence("at_or_above") == ATTACK

    def test_below_is_defence(self):
        assert classify_attack_defence("below") == DEFENCE

    def test_none_is_unknown(self):
        assert classify_attack_defence(None) is None

    def test_unknown_label_is_unknown_not_a_guess(self):
        # Vocabulary from a different concept must not be mapped.
        assert classify_attack_defence("above_net") is None  # net-relative hit_height
        assert classify_attack_defence("overhead") is None    # contact_height form
        assert classify_attack_defence("") is None

    def test_vocabulary_is_shared_with_validators(self):
        assert VALID_WRIST_VS_RACKET == VALIDATORS_VOCAB == frozenset({"at_or_above", "below"})


class TestStrokeAccessor:
    def test_reads_orm_object(self):
        assert stroke_attack_defence(_Stroke("at_or_above")) == ATTACK
        assert stroke_attack_defence(_Stroke("below")) == DEFENCE
        assert stroke_attack_defence(_Stroke(None)) is None

    def test_reads_dict(self):
        assert stroke_attack_defence({"wrist_vs_racket": "below"}) == DEFENCE
        assert stroke_attack_defence({}) is None


class TestSummary:
    def test_counts_and_rate_over_classified_only(self):
        strokes = [
            _Stroke("at_or_above"),
            _Stroke("at_or_above"),
            _Stroke("below"),
            _Stroke(None),          # unrecorded -> unknown, excluded from rate
            _Stroke("overhead"),    # unknown label -> unknown
        ]
        out = summarize_attack_defence(strokes)
        assert out["attack"] == 2
        assert out["defence"] == 1
        assert out["unknown"] == 2
        assert out["classified"] == 3
        assert abs(out["attack_rate"] - (2 / 3)) < 1e-9

    def test_rate_is_none_when_nothing_classified(self):
        out = summarize_attack_defence([_Stroke(None), _Stroke("")])
        assert out["classified"] == 0
        assert out["attack_rate"] is None
        assert out["unknown"] == 2

    def test_empty_input(self):
        out = summarize_attack_defence([])
        assert out == {
            "attack": 0,
            "defence": 0,
            "unknown": 0,
            "classified": 0,
            "attack_rate": None,
        }
