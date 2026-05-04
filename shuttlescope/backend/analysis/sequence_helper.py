"""
sequence_helper.py — ストロークシーケンス解析共通ヘルパー

pre-win / pre-loss 比較、counterfactual、レコメンデーションランキング、
シーケンス埋め込みなど、ショット列を使う解析の土台になるモジュール。

すべての関数は純粋関数（副作用なし）として実装し、テスト容易性を確保する。
"""
from __future__ import annotations
from collections import Counter
from typing import Optional

from backend.db.models import Rally, Stroke


# ── ストロークシーケンス抽出 ─────────────────────────────────────────────────

def player_stroke_sequence(
    rallies: list[Rally],
    strokes_by_rally: dict[int, list[Stroke]],
    player_role: str,
) -> list[str]:
    """
    target_player のストロークを時系列順に並べた shot_type リストを返す。

    Parameters:
        rallies:          ラリー一覧（rally_num 昇順推奨）
        strokes_by_rally: rally_id → Stroke リスト
        player_role:      'player_a' / 'player_b' / 'partner_a' / 'partner_b'

    Returns:
        ['smash', 'net_shot', 'clear', ...] のような shot_type 列
    """
    seq: list[str] = []
    for rally in rallies:
        strokes = strokes_by_rally.get(rally.id, [])
        for s in sorted(strokes, key=lambda x: x.stroke_num):
            if s.player == player_role:
                seq.append(s.shot_type)
    return seq


def rally_stroke_sequence(
    rally: Rally,
    strokes: list[Stroke],
    player_role: str,
) -> list[str]:
    """単一ラリー内の target_player ストローク列を返す"""
    return [
        s.shot_type
        for s in sorted(strokes, key=lambda x: x.stroke_num)
        if s.player == player_role
    ]


def all_player_strokes_in_rally(
    rally: Rally,
    strokes: list[Stroke],
    player_role: str,
) -> list[Stroke]:
    """単一ラリー内の target_player の Stroke オブジェクトリストを返す"""
    return [
        s for s in sorted(strokes, key=lambda x: x.stroke_num)
        if s.player == player_role
    ]


# ── シーケンス分析ユーティリティ ─────────────────────────────────────────────

def last_n_shots(sequence: list[str], n: int = 3) -> list[str]:
    """シーケンスの末尾 n 件を返す"""
    return sequence[-n:] if len(sequence) >= n else sequence[:]


def context_response_pairs(
    sequence: list[str],
    context_len: int = 1,
) -> list[tuple[tuple[str, ...], str]]:
    """
    (コンテキスト n-gram, 次のショット) のペアリストを返す。
    予測モデル・推薦の特徴量として使う。

    >>> context_response_pairs(['A','B','C','D'], context_len=2)
    [(('A','B'), 'C'), (('B','C'), 'D')]
    """
    pairs: list[tuple[tuple[str, ...], str]] = []
    for i in range(len(sequence) - context_len):
        ctx = tuple(sequence[i : i + context_len])
        resp = sequence[i + context_len]
        pairs.append((ctx, resp))
    return pairs


def stroke_ngrams(sequence: list[str], n: int = 2) -> list[tuple[str, ...]]:
    """
    ストロークシーケンスから n-gram タプルのリストを返す。

    >>> stroke_ngrams(['A','B','C'], 2)
    [('A', 'B'), ('B', 'C')]
    """
    return [tuple(sequence[i : i + n]) for i in range(len(sequence) - n + 1)]


def transition_pairs(sequence: list[str]) -> list[tuple[str, str]]:
    """
    隣接ショット間の遷移ペア (from_shot, to_shot) リストを返す。
    遷移行列構築の基礎データ。
    """
    return [(sequence[i], sequence[i + 1]) for i in range(len(sequence) - 1)]


def ngram_frequency(sequence: list[str], n: int = 2) -> dict[tuple[str, ...], int]:
    """n-gram の出現頻度カウントを返す"""
    return dict(Counter(stroke_ngrams(sequence, n)))


def transition_matrix(sequence: list[str], shot_keys: list[str]) -> dict[str, dict[str, int]]:
    """
    遷移行列を {from_shot: {to_shot: count}} の形式で返す。

    Parameters:
        sequence:  shot_type の時系列リスト
        shot_keys: 遷移行列の行・列に使う shot_type 一覧
    """
    matrix: dict[str, dict[str, int]] = {k: {j: 0 for j in shot_keys} for k in shot_keys}
    for from_shot, to_shot in transition_pairs(sequence):
        if from_shot in matrix and to_shot in matrix[from_shot]:
            matrix[from_shot][to_shot] += 1
    return matrix


# ── ラリー文脈付きシーケンス ─────────────────────────────────────────────────

def pre_outcome_sequences(
    rallies: list[Rally],
    strokes_by_rally: dict[int, list[Stroke]],
    player_role: str,
    outcome: str,   # 'win' / 'loss'
    tail_n: int = 3,
) -> list[list[str]]:
    """
    勝利/敗戦ラリー直前 tail_n 打のショット列を返す。
    pre-win / pre-loss 比較分析に使う。
    """
    results: list[list[str]] = []
    for rally in rallies:
        player_won = rally.winner == player_role
        if (outcome == "win" and player_won) or (outcome == "loss" and not player_won):
            seq = rally_stroke_sequence(rally, strokes_by_rally.get(rally.id, []), player_role)
            if seq:
                results.append(last_n_shots(seq, tail_n))
    return results


def score_context_shots(
    rallies: list[Rally],
    strokes_by_rally: dict[int, list[Stroke]],
    player_role: str,
    pressure_min: int = 15,
) -> list[str]:
    """
    プレッシャー局面（得点が pressure_min 以上）でのショット列を返す。
    Pressure performance 解析に使う。

    score_a_before / score_b_before が利用可能な場合はそちらを使用し、
    ない場合は score_a_after / score_b_after から推定する。
    """
    result: list[str] = []
    for rally in rallies:
        # score_before が入っていればそちらを優先
        score_a = getattr(rally, 'score_a_before', None)
        score_b = getattr(rally, 'score_b_before', None)
        if score_a is None or score_b is None:
            # フォールバック: score_after を使う（精度は低下する）
            score_a = rally.score_a_after
            score_b = rally.score_b_after

        if score_a >= pressure_min or score_b >= pressure_min:
            strokes = strokes_by_rally.get(rally.id, [])
            for s in sorted(strokes, key=lambda x: x.stroke_num):
                if s.player == player_role:
                    result.append(s.shot_type)
    return result
