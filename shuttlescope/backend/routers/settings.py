"""アプリ設定API（/api/settings）
シンプルなキーバリューストア。SQLite にJSONで永続化。
TrackNet設定など再起動後も保持すべき設定に使用。
"""
import json
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.db.database import get_db, engine

router = APIRouter()

# 設定テーブルを初回起動時に作成（add_columns_if_missing とは別に管理）
def create_settings_table():
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """))
        conn.commit()

create_settings_table()

# デフォルト設定
DEFAULT_SETTINGS: dict = {
    "tracknet_enabled": False,
    "tracknet_backend": "openvino",   # openvino | onnx_cpu
    "tracknet_mode": "batch",          # batch | assist
    "tracknet_max_cpu_pct": 50,
    "video_source_mode": "local",      # local | webview | none
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
def get_settings(db: Session = Depends(get_db)):
    """全設定を返す（未設定キーはデフォルト値）"""
    return {"success": True, "data": _load_all(db)}


@router.put("/settings")
def update_settings(body: SettingsUpdate, db: Session = Depends(get_db)):
    """設定を部分更新（指定したキーのみ上書き）"""
    for key, value in body.settings.items():
        db.execute(
            text("INSERT OR REPLACE INTO app_settings(key, value) VALUES(:k, :v)"),
            {"k": key, "v": json.dumps(value)},
        )
    db.commit()
    return {"success": True, "data": _load_all(db)}
