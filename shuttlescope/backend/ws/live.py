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

    def __init__(self):
        # { session_code: [WebSocket, ...] }
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, session_code: str, ws: WebSocket) -> None:
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
        logger.info("WS disconnected: session=%s", session_code)

    def connection_count(self, session_code: str) -> int:
        return len(self._connections.get(session_code, []))

    async def broadcast(self, session_code: str, message: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for ws in list(self._connections.get(session_code, [])):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(session_code, ws)

    async def broadcast_to_match(self, match_id: int, message: dict[str, Any], db) -> None:
        """match_id に紐づくアクティブセッションへ一括ブロードキャスト"""
        from backend.db.models import SharedSession
        sessions = (
            db.query(SharedSession)
            .filter(SharedSession.match_id == match_id, SharedSession.is_active.is_(True))
            .all()
        )
        for s in sessions:
            await self.broadcast(s.session_code, message)
            s.last_broadcast_at = datetime.utcnow()
        if sessions:
            try:
                db.commit()
            except Exception:
                pass


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

    # 受信メッセージ数のバースト制限カウンタ (1 秒窓)
    _msg_window_start = _time.monotonic()
    _msg_count = 0

    try:
        # 接続直後: 現在スナップショットを送信
        snapshot = _build_session_snapshot(session, db)
        await websocket.send_json({"type": "snapshot", "data": snapshot})

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
                if isinstance(data, dict) and data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                # タイムアウト時は keepalive ping を送る
                await websocket.send_json({"type": "ping"})
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
