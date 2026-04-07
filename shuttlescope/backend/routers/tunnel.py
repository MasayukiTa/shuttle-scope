"""Cloudflare Tunnel 管理 API

エンドポイント:
  GET  /api/tunnel/status  — 実行状態・公開URL を返す
  POST /api/tunnel/start   — cloudflared を起動
  POST /api/tunnel/stop    — cloudflared を停止

cloudflared がPATHにない場合は status の available=false で通知。
"""
import re
import shutil
import subprocess
import threading
from typing import Optional

from fastapi import APIRouter

from backend.config import settings

router = APIRouter()

# ─── プロセス状態（インメモリシングルトン） ───────────────────────────────────
_proc: Optional[subprocess.Popen] = None
_tunnel_url: Optional[str] = None
_stderr_lines: list[str] = []  # 直近ログ（最大50行）
_lock = threading.Lock()

_URL_PATTERN = re.compile(r'https://[a-z0-9\-]+\.trycloudflare\.com', re.IGNORECASE)


def _read_stderr(proc: subprocess.Popen) -> None:
    """cloudflared の stderr を読み、トンネルURLを抽出するバックグラウンドスレッド"""
    global _tunnel_url, _stderr_lines
    for line in iter(proc.stderr.readline, b''):
        text = line.decode('utf-8', errors='replace').strip()
        with _lock:
            _stderr_lines.append(text)
            if len(_stderr_lines) > 50:
                _stderr_lines.pop(0)
            if not _tunnel_url:
                m = _URL_PATTERN.search(text)
                if m:
                    _tunnel_url = m.group(0)


# ─── エンドポイント ───────────────────────────────────────────────────────────

@router.get("/tunnel/status")
def tunnel_status():
    """トンネルの現在状態を返す"""
    available = shutil.which("cloudflared") is not None
    with _lock:
        running = _proc is not None and _proc.poll() is None
        url = _tunnel_url if running else None
        recent_log = list(_stderr_lines[-10:])

    return {
        "success": True,
        "data": {
            "available": available,
            "running": running,
            "url": url,
            "recent_log": recent_log,
        },
    }


@router.post("/tunnel/start")
def tunnel_start():
    """cloudflared トンネルを起動する"""
    global _proc, _tunnel_url, _stderr_lines

    if shutil.which("cloudflared") is None:
        return {
            "success": False,
            "error": "cloudflared が PATH に見つかりません。https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/ からインストールしてください。",
        }

    with _lock:
        if _proc is not None and _proc.poll() is None:
            return {"success": True, "data": {"message": "すでに起動中", "url": _tunnel_url}}

        _tunnel_url = None
        _stderr_lines = []

    port = settings.API_PORT
    proc = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", f"http://localhost:{port}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    with _lock:
        _proc = proc

    t = threading.Thread(target=_read_stderr, args=(proc,), daemon=True)
    t.start()

    return {"success": True, "data": {"message": "起動しました。URL取得まで数秒かかります。"}}


@router.post("/tunnel/stop")
def tunnel_stop():
    """cloudflared トンネルを停止する"""
    global _proc, _tunnel_url, _stderr_lines

    with _lock:
        proc = _proc
        _proc = None
        _tunnel_url = None
        _stderr_lines = []

    if proc is not None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    return {"success": True, "data": {"message": "停止しました"}}
