"""リモートトンネル管理 API

プロバイダー:
  - cloudflare : cloudflared tunnel --url
  - ngrok      : ngrok http {port}  (ngrok local API localhost:4040 から URL 取得)
  - auto       : ngrok → cloudflare の順で利用可能なものを選択

エンドポイント:
  GET  /api/tunnel/status          — 実行状態・公開URL・プロバイダー情報を返す
  POST /api/tunnel/start?provider= — トンネル起動（auto|cloudflare|ngrok）
  POST /api/tunnel/stop            — トンネル停止
  GET  /api/webrtc/ice-config      — WebRTC ICE サーバー設定（STUN + TURN）
"""
import json
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from typing import Optional, Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.database import get_db

router = APIRouter()

TunnelProvider = Literal['cloudflare', 'ngrok']

# ─── プロセス状態（インメモリシングルトン） ───────────────────────────────────
_proc: Optional[subprocess.Popen] = None
_tunnel_url: Optional[str] = None
_active_provider: Optional[TunnelProvider] = None
_stderr_lines: list[str] = []
_lock = threading.Lock()

_CF_URL_PATTERN = re.compile(r'https://[a-z0-9\-]+\.trycloudflare\.com', re.IGNORECASE)


# ─── プロバイダー可用性チェック ──────────────────────────────────────────────

def _cloudflare_available() -> bool:
    return shutil.which("cloudflared") is not None


def _ngrok_available() -> bool:
    return shutil.which("ngrok") is not None


def _resolve_provider(provider: str) -> Optional[TunnelProvider]:
    """'auto' の場合は ngrok → cloudflare の順で選択"""
    if provider == 'ngrok':
        return 'ngrok' if _ngrok_available() else None
    if provider == 'cloudflare':
        return 'cloudflare' if _cloudflare_available() else None
    # auto
    if _ngrok_available():
        return 'ngrok'
    if _cloudflare_available():
        return 'cloudflare'
    return None


# ─── Cloudflare stderr 読み取りスレッド ──────────────────────────────────────

def _read_stderr_cloudflare(proc: subprocess.Popen) -> None:
    global _tunnel_url, _stderr_lines
    for line in iter(proc.stderr.readline, b''):
        text = line.decode('utf-8', errors='replace').strip()
        with _lock:
            _stderr_lines.append(text)
            if len(_stderr_lines) > 50:
                _stderr_lines.pop(0)
            if not _tunnel_url:
                m = _CF_URL_PATTERN.search(text)
                if m:
                    _tunnel_url = m.group(0)


# ─── ngrok local API ポーリングスレッド ──────────────────────────────────────

def _poll_ngrok_url(proc: subprocess.Popen) -> None:
    """ngrok local API (http://localhost:4040/api/tunnels) から HTTPS URL を取得する"""
    global _tunnel_url
    deadline = time.time() + 30  # 最大30秒待機
    while time.time() < deadline:
        if proc.poll() is not None:
            break  # プロセスが終了した
        try:
            req = urllib.request.urlopen('http://localhost:4040/api/tunnels', timeout=2)
            data = json.loads(req.read())
            for t in data.get('tunnels', []):
                url = t.get('public_url', '')
                if url.startswith('https://'):
                    with _lock:
                        _tunnel_url = url
                    return
        except Exception:
            pass
        time.sleep(1)


# ─── プロセス起動ヘルパー ─────────────────────────────────────────────────────

def _start_cloudflare(port: int) -> subprocess.Popen:
    use_shell = sys.platform == "win32"
    cf_path = shutil.which("cloudflared")
    cmd = (
        f'"{cf_path}" tunnel --url http://localhost:{port}'
        if use_shell
        else [cf_path, "tunnel", "--url", f"http://localhost:{port}"]
    )
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, shell=use_shell)


def _start_ngrok(port: int) -> subprocess.Popen:
    use_shell = sys.platform == "win32"
    ngrok_path = shutil.which("ngrok")
    cmd = (
        f'"{ngrok_path}" http {port}'
        if use_shell
        else [ngrok_path, "http", str(port)]
    )
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, shell=use_shell)


# ─── エンドポイント ──────────────────────────────────────────────────────────

@router.get("/tunnel/status")
def tunnel_status():
    cf_avail = _cloudflare_available()
    ngrok_avail = _ngrok_available()

    with _lock:
        running = _proc is not None and _proc.poll() is None
        url = _tunnel_url if running else None
        recent_log = list(_stderr_lines[-10:])
        provider = _active_provider if running else None

    return {
        "success": True,
        "data": {
            # 後方互換フィールド（AnnotatorPage 等が参照）
            "available": cf_avail or ngrok_avail,
            "running": running,
            "url": url,
            # 拡張フィールド
            "active_provider": provider,
            "providers": {
                "cloudflare": {"available": cf_avail},
                "ngrok": {"available": ngrok_avail},
            },
            "recent_log": recent_log,
        },
    }


@router.post("/tunnel/start")
def tunnel_start(provider: str = "auto"):
    global _proc, _tunnel_url, _stderr_lines, _active_provider

    resolved = _resolve_provider(provider)
    if resolved is None:
        return {
            "success": False,
            "error": (
                "利用可能なトンネルプロバイダーが見つかりません。"
                "ngrok または cloudflared をインストールしてください。"
            ),
        }

    with _lock:
        if _proc is not None and _proc.poll() is None:
            return {
                "success": True,
                "data": {"message": "すでに起動中", "url": _tunnel_url, "provider": _active_provider},
            }
        _tunnel_url = None
        _stderr_lines = []
        _active_provider = None

    port = settings.API_PORT

    if resolved == 'ngrok':
        proc = _start_ngrok(port)
        with _lock:
            _proc = proc
            _active_provider = 'ngrok'
        t = threading.Thread(target=_poll_ngrok_url, args=(proc,), daemon=True)
        t.start()
        return {
            "success": True,
            "data": {
                "message": "ngrok を起動しました。URL取得まで数秒かかります。",
                "provider": "ngrok",
            },
        }
    else:
        proc = _start_cloudflare(port)
        with _lock:
            _proc = proc
            _active_provider = 'cloudflare'
        t = threading.Thread(target=_read_stderr_cloudflare, args=(proc,), daemon=True)
        t.start()
        return {
            "success": True,
            "data": {
                "message": "cloudflared を起動しました。URL取得まで数秒かかります。",
                "provider": "cloudflare",
            },
        }


@router.post("/tunnel/stop")
def tunnel_stop():
    global _proc, _tunnel_url, _stderr_lines, _active_provider

    with _lock:
        proc = _proc
        _proc = None
        _tunnel_url = None
        _stderr_lines = []
        _active_provider = None

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


# ─── WebRTC ICE 設定 ─────────────────────────────────────────────────────────

@router.get("/webrtc/ice-config")
def webrtc_ice_config(db: Session = Depends(get_db)):
    """WebRTC ICE サーバー設定を返す（STUN デフォルト + TURN オプション）

    Settings の turn_enabled / turn_url / turn_username / turn_credential を読み取り、
    RTCPeerConnection の iceServers 形式で返す。
    TURN が無効の場合は STUN のみ返す（ベストエフォート）。
    """
    from backend.routers.settings import _load_all
    cfg = _load_all(db)

    ice_servers: list[dict] = [{"urls": "stun:stun.l.google.com:19302"}]

    if cfg.get("turn_enabled") and cfg.get("turn_url"):
        entry: dict = {"urls": cfg["turn_url"]}
        if cfg.get("turn_username"):
            entry["username"] = cfg["turn_username"]
        if cfg.get("turn_credential"):
            entry["credential"] = cfg["turn_credential"]
        ice_servers.append(entry)

    return {
        "success": True,
        "data": {
            "ice_servers": ice_servers,
            "turn_enabled": bool(cfg.get("turn_enabled")),
        },
    }
