"""analysis_registry の利用者向け文言に、開発者向けの表記が混ざらないことを固定する。

caution / assumptions / promotion_criteria は ResearchNotice 等でそのまま画面に出る。
以前はファイル名・内部定数名・Markdown の強調記号・作業用の工程ラベル・英語の専門語が
そのまま表示されていた。ここでは「画面に出してはいけない形」を機械的に検出する。
"""
from __future__ import annotations

import re

import pytest

from backend.analysis.analysis_registry import _RAW

_FIELDS = ("caution", "assumptions", "promotion_criteria")

# 画面に出してはいけない形
_FORBIDDEN = {
    "Markdown の強調記号": re.compile(r"\*\*|`"),
    "ソースファイル名": re.compile(r"\b[\w]+\.(py|ts|tsx|json)\b"),
    "内部定数名・snake_case 識別子": re.compile(r"\b_?[A-Za-z]+_[A-Za-z_]+\b"),
    "作業用の工程ラベル (CF-1 / DB-2 など)": re.compile(r"\b(CF|DB|RS)-\d"),
}

# 英語の専門語 (日本語で言い換えたもの)。再混入を防ぐ。
_ENGLISH_JARGON = [
    "Bootstrap", "Laplace", "softmax", "cohort", "Euclidean", "Sinkhorn",
    "fictitious", "split-conformal", "Beta-Binomial", "Brier", "Cox", "HMM",
    "admin-only", "experimental", "opt-in", "consent", "k-anonymity", "privacy",
    "peer", "demo", "bandit", "pooling", "reliability", "MAP",
]


def _texts():
    for raw in _RAW:
        for field in _FIELDS:
            value = raw.get(field)
            if value:
                yield raw["analysis_type"], field, value


@pytest.mark.parametrize(
    "label,pattern",
    list(_FORBIDDEN.items()),
    ids=["markdown", "source_file", "identifier", "phase_label"],
)
def test_no_developer_notation_in_user_text(label, pattern):
    hits = [
        (atype, field, m.group(0))
        for atype, field, text in _texts()
        for m in [pattern.search(text)]
        if m
    ]
    assert not hits, f"{label} が画面用の文言に残っている: {hits}"


def test_no_english_jargon_left():
    hits = [
        (atype, field, word)
        for atype, field, text in _texts()
        for word in _ENGLISH_JARGON
        if word.lower() in text.lower()
    ]
    assert not hits, f"英語の専門語が画面用の文言に残っている: {hits}"


def test_every_text_contains_japanese():
    # 全項目が日本語 (ひらがな・カタカナ・漢字) を含むこと。英数字だけの文言を弾く
    jp = re.compile(r"[぀-ヿ一-鿿]")
    bad = [(a, f) for a, f, t in _texts() if not jp.search(t)]
    assert not bad, f"日本語を含まない文言: {bad}"
