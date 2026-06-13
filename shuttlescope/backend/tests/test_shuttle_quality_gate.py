"""shuttle_quality_gate (A0) のユニットテスト。

quality-gate の ON/OFF で confidence が変わること、誤検出疑い（瞬間移動）の
フレームがより強く減衰されることを検証する。DB アクセスなし・純粋関数レベル。
"""
import os

import pytest

from backend.cv import shuttle_quality_gate as q


@pytest.fixture(autouse=True)
def _clean_env():
    """各テスト後に gate 関連 env をクリアして相互汚染を防ぐ。"""
    keys = [k for k in os.environ if k.startswith("SS_SHUTTLE_GATE") or k == "SS_SHUTTLE_QUALITY_GATE"]
    saved = {k: os.environ[k] for k in keys}
    yield
    for k in list(os.environ):
        if k.startswith("SS_SHUTTLE_GATE") or k == "SS_SHUTTLE_QUALITY_GATE":
            del os.environ[k]
    os.environ.update(saved)


def _smooth_frames(n=6, conf=0.9):
    return [
        {"timestamp_sec": i * 0.1, "confidence": conf,
         "x_norm": 0.3 + i * 0.01, "y_norm": 0.5 + i * 0.01}
        for i in range(n)
    ]


class TestGateOnOff:
    def test_gate_off_returns_unchanged(self):
        os.environ["SS_SHUTTLE_QUALITY_GATE"] = "0"
        frames = _smooth_frames()
        out = q.gate_frames(frames)
        assert all(f["confidence"] == 0.9 for f in out)
        assert "quality_factor" not in out[0]

    def test_gate_on_attenuates_and_annotates(self):
        os.environ.pop("SS_SHUTTLE_QUALITY_GATE", None)  # 既定 ON
        frames = _smooth_frames()
        out = q.gate_frames(frames)
        # gated_conf <= raw_conf、raw は保全される
        assert out[0]["raw_confidence"] == 0.9
        assert out[0]["confidence"] <= 0.9
        assert "quality_factor" in out[0]
        assert "quality_signals" in out[0]

    def test_does_not_mutate_input(self):
        frames = _smooth_frames()
        original = frames[0]["confidence"]
        q.gate_frames(frames)
        assert frames[0]["confidence"] == original
        assert "quality_factor" not in frames[0]


class TestMotionConsistency:
    def test_teleport_frame_more_attenuated_than_smooth(self):
        """瞬間移動するフレーム（ユニフォーム/ネット誤検出疑い）は強く減衰される。"""
        os.environ.pop("SS_SHUTTLE_QUALITY_GATE", None)
        frames = _smooth_frames()
        # 連続軌道から大きく外れた点を末尾に追加
        frames.append({"timestamp_sec": 0.6, "confidence": 0.9,
                       "x_norm": 0.95, "y_norm": 0.05})
        out = q.gate_frames(frames)
        smooth_factor = out[1]["quality_factor"]
        teleport_factor = out[-1]["quality_factor"]
        assert teleport_factor < smooth_factor


class TestSharpness:
    def test_explicit_heatmap_sharpness_used(self):
        os.environ.pop("SS_SHUTTLE_QUALITY_GATE", None)
        sharp = {"timestamp_sec": 0.0, "confidence": 0.5,
                 "x_norm": 0.5, "y_norm": 0.5, "heatmap_sharpness": 1.0}
        blunt = {"timestamp_sec": 0.0, "confidence": 0.5,
                 "x_norm": 0.5, "y_norm": 0.5, "heatmap_sharpness": 0.0}
        assert q._sharpness_score(sharp) == 1.0
        assert q._sharpness_score(blunt) == 0.0


class TestEnvOverrides:
    def test_floor_overridable(self):
        os.environ["SS_SHUTTLE_GATE_FLOOR"] = "0.5"
        # sharpness=0, motion=0 でも floor で 0.5 を下回らない
        assert q.compute_quality_factor(0.0, 0.0) == 0.5

    def test_weights_overridable(self):
        os.environ["SS_SHUTTLE_GATE_W_SHARPNESS"] = "1.0"
        os.environ["SS_SHUTTLE_GATE_W_MOTION"] = "0.0"
        # motion を無視 → sharpness のみで決まる
        assert q.compute_quality_factor(1.0, 0.0) == 1.0
