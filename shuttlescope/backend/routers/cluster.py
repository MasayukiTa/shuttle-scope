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

    # Ray 状態
    ray_status = "off"
    ray_nodes: List[Dict] = []
    if _bootstrap.is_ray_available():
        try:
            import ray  # type: ignore
            if ray.is_initialized():
                ray_status = "running"
                try:
                    nodes = ray.nodes()
                    ray_nodes = [
                        {
                            "node_id": n.get("NodeID", "")[:8],
                            "alive": n.get("Alive", False),
                            "resources": n.get("Resources", {}),
                        }
                        for n in nodes
                    ]
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


@router.post("/cluster/ping")
def ping_node(body: PingRequest) -> Dict[str, Any]:
    """指定ノードへの疎通確認を行う。"""
    result = topology.ping_node(body.ip, body.port, body.timeout)
    return {"ip": body.ip, "port": body.port, **result}


@router.get("/cluster/nodes")
def get_nodes() -> List[Dict[str, Any]]:
    """ワーカーノード一覧と疎通状態を返す（primary 視点）。"""
    cfg = topology.load_config()
    workers = cfg.get("network", {}).get("workers", [])
    results = []
    for w in workers:
        ip = w.get("ip", "")
        ping = topology.ping_node(ip) if ip else {"reachable": False}
        results.append({**w, "ping": ping})
    return results
