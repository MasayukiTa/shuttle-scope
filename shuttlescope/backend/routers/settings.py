"""アプリ設定API（/api/settings）
シンプルなキーバリューストア。SQLite にJSONで永続化。
TrackNet設定など再起動後も保持すべき設定に使用。
"""
import json
import socket
import uuid as _uuid_mod
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.db import database as _db_module
from backend.db.database import get_db
from backend.utils.auth import require_analyst, get_auth

router = APIRouter()

# 機密扱いの設定キー。admin / analyst 以外には値を返さない。
# (ngrok/TURN 認証情報、Webhook URL 等が player / coach の画面で参照できると
#  アカウント情報漏洩・SSRF 原資になる)
_SENSITIVE_SETTING_KEYS = {
    "ngrok_authtoken",
    "turn_credential",
    "turn_username",
    "turn_url",
    "ss_notify_webhook_url",
}


def _redact_sensitive(data: dict, ctx) -> dict:
    """admin / analyst 以外には機密キーを隠す（空文字に差し替え）"""
    if ctx.is_admin or ctx.is_analyst:
        return data
    redacted = dict(data)
    for k in _SENSITIVE_SETTING_KEYS:
        if k in redacted and redacted[k]:
            redacted[k] = ""
    return redacted


# 設定テーブル DDL（app_settings）。import 時に engine を固定してしまうと、
# テスト用に db_module.engine を差し替えた場合に別 DB 上でテーブル作成してしまい
# 本来の操作先で "no such table" となる。そのため各リクエストで現在の engine を
# 参照しつつ CREATE TABLE IF NOT EXISTS を冪等に実行する。
def _ensure_settings_table(db: Session) -> None:
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """))
    db.commit()

def _default_device_id() -> str:
    """ホスト名 + UUID ショートを組み合わせたデバイス識別子"""
    hostname = socket.gethostname()
    short_uuid = str(_uuid_mod.uuid4())[:8]
    return f"{hostname}-{short_uuid}"


# デフォルト設定
DEFAULT_SETTINGS: dict = {
    "tracknet_enabled": True,
    "tracknet_backend": "auto",       # auto | cuda | onnx_cuda | directml | tensorflow_cpu | openvino | onnx_cpu
    "tracknet_mode": "batch",          # batch | assist
    "tracknet_max_cpu_pct": 50,
    # ─── GPU / デバイス設定 ───────────────────────────────────────────────────
    "cuda_device_index": 0,           # CUDA デバイス番号（0 = 最初の GPU）
    "openvino_device": "GPU",          # OpenVINO ターゲットデバイス（GPU / GPU.1 / CPU）
    "yolo_backend": "auto",            # auto | openvino | ultralytics | onnx_cpu
    # ─── CV 解析レート設定 ────────────────────────────────────────────────────
    # YOLO: リアルタイム・バッチそれぞれの解析フレームレート（60fps 動画想定）
    "yolo_realtime_fps": 10,          # リアルタイム解析レート（fps）
    "yolo_batch_fps": 30,             # バッチ解析レート（fps）
    # TrackNet: シャトル軌跡密度（step = 1 / fps 秒）
    "tracknet_realtime_fps": 2,       # リアルタイム軌跡密度（fps）
    "tracknet_batch_fps": 10,         # バッチ軌跡密度（fps）
    "yolo_enabled": True,               # YOLO プレイヤー検出
    "video_source_mode": "local",      # local | webview | none
    # データ同期設定
    "sync_device_id": "",              # 空のときは初回起動時に自動生成
    "sync_folder_path": "",            # クラウドフォルダパス（OneDrive 等）
    # リモートトンネル設定
    "tunnel_provider": "auto",         # auto | cloudflare | ngrok
    "ngrok_authtoken": "",             # ngrok 認証トークン（3.x 以降必須）
    # リモート映像（WebRTC）設定
    "video_transport": "off",          # off | webrtc
    "turn_enabled": False,             # TURN リレー有効化
    "turn_url": "",                    # turn:your-server.example.com:3478
    "turn_username": "",               # TURN ユーザー名
    "turn_credential": "",             # TURN パスワード
}


class SettingsUpdate(BaseModel):
    settings: dict


def _load_all(db: Session) -> dict:
    rows = db.execute(text("SELECT key, value FROM app_settings")).fetchall()
    result = dict(DEFAULT_SETTINGS)
    for key, value in rows:
        try:
            result[key] = json.loads(value)
        except Exception:
            result[key] = value
    return result


@router.get("/settings")
def get_settings(request: Request, db: Session = Depends(get_db)):
    """全設定を返す（未設定キーはデフォルト値）。

    機密キー（認証情報・Webhook URL 等）は admin / analyst 以外には
    空文字で返す（値の存在自体は DEFAULT_SETTINGS で公開されるが、
    実値は漏らさない）。設定値そのものはアプリ内部構成情報 (sync_device_id,
    tracknet_backend 等) を含むため player ロールには一切返さない。
    """
    from backend.utils.auth import require_non_player
    require_non_player(request)
    ctx = get_auth(request)
    _ensure_settings_table(db)
    data = _load_all(db)
    # sync_device_id が未設定なら自動生成して永続化
    if not data.get("sync_device_id"):
        new_id = _default_device_id()
        db.execute(
            text("INSERT OR REPLACE INTO app_settings(key, value) VALUES(:k, :v)"),
            {"k": "sync_device_id", "v": json.dumps(new_id)},
        )
        db.commit()
        data["sync_device_id"] = new_id
    return {"success": True, "data": _redact_sensitive(data, ctx)}


@router.put("/settings")
def update_settings(
    body: SettingsUpdate,
    db: Session = Depends(get_db),
    _ctx=Depends(require_analyst),
):
    """設定を部分更新（指定したキーのみ上書き）"""
    _ensure_settings_table(db)
    for key, value in body.settings.items():
        db.execute(
            text("INSERT OR REPLACE INTO app_settings(key, value) VALUES(:k, :v)"),
            {"k": key, "v": json.dumps(value)},
        )
    db.commit()
    return {"success": True, "data": _load_all(db)}


@router.get("/settings/devices")
def get_devices(request: Request):
    """利用可能なコンピュートデバイス一覧を返す。

    GPU/CPU 型番・ドライババージョン・VRAM が含まれるため admin/analyst 限定。
    """
    from backend.utils.auth import require_admin_or_analyst
    require_admin_or_analyst(request)
    cuda_devices = []
    try:
        import torch
        if torch.cuda.is_available():
            for i in range(torch.cuda.device_count()):
                props = torch.cuda.get_device_properties(i)
                cuda_devices.append({
                    "index": i,
                    "name": props.name,
                    "vram_mb": props.total_memory // (1024 * 1024),
                })
    except Exception:
        pass

    openvino_devices: list[str] = []
    try:
        import openvino as ov
        core = ov.Core()
        openvino_devices = list(core.available_devices)
    except Exception:
        pass

    onnx_providers: list[str] = []
    try:
        import onnxruntime as ort
        onnx_providers = list(ort.get_available_providers())
    except Exception:
        pass

    return {
        "success": True,
        "cuda_devices": cuda_devices,
        "openvino_devices": openvino_devices,
        "onnx_providers": onnx_providers,
    }
