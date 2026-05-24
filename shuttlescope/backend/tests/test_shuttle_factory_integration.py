"""Integration tests: factory.get_shuttle_detector() env switch.

production の routers / pipeline / analysis から呼ばれる ``get_shuttle_detector()``
が ``SS_SHUTTLE_IMPL`` env で TrackNet と WASB を正しく切り替えること、
キャッシュが env 変更で無効化されることを担保する。

ONNX 重みや CUDA がない環境でも動くよう、WASB 経路はモック化する。
"""
from __future__ import annotations

import numpy as np
import pytest

from backend.cv import factory


@pytest.fixture(autouse=True)
def _clear_factory_cache():
    factory.clear_cache()
    yield
    factory.clear_cache()


def test_default_returns_tracknet_instance(monkeypatch):
    """SS_SHUTTLE_IMPL 未設定なら TrackNet が返ること。"""
    monkeypatch.delenv("SS_SHUTTLE_IMPL", raising=False)
    sd = factory.get_shuttle_detector()
    tn = factory.get_tracknet()
    assert sd is tn
    # TrackNet 互換 API
    assert hasattr(sd, "run")


def test_explicit_tracknet_env(monkeypatch):
    """SS_SHUTTLE_IMPL=tracknet で TrackNet が返ること。"""
    monkeypatch.setenv("SS_SHUTTLE_IMPL", "tracknet")
    sd = factory.get_shuttle_detector()
    assert sd is factory.get_tracknet()


def test_wasb_env_returns_wasb_instance(monkeypatch):
    """SS_SHUTTLE_IMPL=wasb で WasbInference が返ること (load を mock)。"""
    from backend.wasb.inference import WasbInference

    monkeypatch.setenv("SS_SHUTTLE_IMPL", "wasb")
    # load() が常に True を返すよう mock し、ONNX 不在環境でも WASB を返させる
    monkeypatch.setattr(WasbInference, "load", lambda self: True)
    monkeypatch.setattr(WasbInference, "backend_name", lambda self: "mock")

    sd = factory.get_shuttle_detector()
    assert isinstance(sd, WasbInference)


def test_wasb_fallback_to_tracknet_when_load_fails(monkeypatch, tmp_path):
    """WASB の load 失敗時は TrackNet にフォールバックすること。"""
    monkeypatch.setenv("SS_SHUTTLE_IMPL", "wasb")
    monkeypatch.setenv("SS_WASB_ONNX", str(tmp_path / "missing.onnx"))
    sd = factory.get_shuttle_detector()
    # WASB の load が失敗 → TrackNet にフォールバック
    assert sd is factory.get_tracknet()


def test_cache_invalidated_on_env_change(monkeypatch):
    """env 変更後に clear_cache を挟まなくても、キーの違いで別 impl が返ること。

    factory.get_shuttle_detector は SS_SHUTTLE_IMPL を含むキーでキャッシュする
    ため、env を変えれば再解決される (clear_cache は本来不要だが、念のため明示)。
    """
    from backend.wasb.inference import WasbInference

    # 1) tracknet
    monkeypatch.setenv("SS_SHUTTLE_IMPL", "tracknet")
    sd1 = factory.get_shuttle_detector()
    assert sd1 is factory.get_tracknet()

    # 2) wasb
    monkeypatch.setattr(WasbInference, "load", lambda self: True)
    monkeypatch.setattr(WasbInference, "backend_name", lambda self: "mock")
    monkeypatch.setenv("SS_SHUTTLE_IMPL", "wasb")
    sd2 = factory.get_shuttle_detector()
    assert isinstance(sd2, WasbInference)
    assert sd2 is not sd1


def test_both_impls_have_run_api(monkeypatch):
    """TrackNet / WASB 両方 .run(video_path) API を持つ (production 互換性)。

    production の video_pipeline / tracknet_runner は inferencer.run(video_path)
    を呼ぶため、両 impl にこの method が存在することを保証する。
    """
    from backend.wasb.inference import WasbInference

    # TrackNet
    monkeypatch.setenv("SS_SHUTTLE_IMPL", "tracknet")
    tn = factory.get_shuttle_detector()
    assert callable(getattr(tn, "run", None))

    # WASB
    monkeypatch.setattr(WasbInference, "load", lambda self: True)
    monkeypatch.setattr(WasbInference, "backend_name", lambda self: "mock")
    monkeypatch.setenv("SS_SHUTTLE_IMPL", "wasb")
    wasb = factory.get_shuttle_detector()
    assert callable(getattr(wasb, "run", None))


def test_wasb_run_adapter_returns_shuttle_samples(monkeypatch):
    """WasbInference.run() が ShuttleSample のリストを返すこと (predict_frames から変換)。"""
    from backend.cv.base import ShuttleSample
    from backend.wasb.inference import FRAME_STACK, WasbInference

    eng = WasbInference(backend="cpu", device="CPU")
    eng._loaded = True  # load を skip

    fake_frames = [np.full((288, 512, 3), 128, dtype=np.uint8) for _ in range(5)]

    def _fake_predict(self, frames):
        return [
            {
                "frame_idx": i + 1, "zone": "z1", "confidence": 0.8,
                "x_norm": 0.5, "y_norm": 0.5, "visible": True,
            }
            for i in range(len(frames) - FRAME_STACK + 1)
        ]

    monkeypatch.setattr(WasbInference, "predict_frames", _fake_predict)

    # cv2.VideoCapture を mock して fake_frames を流す
    import cv2

    class _FakeCap:
        def __init__(self, _p):
            self._i = 0
        def isOpened(self):
            return True
        def get(self, _prop):
            return 30.0
        def read(self):
            if self._i >= len(fake_frames):
                return False, None
            f = fake_frames[self._i]
            self._i += 1
            return True, f
        def release(self):
            pass

    monkeypatch.setattr(cv2, "VideoCapture", _FakeCap)

    samples = eng.run("dummy.mp4")
    assert len(samples) == 5 - FRAME_STACK + 1
    assert all(isinstance(s, ShuttleSample) for s in samples)
    assert samples[0].confidence == pytest.approx(0.8)
    # x/y は px (normalized * resolution)
    assert samples[0].x == pytest.approx(0.5 * 512)
    assert samples[0].y == pytest.approx(0.5 * 288)
