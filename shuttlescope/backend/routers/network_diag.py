"""Q-002 / Q-008: ネットワーク環境診断API（/api/network）

miasma-protocol の network/environment.rs と transport/diagnostics.rs の思想を
Python / FastAPI で実装。

企業 VPN / DPI 環境での接続問題を「原因不明」にしないための診断ツール。

検出項目:
  - LAN IP 一覧
  - TCP 443 / 80 到達性（外部）
  - 環境変数ベースのプロキシ検出
  - localhost bridge 自己ヘルスチェック
  - LAN モード有効状態
  - 推奨アクション（transport ladder）
"""
import asyncio
import os
import platform
import socket
import time
from typing import Optional

from fastapi import APIRouter, Request

from backend import config as _config_module

# settings は test などで importlib.reload(backend.config) により差し替わる可能性があるため、
# 常に最新のモジュール属性を参照する。
def _get_settings():
    return _config_module.settings

router = APIRouter()

# ─── ネットワーク環境分類 ────────────────────────────────────────────────────
# miasma-protocol / NetworkEnvironment に対応する分類

ENV_OPEN         = "open"
ENV_CORP_PROXY   = "corporate_proxy"
ENV_VPN          = "vpn"
ENV_FILTERED     = "filtered"
ENV_CAPTIVE      = "captive_portal"
ENV_UNKNOWN      = "unknown"

# TLS 検査ベンダー（miasma-protocol KNOWN_TLS_INSPECTORS に対応）
KNOWN_TLS_INSPECTORS = [
    ("zscaler",    "Zscaler"),
    ("netskope",   "Netskope"),
    ("palo alto",  "Palo Alto GlobalProtect"),
    ("forcepoint", "Forcepoint"),
    ("fortinet",   "Fortinet"),
    ("barracuda",  "Barracuda"),
    ("sophos",     "Sophos"),
    ("mcafee",     "McAfee/Trellix"),
    ("checkpoint", "Check Point"),
    ("bluecoat",   "Blue Coat/Symantec"),
]


async def _probe_tcp(host: str, port: int, timeout: float = 3.0) -> tuple[bool, Optional[str]]:
    """TCP 接続プローブ。成功 True、失敗 False + エラー文字列"""
    try:
        conn = asyncio.open_connection(host, port)
        reader, writer = await asyncio.wait_for(conn, timeout=timeout)
        writer.close()
        await writer.wait_closed()
        return True, None
    except asyncio.TimeoutError:
        return False, f"timeout ({timeout}s)"
    except OSError:
        return False, "connection refused or unreachable"


def _get_lan_ips() -> list[str]:
    ips: list[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip.startswith(("192.168.", "10.", "172.")):
                ips.append(ip)
    except Exception:
        pass
    if not ips:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ips.append(s.getsockname()[0])
            s.close()
        except Exception:
            pass
    return list(dict.fromkeys(ips))


def _detect_proxy() -> dict:
    """環境変数ベースのプロキシ検出"""
    found: dict[str, str] = {}
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        val = os.environ.get(key)
        if val:
            found[key] = val
    return found


def _classify_environment(
    tcp_443: bool,
    tcp_80: bool,
    proxy: dict,
) -> str:
    """miasma-protocol NetworkCapabilities.classify() に対応する環境分類"""
    if proxy:
        return ENV_CORP_PROXY
    if not tcp_443 and not tcp_80:
        return ENV_FILTERED
    if not tcp_443 and tcp_80:
        return ENV_FILTERED
    return ENV_OPEN


def _transport_recommendations(env: str, proxy: dict, lan_ips: list) -> list[str]:
    """
    miasma-protocol transport ladder に対応する推奨アクション。
    優先順位:
      1. localhost bridge（常に有効）
      2. 同一 LAN 直接接続（LAN IP があれば）
      3. WSS/TLS 443（外部接続可能なら）
      4. HTTP CONNECT proxy 経由 WSS（プロキシが検出されたら）
      5. relay / Dev Tunnel（フォールバック）
    """
    recs: list[str] = []
    recs.append("✅ localhost bridge: 常時利用可能（同一PC）")
    if lan_ips:
        recs.append(f"✅ 同一LAN接続: {', '.join(lan_ips)} でアクセス可能")
    else:
        recs.append("⚠️ 同一LAN接続: LAN IPが取得できません")

    if env == ENV_OPEN:
        recs.append("✅ WSS/443: 外部接続可能")
    elif env == ENV_CORP_PROXY:
        proxy_types = list(proxy.keys())
        recs.append(f"⚠️ プロキシ検出: {', '.join(proxy_types)}")
        recs.append("→ HTTP CONNECT proxy 経由でWSS接続を試みてください")
    elif env == ENV_FILTERED:
        recs.append("❌ 外部TCP接続が制限されています")
        recs.append("→ LAN内共有またはDev Tunnel / Tailnetを使用してください")

    recs.append("ℹ️ フォールバック: Dev Tunnel / Tailnet（PoC向け）")
    return recs


# ─── エンドポイント ───────────────────────────────────────────────────────────

@router.get("/network/diagnostics")
async def network_diagnostics(request: Request):
    # hostname / OS バージョン / LAN IP 等を含むため admin/analyst のみ。
    from backend.utils.auth import require_admin_or_analyst
    require_admin_or_analyst(request)
    """
    Q-002/Q-008: ネットワーク環境診断

    miasma-protocol の hostile environment classification に対応。
    接続失敗を「原因不明」にしないための診断レポートを返す。
    """
    start_ms = time.monotonic() * 1000

    # 並列 TCP プローブ（外部 Google DNS 8.8.8.8 を使用）
    tcp_443_result, tcp_80_result = await asyncio.gather(
        _probe_tcp("8.8.8.8", 443),
        _probe_tcp("8.8.8.8", 80),
    )
    tcp_443, tcp_443_err = tcp_443_result
    tcp_80, tcp_80_err = tcp_80_result

    # localhost bridge 自己チェック
    settings = _get_settings()
    local_ok, local_err = await _probe_tcp("127.0.0.1", settings.API_PORT, timeout=1.0)

    # プロキシ検出
    proxy = _detect_proxy()

    # LAN IP
    lan_ips = _get_lan_ips()

    # 環境分類
    env = _classify_environment(tcp_443, tcp_80, proxy)

    # 推奨アクション
    recommendations = _transport_recommendations(env, proxy, lan_ips)

    elapsed = time.monotonic() * 1000 - start_ms

    return {
        "success": True,
        "data": {
            # miasma-protocol NetworkEnvironment に対応
            "environment": env,
            "capabilities": {
                "tcp_443": {"ok": tcp_443, "error": tcp_443_err},
                "tcp_80":  {"ok": tcp_80,  "error": tcp_80_err},
                "localhost_bridge": {"ok": local_ok, "error": local_err},
                "proxy_detected": bool(proxy),
                "proxy_env_vars": proxy,
            },
            "lan": {
                "lan_ips": lan_ips,
                "lan_mode_enabled": settings.LAN_MODE,
                "api_port": settings.API_PORT,
                "accessible": settings.LAN_MODE and bool(lan_ips),
            },
            "platform": {
                "os": platform.system(),
                "version": platform.version(),
                "hostname": socket.gethostname(),
            },
            # transport ladder 推奨（miasma-protocol の fallback ladder 思想）
            "transport_ladder": recommendations,
            "probe_duration_ms": round(elapsed),
        },
    }


@router.post("/network/lan-mode")
def toggle_lan_mode(enable: bool):
    """
    LAN 共有モードの有効/無効を切替。
    ※ uvicorn の bind アドレスは起動時に決まるため、実際の効果は次回起動時。
       本エンドポイントは設定フラグの更新のみ行う。
    """
    # .env.development に書き込む（次回起動時に有効）
    # config.py が読む env_file と同じパスに書く（CWD=shuttlescope/ を前提）
    import pathlib
    env_file = pathlib.Path(__file__).resolve().parent.parent.parent / ".env.development"
    lines: list[str] = []
    if env_file.exists():
        lines = env_file.read_text(encoding="utf-8").splitlines()

    key = "LAN_MODE"
    value = "true" if enable else "false"
    found = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}")

    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # メモリ上の設定値も即時反映（再起動なしでトグル状態を UI に返す）
    _get_settings().LAN_MODE = enable

    return {
        "success": True,
        "data": {
            "lan_mode": enable,
            "note": "設定を更新しました",
        },
    }
