"""クラスタトポロジー管理 (INFRA Phase D)

cluster.config.yaml を読み込み、ノード構成・ネットワーク情報を提供する。
設定ファイルが存在しない場合は single モードのデフォルト値にフォールバック。
"""
from __future__ import annotations

import logging
import pathlib
import socket
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# タスク分散設定のデフォルト値
_DEFAULT_TASK_ROUTING: Dict[str, str] = {
    "tracknet": "auto",
    "pose": "auto",
    "yolo": "auto",
}

logger = logging.getLogger(__name__)

# cluster.config.yaml の検索パス（shuttlescope/ ルート）
_CONFIG_PATH = pathlib.Path(__file__).resolve().parent.parent.parent / "cluster.config.yaml"

# キャッシュ（起動後に変更された場合は reload() を呼ぶ）
_cached_config: Optional[Dict[str, Any]] = None


def _load_yaml(path: pathlib.Path) -> Dict[str, Any]:
    """YAML を安全に読み込む。pyyaml 未インストールなら空 dict。"""
    try:
        import yaml  # type: ignore
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning("topology: cluster.config.yaml 読み込み失敗 (%s) — デフォルト使用", exc)
        return {}


def _save_yaml(path: pathlib.Path, data: Dict[str, Any]) -> None:
    """YAML を書き込む。"""
    import yaml  # type: ignore
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def load_config(force: bool = False) -> Dict[str, Any]:
    """cluster.config.yaml を返す（キャッシュあり）。"""
    global _cached_config
    if _cached_config is None or force:
        _cached_config = _load_yaml(_CONFIG_PATH)
    return _cached_config


def reload() -> Dict[str, Any]:
    """キャッシュを破棄して再読み込みする。"""
    return load_config(force=True)


def save_config(data: Dict[str, Any]) -> None:
    """cluster.config.yaml を上書き保存してキャッシュを更新する。"""
    global _cached_config
    _save_yaml(_CONFIG_PATH, data)
    _cached_config = data


# ────────────────────────────────────────────────────────────────────────────
# アクセサ
# ────────────────────────────────────────────────────────────────────────────

def get_mode() -> str:
    """動作モードを返す: single | primary | worker"""
    return load_config().get("mode", "single")


def is_single() -> bool:
    return get_mode() == "single"


def is_primary() -> bool:
    return get_mode() == "primary"


def is_worker() -> bool:
    return get_mode() == "worker"


def get_node_id() -> str:
    return load_config().get("node", {}).get("id", "pc1")


def get_primary_ip() -> str:
    return load_config().get("network", {}).get("primary_ip", "127.0.0.1")


def get_workers() -> List[Dict[str, str]]:
    """ワーカーノード一覧を返す（primary 設定時のみ意味を持つ）。"""
    return load_config().get("network", {}).get("workers", [])


def get_ray_head_address() -> str:
    return load_config().get("ray", {}).get("head_address", "127.0.0.1:6379")


def get_pg_host() -> str:
    return load_config().get("postgresql", {}).get("host", "127.0.0.1")


def get_load_limits() -> Dict[str, Any]:
    return load_config().get("load_limits", {
        "max_gpu_percent": 80,
        "max_cpu_percent": 70,
        "max_concurrent_inference": 4,
        "throttle_interval_sec": 1.0,
    })


def get_inference_config() -> Dict[str, Any]:
    return load_config().get("inference", {
        "frame_compression": "jpeg",
        "jpeg_quality": 80,
        "max_cameras": 4,
    })


# ────────────────────────────────────────────────────────────────────────────
# ネットワークインターフェース一覧
# ────────────────────────────────────────────────────────────────────────────

def list_interfaces() -> List[Dict[str, str]]:
    """システムのネットワークインターフェース一覧を返す。

    psutil が利用可能な場合は詳細情報を返す。
    利用不可の場合は socket から最低限の情報を返す。
    """
    try:
        import psutil  # type: ignore
        ifaces = []
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        for name, addr_list in addrs.items():
            ipv4 = next(
                (a.address for a in addr_list if a.family == socket.AF_INET),
                None,
            )
            is_up = stats.get(name, None)
            ifaces.append({
                "name": name,
                "ip": ipv4 or "",
                "is_up": str(is_up.isup).lower() if is_up else "unknown",
                "speed_mbps": str(is_up.speed) if is_up else "0",
            })
        return ifaces
    except Exception as exc:
        logger.debug("list_interfaces: psutil unavailable (%s)", exc)
        return [{"name": "unknown", "ip": "", "is_up": "unknown", "speed_mbps": "0"}]


# ────────────────────────────────────────────────────────────────────────────
# ノード疎通確認
# ────────────────────────────────────────────────────────────────────────────

def get_task_routing() -> Dict[str, str]:
    """task_routing 設定を返す。未設定はすべて 'auto'。"""
    cfg = load_config()
    routing = cfg.get("task_routing", {})
    result = dict(_DEFAULT_TASK_ROUTING)
    if isinstance(routing, dict):
        result.update({k: str(v) for k, v in routing.items()})
    return result


def save_task_routing(routing: Dict[str, str]) -> None:
    """task_routing を cluster.config.yaml に保存する。"""
    cfg = load_config(force=True)
    cfg["task_routing"] = routing
    save_config(cfg)
    logger.info("save_task_routing: task_routing を保存しました: %s", routing)


def get_worker_model_base(worker_ip: str) -> str:
    """指定ワーカーの model_base パスを返す。デフォルト C:\\ss-models"""
    workers = get_workers()
    for w in workers:
        if w.get("ip") == worker_ip:
            base = w.get("model_base", "")
            if base:
                return str(base)
    return "C:\\ss-models"


def ping_icmp(ip: str, timeout: float = 2.0) -> Dict[str, Any]:
    """ICMP ping で疎通確認する（subprocess 経由）。

    HTTP ではなく ICMP を使うため、ShuttleScope 未搭載の K10 等でも機能する。
    """
    import subprocess, sys, time

    started = time.time()
    kw: dict = {"capture_output": True, "text": True}
    if sys.platform == "win32":
        cmd = ["ping", "-n", "1", "-w", str(int(timeout * 1000)), ip]
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    else:
        cmd = ["ping", "-c", "1", "-W", str(int(timeout)), ip]

    try:
        result = subprocess.run(cmd, timeout=timeout + 1, **kw)
        latency_ms = int((time.time() - started) * 1000)
        return {"reachable": result.returncode == 0, "latency_ms": latency_ms, "via": "icmp"}
    except Exception as exc:
        latency_ms = int((time.time() - started) * 1000)
        return {"reachable": False, "latency_ms": latency_ms, "via": "icmp", "error": str(exc)}


def ping_node(ip: str, port: int = 8765, timeout: float = 2.0) -> Dict[str, Any]:
    """指定ノードへの疎通確認。ICMP ping を優先し、失敗時は HTTP にフォールバック。

    K10 は ShuttleScope を動かしていないため HTTP ではなく ICMP で確認する。
    """
    result = ping_icmp(ip, timeout=timeout)
    if result["reachable"]:
        return result
    # ICMP が通らない場合（ファイアウォール等）は HTTP も試みる
    import time, urllib.request, ipaddress
    started = time.time()
    try:
        # SSRF防止: ip が有効なIPアドレスであることを確認
        _addr = ipaddress.ip_address(ip)
        if not (_addr.is_private or _addr.is_loopback or _addr.is_link_local):
            raise ValueError("クラスタ外アドレスへの HTTP 疎通確認は許可されていません")
        url = f"http://{ip}:{port}/api/health"
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            latency_ms = int((time.time() - started) * 1000)
            return {"reachable": True, "latency_ms": latency_ms, "via": "http"}
    except Exception:
        pass
    return result  # ICMP の結果を返す
