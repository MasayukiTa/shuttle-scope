"""打球者候補の平均確信度は、候補が 0 件なら 0.0 ではなく None。"""
from backend.yolo.cv_aligner import _summarize_events


def _ev(hitter, conf=0.7):
    return {"formation": "front_back", "hitter_candidate": hitter, "hitter_confidence": conf}


def test_no_events_confidence_is_none():
    s = _summarize_events([])
    assert s["hitter_a_avg_confidence"] is None
    assert s["hitter_b_avg_confidence"] is None


def test_only_one_side_has_candidates():
    s = _summarize_events([_ev("player_a", 0.8), _ev("player_a", 0.6)])
    assert abs(s["hitter_a_avg_confidence"] - 0.7) < 1e-6
    assert s["hitter_b_avg_confidence"] is None
