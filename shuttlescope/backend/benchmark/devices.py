"""ベンチマーク計測対象デバイスの型定義とプローブ関数。

ComputeDevice は runner / routers / probe から共通参照する。
probe_all() が利用可能な計算デバイス（CPU / iGPU / dGPU / Ray ワーカー）を列挙して返す。
pynvml / openvino / ray が未インストールでも動作する（try/except で遅延インポート）。
probe 結果は TTL 60秒でメモリキャッシュし、起動時の重い初期化を繰り返さない。
"""
from __future__ import annotations

import os
import platform
import re
import time
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class ComputeDevice:
    """計算デバイス 1 台を表す。

    device_type: "cpu" | "igpu" | "dgpu" | "ray_worker"
    backend:     "pytorch-cpu" | "pytorch-cuda" | "openvino" | "onnx" | "ray"
    available:   False の場合、runner は {"error": "device unavailable"} を即座に返す
    specs:       追加メタ情報（VRAM, コア数など）
    """

    device_id: str
    label: str
    device_type: str  # cpu | igpu | dgpu | ray_worker
    backend: str
    available: bool
    specs: dict = field(default_factory=dict)


# ─── キャッシュ ────────────────────────────────────────────────────────────────

_CACHE_TTL = 60  # 秒
_cache_result: list[ComputeDevice] | None = None
_cache_ts: float = 0.0


def _sanitize(name: str) -> str:
    """デバイス ID 生成用: スペース・特殊文字を _ に変換して小文字化"""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


# ─── 個別プローブ関数 ──────────────────────────────────────────────────────────

def _probe_cpu() -> list[ComputeDevice]:
    """CPU を常に 1 件検出して返す"""
    try:
        import psutil
        cores: int = psutil.cpu_count(logical=False) or 1
        logical: int = psutil.cpu_count(logical=True) or 1
    except Exception:
        cores = 1
        logical = 1

    name = platform.processor() or platform.machine() or "CPU"
    # 長すぎる場合は先頭 40 文字に丸める
    name = name[:40].strip()

    specs: dict[str, Any] = {
        "name": name,
        "cores": cores,
        "logical_cores": logical,
    }
    dev_id = "cpu_" + _sanitize(name)
    return [
        ComputeDevice(
            device_id=dev_id,
            label=f"CPU: {name}",
            device_type="cpu",
            backend="pytorch-cpu",
            available=True,
            specs=specs,
        )
    ]


def _probe_nvidia() -> list[ComputeDevice]:
    """pynvml で NVIDIA GPU を検出する。未インストールまたはエラー時は空リスト"""
    devices: list[ComputeDevice] = []
    try:
        import pynvml  # type: ignore

        pynvml.nvmlInit()
        count = pynvml.nvmlDeviceGetCount()
        for i in range(count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            try:
                raw_name = pynvml.nvmlDeviceGetName(handle)
                # pynvml は bytes または str を返す場合がある
                name: str = raw_name.decode() if isinstance(raw_name, bytes) else str(raw_name)
            except Exception:
                name = f"NVIDIA GPU {i}"

            # VRAM (MiB)
            try:
                mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                vram_mb: int | None = mem_info.total // (1024 * 1024)
            except Exception:
                vram_mb = None

            # ドライババージョン
            try:
                driver_raw = pynvml.nvmlSystemGetDriverVersion()
                driver: str | None = driver_raw.decode() if isinstance(driver_raw, bytes) else str(driver_raw)
            except Exception:
                driver = None

            # CUDA Compute Capability
            try:
                major, minor = pynvml.nvmlDeviceGetCudaComputeCapability(handle)
                cc: str | None = f"{major}.{minor}"
            except Exception:
                cc = None

            specs: dict[str, Any] = {"name": name}
            if vram_mb is not None:
                specs["vram_mb"] = vram_mb
            if driver:
                specs["driver"] = driver
            if cc:
                specs["compute_capability"] = cc

            dev_id = f"cuda_{i}_{_sanitize(name)}"
            devices.append(
                ComputeDevice(
                    device_id=dev_id,
                    label=f"dGPU: {name}",
                    device_type="dgpu",
                    backend="pytorch-cuda",
                    available=True,
                    specs=specs,
                )
            )
        pynvml.nvmlShutdown()
    except Exception:
        # pynvml 未インストール、ドライバ無し等はすべて空リストで返す
        pass
    return devices


def _probe_openvino() -> list[ComputeDevice]:
    """OpenVINO Runtime で GPU（iGPU）デバイスを検出する。未インストール時は空リスト"""
    devices: list[ComputeDevice] = []
    try:
        from openvino.runtime import Core  # type: ignore

        core = Core()
        available = core.available_devices  # 例: ["CPU", "GPU", "GPU.0"]
        gpu_devices = [d for d in available if d.startswith("GPU")]

        for ov_dev in gpu_devices:
            try:
                name = core.get_property(ov_dev, "FULL_DEVICE_NAME")
            except Exception:
                name = ov_dev

            # Intel iGPU 判定（"Intel" が含まれるもの）
            is_igpu = "intel" in str(name).lower()
            dtype = "igpu" if is_igpu else "dgpu"
            prefix = "igpu" if is_igpu else "dgpu"

            dev_id = f"{prefix}_{_sanitize(str(name))}"
            devices.append(
                ComputeDevice(
                    device_id=dev_id,
                    label=f"{'iGPU' if is_igpu else 'GPU'}: {name}",
                    device_type=dtype,
                    backend="openvino",
                    available=True,
                    specs={"name": str(name)},
                )
            )
    except Exception:
        # openvino 未インストールはすべて空リスト
        pass
    return devices


def _probe_onnx() -> list[ComputeDevice]:
    """onnxruntime の利用可能 EP から追加デバイスを検出する。
    CPU EP は CPU プローブ済みのためスキップ。CUDA EP のみを対象とする。
    """
    devices: list[ComputeDevice] = []
    try:
        import onnxruntime as ort  # type: ignore

        providers = ort.get_available_providers()
        if "CUDAExecutionProvider" in providers:
            devices.append(
                ComputeDevice(
                    device_id="onnx_cuda",
                    label="ONNX: CUDA ExecutionProvider",
                    device_type="dgpu",
                    backend="onnx",
                    available=True,
                    specs={"name": "ONNX CUDA"},
                )
            )
    except Exception:
        pass
    return devices


def _probe_windows_igpu() -> list[ComputeDevice]:
    """Windows WMI 経由で NVIDIA 以外の GPU アダプタ（AMD/Intel iGPU 等）を列挙する。

    pynvml で既に検出した NVIDIA dGPU はスキップする。
    Windows 10/11 上の DirectX 12 対応アダプタは DirectML が利用可能なため
    available=True とする（onnxruntime-directml は別途必要だが表示上は有効）。
    """
    if platform.system() != "Windows":
        return []

    devices: list[ComputeDevice] = []
    try:
        import json
        import subprocess

        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                (
                    "Get-WmiObject Win32_VideoController"
                    " | Select-Object Name,AdapterCompatibility,AdapterRAM"
                    " | ConvertTo-Json -Compress"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return devices

        data = json.loads(result.stdout)
        if isinstance(data, dict):
            data = [data]

        for adapter in data:
            name: str = str(adapter.get("Name") or "").strip()
            compat: str = str(adapter.get("AdapterCompatibility") or "").lower()
            vram_bytes: int = int(adapter.get("AdapterRAM") or 0)
            vram_mb = vram_bytes // (1024 * 1024) if vram_bytes > 0 else 0
            name_lower = name.lower()

            # NVIDIA は pynvml で既に検出済みのためスキップ
            if "nvidia" in name_lower or "nvidia" in compat:
                continue

            if "intel" in name_lower or "intel" in compat:
                # Intel Arc は dGPU、それ以外（UHD/Iris等）は iGPU
                dtype = "dgpu" if "arc" in name_lower else "igpu"
            elif "amd" in name_lower or "radeon" in name_lower or "amd" in compat:
                # 外付け相当の型番（RX, Pro）は dGPU、統合グラフィックスは iGPU
                is_discrete = any(k in name_lower for k in ["rx ", " pro ", "vega frontier"])
                dtype = "dgpu" if is_discrete else "igpu"
            else:
                # 不明なアダプタは除外
                continue

            prefix = "igpu" if dtype == "igpu" else "dgpu"
            dev_id = f"{prefix}_{_sanitize(name)}"
            label_prefix = "iGPU" if dtype == "igpu" else "GPU"
            devices.append(
                ComputeDevice(
                    device_id=dev_id,
                    label=f"{label_prefix}: {name}",
                    device_type=dtype,
                    backend="directml",
                    available=True,  # Win10/11 の DX12 対応 GPU は DirectML 利用可能
                    specs={"name": name, "vram_mb": vram_mb},
                )
            )
    except Exception:
        pass
    return devices


# AMD XDNA NPU の既知 PCI VendorID:DeviceID（Phoenix/HawkPoint/StrixPoint）
_AMD_NPU_PCI_IDS = {
    "1022:1502",  # Phoenix (Ryzen 7040 / 8040 series)
    "1022:17f0",  # Strix Point (Ryzen AI 300 series)
    "1022:1505",  # Phoenix variant
    "1022:150c",  # Hawk Point variant
}


def _probe_npu() -> list[ComputeDevice]:
    """NPU デバイスを検出する。

    Intel NPU: OpenVINO Runtime の "NPU" デバイス。
    AMD XDNA NPU: PCI ハードウェア ID で正確に特定する（名前マッチは誤検知が多い）。
    """
    devices: list[ComputeDevice] = []

    # Intel NPU (OpenVINO)
    try:
        from openvino.runtime import Core  # type: ignore

        core = Core()
        for ov_dev in core.available_devices:
            if "NPU" not in ov_dev.upper():
                continue
            try:
                name = core.get_property(ov_dev, "FULL_DEVICE_NAME")
            except Exception:
                name = ov_dev
            dev_id = f"npu_{_sanitize(str(name))}"
            devices.append(
                ComputeDevice(
                    device_id=dev_id,
                    label=f"NPU: {name}",
                    device_type="npu",
                    backend="openvino",
                    available=True,
                    specs={"name": str(name)},
                )
            )
    except Exception:
        pass

    # AMD XDNA NPU (Windows — PCI ハードウェア ID で特定)
    if platform.system() == "Windows":
        try:
            import json
            import subprocess

            # HardwareID で VEN_1022 (AMD) かつ既知の NPU DeviceID を持つエントリを検索
            ps_cmd = (
                "$ids = @('1022:1502','1022:17f0','1022:1505','1022:150c');"
                "$found = Get-WmiObject Win32_PnPEntity | Where-Object {"
                "  $hw = $_.HardwareID;"
                "  if (-not $hw) { return $false };"
                "  $hwStr = ($hw -join ',').ToLower();"
                "  foreach ($id in $ids) {"
                "    $ven = 'ven_' + $id.Split(':')[0];"
                "    $dev = 'dev_' + $id.Split(':')[1];"
                "    if ($hwStr -match $ven -and $hwStr -match $dev) { return $true }"
                "  };"
                "  return $false"
                "};"
                "if ($found) { $found | Select-Object Name,DeviceID | ConvertTo-Json -Compress }"
                " else { '[]' }"
            )

            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                capture_output=True,
                text=True,
                timeout=20,
            )
            if result.returncode == 0 and result.stdout.strip():
                raw = result.stdout.strip()
                data = json.loads(raw)
                if isinstance(data, dict):
                    data = [data]
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    npu_name: str = str(item.get("Name") or "AMD NPU Device").strip()
                    dev_id = f"npu_{_sanitize(npu_name)}"
                    if any(d.device_id == dev_id for d in devices):
                        continue
                    devices.append(
                        ComputeDevice(
                            device_id=dev_id,
                            label=f"NPU: {npu_name}",
                            device_type="npu",
                            backend="directml",
                            available=False,  # NPU 推論バックエンド未実装
                            specs={"name": npu_name, "note": "NPU inference not yet implemented"},
                        )
                    )
        except Exception:
            pass

    return devices


def _probe_ray() -> list[ComputeDevice]:
    """SS_CLUSTER_MODE=ray のとき Ray クラスタのワーカーノードを列挙する"""
    devices: list[ComputeDevice] = []
    cluster_mode = os.environ.get("SS_CLUSTER_MODE", "off")
    if cluster_mode != "ray":
        return devices

    try:
        import ray  # type: ignore

        if not ray.is_initialized():
            ray.init(ignore_reinit_error=True)

        nodes = ray.nodes()
        for node in nodes:
            if not node.get("Alive", False):
                continue
            node_id = node.get("NodeID", "unknown")[:8]
            resources = node.get("Resources", {})
            addr = node.get("NodeManagerAddress", node_id)
            label = f"Ray worker: {addr}"
            dev_id = f"ray_worker_{_sanitize(node_id)}"
            devices.append(
                ComputeDevice(
                    device_id=dev_id,
                    label=label,
                    device_type="ray_worker",
                    backend="ray",
                    available=True,
                    specs={"name": label, "resources": resources},
                )
            )
    except Exception:
        pass
    return devices


# ─── メイン API ────────────────────────────────────────────────────────────────

def probe_all() -> list[ComputeDevice]:
    """利用可能な計算デバイスを列挙して返す（TTL 60秒キャッシュ）。
    CPU は常に 1 件以上含まれる。pynvml / openvino / ray が未インストールでも例外を投げない。
    """
    global _cache_result, _cache_ts

    now = time.monotonic()
    if _cache_result is not None and (now - _cache_ts) < _CACHE_TTL:
        return _cache_result

    result: list[ComputeDevice] = []

    # 1. CPU（常に存在）
    result.extend(_probe_cpu())

    # 2. NVIDIA GPU（pynvml 経由）
    nvidia_devices = _probe_nvidia()
    result.extend(nvidia_devices)

    # 3. OpenVINO GPU（Intel iGPU/dGPU のみ検出）
    result.extend(_probe_openvino())

    # 4. Windows iGPU（AMD/Intel — OpenVINO で未検出のものを DirectML で補完）
    existing_ids = {d.device_id for d in result}
    for dev in _probe_windows_igpu():
        if dev.device_id not in existing_ids:
            result.append(dev)
            existing_ids.add(dev.device_id)

    # 5. NPU（Intel via OpenVINO / AMD XDNA via WMI）
    for dev in _probe_npu():
        if dev.device_id not in existing_ids:
            result.append(dev)
            existing_ids.add(dev.device_id)

    # 6. ONNX Runtime（CUDA EP、NVIDIA 未検出時のみ追加）
    has_cuda = any(d.backend == "pytorch-cuda" for d in result)
    if not has_cuda:
        result.extend(_probe_onnx())

    # 7. Ray ワーカー（SS_CLUSTER_MODE=ray のとき）
    result.extend(_probe_ray())

    _cache_result = result
    _cache_ts = now
    return result


def invalidate_cache() -> None:
    """キャッシュを手動でクリアする（テスト用）"""
    global _cache_result, _cache_ts
    _cache_result = None
    _cache_ts = 0.0
