"""S-12: 対戦相手ポリシーの「状況」は打つ前の情報（受けた球の着地ゾーン）で定義する。

予測対象ショット自身の land_zone（結果）を条件に使うと、結果が条件に漏れて
「予測可能な状況」が膨らむ。合成ラリーで、旧定義（自身の着地ゾーン）と新定義
（受けた球の着地ゾーン）で予測可能性が食い違うことを固定する。
"""
from types import SimpleNamespace

from backend.analysis.opponent_policy_engine import compute_opponent_policy


def _stroke(num, player, shot, land_zone):
    return SimpleNamespace(stroke_num=num, player=player, shot_type=shot, land_zone=land_zone)


def _rally(rid, strokes):
    r = SimpleNamespace(
        id=rid, set_id=1, score_a_before=0, score_b_before=0,
        rally_length=len(strokes), server="player_a",
    )
    return r, strokes


def _compute(specs, min_support=2):
    """specs: [(incoming_zone, opp_shot, opp_own_land_zone)]。player_a 視点で、
    各ラリーは「player_a が incoming_zone へ打つ → player_b が opp_shot を打つ」の2球。"""
    rallies, by_rally = [], {}
    for i, (inc, shot, own) in enumerate(specs, start=1):
        r, stks = _rally(i, [
            _stroke(1, "player_a", "serve", inc),
            _stroke(2, "player_b", shot, own),
        ])
        rallies.append(r)
        by_rally[i] = stks
    return compute_opponent_policy(
        rallies=rallies, strokes_by_rally=by_rally,
        role_by_match={1: "player_a"}, set_to_match={1: 1}, set_num_by_set={1: 1},
        min_support=min_support,
    )


# 受けた球が NL のときは必ず clear、NR のときは必ず drop（受球ゾーンで完全に決まる）。
# 一方、打球自身の着地ゾーンは BL/BR/ML に散らばり、各着地ゾーンでは clear/drop が半々。
_SPECS = [
    ("NL", "clear", "BL"), ("NL", "clear", "BR"), ("NL", "clear", "ML"),
    ("NR", "drop", "BL"), ("NR", "drop", "BR"), ("NR", "drop", "ML"),
]


def _predictable(result):
    return [c for c in result["context_policies"] if c["predictability"] == "predictable"]


def test_situation_uses_incoming_zone_not_own_landing_zone():
    res = _compute(_SPECS)
    zones = sorted(c["context"]["zone"] for c in res["context_policies"])
    assert zones == ["NL", "NR"]  # 受けた球の着地ゾーン
    assert len(_predictable(res)) == 2
    for c in res["context_policies"]:
        assert c["n"] == 3  # n は状況ごとに報告される
        assert c["dominant_prob"] == 1.0


def test_own_landing_zone_does_not_change_the_result():
    # 自身の着地ゾーンをすべて同じ値に変えても（旧定義なら状況が変わる）結果は同じ
    other = [(inc, shot, "NC") for inc, shot, _ in _SPECS]
    assert _compute(_SPECS)["context_policies"] == _compute(other)["context_policies"]


def test_missing_incoming_zone_is_all_and_n_is_never_zero():
    res = _compute([(None, "clear", "BL"), (None, "drop", "BR")])
    assert [c["context"]["zone"] for c in res["context_policies"]] == [None]
    assert res["context_policies"][0]["n"] == 2
    assert res["context_policies"][0]["predictability"] == "mixed"
    # 支持数に満たない状況は出力しない（n=0/0.0 の偽値を作らない）
    assert _compute([(None, "clear", "BL")], min_support=2)["context_policies"] == []
