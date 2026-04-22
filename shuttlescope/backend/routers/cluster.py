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

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from backend.cluster import bootstrap as _bootstrap
from backend.cluster.load_guard import load_guard
from backend.cluster import topology
from backend.utils.control_plane import require_local_or_operator_token

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
def save_cluster_config(body: ConfigSaveRequest, request: Request) -> Dict[str, Any]:
    """cluster.config.yaml を更新する。"""
    require_local_or_operator_token(request)
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
def start_ray(request: Request) -> Dict[str, Any]:
    """Ray クラスタへの接続確認をバックグラウンドで行う。

    Windows Firewall 環境では ray.init() の TCP 接続がブロックされるため、
    subprocess で ray status を実行してクラスタ稼働を確認する方式を採用する。
    確認完了後は /cluster/status の ray.status が "running" に変わる。
    """
    require_local_or_operator_token(request)
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


@router.post("/cluster/ray/start-head")
def start_ray_head(body: StartHeadRequest, request: Request) -> Dict[str, Any]:
    """このノードで Ray ヘッドとして起動する（ray start --head を実行）。

    既存の Ray プロセスは先に停止してから起動する。
    """
    require_local_or_operator_token(request)
    import subprocess, sys, os

    ray_cmd = _bootstrap._find_ray_cmd()
    kw: dict = {"capture_output": True, "text": True, "errors": "replace", "timeout": 30}
    if sys.platform == "win32":
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

    # 既存プロセスをクリーンアップ
    try:
        subprocess.run([ray_cmd, "stop", "--force"], **kw)
        _bootstrap.unmark_ray_connected()
    except Exception:
        pass

    # ray start --head
    cmd = [
        ray_cmd, "start", "--head",
        f"--node-ip-address={body.node_ip}",
        f"--port={body.port}",
        "--dashboard-host=0.0.0.0",
    ]
    if body.num_cpus is not None:
        cmd.append(f"--num-cpus={body.num_cpus}")
    if body.num_gpus is not None:
        cmd.append(f"--num-gpus={body.num_gpus}")

    import os as _os
    env = _os.environ.copy()
    env["RAY_ENABLE_WINDOWS_OR_OSX_CLUSTER"] = "1"
    kw["env"] = env

    try:
        result = subprocess.run(cmd, **kw)
        if result.returncode != 0:
            return {"ok": False, "message": result.stderr or result.stdout}
        # 起動確認
        import time; time.sleep(2)
        status = _bootstrap.subprocess_ray_status()
        if status["running"]:
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
    require_local_or_operator_token(request)
    try:
        _bootstrap.shutdown_ray()
        return {"ok": True, "message": "Ray 接続をクリアしました"}
    except Exception as exc:
        logger.error("Ray stop failed: %s", exc, exc_info=True)
        raise HTTPException(500, "Ray 停止処理に失敗しました")


@router.post("/cluster/nodes/{worker_ip}/detect")
def detect_worker_hardware(worker_ip: str, request: Request) -> Dict[str, Any]:
    """SSH または Ray 経由で指定ワーカーのハードウェア情報を取得する。

    取得成功後は cluster.config.yaml のワーカー設定を自動更新する。
    worker_ip はパスパラメータ（ドット → アンダースコア変換不要、そのまま渡す）。
    """
    require_local_or_operator_token(request)
    actual_ip = worker_ip.replace("_", ".")

    from backend.cluster.remote_tasks import dispatch_hardware_detect

    hw = dispatch_hardware_detect(actual_ip)
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
    require_local_or_operator_token(request)
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
        results.append({**w, "ping": ping})
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
    require_local_or_operator_token(request)
    actual_ip = worker_ip.replace("_", ".")
    return topology.wake_worker(actual_ip)


class SleepDisableRequest(BaseModel):
    username: str
    password: str


@router.post("/cluster/nodes/{worker_ip}/disable-sleep")
def disable_worker_sleep(worker_ip: str, body: SleepDisableRequest, request: Request) -> Dict[str, Any]:
    """SSH 経由でワーカーのスリープ設定を無効化する。

    Windows の電源設定を変更し、AC 電源接続中はスリープしないようにする。
    K10 側で OpenSSH Server が有効になっている必要がある。
    """
    require_local_or_operator_token(request)
    try:
        import paramiko  # type: ignore
    except ImportError:
        raise HTTPException(500, "paramiko が必要です: pip install paramiko")

    actual_ip = worker_ip.replace("_", ".")

    # スリープ無効化コマンド（AC 電源接続中のスタンバイタイムアウトを 0 = 無効）
    cmds = [
        "powercfg /change standby-timeout-ac 0",
        "powercfg /change hibernate-timeout-ac 0",
        "powercfg /change monitor-timeout-ac 0",
    ]

    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
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
    except Exception as exc:
        logger.error("disable_worker_sleep %s failed: %s", actual_ip, exc)
        return {"ok": False, "message": f"SSH 接続またはコマンド実行に失敗しました: {exc}"}


@router.post("/cluster/nodes/{worker_ip}/ray-join")
def remote_ray_join(worker_ip: str, body: RemoteRayJoinRequest, request: Request) -> Dict[str, Any]:
    """SSH 経由でワーカーノードに ray start コマンドを送信する。

    paramiko が必要: pip install paramiko
    K10 側で OpenSSH Server が有効になっている必要がある。
    """
    require_local_or_operator_token(request)
    try:
        import paramiko  # type: ignore
    except ImportError:
        raise HTTPException(500, "paramiko が必要です: pip install paramiko")

    actual_ip = worker_ip.replace("_", ".")

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

    cmd = f"ray start --address={body.head_ip}:{body.port} --node-ip-address={actual_ip}"
    if num_cpus is not None:
        cmd += f" --num-cpus={num_cpus}"
    if num_gpus:
        cmd += f" --num-gpus={num_gpus}"

    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
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
    require_local_or_operator_token(request)
    try:
        import paramiko  # type: ignore
    except ImportError:
        raise HTTPException(500, "paramiko が必要です: pip install paramiko")

    actual_ip = worker_ip.replace("_", ".")

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
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
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
    except Exception as exc:
        logger.error("remote_ray_restart %s failed: %s", actual_ip, exc, exc_info=True)
        return {"ok": False, "message": f"SSH 接続またはコマンド実行に失敗しました: {exc}"}
