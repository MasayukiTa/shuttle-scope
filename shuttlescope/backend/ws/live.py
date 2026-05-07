"""S-001: WebSocket ライブフィード — コーチ配信モード

セッションコードをキーにして、接続中のコーチ / ビューワーへリアルタイムで
スコア・ラリー情報をブロードキャストする。

設計方針（miasma-protocol の broadcaster 思想を参考）:
- ConnectionManager はインメモリシングルトン
- 同一セッションコードに複数 WebSocket を束ねる
- ルーター側から broadcast_to_match() を呼ぶだけで全接続へ配信
- 切断時は自動除去（例外 catch で dead socket を drop）
"""
import asyncio
import json as _json
import logging
import time as _time
from datetime import datetime
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

# ─── DoS 対策上限 ────────────────────────────────────────────────────────────
# 受信メッセージは ping/pong/role 通知のみ想定なので 4 KB あれば十分。
# 攻撃者が巨大 JSON を送り込んでサーバメモリを膨らませる経路を遮断する。
_MAX_WS_MESSAGE_BYTES = 4 * 1024
# 1 接続あたりの 1 秒間メッセージ流量 (受信側 flood DoS 対策)。
_MAX_WS_MESSAGES_PER_SEC = 30


class ConnectionManager:
    """セッションコード → WebSocket 接続リスト のインメモリ管理"""

    # T-9 (round124): 1 セッションあたりの最大接続数 (memory bloat 防止)
    MAX_CONN_PER_SESSION = 20

    def __init__(self):
        # { session_code: [WebSocket, ...] }
        self._connections: dict[str, list[WebSocket]] = {}
        # T-9 (round124): cap check の race を防ぐ per-session lock
        self._cap_locks: dict[str, "asyncio.Lock"] = {}
        # ws #1 fix: per-WebSocket send lock。
        # Starlette の send channel は concurrent-sender 非安全 (`RuntimeError:
        # Unexpected ASGI message`)。broadcaster と receive loop が同一 WS に
        # send_* を並行 await すると稀に発火してクライアントが silent drop される。
        # send 系は必ずこの lock 経由で直列化する。
        self._send_locks: dict[int, "asyncio.Lock"] = {}

    def _lock(self, session_code: str) -> "asyncio.Lock":
        import asyncio as _aio
        if session_code not in self._cap_locks:
            self._cap_locks[session_code] = _aio.Lock()
        return self._cap_locks[session_code]

    def _send_lock(self, ws: WebSocket) -> "asyncio.Lock":
        import asyncio as _aio
        key = id(ws)
        lk = self._send_locks.get(key)
        if lk is None:
            lk = _aio.Lock()
            self._send_locks[key] = lk
        return lk

    async def safe_send_json(self, ws: WebSocket, message: dict[str, Any]) -> bool:
        """concurrent-sender 安全な send_json。失敗時は False。"""
        lk = self._send_lock(ws)
        async with lk:
            try:
                await ws.send_json(message)
                return True
            except Exception:
                return False

    async def connect(self, session_code: str, ws: WebSocket) -> None:
        async with self._lock(session_code):
            existing = len(self._connections.get(session_code, []))
            if existing >= self.MAX_CONN_PER_SESSION:
                # 上限超過: accept 前に close (1013 = try again later)
                await ws.close(code=1013, reason="too many connections for this session")
                logger.warning("WS reject: session=%s exceeds max %d",
                               session_code, self.MAX_CONN_PER_SESSION)
                return
            await ws.accept()
            self._connections.setdefault(session_code, []).append(ws)
        logger.info("WS connected: session=%s total=%d", session_code,
                    len(self._connections[session_code]))

    def disconnect(self, session_code: str, ws: WebSocket) -> None:
        conns = self._connections.get(session_code, [])
        if ws in conns:
            conns.remove(ws)
        if not conns:
            self._connections.pop(session_code, None)
            # session 単位 lock も解放 (ws #7 fix: _cap_locks リーク対策)
            self._cap_locks.pop(session_code, None)
        # ws #7 fix: per-WS send lock も解放
        self._send_locks.pop(id(ws), None)
        logger.info("WS disconnected: session=%s", session_code)

    def connection_count(self, session_code: str) -> int:
        # ws #8 fix: dict 参照を 1 度に抑えてロック外 KeyError 競合を避ける。
        # 旧コードは len(self._connections[session_code]) で `[session_code]` を直接
        # アクセスしていたため、別タスクが pop した瞬間に KeyError が起きていた。
        return len(self._connections.get(session_code) or [])

    async def broadcast(self, session_code: str, message: dict[str, Any]) -> None:
        # rereview ws N4 fix: 旧コードは逐次 await で 1 台の遅いクライアントが
        # 全クライアントへの配信を直列ブロックしていた。asyncio.gather で並行化し
        # broadcaster の DB session 保持時間も短縮する (broadcast_to_match からの呼出)。
        targets = list(self._connections.get(session_code, []))
        if not targets:
            return
        results = await asyncio.gather(
            *(self.safe_send_json(ws, message) for ws in targets),
            return_exceptions=True,
        )
        for ws, ok in zip(targets, results):
            if ok is True:
                continue
            self.disconnect(session_code, ws)

    async def broadcast_to_match(self, match_id: int, message: dict[str, Any], db=None) -> None:
        """match_id に紐づくアクティブセッションへ一括ブロードキャスト。

        ws #2 fix: 旧コードは ensure_future で渡された request-scoped DB session に
        対し finally で close 済の状態で commit を試み ResourceClosedError を握りつぶし、
        last_broadcast_at が永久に更新されなかった。
        独立した SessionLocal を都度開いて完結させる (db 引数は後方互換のため受けるが
        参照しない)。
        """
        from backend.db.database import SessionLocal
        from backend.db.models import SharedSession
        with SessionLocal() as own_db:
            sessions = (
                own_db.query(SharedSession)
                .filter(SharedSession.match_id == match_id, SharedSession.is_active.is_(True))
                .all()
            )
            for s in sessions:
                await self.broadcast(s.session_code, message)
                s.last_broadcast_at = datetime.utcnow()
            if sessions:
                try:
                    own_db.commit()
                except Exception:
                    own_db.rollback()
                    logger.exception("broadcast_to_match commit failed match_id=%d", match_id)


# モジュールレベルシングルトン
manager = ConnectionManager()


# ─── WebSocket エンドポイントハンドラ ────────────────────────────────────────

async def ws_live_handler(session_code: str, websocket: WebSocket, db) -> None:
    """
    GET /ws/live/{session_code}

    コーチ / ビューワーがセッションコードで接続する。
    接続直後に現在セッション状態（スコア・直近ラリー）を送信し、
    その後はアナリストが保存するたびにブロードキャストを受け取る。
    """
    from backend.db.models import SharedSession, Match, GameSet, Rally

    # セッション存在確認
    session = (
        db.query(SharedSession)
        .filter(SharedSession.session_code == session_code, SharedSession.is_active.is_(True))
        .first()
    )
    if not session:
        await websocket.close(code=4404, reason="セッションが存在しないか終了しています")
        return

    await manager.connect(session_code, websocket)
    # T-9 (round124): connect 上限超過時は接続が close されているので即終了
    if websocket not in manager._connections.get(session_code, []):
        return

    # 受信メッセージ数のバースト制限カウンタ (1 秒窓)
    _msg_window_start = _time.monotonic()
    _msg_count = 0

    try:
        # 接続直後: 現在スナップショットを送信
        snapshot = _build_session_snapshot(session, db)
        await manager.safe_send_json(websocket, {"type": "snapshot", "data": snapshot})

        # keepalive ループ（ping / 切断検知）
        while True:
            try:
                # 受信は text として読み出してサイズチェック → 自前で JSON parse する。
                # WebSocket.receive_json() は内部で全文をバッファするため、巨大 frame を
                # 投げられるとメモリを食い尽くす経路がある (CWE-770)。
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                if len(raw) > _MAX_WS_MESSAGE_BYTES:
                    logger.warning("WS oversized message session=%s len=%d", session_code, len(raw))
                    await websocket.close(code=1009, reason="message too large")
                    return
                # 受信レート制限 (flood DoS 対策)
                now = _time.monotonic()
                if now - _msg_window_start >= 1.0:
                    _msg_window_start = now
                    _msg_count = 0
                _msg_count += 1
                if _msg_count > _MAX_WS_MESSAGES_PER_SEC:
                    logger.warning("WS message flood session=%s", session_code)
                    await websocket.close(code=1008, reason="rate limit exceeded")
                    return
                try:
                    data = _json.loads(raw)
                except (ValueError, TypeError):
                    # 不正 JSON は黙って無視（接続は維持）
                    continue
                # A-3 防御 (round110): type field を allowlist で明示的に検証。
                # 現状受け付けるのは "ping" のみ (broadcast は server→client のみ)。
                # 未知 type / 非 dict / 過長 type は黙って無視 (接続維持)。
                if not isinstance(data, dict):
                    continue
                msg_type = data.get("type")
                if not isinstance(msg_type, str) or len(msg_type) > 64:
                    continue
                _ALLOWED_TYPES = {"ping"}
                if msg_type not in _ALLOWED_TYPES:
                    continue
                if msg_type == "ping":
                    await manager.safe_send_json(websocket, {"type": "pong"})
            except asyncio.TimeoutError:
                # タイムアウト時は keepalive ping を送る (concurrent-sender 安全な送信)
                await manager.safe_send_json(websocket, {"type": "ping"})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("WS error session=%s: %s", session_code, e)
    finally:
        manager.disconnect(session_code, websocket)


def _build_session_snapshot(session, db) -> dict:
    """セッションの現在スコア・直近ラリーを返す"""
    from backend.db.models import Match, GameSet, Rally

    match = db.get(type(session.match), session.match_id)
    if not match:
        return {"error": "試合データが見つかりません"}

    sets = db.query(GameSet).filter(GameSet.match_id == session.match_id).order_by(GameSet.set_num).all()

    # 最新セットの直近 5 ラリー
    recent_rallies = []
    if sets:
        latest_set = sets[-1]
        rallies = (
            db.query(Rally)
            .filter(Rally.set_id == latest_set.id, Rally.is_skipped.is_(False))
            .order_by(Rally.rally_num.desc())
            .limit(5)
            .all()
        )
        for r in reversed(rallies):
            recent_rallies.append({
                "rally_num": r.rally_num,
                "winner": r.winner,
                "end_type": r.end_type,
                "score_a": r.score_a_after,
                "score_b": r.score_b_after,
                "rally_length": r.rally_length,
            })

    return {
        "match_id": match.id,
        "session_code": session.session_code,
        "set_scores": [
            {"set_num": s.set_num, "score_a": s.score_a, "score_b": s.score_b, "winner": s.winner}
            for s in sets
        ],
        "recent_rallies": recent_rallies,
        "annotation_progress": match.annotation_progress,
        "participants": manager.connection_count(session.session_code),
    }
