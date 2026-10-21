"""最頻スコアライン: 帯データが無いときは偽の値 ('21-??') でなく null を返す。"""
from backend.analysis.prediction_engine import compute_most_likely_scorelines


def test_no_score_band_gives_null_not_placeholder():
    out = compute_most_likely_scorelines({"2-0": 0.6, "0-2": 0.4}, {})
    assert out, "scorelines must still be returned"
    for item in out:
        assert item["set1_score"] is None
        assert "?" not in str(item)
