"""ShuttleScope FastAPI メインアプリケーション"""
import sys
import os

# `python backend/main.py` で直接実行された場合でも
# shuttlescope/ をルートとしてimportできるようパスを追加
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

import asyncio
import logging
import uvicorn
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import FastAPI, Query, WebSocket

logger = logging.getLogger(__name__)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from backend.config import settings as app_settings
from backend.db.database import engine, get_db, bootstrap_database
from backend.routers import matches, rallies, strokes, players, analysis, reports, sets, tracknet
from backend.routers import settings as settings_router
from backend.routers import sessions, comments, bookmarks, network_diag, warmup
from backend.routers import prediction, tunnel
from backend.routers import human_forecast
from backend.routers import sync as sync_router
from backend.routers import yolo
from backend.routers import cv_candidates
from backend.utils.video_downloader import video_downloader

# React renderer ビルド出力パス（Electron / ブラウザ共用）
_RENDERER_DIR = Path(__file__).resolve().parent.parent / "out" / "renderer"


async def _stale_device_cleanup():
    """60 秒以上ハートビートがないデバイスを is_connected=False にする（30 秒ごと）"""
    from backend.db.database import SessionLocal
    from backend.db.models import SessionParticipant
    while True:
        await asyncio.sleep(30)
        try:
            db = SessionLocal()
            cutoff = datetime.utcnow() - timedelta(seconds=60)
            stale = (
                db.query(SessionParticipant)
                .filter(
                    SessionParticipant.is_connected.is_(True),
                    SessionParticipant.last_heartbeat.isnot(None),
                    SessionParticipant.last_heartbeat < cutoff,
                )
                .all()
            )
            for p in stale:
                p.is_connected = False
                logger.debug("stale device disconnected: participant_id=%d", p.id)
            if stale:
                db.commit()
            db.close()
        except Exception as exc:
            logger.warning("stale cleanup error: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """アプリ起動時にテーブル作成 + stale cleanup タスク開始"""
    try:
        loop = asyncio.get_event_loop()
        await asyncio.wait_for(
            loop.run_in_executor(None, lambda: bootstrap_database(engine, app_settings.DATABASE_URL)),
            timeout=30.0,
        )
    except asyncio.TimeoutError:
        logger.warning("bootstrap_database がタイムアウト（30s）— 起動を続行します")
    except Exception as exc:
        logger.warning("bootstrap_database エラー: %s — 起動を続行します", exc)
    cleanup_task = asyncio.create_task(_stale_device_cleanup())
    yield
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass


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
app.include_router(settings_router.router, prefix="/api")
app.include_router(tracknet.router, prefix="/api")
app.include_router(yolo.router, prefix="/api")
# CV補助アノテーション候補
app.include_router(cv_candidates.router, prefix="/api")
# R-001/R-002: 共有セッション
app.include_router(sessions.router, prefix="/api")
# S-003: コメント
app.include_router(comments.router, prefix="/api")
# U-001: ブックマーク
app.include_router(bookmarks.router, prefix="/api")
# Q-002/Q-008: ネットワーク診断
app.include_router(network_diag.router, prefix="/api")
# G3: ウォームアップ観察
app.include_router(warmup.router, prefix="/api")
# 予測エンジン (Phase A+B)
app.include_router(prediction.router, prefix="/api")
# Cloudflare Tunnel 管理
app.include_router(tunnel.router, prefix="/api")
# Phase S2: ヒューマンベンチマーク
app.include_router(human_forecast.router, prefix="/api")
# データ同期（Export / Import / Backup）
app.include_router(sync_router.router, prefix="/api")



@app.get("/api/health")
async def health():
    """ヘルスチェック（Electron起動確認用）"""
    return {"status": "ok", "version": "1.0.0"}


# ─── S-001: WebSocket ライブフィード ─────────────────────────────────────────

@app.websocket("/ws/live/{session_code}")
async def ws_live(session_code: str, websocket: WebSocket):
    """コーチ / ビューワーがリアルタイムでスコア・ラリー情報を受け取る WS エンドポイント"""
    from backend.ws.live import ws_live_handler
    db = next(get_db())
    try:
        await ws_live_handler(session_code, websocket, db)
    finally:
        db.close()


# ─── LAN カメラ: WebRTC シグナリング WS ──────────────────────────────────────

@app.websocket("/ws/camera/{session_code}")
async def ws_camera(
    session_code: str,
    websocket: WebSocket,
    role: str = Query(default=None),
    participant_id: str = Query(default=None),
    viewer_id: str = Query(default=None),
):
    """WebRTC シグナリング中継エンドポイント
    ?role=operator               → PC オペレーター
    ?role=viewer&viewer_id={id}  → ビューワーデバイス（他PC / タブレット）
    ?participant_id={id}         → iOS / タブレット 送信デバイス
    """
    from backend.ws.camera import ws_camera_handler
    await ws_camera_handler(
        session_code, websocket,
        role=role, participant_id=participant_id, viewer_id=viewer_id,
    )


# ─── S-001: コーチビュー HTML（LAN ブラウザ向けスタンドアロンページ） ──────────

_COACH_HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ShuttleScope コーチビュー</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0f172a; color: #f1f5f9; font-family: system-ui, -apple-system, sans-serif; min-height: 100vh; }
  .header { background: #1e293b; border-bottom: 1px solid #334155; padding: 12px 20px; display: flex; align-items: center; gap: 12px; }
  .header h1 { font-size: 1.1rem; font-weight: 700; }
  .status-dot { width: 8px; height: 8px; border-radius: 50%; background: #64748b; flex-shrink: 0; }
  .status-dot.connected { background: #22c55e; animation: pulse 2s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.5} }
  .session-code { font-size: 0.75rem; color: #94a3b8; margin-left: auto; }
  .main { padding: 20px; max-width: 600px; margin: 0 auto; }
  .score-card { background: #1e293b; border-radius: 12px; padding: 24px; margin-bottom: 16px; text-align: center; }
  .score-row { display: flex; align-items: center; justify-content: center; gap: 24px; margin-bottom: 12px; }
  .score-val { font-size: 3.5rem; font-weight: 800; line-height: 1; }
  .score-sep { font-size: 2rem; color: #475569; font-weight: 300; }
  .player-label { font-size: 0.8rem; color: #94a3b8; margin-top: 4px; }
  .set-badges { display: flex; gap: 8px; justify-content: center; flex-wrap: wrap; margin-top: 12px; }
  .set-badge { background: #0f172a; border-radius: 6px; padding: 4px 10px; font-size: 0.75rem; color: #94a3b8; }
  .set-badge.win { color: #60a5fa; border: 1px solid #3b82f6; }
  .section-title { font-size: 0.75rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: #64748b; margin-bottom: 8px; }
  .rally-list { background: #1e293b; border-radius: 12px; overflow: hidden; }
  .rally-item { display: flex; align-items: center; gap: 12px; padding: 10px 16px; border-bottom: 1px solid #0f172a; font-size: 0.85rem; }
  .rally-item:last-child { border-bottom: none; }
  .rally-num { color: #64748b; width: 28px; flex-shrink: 0; }
  .rally-score { font-weight: 600; color: #e2e8f0; }
  .rally-winner { width: 20px; height: 20px; border-radius: 50%; background: #3b82f6; display: flex; align-items: center; justify-content: center; font-size: 0.6rem; font-weight: 700; flex-shrink: 0; }
  .rally-winner.b { background: #f59e0b; }
  .rally-end { color: #94a3b8; font-size: 0.75rem; margin-left: auto; }
  .progress-bar { height: 4px; background: #0f172a; border-radius: 2px; overflow: hidden; margin-top: 12px; }
  .progress-fill { height: 100%; background: #3b82f6; transition: width 0.5s; }
  .empty { text-align: center; color: #475569; padding: 32px; font-size: 0.9rem; }
  .error-banner { background: #7f1d1d; color: #fca5a5; padding: 10px 16px; border-radius: 8px; font-size: 0.85rem; margin-bottom: 12px; }
  .participants { font-size: 0.75rem; color: #64748b; text-align: center; margin-top: 8px; }
</style>
</head>
<body>
<div class="header">
  <div class="status-dot" id="statusDot"></div>
  <h1>ShuttleScope コーチビュー</h1>
  <span class="session-code" id="sessionCodeLabel"></span>
</div>
<div class="main">
  <div id="errorBanner" class="error-banner" style="display:none"></div>
  <div class="score-card">
    <div class="score-row">
      <div>
        <div class="score-val" id="scoreA">-</div>
        <div class="player-label" id="playerALabel">A</div>
      </div>
      <div class="score-sep">:</div>
      <div>
        <div class="score-val" id="scoreB">-</div>
        <div class="player-label" id="playerBLabel">B</div>
      </div>
    </div>
    <div class="set-badges" id="setBadges"></div>
    <div class="progress-bar"><div class="progress-fill" id="progressFill" style="width:0%"></div></div>
    <div class="participants" id="participantsLabel"></div>
  </div>
  <div class="section-title">直近ラリー</div>
  <div class="rally-list" id="rallyList"><div class="empty">データ待機中…</div></div>
</div>
<script>
const SESSION_CODE = location.pathname.split('/coach/')[1] || '';
const API_BASE = location.origin;
document.getElementById('sessionCodeLabel').textContent = 'セッション: ' + SESSION_CODE;

let scoreA = '-', scoreB = '-';

function setDot(connected) {
  document.getElementById('statusDot').className = 'status-dot' + (connected ? ' connected' : '');
}

function renderSnapshot(data) {
  const sets = data.set_scores || [];
  if (sets.length > 0) {
    const latest = sets[sets.length - 1];
    document.getElementById('scoreA').textContent = latest.score_a;
    document.getElementById('scoreB').textContent = latest.score_b;
  }
  const badges = document.getElementById('setBadges');
  badges.innerHTML = sets.slice(0, -1).map(s =>
    `<span class="set-badge ${s.winner ? 'win' : ''}">${s.set_num}セット ${s.score_a}-${s.score_b}</span>`
  ).join('');
  const progress = Math.round((data.annotation_progress || 0) * 100);
  document.getElementById('progressFill').style.width = progress + '%';
  const pc = data.participants || 0;
  document.getElementById('participantsLabel').textContent = pc + ' 名が接続中';
  renderRallies(data.recent_rallies || []);
}

function renderRallies(rallies) {
  const el = document.getElementById('rallyList');
  if (!rallies.length) { el.innerHTML = '<div class="empty">ラリーなし</div>'; return; }
  el.innerHTML = rallies.map(r => {
    const isA = r.winner === 'player_a';
    return `<div class="rally-item">
      <span class="rally-num">#${r.rally_num}</span>
      <div class="rally-winner ${isA ? 'a' : 'b'}">${isA ? 'A' : 'B'}</div>
      <span class="rally-score">${r.score_a} : ${r.score_b}</span>
      <span class="rally-end">${r.end_type || ''} / ${r.rally_length}球</span>
    </div>`;
  }).join('');
}

function appendRally(data) {
  const el = document.getElementById('rallyList');
  if (el.querySelector('.empty')) el.innerHTML = '';
  const isA = data.winner === 'player_a';
  const div = document.createElement('div');
  div.className = 'rally-item';
  div.innerHTML = `<span class="rally-num">#${data.rally_num}</span>
    <div class="rally-winner ${isA ? 'a' : 'b'}">${isA ? 'A' : 'B'}</div>
    <span class="rally-score">${data.score_a} : ${data.score_b}</span>
    <span class="rally-end">${data.end_type || ''} / ${data.rally_length}球</span>`;
  el.insertBefore(div, el.firstChild);
  while (el.children.length > 8) el.removeChild(el.lastChild);
  document.getElementById('scoreA').textContent = data.score_a;
  document.getElementById('scoreB').textContent = data.score_b;
}

// 初期スナップショットを REST で取得
fetch(API_BASE + '/api/sessions/' + SESSION_CODE + '/state')
  .then(r => r.json())
  .then(res => { if (res.success) renderSnapshot(res.data); })
  .catch(() => {});

// WebSocket 接続
function connectWS() {
  const wsProto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(wsProto + '://' + location.host + '/ws/live/' + SESSION_CODE);
  ws.onopen = () => setDot(true);
  ws.onclose = () => { setDot(false); setTimeout(connectWS, 3000); };
  ws.onerror = () => setDot(false);
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'snapshot') { renderSnapshot(msg.data); }
    else if (msg.type === 'rally_saved') { appendRally(msg.data); }
    else if (msg.type === 'comment') {
      // コメントはシンプルにトースト表示
      const d = msg.data;
      if (d.is_flagged) {
        const banner = document.getElementById('errorBanner');
        banner.style.display = 'block';
        banner.textContent = '⚑ ' + (d.author_role === 'coach' ? 'コーチ' : 'アナリスト') + ': ' + d.text;
        setTimeout(() => { banner.style.display = 'none'; }, 8000);
      }
    }
    else if (msg.type === 'ping') { ws.send(JSON.stringify({type:'ping'})); }
  };
}
connectWS();
</script>
</body>
</html>"""


@app.get("/coach/{session_code}", response_class=HTMLResponse)
async def coach_view(session_code: str):
    """S-001: コーチビュー HTML ページ（後方互換、フル React アプリへ誘導）"""
    # React SPA が利用可能な場合はリダイレクト
    if _RENDERER_DIR.exists():
        return HTMLResponse(
            content=f'<meta http-equiv="refresh" content="0; url=/#/"><script>location.replace("/#/");</script>',
            status_code=302,
        )
    return HTMLResponse(content=_COACH_HTML)


@app.get("/api/system/capabilities")
async def system_capabilities():
    """動作環境の依存ツール可用性を返す（フロントエンド向け）
    - yt_dlp: ダウンロード機能が使えるか
    - ffmpeg: 高画質マージダウンロードが使えるか（未インストール時は低画質フォールバック）
    """
    caps = video_downloader.get_capabilities()
    return {"success": True, "data": caps}


@app.get("/api/version")
async def version():
    """バージョン情報"""
    return {"version": "1.0.0", "environment": app_settings.ENVIRONMENT}


# ─── React SPA 配信（LAN / トンネルブラウザアクセス用）───────────────────────
# out/renderer/ が存在するとき（npm run build 後）に assets をマウント。
# HashRouter 使用のため / を常に返せば全クライアントサイドルートが動作する。
_assets_dir = _RENDERER_DIR / "assets"
if _assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="renderer-assets")

_INDEX_HTML = _RENDERER_DIR / "index.html"

_FALLBACK_HTML = """<!DOCTYPE html>
<html lang="ja">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ShuttleScope</title>
<style>
  body{font-family:system-ui,sans-serif;background:#0f172a;color:#f1f5f9;
       display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;}
  .card{background:#1e293b;border-radius:12px;padding:32px 40px;text-align:center;max-width:400px;}
  h1{font-size:1.4rem;margin-bottom:8px;}
  p{color:#94a3b8;font-size:.9rem;line-height:1.6;}
  code{background:#0f172a;padding:2px 6px;border-radius:4px;font-size:.85rem;color:#60a5fa;}
</style>
</head>
<body>
<div class="card">
  <h1>ShuttleScope</h1>
  <p>バックエンドは起動しています。<br>
  フロントエンドを配信するには一度ビルドが必要です。</p>
  <p style="margin-top:12px;"><code>npm run build</code><br>
  <span style="font-size:.8rem;color:#64748b;">実行後に再起動してください</span></p>
</div>
</body>
</html>"""


@app.get("/")
async def spa_root():
    """React SPA エントリポイント（ブラウザ / LAN / トンネルアクセス用）"""
    if _INDEX_HTML.exists():
        return FileResponse(str(_INDEX_HTML))
    return HTMLResponse(content=_FALLBACK_HTML)


@app.get("/index.html")
async def spa_index():
    if _INDEX_HTML.exists():
        return FileResponse(str(_INDEX_HTML))
    return HTMLResponse(content=_FALLBACK_HTML)


if __name__ == "__main__":
    # R-002: LAN_MODE=true のとき 0.0.0.0 でバインドして LAN 内からアクセス可能にする
    host = "0.0.0.0" if app_settings.LAN_MODE else "127.0.0.1"
    uvicorn.run(
        "backend.main:app",
        host=host,
        port=app_settings.API_PORT,
        reload=app_settings.ENVIRONMENT == "development",
        log_level="info",
    )
