"""Ray リモートタスク関数 (INFRA Phase D)

K10 ワーカーノード上で実行される推論関数群。
K10 には ShuttleScope コードベースが存在しないため、
onnxruntime / mediapipe / numpy を直接使用して推論を実装する。

設計方針:
- SSH 優先: cluster.config.yaml に ssh_user / ssh_password が設定されている場合は
  SSH 経由でスクリプトを実行する（Ray の Windows 不安定問題を回避）
- Ray フォールバック: SSH が使えない場合のみ Ray remote を使用する
- @ray.remote デコレータは使用しない（インポート時に ray が必要になるため）
- ray.remote(fn).remote(...) パターンで呼び出し時に動的に Ray リモート化する
- ray は遅延インポートする（ImportError 時はエラーを返す）
- K10 では backend.* モジュールを import しない
"""
from __future__ import annotations

import io
import json
import logging
import time
from typing import Any, Dict, Optional

import numpy as np

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────────────
# ワーカー上で実行される純粋関数（ray デコレータなし）
# ────────────────────────────────────────────────────────────────────────────

def _run_benchmark_tracknet(model_path: str, n_iters: int, use_gpu: bool) -> dict:
    """TrackNet ベンチマーク。OpenVINO → ONNX の順で試みる。

    K10 上でローカル実行される。
    戻り値: {"fps": float, "avg_ms": float, "p95_ms": float} または {"error": str}
    """
    import numpy as np
    import time
    import os

    if not os.path.exists(model_path):
        return {"error": f"モデルファイルが見つかりません: {model_path}"}

    SHAPE = [1, 3, 288, 512]
    dummy = np.zeros(SHAPE, dtype=np.float32)

    def _measure(fn):
        fn()
        lats = []
        for _ in range(n_iters):
            t0 = time.perf_counter(); fn(); lats.append(time.perf_counter() - t0)
        arr = np.array(lats) * 1000.0
        return round(1000.0 / float(np.mean(arr)), 2), round(float(np.mean(arr)), 2), round(float(np.percentile(arr, 95)), 2)

    # OpenVINO 試行（use_gpu フラグ時）
    # pipeline #7 fix: 旧コードは openvino import / compile / infer 失敗時に
    # `except: continue` / `except: pass` で握りつぶし、provider トレースが残らず
    # ベンチマーク結果から原因を特定できなかった。
    # 修正: トレースを `_provider_attempts` に蓄積し、最終 ONNX フォールバック結果に
    # `attempts` として返す。
    _provider_attempts: list[dict] = []
    if use_gpu:
        xml_path = model_path.replace(".onnx", ".xml")
        try:
            import openvino as ov
            core = ov.Core()
            src = xml_path if os.path.exists(xml_path) else model_path
            model = core.read_model(src)
            model.reshape({model.input(0).any_name: SHAPE})
            for dev in ("GPU", "CPU"):
                if dev not in core.available_devices:
                    _provider_attempts.append({"provider": f"openvino:{dev}", "ok": False, "reason": "device not available"})
                    continue
                try:
                    compiled = core.compile_model(model, dev, {"PERFORMANCE_HINT": "LATENCY"})
                    req = compiled.create_infer_request()
                    iname = compiled.input(0).any_name
                    fps, avg_ms, p95_ms = _measure(lambda: req.infer({iname: dummy}))
                    return {"fps": fps, "avg_ms": avg_ms, "p95_ms": p95_ms, "provider": f"openvino:{dev}", "attempts": _provider_attempts}
                except Exception as exc:
                    _provider_attempts.append({"provider": f"openvino:{dev}", "ok": False, "reason": f"{type(exc).__name__}: {exc}"})
                    continue
        except Exception as exc:
            _provider_attempts.append({"provider": "openvino:import", "ok": False, "reason": f"{type(exc).__name__}: {exc}"})

    # ONNX フォールバック
    try:
        import onnxruntime as ort
        available = ort.get_available_providers()
        if use_gpu and "DmlExecutionProvider" in available:
            providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
        elif use_gpu and "CUDAExecutionProvider" in available:
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        else:
            providers = ["CPUExecutionProvider"]
        try:
            sess = ort.InferenceSession(model_path, providers=providers)
        except Exception as exc:
            return {"error": f"ONNX セッション初期化失敗: {exc}"}
        iname = sess.get_inputs()[0].name
        fps, avg_ms, p95_ms = _measure(lambda: sess.run(None, {iname: dummy}))
        return {"fps": fps, "avg_ms": avg_ms, "p95_ms": p95_ms, "provider": providers[0]}
    except ImportError as exc:
        return {"error": f"onnxruntime 未インストール: {exc}"}
    except Exception as exc:
        return {"error": str(exc)}


def _run_benchmark_pose(n_iters: int) -> dict:
    """MediaPipe Pose ベンチマーク（モデルファイル不要）。

    K10 上でローカル実行される。mediapipe を直接使用する。
    戻り値: {"fps": float, "avg_ms": float, "p95_ms": float} または {"error": str}
    """
    try:
        import mediapipe as mp
        import numpy as np
        import time

        mp_pose = mp.solutions.pose  # type: ignore[attr-defined]

        # 合成フレームを生成 (480x270 BGR)
        dummy_frame = np.zeros((270, 480, 3), dtype=np.uint8)
        # 中央に白い円を描いてポーズ検出しやすくする
        try:
            import cv2
            cv2.circle(dummy_frame, (240, 135), 50, (255, 255, 255), -1)
        except ImportError:
            pass

        latencies = []

        with mp_pose.Pose(
            static_image_mode=False,
            model_complexity=0,
            enable_segmentation=False,
            min_detection_confidence=0.3,
        ) as pose:
            # ウォームアップ
            try:
                pose.process(dummy_frame)
            except Exception:
                pass

            for _ in range(n_iters):
                t0 = time.perf_counter()
                pose.process(dummy_frame)
                latencies.append(time.perf_counter() - t0)

        if not latencies:
            return {"error": "計測データなし"}

        arr = np.array(latencies) * 1000.0
        avg_ms = float(np.mean(arr))
        p95_ms = float(np.percentile(arr, 95))
        fps = 1000.0 / avg_ms if avg_ms > 0 else 0.0
        return {
            "fps": round(fps, 2),
            "avg_ms": round(avg_ms, 2),
            "p95_ms": round(p95_ms, 2),
        }

    except ImportError as exc:
        return {"error": f"mediapipe 未インストール: {exc}"}
    except Exception as exc:
        return {"error": str(exc)}


def _run_benchmark_yolo(model_path: str, n_iters: int, use_gpu: bool) -> dict:
    """YOLO ONNX ベンチマーク。

    K10 上でローカル実行される。onnxruntime を直接使用する。
    戻り値: {"fps": float, "avg_ms": float, "p95_ms": float} または {"error": str}
    """
    try:
        import onnxruntime as ort
        import numpy as np
        import time
        import os

        if not os.path.exists(model_path):
            return {"error": f"モデルファイルが見つかりません: {model_path}"}

        # EP 選択
        available = ort.get_available_providers()
        if use_gpu and "DmlExecutionProvider" in available:
            providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
        elif use_gpu and "CUDAExecutionProvider" in available:
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        else:
            providers = ["CPUExecutionProvider"]

        try:
            sess = ort.InferenceSession(model_path, providers=providers)
        except Exception as exc:
            return {"error": f"ONNX セッション初期化失敗: {exc}"}

        # YOLO 標準入力: (1, 3, 384, 640)
        input_info = sess.get_inputs()[0]
        input_name = input_info.name
        shape = input_info.shape
        fixed_shape = []
        for i, dim in enumerate(shape):
            if dim is None or isinstance(dim, str):
                defaults = [1, 3, 384, 640]
                fixed_shape.append(defaults[i] if i < len(defaults) else 1)
            else:
                fixed_shape.append(int(dim))

        dummy = np.zeros(fixed_shape, dtype=np.float32)

        latencies = []
        try:
            sess.run(None, {input_name: dummy})
        except Exception:
            pass

        for _ in range(n_iters):
            t0 = time.perf_counter()
            sess.run(None, {input_name: dummy})
            latencies.append(time.perf_counter() - t0)

        if not latencies:
            return {"error": "計測データなし"}

        arr = np.array(latencies) * 1000.0
        avg_ms = float(np.mean(arr))
        p95_ms = float(np.percentile(arr, 95))
        fps = 1000.0 / avg_ms if avg_ms > 0 else 0.0
        return {
            "fps": round(fps, 2),
            "avg_ms": round(avg_ms, 2),
            "p95_ms": round(p95_ms, 2),
        }

    except ImportError as exc:
        return {"error": f"onnxruntime 未インストール: {exc}"}
    except Exception as exc:
        return {"error": str(exc)}


def _run_benchmark_pipeline(tracknet_model_path: str, pose_task_path: str,
                             n_iters: int, use_gpu: bool = False) -> dict:
    """パイプライン（TrackNet + Pose）ベンチマーク。K10 上でローカル実行される。"""
    try:
        import numpy as np
        import time
        import os

        N_FRAMES = 10
        dummy_tracknet = np.zeros([1, 3, 288, 512], dtype=np.float32)
        dummy_frame = np.zeros((270, 480, 3), dtype=np.uint8)

        if not os.path.exists(tracknet_model_path):
            return {"error": f"モデル未配置: {tracknet_model_path}"}

        import onnxruntime as ort
        sess = ort.InferenceSession(tracknet_model_path, providers=["CPUExecutionProvider"])
        iname = sess.get_inputs()[0].name

        pose_lm = None
        mp_img = None
        try:
            import mediapipe as mp
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision as mp_vision
            if os.path.exists(pose_task_path):
                opts = mp_vision.PoseLandmarkerOptions(
                    base_options=mp_python.BaseOptions(model_asset_path=pose_task_path),
                    running_mode=mp_vision.RunningMode.IMAGE)
                pose_lm = mp_vision.PoseLandmarker.create_from_options(opts)
                mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=dummy_frame)
        except Exception:
            pose_lm = None

        def _run():
            sess.run(None, {iname: dummy_tracknet})
            if pose_lm:
                pose_lm.detect(mp_img)

        for _ in range(2):
            _run()
        latencies = []
        for _ in range(n_iters):
            t0 = time.perf_counter()
            _run()
            latencies.append(time.perf_counter() - t0)
        if pose_lm:
            try:
                pose_lm.close()
            except Exception:
                pass

        arr = np.array(latencies) * 1000.0
        avg_ms = float(np.mean(arr))
        fps = N_FRAMES * 1000.0 / avg_ms if avg_ms > 0 else 0.0
        return {
            "fps": round(fps, 2),
            "avg_ms": round(avg_ms / N_FRAMES, 2),
            "p95_ms": round(float(np.percentile(arr, 95)) / N_FRAMES, 2),
            "iters": len(latencies),
            "batch": N_FRAMES,
        }
    except Exception as exc:
        return {"error": str(exc)}


def _run_benchmark_clip(n_iters: int) -> dict:
    """ffmpeg クリップ抽出ベンチマーク。K10 上でローカル実行される。"""
    try:
        import subprocess
        import tempfile
        import os
        import time
        import numpy as np

        _fd, video_path = tempfile.mkstemp(suffix=".mp4")
        os.close(_fd)
        ret = subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=5:size=1280x720:rate=60",
             "-c:v", "libx264", "-preset", "ultrafast", video_path],
            capture_output=True, timeout=60)
        if ret.returncode != 0:
            return {"error": "ffmpeg unavailable"}

        latencies = []
        for i in range(n_iters):
            _fd2, out_path = tempfile.mkstemp(suffix=f"_clip_{i}.mp4")
            os.close(_fd2)
            t0 = time.perf_counter()
            r = subprocess.run(
                ["ffmpeg", "-y", "-ss", "0", "-i", video_path, "-t", "1", "-c", "copy", out_path],
                capture_output=True, timeout=30)
            latencies.append(time.perf_counter() - t0)
            try:
                os.remove(out_path)
            except OSError:
                pass
            if r.returncode != 0:
                try:
                    os.remove(video_path)
                except OSError:
                    pass
                return {"error": f"ffmpeg clip 失敗 (code={r.returncode})"}
        try:
            os.remove(video_path)
        except OSError:
            pass

        arr = np.array(latencies) * 1000.0
        return {
            "fps": round(1000.0 / float(np.mean(arr)), 2),
            "avg_ms": round(float(np.mean(arr)), 2),
            "p95_ms": round(float(np.percentile(arr, 95)), 2),
            "iters": len(latencies),
        }
    except Exception as exc:
        return {"error": str(exc)}


def _run_benchmark_stats(n_iters: int) -> dict:
    """numpy/scipy 統計ベンチマーク。K10 上でローカル実行される。"""
    try:
        import time
        import numpy as np

        try:
            from scipy import stats as scipy_stats
        except ImportError:
            scipy_stats = None

        rng = np.random.default_rng(123)

        def _run():
            data = rng.standard_normal((200, 10))
            np.corrcoef(data.T)
            w = np.exp(data[:, 0])
            w /= w.sum()
            float(np.dot(w, data[:, 1]))
            if scipy_stats is not None:
                scipy_stats.linregress(data[:, 0], data[:, 1])

        for _ in range(5):
            _run()
        latencies = []
        for _ in range(n_iters):
            t0 = time.perf_counter()
            _run()
            latencies.append(time.perf_counter() - t0)

        arr = np.array(latencies) * 1000.0
        return {
            "fps": round(1000.0 / float(np.mean(arr)), 2),
            "avg_ms": round(float(np.mean(arr)), 2),
            "p95_ms": round(float(np.percentile(arr, 95)), 2),
            "iters": len(latencies),
        }
    except Exception as exc:
        return {"error": str(exc)}


def _infer_tracknet_frames(model_path: str, frames_npy: bytes) -> bytes:
    """TrackNet 推論をシリアライズされた numpy フレームに対して実行する。

    K10 上でローカル実行される。
    Args:
        model_path: ONNX または OpenVINO XML モデルファイルのパス
        frames_npy: 先頭16バイトが shape (N,C,H,W) の int32x4、残りが float32 フレームデータ
    Returns:
        先頭12バイトが出力 shape (N,H,W) の int32x3、残りが float32 ヒートマップデータ
        エラー時は JSON エンコードされたエラー dict の bytes
    """
    try:
        import numpy as np
        import os

        if not os.path.exists(model_path):
            return json.dumps({"error": f"モデルファイルが見つかりません: {model_path}"}).encode("utf-8")

        # フレームデシリアライズ: 先頭 16 バイトが shape (4 x int32)
        header = np.frombuffer(frames_npy[:16], dtype=np.int32)
        n, c, h, w = int(header[0]), int(header[1]), int(header[2]), int(header[3])
        frames = np.frombuffer(frames_npy[16:], dtype=np.float32).reshape(n, c, h, w)

        def _serialize(raw: "np.ndarray") -> bytes:
            # (N,1,H,W) → (N,H,W) に正規化、12バイトヘッダ付きで返す
            out = raw.squeeze(1) if raw.ndim == 4 else raw
            shape_bytes = np.array(out.shape, dtype=np.int32).tobytes()  # 3×int32=12B
            return shape_bytes + out.astype(np.float32).tobytes()

        # ── OpenVINO 優先（K10 は GPU/CPU とも利用可能）────────────────────────
        try:
            import openvino as ov
            xml_path = model_path.replace(".onnx", ".xml")
            load_path = xml_path if os.path.exists(xml_path) else model_path
            core = ov.Core()
            model = core.read_model(load_path)
            try:
                model.reshape({model.input(0).any_name: list(frames.shape)})
            except Exception:
                pass
            for dev in ("GPU", "CPU"):
                if dev not in core.available_devices:
                    continue
                try:
                    compiled = core.compile_model(model, dev, {"PERFORMANCE_HINT": "LATENCY"})
                    req = compiled.create_infer_request()
                    iname = compiled.input(0).any_name
                    req.infer({iname: frames})
                    return _serialize(req.get_output_tensor(0).data)
                except Exception:
                    continue
        except Exception:
            pass

        # ── onnxruntime フォールバック ────────────────────────────────────────
        import onnxruntime as ort
        available = ort.get_available_providers()
        if "DmlExecutionProvider" in available:
            providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
        elif "CUDAExecutionProvider" in available:
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        else:
            providers = ["CPUExecutionProvider"]
        sess = ort.InferenceSession(model_path, providers=providers)
        result = sess.run(None, {sess.get_inputs()[0].name: frames})
        return _serialize(result[0])

    except ImportError as exc:
        return json.dumps({"error": f"推論ライブラリ未インストール: {exc}"}).encode("utf-8")
    except Exception as exc:
        return json.dumps({"error": str(exc)}).encode("utf-8")


def _detect_hardware() -> dict:
    """ワーカーノードのハードウェア情報を収集して返す。

    K10（Windows 11）上で実行される。psutil + PowerShell WMI で取得する。
    戻り値:
        {
            "num_cpus": int,          # 論理 CPU 数
            "cpu_name": str,          # CPU 製品名
            "num_gpus": int,          # GPU 数
            "gpu_label": str,         # プライマリ GPU 名
            "gpu_vram_mb": int,       # プライマリ GPU VRAM MB（不明時 0）
            "ram_gb": int,            # 搭載 RAM GB
        }
    """
    import sys
    import subprocess

    result: dict = {
        "num_cpus": 0,
        "cpu_name": "",
        "num_gpus": 0,
        "gpu_label": "",
        "gpu_vram_mb": 0,
        "ram_gb": 0,
    }

    # ── CPU 数 ────────────────────────────────────────────────────────────────
    try:
        import psutil
        result["num_cpus"] = psutil.cpu_count(logical=True) or 0
        result["ram_gb"] = round(psutil.virtual_memory().total / (1024 ** 3))
    except ImportError:
        try:
            import os
            result["num_cpus"] = os.cpu_count() or 0
        except Exception:
            pass

    # ── CPU 名 / GPU 情報 (Windows PowerShell WMI) ───────────────────────────
    if sys.platform == "win32":
        ps_flags: dict = {"capture_output": True, "text": True, "timeout": 15}
        ps_flags["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

        # CPU 名
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-WmiObject Win32_Processor | Select-Object -First 1 -ExpandProperty Name"],
                **ps_flags,
            )
            name = r.stdout.strip()
            if name:
                result["cpu_name"] = name
        except Exception:
            pass

        # GPU 情報（全ビデオコントローラ）
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-WmiObject Win32_VideoController | Select-Object Name,AdapterRAM | ConvertTo-Json -Compress"],
                **ps_flags,
            )
            import json as _json
            raw = r.stdout.strip()
            if raw:
                gpus = _json.loads(raw)
                if isinstance(gpus, dict):
                    gpus = [gpus]  # 1件だけの場合は配列でなくオブジェクト
                # "Microsoft Basic Display Adapter" 等のソフトウェアアダプタを除外
                real_gpus = [
                    g for g in gpus
                    if g.get("Name") and "basic display" not in g["Name"].lower()
                ]
                result["num_gpus"] = len(real_gpus)
                if real_gpus:
                    first = real_gpus[0]
                    result["gpu_label"] = first.get("Name", "")
                    vram = first.get("AdapterRAM") or 0
                    result["gpu_vram_mb"] = int(vram) // (1024 * 1024) if vram > 0 else 0
        except Exception:
            pass
    else:
        # Linux: lspci / nvidia-smi など（将来拡張用）
        try:
            r = subprocess.run(["lspci"], capture_output=True, text=True, timeout=5)
            gpu_lines = [l for l in r.stdout.splitlines() if "VGA" in l or "3D" in l or "Display" in l]
            result["num_gpus"] = len(gpu_lines)
            if gpu_lines:
                result["gpu_label"] = gpu_lines[0].split(":", 2)[-1].strip()
        except Exception:
            pass

    # タスクが実際に動いたノードのIDを記録（スケジューリング検証用）
    try:
        import ray as _ray
        result["_node_id"] = _ray.get_runtime_context().get_node_id()
    except Exception:
        result["_node_id"] = ""

    return result


# ────────────────────────────────────────────────────────────────────────────
# SSH ディスパッチ（Ray の Windows 不安定問題回避）
# ────────────────────────────────────────────────────────────────────────────

# SSH 経由でワーカーに送り込む自己完結スクリプトテンプレート
_SSH_DETECT_SCRIPT = '''\
import sys, subprocess, json

result = {
    "num_cpus": 0, "cpu_name": "", "num_gpus": 0,
    "gpu_label": "", "gpu_vram_mb": 0, "ram_gb": 0,
}

try:
    import psutil
    result["num_cpus"] = psutil.cpu_count(logical=True) or 0
    result["ram_gb"] = round(psutil.virtual_memory().total / (1024 ** 3))
except ImportError:
    import os
    result["num_cpus"] = os.cpu_count() or 0

if sys.platform == "win32":
    kw = {"capture_output": True, "text": True, "timeout": 15, "creationflags": 0x08000000}
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-WmiObject Win32_Processor | Select-Object -First 1 -ExpandProperty Name"],
            **kw)
        result["cpu_name"] = r.stdout.strip()
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-WmiObject Win32_VideoController | Select-Object Name,AdapterRAM | ConvertTo-Json -Compress"],
            **kw)
        import json as _j
        raw = r.stdout.strip()
        if raw:
            gpus = _j.loads(raw)
            if isinstance(gpus, dict): gpus = [gpus]
            real = [g for g in gpus if g.get("Name") and "basic display" not in str(g.get("Name","")).lower()]
            result["num_gpus"] = len(real)
            if real:
                result["gpu_label"] = real[0].get("Name", "")
                vram = real[0].get("AdapterRAM") or 0
                result["gpu_vram_mb"] = int(vram) // (1024*1024) if vram > 0 else 0
    except Exception:
        pass

try:
    import onnxruntime as ort
    result["ort_providers"] = ort.get_available_providers()
    result["ort_version"] = ort.__version__
except ImportError:
    result["ort_providers"] = []

print(json.dumps(result))
'''

_SSH_BENCH_TRACKNET_SCRIPT = '''\
import sys, os, time, json
import numpy as np

model_path = {model_path!r}
n_iters = {n_iters}
use_gpu = {use_gpu}
SHAPE = [1, 3, 288, 512]
dummy = np.zeros(SHAPE, dtype=np.float32)

def _measure(fn, n):
    fn()
    lats = []
    for _ in range(n):
        t0 = time.perf_counter(); fn(); lats.append(time.perf_counter()-t0)
    arr = np.array(lats)*1000
    return round(1000/float(np.mean(arr)),2), round(float(np.mean(arr)),2), round(float(np.percentile(arr,95)),2)

# OpenVINO 試行（use_gpu フラグに応じてデバイス優先順位を変更）
try:
    import openvino as ov
    xml_path = model_path.replace(".onnx", ".xml")
    core = ov.Core()
    if not os.path.exists(xml_path) and not os.path.exists(model_path):
        print(json.dumps({{"error": "model not found: " + model_path}})); sys.exit(0)
    model = core.read_model(xml_path if os.path.exists(xml_path) else model_path)
    model.reshape({{model.input(0).any_name: SHAPE}})
    dev_order = ("GPU", "CPU") if use_gpu else ("CPU",)
    for dev in dev_order:
        if dev not in core.available_devices: continue
        try:
            compiled = core.compile_model(model, dev, {{"PERFORMANCE_HINT": "LATENCY"}})
            req = compiled.create_infer_request()
            iname = compiled.input(0).any_name
            fps, avg, p95 = _measure(lambda: req.infer({{iname: dummy}}), n_iters)
            print(json.dumps({{"fps": fps, "avg_ms": avg, "p95_ms": p95, "provider": "openvino:" + dev}}))
            sys.exit(0)
        except Exception: continue
except Exception: pass

# ONNX フォールバック
try:
    import onnxruntime as ort
    if not os.path.exists(model_path):
        print(json.dumps({{"error": "model not found: " + model_path}})); sys.exit(0)
    available = ort.get_available_providers()
    if use_gpu and "DmlExecutionProvider" in available:
        providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
    elif use_gpu and "CUDAExecutionProvider" in available:
        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    else:
        providers = ["CPUExecutionProvider"]
    sess = ort.InferenceSession(model_path, providers=providers)
    iname = sess.get_inputs()[0].name
    fps, avg, p95 = _measure(lambda: sess.run(None, {{iname: dummy}}), n_iters)
    print(json.dumps({{"fps": fps, "avg_ms": avg, "p95_ms": p95, "provider": providers[0]}}))
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
'''

_SSH_BENCH_POSE_SCRIPT = '''\
import time, json, os
import numpy as np

n_iters = {n_iters}
task_path = {task_path!r}
dummy = np.zeros((270, 480, 3), dtype=np.uint8)

def _measure(fn, n):
    fn()
    lats = []
    for _ in range(n):
        t0 = time.perf_counter(); fn(); lats.append(time.perf_counter()-t0)
    arr = np.array(lats)*1000
    return round(1000/float(np.mean(arr)),2), round(float(np.mean(arr)),2), round(float(np.percentile(arr,95)),2)

# Tasks API (mediapipe >= 0.10)
if os.path.exists(task_path):
    try:
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision as mp_vision
        opts = mp_vision.PoseLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=task_path),
            running_mode=mp_vision.RunningMode.IMAGE)
        img = mp.Image(image_format=mp.ImageFormat.SRGB, data=dummy)
        with mp_vision.PoseLandmarker.create_from_options(opts) as lm:
            fps, avg, p95 = _measure(lambda: lm.detect(img), n_iters)
        print(json.dumps({{"fps": fps, "avg_ms": avg, "p95_ms": p95, "backend": "mediapipe_tasks"}}))
        import sys; sys.exit(0)
    except Exception as e:
        pass

# Legacy solutions API fallback
try:
    import mediapipe as mp
    if hasattr(mp, "solutions"):
        mp_pose = mp.solutions.pose
        with mp_pose.Pose(static_image_mode=False, model_complexity=0,
                          enable_segmentation=False, min_detection_confidence=0.3) as pose:
            fps, avg, p95 = _measure(lambda: pose.process(dummy), n_iters)
        print(json.dumps({{"fps": fps, "avg_ms": avg, "p95_ms": p95, "backend": "mediapipe_solutions"}}))
    else:
        print(json.dumps({{"error": "mediapipe solutions removed and no task file: " + task_path}}))
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
'''

_SSH_BENCH_YOLO_SCRIPT = '''\
import sys, os, time, json
import numpy as np

model_path = {model_path!r}
n_iters = {n_iters}
use_gpu = {use_gpu}
SHAPE = [1, 3, 384, 640]
dummy = np.zeros(SHAPE, dtype=np.float32)

def _measure(fn, n):
    # ウォームアップ3回
    for _ in range(3): fn()
    lats = []
    for _ in range(n):
        t0 = time.perf_counter(); fn(); lats.append(time.perf_counter()-t0)
    arr = np.array(lats)*1000
    return round(1000/float(np.mean(arr)),2), round(float(np.mean(arr)),2), round(float(np.percentile(arr,95)),2)

if not os.path.exists(model_path):
    print(json.dumps({{"error": "model not found: " + model_path}})); sys.exit(0)

# OpenVINO 試行 — IR形式(.xml)があれば優先、なければONNXを直接読む
if use_gpu:
    try:
        import openvino as ov
        xml_path = model_path.replace(".onnx", ".xml")
        load_path = xml_path if os.path.exists(xml_path) else model_path
        core = ov.Core()
        model = core.read_model(load_path)
        try:
            model.reshape({{model.input(0).any_name: SHAPE}})
        except Exception:
            pass
        for dev in ("GPU", "CPU"):
            if dev not in core.available_devices: continue
            try:
                compiled = core.compile_model(model, dev, {{"PERFORMANCE_HINT": "LATENCY"}})
                req = compiled.create_infer_request()
                iname = compiled.input(0).any_name
                fps, avg, p95 = _measure(lambda: req.infer({{iname: dummy}}), n_iters)
                src = "ir" if os.path.exists(xml_path) else "onnx"
                print(json.dumps({{"fps": fps, "avg_ms": avg, "p95_ms": p95, "provider": f"openvino:{{dev}}({{src}})"}}))
                sys.exit(0)
            except Exception: continue
    except Exception: pass

# ONNX フォールバック
try:
    import onnxruntime as ort
    available = ort.get_available_providers()
    if use_gpu and "DmlExecutionProvider" in available:
        providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
    elif use_gpu and "CUDAExecutionProvider" in available:
        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    else:
        providers = ["CPUExecutionProvider"]
    sess = ort.InferenceSession(model_path, providers=providers)
    iname = sess.get_inputs()[0].name
    fps, avg, p95 = _measure(lambda: sess.run(None, {{iname: dummy}}), n_iters)
    print(json.dumps({{"fps": fps, "avg_ms": avg, "p95_ms": p95, "provider": providers[0]}}))
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
'''

_SSH_BENCH_PIPELINE_SCRIPT = '''\
import sys, os, time, json
import numpy as np

tracknet_model_path = {tracknet_model_path!r}
pose_task_path = {pose_task_path!r}
n_iters = {n_iters}
N_FRAMES = 10
dummy_tracknet = np.zeros([1, 3, 288, 512], dtype=np.float32)
dummy_frame = np.zeros((270, 480, 3), dtype=np.uint8)

try:
    import onnxruntime as ort
    if not os.path.exists(tracknet_model_path):
        print(json.dumps({{"error": "モデル未配置: " + tracknet_model_path}})); sys.exit(0)
    sess = ort.InferenceSession(tracknet_model_path, providers=["CPUExecutionProvider"])
    iname = sess.get_inputs()[0].name
except Exception as e:
    print(json.dumps({{"error": "tracknet load: " + str(e)}})); sys.exit(0)

pose_lm = None
mp_img = None
try:
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision as mp_vision
    if os.path.exists(pose_task_path):
        opts = mp_vision.PoseLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=pose_task_path),
            running_mode=mp_vision.RunningMode.IMAGE)
        pose_lm = mp_vision.PoseLandmarker.create_from_options(opts)
        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=dummy_frame)
except Exception:
    pose_lm = None

def _run():
    sess.run(None, {{iname: dummy_tracknet}})
    if pose_lm:
        pose_lm.detect(mp_img)

for _ in range(2): _run()
lats = []
for _ in range(n_iters):
    t0 = time.perf_counter(); _run(); lats.append(time.perf_counter() - t0)
if pose_lm:
    try: pose_lm.close()
    except: pass

arr = np.array(lats) * 1000
fps = round(N_FRAMES * 1000 / float(np.mean(arr)), 2) if np.mean(arr) > 0 else 0.0
print(json.dumps({{
    "fps": fps,
    "avg_ms": round(float(np.mean(arr)) / N_FRAMES, 2),
    "p95_ms": round(float(np.percentile(arr, 95)) / N_FRAMES, 2),
    "iters": len(lats), "batch": N_FRAMES
}}))
'''

_SSH_BENCH_CLIP_SCRIPT = '''\
import sys, os, time, json, subprocess, tempfile
import numpy as np

n_iters = {n_iters}

try:
    _fd, video_path = tempfile.mkstemp(suffix=".mp4")
    os.close(_fd)
    ret = subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=5:size=1280x720:rate=60",
         "-c:v", "libx264", "-preset", "ultrafast", video_path],
        capture_output=True, timeout=60)
    if ret.returncode != 0:
        print(json.dumps({{"error": "ffmpeg 生成失敗 (code=" + str(ret.returncode) + ")"}})); sys.exit(0)
except FileNotFoundError:
    print(json.dumps({{"error": "ffmpeg 未インストール (K10 の PATH に ffmpeg が必要)"}})); sys.exit(0)
except Exception as e:
    print(json.dumps({{"error": "ffmpeg 実行失敗: " + str(e)}})); sys.exit(0)

lats = []
for i in range(n_iters):
    _fd2, out_path = tempfile.mkstemp(suffix=f"_clip_{{i}}.mp4")
    os.close(_fd2)
    t0 = time.perf_counter()
    r = subprocess.run(
        ["ffmpeg", "-y", "-ss", "0", "-i", video_path, "-t", "1", "-c", "copy", out_path],
        capture_output=True, timeout=30)
    lats.append(time.perf_counter() - t0)
    try: os.remove(out_path)
    except: pass
    if r.returncode != 0:
        print(json.dumps({{"error": f"ffmpeg clip 失敗 (code={{r.returncode}})"}})); sys.exit(0)
try: os.remove(video_path)
except: pass

arr = np.array(lats) * 1000
print(json.dumps({{
    "fps": round(1000/float(np.mean(arr)), 2),
    "avg_ms": round(float(np.mean(arr)), 2),
    "p95_ms": round(float(np.percentile(arr, 95)), 2),
    "iters": len(lats)
}}))
'''

_SSH_BENCH_STATS_SCRIPT = '''\
import time, json
import numpy as np

n_iters = {n_iters}
try:
    from scipy import stats as scipy_stats
except ImportError:
    scipy_stats = None

rng = np.random.default_rng(123)

def _run():
    data = rng.standard_normal((200, 10))
    np.corrcoef(data.T)
    w = np.exp(data[:, 0]); w /= w.sum()
    float(np.dot(w, data[:, 1]))
    if scipy_stats is not None:
        scipy_stats.linregress(data[:, 0], data[:, 1])

for _ in range(5): _run()
lats = []
for _ in range(n_iters):
    t0 = time.perf_counter(); _run(); lats.append(time.perf_counter() - t0)

arr = np.array(lats) * 1000
print(json.dumps({{
    "fps": round(1000/float(np.mean(arr)), 2),
    "avg_ms": round(float(np.mean(arr)), 2),
    "p95_ms": round(float(np.percentile(arr, 95)), 2),
    "iters": len(lats)
}}))
'''


def _get_worker_ssh_creds(worker_ip: str) -> Optional[Dict[str, str]]:
    """cluster.config.yaml から指定 IP のワーカーの SSH 認証情報を取得する。"""
    try:
        from backend.cluster.topology import load_config
        cfg = load_config()
        for w in cfg.get("network", {}).get("workers", []):
            if w.get("ip") == worker_ip:
                user = w.get("ssh_user")
                pwd = w.get("ssh_password")
                if user and pwd:
                    return {"host": worker_ip, "username": user, "password": pwd}
    except Exception:
        pass
    return None


_USERNAME_RE = __import__("re").compile(r"^[A-Za-z0-9._-]{1,32}$")


def _ssh_run_python_script(host: str, username: str, password: str,
                           script_code: str, timeout: int = 120) -> dict:
    """SSH 経由でワーカーに Python スクリプトを送り込み、JSON 結果を返す。

    スクリプトは最後の行で json.dumps() を print() すること。

    pipeline #3 fix: username が cluster.config.yaml から取られて文字列補間で
    cmd 文字列に入っていたため、YAML 改竄で `"; del C:\\* &` 等を仕込まれると RCE。
    username を `[A-Za-z0-9._-]{1,32}$` の allowlist で先に検証し、不正値は拒否する。
    パスワード (paramiko 引数) は文字列補間しないので OK だが、host にも同等の
    検証を入れる。
    また paramiko の banner_timeout / auth_timeout / channel timeout を pin する。
    """
    try:
        import paramiko  # type: ignore
    except ImportError:
        return {"error": "paramiko 未インストール: pip install paramiko"}

    if not _USERNAME_RE.match(username or ""):
        return {"error": f"invalid username for ssh dispatch: {username!r}"}
    # host は IPv4/hostname を想定。コロン (port) や cmd メタは拒否。
    if not __import__("re").match(r"^[A-Za-z0-9._-]{1,253}$", host or ""):
        return {"error": f"invalid host for ssh dispatch: {host!r}"}

    import uuid as _uuid

    script_path = f"C:/Users/{username}/ss_task_{_uuid.uuid4().hex[:8]}.py"
    python_exe = f"C:/Users/{username}/AppData/Local/Programs/Python/Python312/python.exe"

    ssh = paramiko.SSHClient()
    ssh.load_system_host_keys()
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        ssh.connect(
            host,
            username=username,
            password=password,
            timeout=10,
            banner_timeout=10,
            auth_timeout=10,
        )

        sftp = ssh.open_sftp()
        with sftp.open(script_path, "wb") as f:
            f.write(script_code.encode("utf-8"))
        sftp.close()

        cmd = f'cmd /c "{python_exe}" "{script_path}" 2>&1'
        _, stdout, _ = ssh.exec_command(cmd)
        stdout.channel.settimeout(timeout)
        try:
            raw = stdout.read().decode("utf-8", errors="replace")
        except Exception as read_exc:
            raw = ""
            logger.warning("_ssh_run_python_script: stdout.read() failed: %s %s",
                           type(read_exc).__name__, read_exc)

        # クリーンアップ（失敗しても続行）
        try:
            sftp = ssh.open_sftp()
            sftp.remove(script_path)
            sftp.close()
        except Exception:
            pass

        # 最後の JSON 行を探す
        for line in reversed(raw.splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                return json.loads(line)

        return {"error": f"JSON 出力なし: {raw[-300:]}"}

    except Exception as exc:
        return {"error": f"SSH 実行失敗 ({type(exc).__name__}): {exc}"}
    finally:
        try:
            ssh.close()
        except Exception:
            pass


def dispatch_hardware_detect_ssh(worker_ip: str, username: str, password: str) -> Dict[str, Any]:
    """SSH 経由でワーカーのハードウェア情報を取得する（Ray 不要）。"""
    return _ssh_run_python_script(worker_ip, username, password, _SSH_DETECT_SCRIPT, timeout=30)


def dispatch_benchmark_ssh(fn_name: str, worker_ip: str, username: str, password: str,
                            **kwargs) -> Dict[str, Any]:
    """SSH 経由でワーカーにベンチマークを実行する（Ray 不要）。

    fn_name: "_run_benchmark_tracknet" | "_run_benchmark_pose" | "_run_benchmark_yolo"
    """
    if fn_name == "_run_benchmark_tracknet":
        script = _SSH_BENCH_TRACKNET_SCRIPT.format(
            model_path=kwargs.get("model_path", ""),
            n_iters=kwargs.get("n_iters", 5),
            use_gpu=kwargs.get("use_gpu", False),
        )
        timeout = 600
    elif fn_name == "_run_benchmark_pose":
        # K10向けにモデルファイルを C:\ss-models\ に配置
        task_path_k10 = r"C:\ss-models\pose_landmarker_lite.task"
        script = _SSH_BENCH_POSE_SCRIPT.format(
            n_iters=kwargs.get("n_iters", 10),
            task_path=task_path_k10,
        )
        timeout = 120
    elif fn_name == "_run_benchmark_yolo":
        model_path = kwargs.get("model_path", r"C:\ss-models\yolov8n.onnx")
        script = _SSH_BENCH_YOLO_SCRIPT.format(
            model_path=model_path,
            n_iters=kwargs.get("n_iters", 10),
            use_gpu=kwargs.get("use_gpu", False),
        )
        timeout = 300
    elif fn_name == "_run_benchmark_pipeline":
        model_base = kwargs.get("model_base", r"C:\ss-models")
        script = _SSH_BENCH_PIPELINE_SCRIPT.format(
            tracknet_model_path=model_base + r"\tracknet.onnx",
            pose_task_path=r"C:\ss-models\pose_landmarker_lite.task",
            n_iters=kwargs.get("n_iters", 3),
        )
        timeout = 300
    elif fn_name == "_run_benchmark_clip":
        script = _SSH_BENCH_CLIP_SCRIPT.format(
            n_iters=kwargs.get("n_iters", 5),
        )
        timeout = 120
    elif fn_name == "_run_benchmark_stats":
        script = _SSH_BENCH_STATS_SCRIPT.format(
            n_iters=kwargs.get("n_iters", 50),
        )
        timeout = 60
    else:
        return {"error": f"SSH 未対応のベンチマーク: {fn_name}"}

    return _ssh_run_python_script(worker_ip, username, password, script, timeout=timeout)


# ────────────────────────────────────────────────────────────────────────────
# ディスパッチ関数（ray は遅延インポート）
# ────────────────────────────────────────────────────────────────────────────

def dispatch_benchmark(fn_name: str, target_ip: str = "", **kwargs) -> Dict[str, Any]:
    """ベンチマーク関数をワーカーノードに dispatch する。

    SSH 認証情報が cluster.config.yaml に設定されているワーカーは SSH 経由で実行。
    SSH 設定がないワーカーは Ray 経由にフォールバック。

    Args:
        fn_name: "_run_benchmark_tracknet" / "_run_benchmark_pose" / "_run_benchmark_yolo"
        **kwargs: 各ベンチマーク関数に渡すキーワード引数

    Returns:
        {"ssh_<ip>": result_dict, ...} または {"ray_<ip>_<id>": result_dict, ...} のマッピング
    """
    results: Dict[str, Any] = {}
    ssh_handled_ips: set = set()

    # ── SSH 経由でワーカーを処理 ──────────────────────────────────────────────
    try:
        from backend.cluster.topology import load_config, get_primary_ip
        cfg = load_config()
        head_ip = get_primary_ip()
        workers = cfg.get("network", {}).get("workers", [])

        for w in workers:
            wip = w.get("ip", "")
            if not wip or wip == head_ip:
                continue
            user = w.get("ssh_user")
            pwd = w.get("ssh_password")
            if not user or not pwd:
                continue

            # TrackNet ベンチマークのモデルパスを worker 設定から補完
            bench_kwargs = dict(kwargs)
            if fn_name == "_run_benchmark_tracknet" and "model_path" not in bench_kwargs:
                model_base = w.get("model_base", r"C:\ss-models")
                bench_kwargs["model_path"] = model_base + r"\tracknet.onnx"

            logger.info("dispatch_benchmark: SSH 経由で %s に %s を実行", wip, fn_name)
            result = dispatch_benchmark_ssh(fn_name, wip, user, pwd, **bench_kwargs)
            results[f"ssh_{wip}"] = result
            # SSH が成功した場合のみ Ray フォールバックから除外する
            # 失敗した場合は Ray 経由で再試行できるようにする
            if "error" not in result:
                ssh_handled_ips.add(wip)

    except Exception as exc:
        logger.warning("dispatch_benchmark SSH フェーズ失敗: %s", exc)

    # SSH で全ワーカーを処理できた場合はここで返す
    if results and all("error" not in v for v in results.values()):
        return results

    # ── Ray フォールバック ────────────────────────────────────────────────────
    try:
        from backend.cluster.bootstrap import is_ray_connected, ensure_ray_initialized
        if not is_ray_connected():
            if results:
                return results  # SSH 結果（エラー含む）があれば返す
            return {"error": "Ray未接続 — 先にRay起動ボタンを押してください"}
        if not ensure_ray_initialized(timeout=10):
            if results:
                return results
            return {"error": "ray.init() 失敗 — PC1 で管理者PowerShellから scripts/fix_ray_firewall.ps1 を実行してください（TCP 6379 の Inbound 許可が必要）"}
    except Exception as exc:
        if results:
            return results
        return {"error": f"Ray 初期化エラー: {exc}"}

    try:
        import ray  # type: ignore
    except ImportError:
        if results:
            return results
        return {"error": "ray 未インストール"}

    if not ray.is_initialized():
        if results:
            return results
        return {"error": "Ray初期化未完了"}

    # 関数名からローカル関数を解決
    fn_map = {
        "_run_benchmark_tracknet": _run_benchmark_tracknet,
        "_run_benchmark_pose": _run_benchmark_pose,
        "_run_benchmark_yolo": _run_benchmark_yolo,
        "_run_benchmark_pipeline": _run_benchmark_pipeline,
        "_run_benchmark_clip": _run_benchmark_clip,
        "_run_benchmark_stats": _run_benchmark_stats,
    }
    fn = fn_map.get(fn_name)
    if fn is None:
        return {**results, **{"error": f"未知のベンチマーク関数: {fn_name}"}}

    try:
        try:
            from backend.cluster.topology import get_primary_ip
            head_ip = get_primary_ip()
        except Exception:
            head_ip = ""

        nodes = ray.nodes()
        worker_nodes = [
            n for n in nodes
            if n.get("Alive")
            and n.get("NodeManagerAddress", "") != head_ip
            and n.get("NodeManagerAddress", "") not in ssh_handled_ips
            and (not target_ip or n.get("NodeManagerAddress", "") == target_ip)
        ]

        if not worker_nodes:
            return results if results else {"error": "Alive なノードが見つかりません"}

        futures = {}
        for node in worker_nodes:
            node_id = node.get("NodeID", "unknown")
            node_ip = node.get("NodeManagerAddress", "unknown")
            node_resource = f"node:{node_ip}"
            remote_fn = ray.remote(
                num_cpus=0,
                resources={node_resource: 0.001},
            )(fn)
            future = remote_fn.remote(**kwargs)
            futures[f"ray_{node_ip}_{node_id[:8]}"] = future

        for device_id, future in futures.items():
            try:
                result = ray.get(future, timeout=120)
                results[device_id] = result
            except ray.exceptions.GetTimeoutError:
                results[device_id] = {"error": "タイムアウト (120s)"}
            except Exception as exc:
                results[device_id] = {"error": str(exc)}

        return results

    except Exception as exc:
        logger.warning("dispatch_benchmark 失敗: %s", exc)
        return {"error": str(exc)}


def dispatch_hardware_detect(worker_ip: str) -> Dict[str, Any]:
    """指定ワーカー IP のハードウェア情報を取得する。

    SSH 認証情報が cluster.config.yaml に設定されている場合は SSH 優先。
    設定がない場合は Ray 経由にフォールバック。

    Args:
        worker_ip: ワーカーノードの IP アドレス

    Returns:
        _detect_hardware() の戻り値、またはエラー dict
    """
    # ── SSH 優先パス ──────────────────────────────────────────────────────────
    creds = _get_worker_ssh_creds(worker_ip)
    if creds:
        logger.info("dispatch_hardware_detect: SSH 経由で %s に接続", worker_ip)
        result = dispatch_hardware_detect_ssh(
            worker_ip=creds["host"],
            username=creds["username"],
            password=creds["password"],
        )
        if "error" not in result:
            return result
        logger.warning(
            "dispatch_hardware_detect: SSH 失敗 (%s)、Ray にフォールバック", result["error"]
        )

    # ── Ray フォールバックパス ────────────────────────────────────────────────
    try:
        from backend.cluster.bootstrap import is_ray_connected, ensure_ray_initialized
        if not is_ray_connected():
            return {"error": "Ray未接続 — 先にRay起動ボタンを押してください"}
        if not ensure_ray_initialized(timeout=10):
            return {"error": "ray.init() 失敗 — PC1 で管理者PowerShellから scripts/fix_ray_firewall.ps1 を実行してください（TCP 6379 の Inbound 許可が必要）"}
    except Exception as exc:
        return {"error": f"Ray 初期化エラー: {exc}"}

    try:
        import ray  # type: ignore
    except ImportError:
        return {"error": "ray 未インストール"}

    if not ray.is_initialized():
        return {"error": "Ray初期化未完了"}

    try:
        nodes = ray.nodes()
        alive_nodes = [n for n in nodes if n.get("Alive")]

        target_node = next(
            (n for n in alive_nodes if n.get("NodeManagerAddress") == worker_ip),
            None,
        )
        if target_node is None:
            target_node = next(
                (n for n in alive_nodes if n.get("NodeManagerAddress", "").endswith(worker_ip)),
                None,
            )

        if target_node is None:
            alive_ips = [n.get("NodeManagerAddress", "?") for n in alive_nodes]
            logger.warning(
                "dispatch_hardware_detect: %s が見つかりません。Alive ノード: %s",
                worker_ip, alive_ips,
            )
            if not alive_ips:
                return {"error": "Alive なノードがありません。K10 で join コマンドを実行してください"}
            return {"error": f"ワーカーノード {worker_ip} が見つかりません。現在のノード: {', '.join(alive_ips)}"}

        node_resource = f"node:{worker_ip}"
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                remote_fn = ray.remote(
                    num_cpus=0,
                    resources={node_resource: 0.001},
                )(_detect_hardware)
                future = remote_fn.remote()
                result = ray.get(future, timeout=30)
                result.pop("_node_id", None)
                return result

            except Exception as exc:
                last_exc = exc
                err_str = str(exc)
                logger.warning("dispatch_hardware_detect attempt=%d: %s", attempt + 1, err_str[:200])
                if attempt < 2:
                    import time as _t
                    _t.sleep(2)
                    continue
                raise
        return {"error": str(last_exc)}

    except Exception as exc:
        logger.warning("dispatch_hardware_detect 失敗: %s", exc)
        return {"error": str(exc)}


def dispatch_tracknet_inference(frames_npy: bytes, model_path: str, device_id: str) -> bytes:
    """TrackNet 推論を特定の Ray ワーカーに dispatch する。

    Args:
        frames_npy: シリアライズされた numpy フレームデータ
                    フォーマット: 先頭 16 バイト = shape (N,C,H,W) as int32x4、
                                残り = float32 フレームデータ
        model_path: ワーカー上の ONNX モデルパス
        device_id:  ターゲットデバイス ID（"ray_igpu_..." で GPU 使用）

    Returns:
        推論結果バイト列（_infer_tracknet_frames と同形式）
        エラー時は JSON エンコードされたエラー dict の bytes
    """
    try:
        import ray  # type: ignore
    except ImportError:
        return json.dumps({"error": "ray 未インストール"}).encode("utf-8")

    if not ray.is_initialized():
        return json.dumps({"error": "Ray初期化未完了 — バックグラウンドでray.init()中"}).encode("utf-8")

    try:
        remote_fn = ray.remote(_infer_tracknet_frames)
        future = remote_fn.remote(model_path=model_path, frames_npy=frames_npy)
        result = ray.get(future, timeout=60)
        return result
    except Exception as exc:
        return json.dumps({"error": str(exc)}).encode("utf-8")
