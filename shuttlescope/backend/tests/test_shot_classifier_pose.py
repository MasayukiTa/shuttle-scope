"""shot_classifier rule-v1 (A1-1) のユニットテスト。

PoseFrame が無ければ rule-v0 相当にフォールバックし、ポーズが shot_type の
典型フォームに整合すれば confidence が上がり、外れれば下がることを検証する。
"""
from backend.cv.shot_classifier import classify_stroke, MODEL_VERSION


def _lm_frame(wrist_y, shoulder_y, elbow_extended=True):
    """MediaPipe 33点 landmarks dict（右手を打球側に置く）。"""
    lms = [[0.5, 0.5, 1.0] for _ in range(33)]
    # 11/12 = shoulders, 13/14 = elbows, 15/16 = wrists, 23/24 = hips
    lms[12] = [0.50, shoulder_y, 1.0]   # right_shoulder
    lms[11] = [0.45, shoulder_y, 1.0]   # left_shoulder
    lms[16] = [0.55, wrist_y, 1.0]      # right_wrist (打球側: より高い)
    lms[15] = [0.40, wrist_y + 0.3, 1.0]  # left_wrist (低い)
    mid_y = (shoulder_y + wrist_y) / 2.0
    lms[14] = [0.52, mid_y, 1.0] if elbow_extended else [0.72, mid_y, 1.0]  # right_elbow
    lms[23] = [0.45, 0.80, 1.0]         # left_hip
    lms[24] = [0.55, 0.80, 1.0]         # right_hip
    return {"landmarks": lms}


class TestModelVersion:
    def test_model_version_is_v1(self):
        assert MODEL_VERSION == "rule-v1"
        out = classify_stroke({"shot_type": "smash"})
        assert out["model_version"] == "rule-v1"


class TestFallback:
    def test_no_pose_uses_rule_v0_logic(self):
        # pose 無し → 従来ルール（base 0.6 + hit_zone 0.1）
        out = classify_stroke({"shot_type": "smash", "hit_zone": "rear"})
        assert out["confidence"] == 0.7

    def test_empty_pose_list_fallback(self):
        out = classify_stroke({"shot_type": "smash"}, pose_frames=[])
        assert abs(out["confidence"] - 0.6) < 1e-9


class TestPoseAdjustment:
    def test_overhead_form_boosts_smash(self):
        base = classify_stroke({"shot_type": "smash"})["confidence"]
        # smash の典型: 手首が肩より上 + 肘伸展
        overhead = [_lm_frame(0.10, 0.40, elbow_extended=True) for _ in range(3)]
        boosted = classify_stroke({"shot_type": "smash"}, pose_frames=overhead)["confidence"]
        assert boosted > base

    def test_mismatched_form_reduces_smash(self):
        base = classify_stroke({"shot_type": "smash"})["confidence"]
        # smash なのに手首が肩より下（アンダー）+ 肘屈曲 → 乖離
        under = [_lm_frame(0.90, 0.40, elbow_extended=False) for _ in range(3)]
        reduced = classify_stroke({"shot_type": "smash"}, pose_frames=under)["confidence"]
        assert reduced < base

    def test_netshot_low_wrist_form_boosts(self):
        base = classify_stroke({"shot_type": "net"})["confidence"]
        low = [_lm_frame(0.90, 0.40, elbow_extended=False) for _ in range(3)]
        boosted = classify_stroke({"shot_type": "net"}, pose_frames=low)["confidence"]
        assert boosted > base

    def test_confidence_stays_in_bounds(self):
        overhead = [_lm_frame(0.05, 0.50, elbow_extended=True) for _ in range(5)]
        out = classify_stroke({"shot_type": "smash", "hit_zone": "rear"}, pose_frames=overhead)
        assert 0.05 <= out["confidence"] <= 0.99
