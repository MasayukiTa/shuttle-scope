"""head-to-head の区間は試合を単位に作る (監査 #302)。

同じ試合のラリーは独立でないので、全ラリー数を n とする Wilson 区間は狭すぎる。値は架空。
"""
from __future__ import annotations

from backend.utils.confidence import cluster_rate_ci, wilson_ci


def test_single_match_has_no_interval():
    assert cluster_rate_ci([(12, 20)]) is None
    assert cluster_rate_ci([]) is None
    assert cluster_rate_ci([(0, 0), (3, 10)]) is None


def test_between_match_variation_widens_the_interval_beyond_wilson():
    # 4 試合 40 ラリー、全体は 20/40。試合ごとのばらつきが大きい。
    clusters = [(9, 10), (1, 10), (8, 10), (2, 10)]
    lo, hi = cluster_rate_ci(clusters)
    w_lo, w_hi = wilson_ci(20, 40)
    assert (hi - lo) > (w_hi - w_lo)
    assert lo < 0.5 < hi


def test_homogeneous_matches_give_narrow_interval_inside_unit_range():
    clusters = [(5, 10)] * 12
    lo, hi = cluster_rate_ci(clusters)
    assert 0.0 <= lo <= 0.5 <= hi <= 1.0
    assert (hi - lo) < 0.05
