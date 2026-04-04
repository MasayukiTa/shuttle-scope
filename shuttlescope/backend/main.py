"""ShuttleScope FastAPI メインアプリケーション"""
import sys
import os

# `python backend/main.py` で直接実行された場合でも
# shuttlescope/ をルートとしてimportできるようパスを追加
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.db.database import create_tables
from backend.routers import matches, rallies, strokes, players, analysis, reports, sets


@asynccontextmanager
async def lifespan(app: FastAPI):
    """アプリ起動時にテーブル作成"""
    create_tables()
    yield


app = FastAPI(
    title="ShuttleScope API",
    version="1.0.0",
    description="バドミントン動画アノテーション・解析API",
    lifespan=lifespan,
)

# CORS設定（ElectronのRenderer Processからのリクエストを許可）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ルーター登録
app.include_router(players.router, prefix="/api")
app.include_router(matches.router, prefix="/api")
app.include_router(rallies.router, prefix="/api")
app.include_router(strokes.router, prefix="/api")
app.include_router(sets.router, prefix="/api")
app.include_router(analysis.router, prefix="/api")
app.include_router(reports.router, prefix="/api")



@app.get("/api/health")
async def health():
    """ヘルスチェック（Electron起動確認用）"""
    return {"status": "ok", "version": "1.0.0"}


@app.get("/api/version")
async def version():
    """バージョン情報"""
    return {"version": "1.0.0", "environment": settings.ENVIRONMENT}


if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host="127.0.0.1",
        port=settings.API_PORT,
        reload=settings.ENVIRONMENT == "development",
        log_level="info",
    )
