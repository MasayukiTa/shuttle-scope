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
  POST /api/webrtc/test-turn       — TURN サーバーへの TCP 疎通チェック
"""
import glob
import json
import os
import re
import shutil
import socket as _socket
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


def _find_ngrok() -> Optional[str]:
    """ngrok バイナリのパスを返す。見つからない場合は None。

    検索順:
      1. PATH に ngrok があればそのまま使用
      2. WinGet インストールパス（Windows）
      3. npm グローバルパス
      4. プロジェクト node_modules/.bin
    """
    # 1. PATH
    p = shutil.which("ngrok")
    if p:
        return p

    # 2. WinGet (Windows)
    local_app = os.environ.get("LOCALAPPDATA", "")
    if local_app:
        pattern = os.path.join(local_app, "Microsoft", "WinGet", "Packages",
                               "Ngrok.Ngrok_*", "ngrok.exe")
        matches = glob.glob(pattern)
        if matches:
            return matches[0]

    # 3. npm グローバル bin（%APPDATA%\npm\ngrok.cmd など）
    app_data = os.environ.get("APPDATA", "")
    for candidate in [
        os.path.join(app_data, "npm", "ngrok.cmd"),
        os.path.join(app_data, "npm", "ngrok"),
    ]:
        if os.path.isfile(candidate):
            return candidate

    # 4. node_modules/.bin（プロジェクトルートからの相対パス）
    here = os.path.dirname(os.path.abspath(__file__))
    for up in range(5):  # 最大5階層上まで探す
        candidate_win = os.path.join(here, *[".."] * up, "node_modules", ".bin", "ngrok.cmd")
        candidate_unix = os.path.join(here, *[".."] * up, "node_modules", ".bin", "ngrok")
        for c in [candidate_win, candidate_unix]:
            if os.path.isfile(os.path.normpath(c)):
                return os.path.normpath(c)

    return None


def _ngrok_available() -> bool:
    return _find_ngrok() is not None


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

def _read_stderr_ngrok(proc: subprocess.Popen) -> None:
    """ngrok の stderr を読んでログに記録する（エラー検出用）"""
    global _stderr_lines, _proc, _tunnel_url, _active_provider
    for line in iter(proc.stderr.readline, b''):
        text = line.decode('utf-8', errors='replace').strip()
        if not text:
            continue
        with _lock:
            _stderr_lines.append(f'[ngrok] {text}')
            if len(_stderr_lines) > 50:
                _stderr_lines.pop(0)
    # stderr が閉じた = プロセス終了。状態をリセット
    with _lock:
        if _proc is proc:
            _proc = None
            _tunnel_url = None
            _active_provider = None
            _stderr_lines.append('[ngrok] プロセスが終了しました')


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


def _start_ngrok(port: int, authtoken: str = "") -> subprocess.Popen:
    ngrok_path = _find_ngrok()
    if not ngrok_path:
        raise FileNotFoundError("ngrok が見つかりません")
    use_shell = sys.platform == "win32"
    if use_shell:
        token_part = f' --authtoken "{authtoken}"' if authtoken else ""
        cmd = f'"{ngrok_path}" http{token_part} {port}'
    else:
        cmd_list = [ngrok_path, "http"]
        if authtoken:
            cmd_list += ["--authtoken", authtoken]
        cmd_list.append(str(port))
        cmd = cmd_list
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
                "ngrok": {"available": ngrok_avail, "path": _find_ngrok()},
            },
            "recent_log": recent_log,
            # env にトークンが設定されているか（フロント側の表示切替用）
            "ngrok_authtoken_from_env": bool((settings.NGROK_AUTHTOKEN or "").strip()),
        },
    }


@router.post("/tunnel/start")
def tunnel_start(provider: str = "auto", db: Session = Depends(get_db)):
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
        old_proc = _proc
        _proc = None

    # 残存プロセスを確実に終了させてから新規起動
    if old_proc is not None:
        try:
            old_proc.terminate()
        except Exception:
            pass
    if resolved == 'ngrok':
        _kill_ngrok_processes()

    port = settings.API_PORT

    if resolved == 'ngrok':
        # authtoken: 環境変数（.env）→ DB設定 の優先順で取得
        authtoken = (settings.NGROK_AUTHTOKEN or "").strip()
        if not authtoken:
            try:
                from backend.routers.settings import _load_all
                cfg = _load_all(db)
                authtoken = (cfg.get("ngrok_authtoken") or "").strip()
            except Exception:
                pass
        try:
            proc = _start_ngrok(port, authtoken)
        except FileNotFoundError as e:
            return {"success": False, "error": str(e)}
        with _lock:
            _proc = proc
            _active_provider = 'ngrok'
        # URL 取得スレッド
        threading.Thread(target=_poll_ngrok_url, args=(proc,), daemon=True).start()
        # stderr 監視スレッド（エラー記録 + プロセス死亡検出）
        threading.Thread(target=_read_stderr_ngrok, args=(proc,), daemon=True).start()
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


def _kill_ngrok_processes() -> None:
    """実行中の ngrok プロセスをすべて強制終了する（Windows: taskkill, Unix: pkill）"""
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/IM", "ngrok.exe"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.run(
                ["pkill", "-f", "ngrok http"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
    except Exception:
        pass
    # ngrok local API (port 4040) が落ちるまで待機（最大 3 秒）
    deadline = time.time() + 3
    while time.time() < deadline:
        try:
            urllib.request.urlopen('http://localhost:4040/api/tunnels', timeout=0.5)
            time.sleep(0.3)
        except Exception:
            break  # port 4040 が応答しなくなった = 完全終了


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
            proc.wait(timeout=3)
        except Exception:
            pass

    # Windows では terminate だけでは残ることがあるので強制 kill
    _kill_ngrok_processes()

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


# ─── TURN 疎通テスト ──────────────────────────────────────────────────────────

_TURN_URL_RE = re.compile(r'^turns?:([^:?]+)(?::(\d+))?', re.IGNORECASE)


@router.post("/webrtc/test-turn")
def webrtc_test_turn(db: Session = Depends(get_db)):
    """TURN サーバーへの TCP 疎通チェック。
    設定された turn_url のホスト:ポートに TCP 接続を試み、到達可能かを返す。
    """
    from backend.routers.settings import _load_all
    cfg = _load_all(db)

    if not cfg.get("turn_enabled"):
        return {"success": False, "error": "TURN が無効です。設定で TURN を有効にしてください。"}

    turn_url = (cfg.get("turn_url") or "").strip()
    if not turn_url:
        return {"success": False, "error": "TURN URL が未設定です。"}

    m = _TURN_URL_RE.match(turn_url)
    if not m:
        return {
            "success": False,
            "error": f"TURN URL の形式が不正です（例: turn:your-server.example.com:3478）",
        }

    host = m.group(1)
    port = int(m.group(2)) if m.group(2) else 3478

    try:
        sock = _socket.create_connection((host, port), timeout=5)
        sock.close()
        return {
            "success": True,
            "data": {"host": host, "port": port, "reachable": True},
        }
    except _socket.timeout:
        return {
            "success": False,
            "data": {"host": host, "port": port, "reachable": False},
            "error": f"{host}:{port} への接続がタイムアウトしました（5秒）",
        }
    except Exception as e:
        return {
            "success": False,
            "data": {"host": host, "port": port, "reachable": False},
            "error": str(e),
        }
