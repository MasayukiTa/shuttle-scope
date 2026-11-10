"""サーブはラリー先頭の 1 打だけ (監査 #327 / #330 / #331 / #38 / #41)。

ラリーの途中に short_service / long_service が混じった列から、
「サーブが 2 回入った 3 連ショット」「ショートサーブ -> ショートサーブ」の遷移、
「ラリー中盤のサーブ」を作らないことを確かめる。値はすべて架空。
"""
from __future__ import annotations

from types import SimpleNamespace

from backend.analysis.markov import MarkovAnalyzer, SHOT_KEYS
from backend.analysis.sequence_helper import (
    pre_outcome_sequences,
    rally_stroke_sequence,
)
from backend.analysis.service_shots import (
    is_service_shot,
    truncate_at_stray_service,
    without_service,
)


def _stroke(num: int, shot: str, player: str = "player_a") -> SimpleNamespace:
    return SimpleNamespace(stroke_num=num, shot_type=shot, player=player)


def test_truncate_keeps_opening_service_and_cuts_stray_service():
    assert truncate_at_stray_service(["short_service", "clear", "smash"]) == [
        "short_service", "clear", "smash",
    ]
    assert truncate_at_stray_service(["short_service", "clear", "short_service", "drop"]) == [
        "short_service", "clear",
    ]
    assert truncate_at_stray_service(["short_service", "short_service"]) == ["short_service"]


def test_without_service_and_is_service_shot():
    assert is_service_shot("long_service") and not is_service_shot("clear")
    assert without_service(["long_service", "clear", "drop"]) == ["clear", "drop"]


def test_markov_triplets_never_contain_two_serves():
    strokes = [
        {"shot_type": "short_service"},
        {"shot_type": "net_shot"},
        {"shot_type": "short_service"},  # 同一ラリーの 2 本目のサーブ (記録の食い違い)
        {"shot_type": "clear"},
        {"shot_type": "smash"},
    ]
    triplets = MarkovAnalyzer().extract_triplets([strokes])
    assert triplets == []  # 打ち切り後は 2 打しか残らない
    ok = MarkovAnalyzer().extract_triplets(
        [[{"shot_type": "short_service"}, {"shot_type": "net_shot"}, {"shot_type": "clear"}]]
    )
    assert ok == [("short_service", "net_shot", "clear")]


def test_markov_matrix_has_no_service_to_service_transition():
    strokes = [
        {"shot_type": "short_service"},
        {"shot_type": "short_service"},
        {"shot_type": "short_service"},
    ]
    m = MarkovAnalyzer().build_transition_matrix([strokes], laplace_alpha=0.0)
    i = SHOT_KEYS.index("short_service")
    # 平滑化なし: 偽の遷移が数えられていれば行 i に確率が立つ
    assert m[i][i] == 0.0


def test_rally_sequence_cuts_at_stray_service():
    strokes = [
        _stroke(1, "short_service"),
        _stroke(3, "clear"),
        _stroke(5, "long_service"),
        _stroke(7, "smash"),
    ]
    seq = rally_stroke_sequence(SimpleNamespace(id=1), strokes, "player_a")
    assert seq == ["short_service", "clear"]


def test_pre_outcome_tail_excludes_serve():
    # 3 打のラリー: 末尾 3 打に先頭のサーブが入っていた
    rally = SimpleNamespace(id=1, winner="player_a")
    strokes = {1: [_stroke(1, "short_service"), _stroke(3, "net_shot"), _stroke(5, "push_rush")]}
    out = pre_outcome_sequences([rally], strokes, "player_a", "win", tail_n=3)
    assert out == [["net_shot", "push_rush"]]
