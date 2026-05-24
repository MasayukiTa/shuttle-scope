"""Tests for backend.wasb.inference.WasbInference and the factory env switch.

ONNX 重みが存在しない CI / 開発機でも動くよう、推論経路はモックで差し替える。
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from backend.wasb.inference import (
    FRAME_STACK,
    INPUT_H,
    INPUT_W,
    WasbInference,
)


def _dummy_frame() -> np.ndarray:
    """BGR HxWx3 uint8 ダミーフレーム。"""
    return np.full((INPUT_H, INPUT_W, 3), 128, dtype=np.uint8)


def test_instantiation_cpu_backend():
    eng = WasbInference(backend="cpu", device="CPU")
    assert eng.backend_name() == "unloaded"
    # _max_batch は load 前でも安全に呼べる (CPU 経路で 4)
    assert isinstance(eng._max_batch, int)
    assert eng._max_batch > 0


def test_predict_frames_empty():
    eng = WasbInference(backend="cpu", device="CPU")
    assert eng.predict_frames([]) == []


def test_predict_frames_below_window():
    eng = WasbInference(backend="cpu", device="CPU")
    # FRAME_STACK 未満なら 0 件
    assert eng.predict_frames([_dummy_frame()] * (FRAME_STACK - 1)) == []


def _fake_session(out_shape):
    """ONNX 出力を模した list[ndarray] を返す session スタブ。"""

    class _Sess:
        def __init__(self):
            self._inputs = [type("I", (), {"name": "input"})()]

        def get_inputs(self):
            return self._inputs

        def run(self, _outputs, feeds):
            b = next(iter(feeds.values())).shape[0]
            # 中心が強いヒートマップを返す → x_norm/y_norm が 0.5 付近に
            hm = np.zeros((b, *out_shape), dtype=np.float32)
            cy, cx = out_shape[-2] // 2, out_shape[-1] // 2
            # (B, 3, H, W) を想定。最終 ch にピーク。
            hm[:, -1, cy, cx] = 0.9
            return [hm]

    return _Sess()


def _install_fake_session(eng: WasbInference):
    eng._session = _fake_session((FRAME_STACK, INPUT_H, INPUT_W))
    eng._input_name = "input"
    eng._backend_name = "cpu"
    eng._loaded = True


def test_predict_frames_returns_n_triplets():
    eng = WasbInference(backend="cpu", device="CPU")
    _install_fake_session(eng)
    frames = [_dummy_frame() for _ in range(5)]
    out = eng.predict_frames(frames)
    # 5 - 3 + 1 = 3
    assert len(out) == 3
    for i, row in enumerate(out, start=1):
        assert row["frame_idx"] == i


def test_predict_frames_schema_keys():
    eng = WasbInference(backend="cpu", device="CPU")
    _install_fake_session(eng)
    frames = [_dummy_frame() for _ in range(FRAME_STACK)]
    out = eng.predict_frames(frames)
    assert len(out) == 1
    required = {"frame_idx", "confidence", "x_norm", "y_norm", "visible", "zone"}
    assert required.issubset(out[0].keys())
    # 中心ピーク (0.9) なので visible True、座標は 0.5 付近
    assert out[0]["visible"] is True
    assert out[0]["confidence"] >= 0.5
    assert 0.4 < out[0]["x_norm"] < 0.6
    assert 0.4 < out[0]["y_norm"] < 0.6


def test_predict_frames_load_failure_returns_placeholders():
    """ONNX が存在しない場合 graceful に visible=False の placeholder を返す。"""
    eng = WasbInference(
        backend="cpu", device="CPU", model_path="/nonexistent/wasb.onnx"
    )
    # 環境変数の漏れを防ぐ
    with patch.dict(os.environ, {"SS_WASB_ONNX": ""}, clear=False):
        out = eng.predict_frames([_dummy_frame() for _ in range(FRAME_STACK)])
    assert len(out) == 1
    assert out[0]["visible"] is False
    assert out[0]["x_norm"] is None
    assert out[0]["y_norm"] is None
    assert eng.get_load_error() is not None


def test_max_batch_positive_int():
    eng = WasbInference(backend="cpu", device="CPU")
    assert eng._max_batch >= 1


def test_factory_env_switch_default_is_tracknet(monkeypatch):
    """SS_SHUTTLE_IMPL 未設定なら TrackNet を返す (backward compat)。"""
    from backend.cv import factory

    monkeypatch.delenv("SS_SHUTTLE_IMPL", raising=False)
    factory.clear_cache()
    tn = factory.get_tracknet()
    sd = factory.get_shuttle_detector()
    assert sd is tn


def test_factory_env_switch_wasb_falls_back_when_model_missing(monkeypatch, tmp_path):
    """SS_SHUTTLE_IMPL=wasb でも ONNX が無ければ TrackNet にフォールバック。"""
    from backend.cv import factory

    monkeypatch.setenv("SS_SHUTTLE_IMPL", "wasb")
    monkeypatch.setenv("SS_WASB_ONNX", str(tmp_path / "does_not_exist.onnx"))
    factory.clear_cache()
    sd = factory.get_shuttle_detector()
    # WASB の load が失敗するので TrackNet impl が返ってくる
    assert sd is factory.get_tracknet()
