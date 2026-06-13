"""YOLO 検出バックエンド選択ロジックのユニットテスト。

GPU は不要。onnxruntime の provider 一覧と ONNX session 生成をモックして、
backend/yolo/inference.py の load() がどの経路を選ぶかだけを検証する。

検証観点 (2026-06-13 root-cause fix):
  - _yolo_backend_pref(): SS_YOLO_BACKEND の正規化
  - _coco_fallback_allowed(): COCO fallback の opt-in ガード
  - _resolve_onnx_model_path(): モデル解決の優先順と opt-in 制御
  - load(): CUDA EP がある環境で SS_YOLO_BACKEND=cuda が onnx_cuda 経路を選ぶ
            (= OpenVINO iGPU に落ちない) こと
  - load(): auto + opt-in 無しでは COCO fallback を使わず従来 OpenVINO に流れること
"""
from __future__ import annotations

import sys
import types

import pytest

import backend.yolo.inference as inf


# ── env helper ────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _clear_yolo_env(monkeypatch):
    """各テスト前に関係 env を一旦クリアする。"""
    for k in (
        "SS_YOLO_BACKEND",
        "SS_YOLO_USE_TRT",
        "SS_YOLO_TRT_FP16",
        "SS_YOLO_MODEL_PATH",
        "SS_YOLO_ALLOW_COCO_FALLBACK",
    ):
        monkeypatch.delenv(k, raising=False)
    yield


# ── _yolo_backend_pref ──────────────────────────────────────────────────────
class TestBackendPref:
    def test_unset_is_auto(self, monkeypatch):
        assert inf._yolo_backend_pref() == "auto"

    @pytest.mark.parametrize("val,expected", [
        ("cuda", "cuda"), ("CUDA", "cuda"), (" trt ", "trt"),
        ("openvino", "openvino"), ("auto", "auto"),
        ("garbage", "auto"), ("", "auto"),
    ])
    def test_normalization(self, monkeypatch, val, expected):
        monkeypatch.setenv("SS_YOLO_BACKEND", val)
        assert inf._yolo_backend_pref() == expected


# ── _coco_fallback_allowed ──────────────────────────────────────────────────
class TestCocoFallbackAllowed:
    def test_auto_default_disallowed(self):
        assert inf._coco_fallback_allowed("auto") is False

    def test_trt_cuda_pref_allowed(self):
        assert inf._coco_fallback_allowed("trt") is True
        assert inf._coco_fallback_allowed("cuda") is True

    def test_explicit_opt_in_flag(self, monkeypatch):
        monkeypatch.setenv("SS_YOLO_ALLOW_COCO_FALLBACK", "1")
        assert inf._coco_fallback_allowed("auto") is True


# ── _resolve_onnx_model_path ────────────────────────────────────────────────
class TestResolveModelPath:
    def test_env_model_path_wins_when_exists(self, monkeypatch, tmp_path):
        p = tmp_path / "finetuned.onnx"
        p.write_bytes(b"x")
        monkeypatch.setenv("SS_YOLO_MODEL_PATH", str(p))
        assert inf._resolve_onnx_model_path("auto") == p

    def test_auto_without_optin_returns_none_when_badminton_absent(self, monkeypatch):
        # 既定構成: yolo_badminton.onnx 不在 & opt-in 無し → None (step0 skip)
        monkeypatch.setattr(inf, "ONNX_MODEL", _FakePath(False))
        monkeypatch.setattr(inf, "COCO_ONNX_MODEL", _FakePath(True))
        assert inf._resolve_onnx_model_path("auto") is None

    def test_coco_fallback_used_when_optin(self, monkeypatch):
        monkeypatch.setattr(inf, "ONNX_MODEL", _FakePath(False))
        coco = _FakePath(True)
        monkeypatch.setattr(inf, "COCO_ONNX_MODEL", coco)
        assert inf._resolve_onnx_model_path("cuda") is coco


class _FakePath:
    """Path 互換の最小スタブ (exists() を固定で返す)。"""
    def __init__(self, exists: bool, name: str = "fake.onnx"):
        self._exists = exists
        self.name = name

    def exists(self) -> bool:
        return self._exists

    def __fspath__(self) -> str:
        return self.name

    def __str__(self) -> str:
        return self.name


# ── load() 経路選択 (onnxruntime をモック) ──────────────────────────────────
class _FakeSession:
    def __init__(self, providers):
        self._providers = providers

    def get_providers(self):
        return list(self._providers)


def _install_fake_ort(monkeypatch, available_providers):
    """onnxruntime をモックし、InferenceSession が指定 providers の最初の名前を
    active provider として返すようにする。"""
    fake = types.ModuleType("onnxruntime")

    class _GraphLevel:
        ORT_ENABLE_ALL = 99

    class _SessOpts:
        def __init__(self):
            self.graph_optimization_level = None

    def _get_available_providers():
        return list(available_providers)

    def _InferenceSession(path, sess_opts=None, providers=None):
        names = []
        for p in providers or []:
            names.append(p[0] if isinstance(p, tuple) else p)
        # 実際の ORT は available なものを順に採用する。ここでは
        # providers の先頭で available なものを active とする。
        active = next((n for n in names if n in available_providers), "CPUExecutionProvider")
        ordered = [active] + [n for n in names if n != active]
        return _FakeSession(ordered)

    fake.get_available_providers = _get_available_providers
    fake.GraphOptimizationLevel = _GraphLevel
    fake.SessionOptions = _SessOpts
    fake.InferenceSession = _InferenceSession
    monkeypatch.setitem(sys.modules, "onnxruntime", fake)


def _new_instance():
    return inf.YOLOInference(cuda_device_index=0, openvino_device="GPU")


class TestLoadDeviceSelection:
    def test_cuda_pref_selects_cuda_ep_not_openvino(self, monkeypatch):
        """SS_YOLO_BACKEND=cuda + CUDA EP あり → onnx_cuda 経路を選ぶ。
        OpenVINO iGPU に落ちないことを backend 名で確認する。"""
        monkeypatch.setenv("SS_YOLO_BACKEND", "cuda")
        _install_fake_ort(monkeypatch, ["CUDAExecutionProvider", "CPUExecutionProvider"])
        # COCO fallback を確実に解決させる
        monkeypatch.setattr(inf, "ONNX_MODEL", _FakePath(False))
        monkeypatch.setattr(inf, "COCO_ONNX_MODEL", _FakePath(True, "yolov8n.onnx"))

        ins = _new_instance()
        assert ins.load() is True
        assert ins._backend == "onnx_cuda:0"

    def test_trt_pref_selects_trt_ep(self, monkeypatch):
        monkeypatch.setenv("SS_YOLO_BACKEND", "trt")
        _install_fake_ort(monkeypatch, [
            "TensorrtExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider",
        ])
        monkeypatch.setattr(inf, "ONNX_MODEL", _FakePath(False))
        monkeypatch.setattr(inf, "COCO_ONNX_MODEL", _FakePath(True, "yolov8n.onnx"))
        # trt_cache.mkdir を回避するため WEIGHTS_DIR を tmp に逃がす
        import tempfile, pathlib
        monkeypatch.setattr(inf, "WEIGHTS_DIR", pathlib.Path(tempfile.mkdtemp()))

        ins = _new_instance()
        assert ins.load() is True
        assert ins._backend == "onnx_trt:0"

    def test_auto_without_optin_skips_onnx_and_falls_through(self, monkeypatch):
        """auto + opt-in 無し + badminton.onnx 不在 → step0 を選ばず
        OpenVINO/PT 経路に流れる (= COCO fallback を使わない)。
        onnxruntime はモックで CUDA ありにしても、モデル解決が None なので
        InferenceSession は呼ばれない。"""
        _install_fake_ort(monkeypatch, ["CUDAExecutionProvider", "CPUExecutionProvider"])
        monkeypatch.setattr(inf, "ONNX_MODEL", _FakePath(False))
        monkeypatch.setattr(inf, "COCO_ONNX_MODEL", _FakePath(True, "yolov8n.onnx"))
        # OpenVINO / ultralytics / ONNX(custom) も全部不在にして load を失敗させ、
        # 「step0 で onnx_cuda を選んでいない」ことだけを確認する。
        monkeypatch.setattr(inf, "OV_MODEL_DIR", _FakeDir())
        monkeypatch.setattr(inf, "PT_MODEL", _FakePath(False))

        ins = _new_instance()
        # ultralytics が入っていない CI では load 失敗 (False)。
        # 重要なのは backend が onnx_cuda になっていないこと。
        ins.load()
        assert not ins._backend.startswith("onnx_cuda")
        assert not ins._backend.startswith("onnx_trt")


class _FakeDir:
    """OV_MODEL_DIR スタブ: / 演算で常に存在しない _FakePath を返す。"""
    def __truediv__(self, other):
        return _FakePath(False, str(other))
