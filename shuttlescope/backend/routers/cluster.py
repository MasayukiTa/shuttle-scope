"""クラスタ管理 API (INFRA Phase D)

エンドポイント:
  GET  /api/cluster/status               — 現在ノードの負荷・Ray・DB 状態
  GET  /api/cluster/config               — cluster.config.yaml の内容
  POST /api/cluster/config               — cluster.config.yaml を更新
  GET  /api/cluster/interfaces           — 利用可能なネットワークインターフェース一覧
  POST /api/cluster/ping                 — 指定ノードへの疎通確認
  GET  /api/cluster/nodes                — ワーカーノード一覧と疎通状態
  GET  /api/cluster/ray/join-script      — K10 で irm <url> | iex する PowerShell スクリプト
  POST /api/cluster/nodes/{ip}/ray-join  — SSH 経由でワーカーに ray start を送信
"""
from __future__ import annotations

import ipaddress
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from backend.cluster import bootstrap as _bootstrap
from backend.cluster.load_guard import load_guard
from backend.cluster import topology
from backend.utils.auth import get_auth
from backend.utils.control_plane import require_local_operator_or_admin

logger = logging.getLogger(__name__)


def _validate_cluster_ip(ip: str) -> str:
    """プライベート / リンクローカル IP のみ許可（SSRF対策）。"""
    try:
        addr = ipaddress.ip_address(ip.strip())
    except ValueError:
        raise HTTPException(status_code=422, detail=f"無効なIPアドレス: {ip}")
    if not (addr.is_private or addr.is_loopback or addr.is_link_local):
        raise HTTPException(status_code=422, detail="プライベートIPアドレスのみ指定可能です")
    return str(addr)


def _require_admin_dep(request: Request) -> None:
    """クラスタ管理エンドポイントは admin ロール限定。

    SSH 資格情報・ネットワーク構成を含むため player/analyst/coach からは秘匿する。
    """
    ctx = get_auth(request)
    if not ctx.is_admin:
        raise HTTPException(status_code=403, detail="admin role required")


def _mask_worker_secrets(worker: Dict[str, Any]) -> Dict[str, Any]:
    """レスポンス経路で SSH 資格情報などの秘密値を除去する。"""
    redacted = dict(worker)
    for k in ("ssh_password", "ssh_user", "ssh_key", "ssh_private_key"):
        if k in redacted:
            redacted[k] = "***" if redacted.get(k) else redacted.get(k)
    return redacted


router = APIRouter(tags=["cluster"], dependencies=[Depends(_require_admin_dep)])


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
    """cluster.config.yaml の内容を返す（SSH 資格情報はマスク）。"""
    cfg = topology.reload()
    try:
        workers = cfg.get("network", {}).get("workers", [])
        if isinstance(workers, list):
            cfg["network"]["workers"] = [_mask_worker_secrets(w) for w in workers]
    except Exception:
        pass
    return cfg


@router.post("/cluster/config")
def save_cluster_config(body: ConfigSaveRequest, request: Request) -> Dict[str, Any]:
    """cluster.config.yaml を更新する。"""
    require_local_operator_or_admin(request)
    try:
        # UI に返した際にマスクされた "***" を受け取った場合は既存値を維持する。
        incoming = body.config or {}
        existing = topology.reload() or {}
        try:
            ex_workers = {w.get("ip"): w for w in existing.get("network", {}).get("workers", []) if isinstance(w, dict)}
            in_workers = incoming.get("network", {}).get("workers", [])
            if isinstance(in_workers, list):
                for w in in_workers:
                    if not isinstance(w, dict):
                        continue
                    ip = w.get("ip")
                    ex = ex_workers.get(ip, {})
                    for k in ("ssh_password", "ssh_user", "ssh_key", "ssh_private_key"):
                        if w.get(k) == "***" and ex.get(k):
                            w[k] = ex[k]
        except Exception:
            pass
        topology.save_config(incoming)
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
def start_ray(request: Request) -> Dict[str, Any]:
    """Ray クラスタへの接続確認をバックグラウンドで行う。

    Windows Firewall 環境では ray.init() の TCP 接続がブロックされるため、
    subprocess で ray status を実行してクラスタ稼働を確認する方式を採用する。
    確認完了後は /cluster/status の ray.status が "running" に変わる。
    """
    require_local_operator_or_admin(request)
    import threading

    if _bootstrap.is_ray_connected():
        return {"ok": True, "message": "Ray は既に接続済みです", "status": "running"}

    def _connect():
        status = _bootstrap.subprocess_ray_status()
        if status["running"]:
            _bootstrap.mark_ray_connected()
            logger.info("Ray クラスタ確認済み (subprocess): active_nodes=%d", status.get("active_count", 0))
            return
        logger.warning("ray status で確認できず。ray.init() を試みます: %s", status["error"])
        try:
            _bootstrap.init_ray(address="auto", force=True)
        except Exception as exc:
            logger.warning("ray.init() フォールバックも失敗: %s", exc)

    threading.Thread(target=_connect, daemon=True).start()
    return {"ok": True, "message": "Ray クラスタ確認中 (ray status)...", "status": "connecting"}


class StartHeadRequest(BaseModel):
    node_ip: str
    port: int = 6379
    num_cpus: Optional[int] = None
    num_gpus: Optional[int] = None
    # force=True で「既に起動中でも強制再起動」。デフォルトは冪等動作（既に
    # 全ノード alive なら no-op で 200 を返す）。連打によるゴーストノード増殖防止。
    force: bool = False


def _ray_cluster_alive_state() -> tuple[bool, set[str], set[str]]:
    """現在の Ray クラスタ状態をチェック。

    Returns:
        (head_alive, alive_worker_ips, dead_worker_ips_recent)
    """
    try:
        if not _bootstrap.is_ray_connected():
            return False, set(), set()
        import ray  # type: ignore
        if not ray.is_initialized():
            try:
                _bootstrap.ensure_ray_initialized(timeout=3)
            except Exception:
                return False, set(), set()
        try:
            head_ip = topology.get_primary_ip()
        except Exception:
            head_ip = ""
        alive_ips: set[str] = set()
        dead_ips: set[str] = set()
        head_alive = False
        for n in ray.nodes():
            ip = n.get("NodeManagerAddress", "")
            if not ip:
                continue
            is_alive = bool(n.get("Alive"))
            if ip == head_ip:
                head_alive = head_alive or is_alive
            else:
                if is_alive:
                    alive_ips.add(ip)
                else:
                    dead_ips.add(ip)
        return head_alive, alive_ips, dead_ips
    except Exception:
        return False, set(), set()


@router.post("/cluster/ray/start-head")
def start_ray_head(body: StartHeadRequest, request: Request) -> Dict[str, Any]:
    """このノードで Ray ヘッドとして起動する（ray start --head を実行）。

    既存の Ray プロセスは先に停止してから起動する。
    """
    require_local_operator_or_admin(request)
    import subprocess, sys, os, ipaddress

    # Command-injection 防止: 入力値を厳格に正規化
    try:
        safe_ip = str(ipaddress.ip_address(body.node_ip))
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="node_ip が不正なIPアドレス形式です")
    try:
        safe_port = int(body.port)
        if not (1 <= safe_port <= 65535):
            raise ValueError
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="port が不正です")
    try:
        safe_cpus = int(body.num_cpus) if body.num_cpus is not None else None
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="num_cpus が不正です")
    try:
        safe_gpus = int(body.num_gpus) if body.num_gpus is not None else None
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="num_gpus が不正です")

    # ── 冪等化: 既にクラスタが健全なら何もしない（連打対策／ゴーストノード防止）
    # head が alive かつ全ワーカーが alive なら早期リターン。
    # body.force=True なら従来通り強制再起動。
    head_alive, alive_workers, _dead_workers = _ray_cluster_alive_state()
    workers_cfg = topology.get_workers()
    expected_worker_ips = {w.get("ip") for w in workers_cfg if w.get("ip")}
    if (not body.force) and head_alive and expected_worker_ips.issubset(alive_workers):
        logger.info("start_ray_head: 既に全ノード alive — no-op (force=false)")
        # 冪等な情報応答を返す
        worker_cmds = [
            {"label": w.get("label", w.get("ip", "")), "ip": w.get("ip", ""),
             "cmd": f"ray start --address={body.node_ip}:{body.port} --node-ip-address={w.get('ip','')} --num-cpus={w.get('num_cpus',16)}"
                    + (f" --num-gpus={w.get('num_gpus',0)}" if w.get('num_gpus') else "")}
            for w in workers_cfg
        ]
        first_cmd = worker_cmds[0]["cmd"] if worker_cmds else ""
        return {
            "ok": True,
            "message": "Ray クラスタは既に全ノード alive — 起動不要",
            "status": "already-running",
            "worker_cmd": first_cmd,
            "worker_cmds": worker_cmds,
        }

    ray_cmd = _bootstrap._find_ray_cmd()
    kw: dict = {"capture_output": True, "text": True, "errors": "replace", "timeout": 30}
    if sys.platform == "win32":
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

    # head が既に alive かつ force=False なら head 再起動は skip。
    # ワーカーで落ちているものだけ SSH 経由で再起動する（部分復旧モード）。
    skip_head_restart = head_alive and not body.force
    if not skip_head_restart:
        # 既存プロセスをクリーンアップ（batと同様に stop → 2秒待ち → start）
        try:
            subprocess.run([ray_cmd, "stop", "--force"], **kw)
            _bootstrap.unmark_ray_connected()
        except Exception:
            pass
        import time as _time; _time.sleep(2)
    else:
        logger.info("start_ray_head: head=alive、ワーカー %s のみ部分再起動",
                    sorted(expected_worker_ips - alive_workers))

    # ray start --head
    cmd = [
        ray_cmd, "start", "--head",
        f"--node-ip-address={safe_ip}",
        f"--port={safe_port}",
        "--dashboard-host=0.0.0.0",
    ]
    if safe_cpus is not None:
        cmd.append(f"--num-cpus={safe_cpus}")
    if safe_gpus is not None:
        cmd.append(f"--num-gpus={safe_gpus}")

    import os as _os
    env = _os.environ.copy()
    env["RAY_ENABLE_WINDOWS_OR_OSX_CLUSTER"] = "1"
    kw["env"] = env

    try:
        if not skip_head_restart:
            result = subprocess.run(cmd, **kw)
            if result.returncode != 0:
                return {"ok": False, "message": result.stderr or result.stdout}
            # 起動確認
            import time; time.sleep(2)
            status = _bootstrap.subprocess_ray_status()
            if not status["running"]:
                if status.get("error"):
                    logger.error("Ray status error detail: %s", status["error"])
                return {"ok": False, "message": "Ray プロセスは終了しましたが起動を確認できませんでした"}
            _bootstrap.mark_ray_connected()
        # workers config から join コマンドを生成（ワーカーごと）
        workers = topology.get_workers()
        worker_cmds = []
        for w in workers:
            wip = w.get("ip", "<WORKER_IP>")
            wcpus = w.get("num_cpus", 16)
            wgpus = w.get("num_gpus", 0)
            cmd_str = f"ray start --address={body.node_ip}:{body.port} --node-ip-address={wip} --num-cpus={wcpus}"
            if wgpus:
                cmd_str += f" --num-gpus={wgpus}"
            worker_cmds.append({"label": w.get("label", wip), "ip": wip, "cmd": cmd_str})

        # SSH 認証情報と ray_restart_bat が設定されているワーカーは自動で bat を実行する
        import threading
        def _trigger_worker_restart(wip: str, user: str, pwd: str, bat: str) -> None:
            try:
                import paramiko  # type: ignore
                client = paramiko.SSHClient()
                client.load_system_host_keys()
                client.set_missing_host_key_policy(paramiko.RejectPolicy())
                client.connect(wip, username=user, password=pwd, timeout=10)
                # bat はリモート側で `cmd /c "<bat>"` の "" 内に直接展開される。
                # cluster.config.yaml が万一汚染された場合に `& malicious` 等で
                # 任意コマンドが連鎖実行されるのを防ぐため、quote 文字と
                # コマンド連結文字を遮断する (CWE-78)。validate 済みでないバッチは
                # 実行を見送り、警告ログを残す。
                client.exec_command(f'cmd /c "{bat}"', timeout=120)  # nosec B601 -- bat validated by _SAFE_BAT_RE + deny-list before thread spawn
                logger.info("worker ray-restart 完了: %s", wip)
            except Exception as exc:
                logger.warning("worker ray-restart 失敗 %s: %s", wip, exc)

        # bat 値の前段バリデーション。Windows パス記号 + 限定された英数記号のみを許容する。
        import re as _re_bat
        _SAFE_BAT_RE = _re_bat.compile(r"^[A-Za-z]:[\\/][A-Za-z0-9_\-\\/. ]+\.(?:bat|cmd)$")
        # head 部分再起動モードでは alive な worker は触らない（連打時の不要な
        # K10 ray restart を防いでゴーストノード増殖を抑える）。
        # head 完全再起動モード（force or head 落ち）では全 worker を再起動する。
        for w in workers:
            wip = w.get("ip", "")
            user = w.get("ssh_user")
            pwd = w.get("ssh_password")
            bat = w.get("ray_restart_bat")
            if not (wip and user and pwd and bat):
                continue
            # 部分再起動モードで既に alive な worker は skip
            if skip_head_restart and wip in alive_workers:
                logger.info("worker=%s は alive のため SSH 再起動 skip", wip)
                continue
            if not isinstance(bat, str) or not _SAFE_BAT_RE.match(bat) or any(
                c in bat for c in ('"', "'", "&", "|", ";", "`", "$", "\n", "\r", "%")
            ):
                logger.warning(
                    "ray_restart_bat skipped (unsafe path): worker=%s value=%r",
                    wip, bat,
                )
                continue
            logger.info("SSH 経由でワーカー ray-restart をトリガー: %s", wip)
            threading.Thread(
                target=_trigger_worker_restart,
                args=(wip, user, pwd, bat),
                daemon=True,
            ).start()

        # 後方互換: 最初のワーカーコマンドを worker_cmd として返す
        first_cmd = worker_cmds[0]["cmd"] if worker_cmds else f"ray start --address={body.node_ip}:{body.port} --node-ip-address=<WORKER_IP> --num-cpus=16 --num-gpus=1"
        return {"ok": True, "message": "Ray head started", "status": "running",
                "worker_cmd": first_cmd, "worker_cmds": worker_cmds}
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "ray start タイムアウト"}
    except Exception as exc:
        logger.error("ray start failed: %s", exc, exc_info=True)
        return {"ok": False, "message": "Ray head 起動に失敗しました"}


@router.post("/cluster/ray/stop")
def stop_ray(request: Request) -> Dict[str, Any]:
    """Ray 接続フラグをクリアする（ray.shutdown() は呼ばない）。"""
    require_local_operator_or_admin(request)
    try:
        _bootstrap.shutdown_ray()
        return {"ok": True, "message": "Ray 接続をクリアしました"}
    except Exception as exc:
        logger.error("Ray stop failed: %s", exc, exc_info=True)
        raise HTTPException(500, "Ray 停止処理に失敗しました")


@router.post("/cluster/nodes/{worker_ip}/detect")
async def detect_worker_hardware(worker_ip: str, request: Request) -> Dict[str, Any]:
    """SSH または Ray 経由で指定ワーカーのハードウェア情報を取得する。

    取得成功後は cluster.config.yaml のワーカー設定を自動更新する。
    worker_ip はパスパラメータ（ドット → アンダースコア変換不要、そのまま渡す）。
    """
    require_local_operator_or_admin(request)
    actual_ip = worker_ip.replace("_", ".")

    from backend.cluster.remote_tasks import dispatch_hardware_detect

    # rereview NEW-D fix: 旧コードは dispatch_hardware_detect (最大 ~96 秒の SSH/Ray
    # dispatch) を request handler 内で同期実行し、CLAUDE.md「long-running を request
    # handler にインラインするな」に違反 + ヘルスチェックを巻き込んで遅延させていた。
    # 短期対応として asyncio.to_thread + wait_for で 100 秒の hard ceiling を付け、
    # event loop と他リクエストへの巻き添えを防ぐ。
    # 中期対応 (TODO): ClusterJob テーブル経由で worker dispatch を非同期化。
    import asyncio as _aio_for_hw
    try:
        hw = await _aio_for_hw.wait_for(
            _aio_for_hw.to_thread(dispatch_hardware_detect, actual_ip),
            timeout=100,
        )
    except _aio_for_hw.TimeoutError:
        raise HTTPException(504, f"hardware detect timed out for {actual_ip} (>100s)")
    if "error" in hw:
        raise HTTPException(400, hw["error"])

    # cluster.config.yaml のワーカー設定を更新
    cfg = topology.load_config(force=True)
    workers = cfg.get("network", {}).get("workers", [])
    updated = False
    for w in workers:
        if w.get("ip") == actual_ip:
            if hw.get("num_cpus"):
                w["num_cpus"] = hw["num_cpus"]
            if hw.get("num_gpus") is not None:
                w["num_gpus"] = hw["num_gpus"]
            if hw.get("gpu_label"):
                w["gpu_label"] = hw["gpu_label"]
            # ORT プロバイダー情報も保存（GPU デバイス判定に使用）
            ort_providers = hw.get("ort_providers")
            if ort_providers is not None:
                w["ort_providers"] = ort_providers
            updated = True
            break

    if updated:
        topology.save_config(cfg)
        logger.info("detect_worker_hardware: %s の設定を更新しました: %s", actual_ip, hw)

    return {**hw, "config_updated": updated}


@router.get("/cluster/network/arp")
def get_arp_devices(request: Request) -> List[Dict[str, Any]]:
    """ARP テーブルから近隣デバイス一覧を返す。

    Windows: arp -a、Linux/Mac: arp -a で解析する。
    このノード自身の全インターフェース IP は除外する。
    """
    require_local_operator_or_admin(request)
    import subprocess, sys, re

    kw: dict = {"capture_output": True, "text": True, "errors": "replace", "timeout": 10}
    if sys.platform == "win32":
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

    # 自分自身の IP セット
    own_ips: set = set()
    try:
        import psutil, socket
        for addrs in psutil.net_if_addrs().values():
            for a in addrs:
                if a.family == socket.AF_INET:
                    own_ips.add(a.address)
    except Exception:
        pass

    try:
        result = subprocess.run(["arp", "-a"], **kw)
        lines = result.stdout.splitlines()
    except Exception as exc:
        logger.error("arp scan failed: %s", exc, exc_info=True)
        return [{"error": "ARP スキャンに失敗しました"}]

    devices: List[Dict[str, Any]] = []
    seen: set = set()

    for line in lines:
        # Windows: "  169.254.140.146      xx-xx-xx-xx-xx-xx     動的"
        # または "  192.168.1.5          xx-xx-xx-xx-xx-xx     static"
        m = re.search(r'(\d{1,3}(?:\.\d{1,3}){3})', line)
        if not m:
            continue
        ip = m.group(1)
        if ip in seen or ip in own_ips:
            continue
        # マルチキャスト・ブロードキャストを除外
        parts = ip.split(".")
        last = int(parts[-1])
        if last in (0, 255) or ip.startswith("224.") or ip.startswith("239."):
            continue
        seen.add(ip)
        devices.append({"ip": ip})

    # 既存ワーカー設定の IP にラベルを付ける
    try:
        workers = topology.get_workers()
        worker_map = {w.get("ip", ""): w.get("label", "") for w in workers}
        for d in devices:
            d["known_label"] = worker_map.get(d["ip"], "")
    except Exception:
        pass

    return devices


@router.post("/cluster/ping")
def ping_node(body: PingRequest) -> Dict[str, Any]:
    """指定ノードへの疎通確認（ICMP → HTTP フォールバック）。

    K10 は ShuttleScope を動かしていないため HTTP ping ではなく ICMP を優先する。
    """
    result = topology.ping_node(body.ip, body.port, body.timeout)
    return {"ip": body.ip, **result}


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
        # Stack-trace-exposure 防止: ping dict からエラー詳細を除去
        if isinstance(ping, dict):
            ping.pop("error", None)
        results.append({**_mask_worker_secrets(w), "ping": ping})
    return results


# ────────────────────────────────────────────────────────────────────────────
# K10 参加スクリプト / SSH リモート起動
# ────────────────────────────────────────────────────────────────────────────

@router.get("/cluster/ray/join-script", response_class=PlainTextResponse)
def get_ray_join_script(request: Request) -> str:
    """K10 で実行する PowerShell join スクリプトを返す。

    呼び出し元 IP が workers 設定と一致すればそのコマンドのみ返す。
    一致しない場合は全ワーカーのコマンドを列挙する。

    K10 側での実行例:
        irm http://169.254.96.137:8765/api/cluster/ray/join-script | iex
    """
    caller_ip = request.client.host if request.client else ""
    cfg = topology.load_config()
    primary_ip = cfg.get("network", {}).get("primary_ip", "127.0.0.1")
    workers = cfg.get("network", {}).get("workers", [])

    targets = [w for w in workers if w.get("ip") == caller_ip] or workers

    lines = [
        "# ShuttleScope Ray Worker Join Script",
        f"# Head: {primary_ip}:6379",
        "$env:RAY_ENABLE_WINDOWS_OR_OSX_CLUSTER = '1'",
    ]
    for w in targets:
        wip = w.get("ip", caller_ip or "<WORKER_IP>")
        wcpus = w.get("num_cpus", 16)
        wgpus = w.get("num_gpus", 0)
        label = w.get("label", wip)
        cmd = f"ray start --address={primary_ip}:6379 --node-ip-address={wip} --num-cpus={wcpus}"
        if wgpus:
            cmd += f" --num-gpus={wgpus}"
        lines.append(f"Write-Host 'Joining Ray cluster as: {label} ({wip})'")
        lines.append(cmd)
        lines.append("Write-Host 'Done.'")

    return "\r\n".join(lines)


class RemoteRayJoinRequest(BaseModel):
    username: str
    password: str
    head_ip: str
    port: int = 6379
    num_cpus: Optional[int] = None
    num_gpus: Optional[int] = None


@router.post("/cluster/nodes/{worker_ip}/wake")
def wake_worker_node(worker_ip: str, request: Request) -> Dict[str, Any]:
    """Wake-on-LAN マジックパケットをワーカーノードへ送信する。

    MAC アドレスは cluster.config.yaml の workers[].mac または ARP テーブルから取得する。
    link-local (169.254.x.x) ネットワークでは 169.254.255.255 にブロードキャストする。

    WOL が動作するには K10 側で:
    1. BIOS の Wake-on-LAN を有効化
    2. NIC ドライバの省電力設定で WOL を許可
    が必要。
    """
    require_local_operator_or_admin(request)
    actual_ip = worker_ip.replace("_", ".")
    wake_result = topology.wake_worker(actual_ip)
    # Stack-trace-exposure 防止: 内部例外文字列を除去
    if isinstance(wake_result, dict):
        wake_result.pop("error", None)
    return wake_result


class SleepDisableRequest(BaseModel):
    username: str
    password: str


@router.post("/cluster/nodes/{worker_ip}/disable-sleep")
def disable_worker_sleep(worker_ip: str, body: SleepDisableRequest, request: Request) -> Dict[str, Any]:
    """SSH 経由でワーカーのスリープ設定を無効化する。

    Windows の電源設定を変更し、AC 電源接続中はスリープしないようにする。
    K10 側で OpenSSH Server が有効になっている必要がある。
    """
    require_local_operator_or_admin(request)
    try:
        import paramiko  # type: ignore
    except ImportError:
        raise HTTPException(500, "paramiko が必要です: pip install paramiko")

    actual_ip = _validate_cluster_ip(worker_ip.replace("_", "."))

    # スリープ無効化コマンド（AC 電源接続中のスタンバイタイムアウトを 0 = 無効）
    cmds = [
        "powercfg /change standby-timeout-ac 0",
        "powercfg /change hibernate-timeout-ac 0",
        "powercfg /change monitor-timeout-ac 0",
    ]

    try:
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        client.connect(actual_ip, username=body.username, password=body.password, timeout=10)
        results = []
        for cmd in cmds:
            _, stdout, stderr = client.exec_command(cmd, timeout=10)
            stdout.channel.recv_exit_status()
            results.append(cmd)
        client.close()
        return {
            "ok": True,
            "message": "スリープ設定を無効化しました（AC 電源接続中）",
            "applied": results,
        }
    except Exception:
        logger.exception("disable_worker_sleep %s failed", actual_ip)
        return {"ok": False, "message": "SSH 接続またはコマンド実行に失敗しました"}


@router.post("/cluster/nodes/{worker_ip}/ray-join")
def remote_ray_join(worker_ip: str, body: RemoteRayJoinRequest, request: Request) -> Dict[str, Any]:
    """SSH 経由でワーカーノードに ray start コマンドを送信する。

    paramiko が必要: pip install paramiko
    K10 側で OpenSSH Server が有効になっている必要がある。
    """
    require_local_operator_or_admin(request)
    try:
        import paramiko  # type: ignore
    except ImportError:
        raise HTTPException(500, "paramiko が必要です: pip install paramiko")

    actual_ip = _validate_cluster_ip(worker_ip.replace("_", "."))
    head_ip = _validate_cluster_ip(body.head_ip)

    # ワーカー設定から num_cpus / num_gpus を補完
    num_cpus = body.num_cpus
    num_gpus = body.num_gpus
    if num_cpus is None or num_gpus is None:
        cfg = topology.load_config()
        for w in cfg.get("network", {}).get("workers", []):
            if w.get("ip") == actual_ip:
                if num_cpus is None:
                    num_cpus = w.get("num_cpus", 16)
                if num_gpus is None:
                    num_gpus = w.get("num_gpus", 0)
                break

    cmd = f"ray start --address={head_ip}:{body.port} --node-ip-address={actual_ip}"
    if num_cpus is not None:
        cmd += f" --num-cpus={num_cpus}"
    if num_gpus:
        cmd += f" --num-gpus={num_gpus}"

    try:
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        client.connect(actual_ip, username=body.username, password=body.password, timeout=10)
        _, stdout, stderr = client.exec_command(cmd, timeout=30)
        out = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        exit_code = stdout.channel.recv_exit_status()
        client.close()
        ok = exit_code == 0
        return {"ok": ok, "message": out.strip() if ok else (err.strip() or out.strip()), "cmd": cmd}
    except Exception as exc:
        logger.error("remote_ray_join %s failed: %s", actual_ip, exc, exc_info=True)
        return {"ok": False, "message": "SSH 接続またはコマンド実行に失敗しました"}


@router.post("/cluster/nodes/{worker_ip}/ray-restart")
def remote_ray_restart(worker_ip: str, request: Request) -> Dict[str, Any]:
    """SSH 経由でワーカーの ray-restart.bat を実行する。

    cluster.config.yaml の workers[] に ssh_user / ssh_password / ray_restart_bat が
    設定されている必要がある。
    """
    require_local_operator_or_admin(request)
    try:
        import paramiko  # type: ignore
    except ImportError:
        raise HTTPException(500, "paramiko が必要です: pip install paramiko")

    actual_ip = _validate_cluster_ip(worker_ip.replace("_", "."))

    cfg = topology.load_config()
    worker: Optional[Dict[str, Any]] = None
    for w in cfg.get("network", {}).get("workers", []):
        if w.get("ip") == actual_ip:
            worker = w
            break
    if worker is None:
        raise HTTPException(404, f"worker {actual_ip} が cluster.config.yaml に見つかりません")

    user = worker.get("ssh_user")
    password = worker.get("ssh_password")
    bat_path = worker.get("ray_restart_bat")
    if not (user and password and bat_path):
        raise HTTPException(
            400,
            "worker の ssh_user / ssh_password / ray_restart_bat が未設定です",
        )

    cmd = f'cmd /c "{bat_path}"'
    try:
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        client.connect(actual_ip, username=user, password=password, timeout=10)
        _, stdout, stderr = client.exec_command(cmd, timeout=120)
        raw_out = stdout.read()
        raw_err = stderr.read()
        exit_code = stdout.channel.recv_exit_status()
        client.close()
        # Windows の batch 出力は cp932 が多いため両方試す
        def _dec(b: bytes) -> str:
            for enc in ("utf-8", "cp932"):
                try:
                    return b.decode(enc)
                except UnicodeDecodeError:
                    continue
            return b.decode("utf-8", errors="replace")

        out = _dec(raw_out)
        err = _dec(raw_err)
        ok = exit_code == 0
        # 出力は末尾 2000 文字のみ返す（UI ログ用）
        return {
            "ok": ok,
            "exit_code": exit_code,
            "stdout": out[-2000:].strip(),
            "stderr": err[-2000:].strip(),
            "cmd": cmd,
        }
    except Exception:
        logger.exception("remote_ray_restart %s failed", actual_ip)
        return {"ok": False, "message": "SSH 接続またはコマンド実行に失敗しました"}
