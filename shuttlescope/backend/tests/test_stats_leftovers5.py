"""陣形割合 (front_back_ratio / parallel_ratio) の n=0 は 0.0 ではなく None。

「陣形を集計できるフレームが無い」を「前後陣 0%・平行陣 0%」と区別する。
court_mapper → doubles_cv_engine → doubles_role_inference の全段で確認する。
"""
from backend.analysis.doubles_cv_engine import _compute_formation_tendency
from backend.analysis.doubles_role_inference import adjust_role_with_cv_signals
from backend.yolo.court_mapper import summarize_frame_positions


def test_court_mapper_zero_frames_ratios_are_none():
    s = summarize_frame_positions([])
    assert s["total_frames"] == 0
    assert s["front_back_ratio"] is None
    assert s["parallel_ratio"] is None


def test_formation_tendency_without_data_is_unknown():
    s = summarize_frame_positions([])
    r = _compute_formation_tendency(s)
    assert r["front_back_ratio"] is None
    assert r["parallel_ratio"] is None
    assert r["style_label"] == "不明"
    assert r["dominant"] == "unknown"
    assert all(v["ratio"] is None for v in r["breakdown"].values())


def test_formation_tendency_with_data_unchanged():
    r = _compute_formation_tendency({
        "formations": {"front_back": 70, "parallel": 15, "mixed": 10, "unknown": 5},
        "front_back_ratio": 0.7,
        "parallel_ratio": 0.15,
    })
    assert r["dominant"] == "front_back"
    assert r["style_label"] == "前後陣傾向"
    assert r["breakdown"]["front_back"]["ratio"] == 0.7


def test_role_inference_cv_unavailable_when_ratios_are_none():
    s = summarize_frame_positions([])
    r = adjust_role_with_cv_signals({"inferred_role": "front", "confidence_score": 0.9}, s)
    assert r["cv_available"] is False
    assert r["agreement"] == "unknown"
