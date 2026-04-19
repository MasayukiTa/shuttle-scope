"""クラスタ管理 API (INFRA Phase D)

エンドポイント:
  GET  /api/cluster/status        — 現在ノードの負荷・Ray・DB 状態
  GET  /api/cluster/config        — cluster.config.yaml の内容
  POST /api/cluster/config        — cluster.config.yaml を更新
  GET  /api/cluster/interfaces    — 利用可能なネットワークインターフェース一覧
  POST /api/cluster/ping          — 指定ノードへの疎通確認
  GET  /api/cluster/nodes         — ワーカーノード一覧と疎通状態
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.cluster import bootstrap as _bootstrap
from backend.cluster.load_guard import load_guard
from backend.cluster import topology

logger = logging.getLogger(__name__)
router = APIRouter(tags=["cluster"])


# ────────────────────────────────────────────────────────────────────────────
# スキーマ
# ────────────────────────────────────────────────────────────────────────────

class PingRequest(BaseModel):
    ip: str
    port: int = 8765
    timeout: float = 2.0


class ConfigSaveRequest(BaseModel):
    config: Dict[str, Any]


# ────────────────────────────────────────────────────────────────────────────
# エンドポイント
# ────────────────────────────────────────────────────────────────────────────

@router.get("/cluster/status")
def get_cluster_status() -> Dict[str, Any]:
    """現在ノードの負荷・Ray・モード情報を返す。"""
    load = load_guard.status()

    ray_status = "off"
    ray_nodes: List[Dict] = []

    if _bootstrap.is_ray_available():
        try:
            import ray  # type: ignore
            if ray.is_initialized():
                # ray.init() で直接接続できている場合
                ray_status = "running"
                try:
                    for n in ray.nodes():
                        ray_nodes.append({
                            "node_id": n.get("NodeID", "")[:8],
                            "alive": n.get("Alive", False),
                            "resources": n.get("Resources", {}),
                        })
                except Exception:
                    pass
            elif _bootstrap._ray_subprocess_connected:
                # subprocess (ray status) 経由で確認済みの場合
                ray_status = "running"
                try:
                    status = _bootstrap.subprocess_ray_status()
                    active_count = status.get("active_count", 0)
                    for i in range(active_count):
                        ray_nodes.append({"node_id": f"node{i+1}", "alive": True, "resources": {}})
                except Exception:
                    pass
            else:
                ray_status = "stopped"
        except Exception:
            ray_status = "error"

    return {
        "mode": topology.get_mode(),
        "node_id": topology.get_node_id(),
        "load": load,
        "ray": {"status": ray_status, "nodes": ray_nodes},
    }


@router.get("/cluster/config")
def get_cluster_config() -> Dict[str, Any]:
    """cluster.config.yaml の内容を返す。"""
    return topology.reload()


@router.post("/cluster/config")
def save_cluster_config(body: ConfigSaveRequest) -> Dict[str, Any]:
    """cluster.config.yaml を更新する。"""
    try:
        topology.save_config(body.config)
        return {"ok": True, "message": "cluster.config.yaml を保存しました"}
    except Exception as exc:
        logger.error("cluster config save failed: %s", exc)
        raise HTTPException(500, f"設定ファイルの保存に失敗しました: {exc}")


@router.get("/cluster/interfaces")
def get_interfaces() -> List[Dict[str, str]]:
    """システムのネットワークインターフェース一覧を返す。"""
    return topology.list_interfaces()


@router.get("/cluster/hardware")
def get_hardware() -> Dict[str, Any]:
    """このノードの実メモリ情報を返す（リソース上限スライダーの max 値用）。"""
    import math

    # システム RAM
    system_ram_gb = 0
    try:
        import psutil
        system_ram_gb = math.ceil(psutil.virtual_memory().total / (1024 ** 3))
    except Exception:
        pass

    # GPU VRAM (全デバイス)
    gpu_devices: List[Dict[str, Any]] = []
    try:
        import pynvml
        pynvml.nvmlInit()
        count = pynvml.nvmlDeviceGetCount()
        for i in range(count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode()
            gpu_devices.append({
                "index": i,
                "name": name,
                "vram_total_gb": round(info.total / (1024 ** 3), 1),
            })
        pynvml.nvmlShutdown()
    except Exception:
        pass

    vram_total_gb = max((d["vram_total_gb"] for d in gpu_devices), default=0)

    return {
        "system_ram_gb": system_ram_gb,
        "vram_total_gb": vram_total_gb,
        "gpu_devices": gpu_devices,
    }


@router.post("/cluster/ray/start")
def start_ray() -> Dict[str, Any]:
    """Ray クラスタへの接続確認をバックグラウンドで行う。

    Windows Firewall 環境では ray.init() の TCP 接続がブロックされるため、
    subprocess で ray status を実行してクラスタ稼働を確認する方式を採用する。
    確認完了後は /cluster/status の ray.status が "running" に変わる。
    """
    import threading

    if _bootstrap.is_ray_connected():
        return {"ok": True, "message": "Ray は既に接続済みです", "status": "running"}

    def _connect():
        # まず subprocess で ray status を確認する（Firewall 回避）
        status = _bootstrap.subprocess_ray_status()
        if status["running"]:
            _bootstrap.mark_ray_connected()
            logger.info("Ray クラスタ確認済み (subprocess): active_nodes=%d", status.get("active_count", 0))
            return

        # subprocess でも確認できなかった場合は ray.init() を試みる（TCP 接続）
        logger.warning("ray status で確認できず。ray.init() を試みます: %s", status["error"])
        try:
            _bootstrap.init_ray(address="auto", force=True)
        except Exception as exc:
            logger.warning("ray.init() フォールバックも失敗: %s", exc)

    threading.Thread(target=_connect, daemon=True).start()
    return {"ok": True, "message": "Ray クラスタ確認中 (ray status)...", "status": "connecting"}


@router.post("/cluster/ray/stop")
def stop_ray() -> Dict[str, Any]:
    """Ray 接続フラグをクリアする（ray.shutdown() は呼ばない）。"""
    try:
        _bootstrap.shutdown_ray()
        return {"ok": True, "message": "Ray 接続をクリアしました"}
    except Exception as exc:
        logger.error("Ray stop failed: %s", exc)
        raise HTTPException(500, str(exc))


@router.post("/cluster/ping")
def ping_node(body: PingRequest) -> Dict[str, Any]:
    """指定ノードへの疎通確認を行う。"""
    result = topology.ping_node(body.ip, body.port, body.timeout)
    return {"ip": body.ip, "port": body.port, **result}


@router.get("/cluster/nodes")
def get_nodes() -> List[Dict[str, Any]]:
    """ワーカーノード一覧と疎通状態を返す（primary 視点）。

    Ray ワーカーノードは ShuttleScope を動かしていないため HTTP /api/health
    への疎通ではなく Ray クラスタのノードリストで生死を判定する。
    Ray 未接続のノードは HTTP ping にフォールバックする。
    """
    cfg = topology.load_config()
    workers = cfg.get("network", {}).get("workers", [])

    # Ray が動いていればアクティブノードの IP セットを収集する
    ray_active_ips: set[str] = set()
    try:
        import ray  # type: ignore
        if ray.is_initialized():
            for node in ray.nodes():
                if node.get("Alive", False):
                    addr = node.get("NodeManagerAddress", "")
                    if addr:
                        ray_active_ips.add(addr)
        elif _bootstrap._ray_subprocess_connected:
            # ダッシュボードなしでIP取得不可のため active_count で判定する。
            # active_count >= workers + 1 (head) なら全ワーカーが参加済みとみなす。
            status = _bootstrap.subprocess_ray_status()
            active_count = status.get("active_count", 0)
            if active_count >= len(workers) + 1:
                for w in workers:
                    ip = w.get("ip", "")
                    if ip:
                        ray_active_ips.add(ip)
    except Exception:
        pass

    results = []
    for w in workers:
        ip = w.get("ip", "")
        if ip and ip in ray_active_ips:
            # Ray クラスタに参加済み → OK
            ping = {"reachable": True, "latency_ms": 0, "via": "ray"}
        elif ip:
            # Ray 未参加 → HTTP ヘルスエンドポイントで確認
            ping = topology.ping_node(ip)
            ping["via"] = "http"
        else:
            ping = {"reachable": False, "via": "none"}
        results.append({**w, "ping": ping})
    return results
