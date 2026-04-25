"""WebRTC カメラシグナリング WebSocket

iOS/タブレット ↔ PC Operator 間、および PC Operator ↔ ビューワー間の
WebRTC シグナリングを中継する。映像データは流れない（SDP/ICE のみ）。

エンドポイント: /ws/camera/{session_code}
  ?role=operator       → PC オペレーター（送受信両方を管理）
  ?role=viewer&vid={v} → ビューワーデバイス（他 PC / 大型タブレット）
  ?participant_id={id} → iOS / デバイス送信機

プロトコル（JSON メッセージ）:

[送信デバイス → Operator]
  device_hello    {participant_id, device_name, device_type}
  camera_accept   {participant_id}
  camera_decline  {participant_id}
  webrtc_offer    {participant_id, sdp}
  ice_candidate   {participant_id, candidate, sdp_mid, sdp_m_line_index}
  camera_stop     {participant_id}

[Operator → 送信デバイス]
  camera_request      {target_participant_id}
  webrtc_answer       {target_participant_id, sdp}
  ice_candidate       {target_participant_id, candidate, sdp_mid, sdp_m_line_index}

[Viewer → Operator]
  viewer_webrtc_answer  {viewer_id, sdp}
  viewer_ice_candidate  {viewer_id, candidate, sdp_mid, sdp_m_line_index}

[Operator → Viewer]
  viewer_webrtc_offer   {viewer_id, sdp}
  viewer_ice_candidate  {viewer_id, candidate, sdp_mid, sdp_m_line_index}

[Server → Operator]
  device_list_update  {devices: [{participant_id, status}]}
  viewer_joined       {viewer_id}
  viewer_left         {viewer_id}
"""
import json
import logging
import time as _time
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

# ─── DoS 対策上限 ────────────────────────────────────────────────────────────
# WebRTC SDP は通常 5〜20 KB、ICE candidate も 1 KB 未満。
# 64 KB あれば全プロトコルメッセージを許容しつつ巨大 frame DoS を遮断できる。
_MAX_WS_MESSAGE_BYTES = 64 * 1024
# 1 接続あたりの 1 秒間メッセージ流量 (シグナリング想定で十分なバッファ)。
_MAX_WS_MESSAGES_PER_SEC = 60


class CameraSignalingManager:
    """セッションコード → {operator, devices, viewers} のインメモリ管理"""

    def __init__(self):
        # { session_code: {
        #     "operator": WebSocket | None,
        #     "devices": {str(pid): WebSocket},
        #     "viewers": {str(vid): WebSocket},
        # }}
        self._sessions: dict[str, dict] = {}

    def _ensure_session(self, session_code: str) -> None:
        if session_code not in self._sessions:
            self._sessions[session_code] = {"operator": None, "devices": {}, "viewers": {}}

    # ─── 接続 ────────────────────────────────────────────────────────────

    async def connect_operator(self, session_code: str, ws: WebSocket) -> None:
        await ws.accept()
        self._ensure_session(session_code)
        self._sessions[session_code]["operator"] = ws
        logger.info("camera operator connected: %s", session_code)

    async def connect_device(self, session_code: str, participant_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._ensure_session(session_code)
        self._sessions[session_code]["devices"][participant_id] = ws
        logger.info("camera device connected: %s pid=%s", session_code, participant_id)
        await self._notify_device_list(session_code)

    async def connect_viewer(self, session_code: str, viewer_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._ensure_session(session_code)
        self._sessions[session_code]["viewers"][viewer_id] = ws
        logger.info("camera viewer connected: %s vid=%s", session_code, viewer_id)
        # Operator に viewer 参加を通知（Operator が WebRTC offer を送る）
        await self._send_to_operator(session_code, {
            "type": "viewer_joined",
            "viewer_id": viewer_id,
        })

    # ─── 切断 ────────────────────────────────────────────────────────────

    def disconnect_operator(self, session_code: str) -> None:
        if session_code in self._sessions:
            self._sessions[session_code]["operator"] = None
            logger.info("camera operator disconnected: %s", session_code)

    async def disconnect_device(self, session_code: str, participant_id: str) -> None:
        if session_code in self._sessions:
            self._sessions[session_code]["devices"].pop(participant_id, None)
            logger.info("camera device disconnected: %s pid=%s", session_code, participant_id)
            await self._notify_device_list(session_code)

    async def disconnect_viewer(self, session_code: str, viewer_id: str) -> None:
        if session_code in self._sessions:
            self._sessions[session_code]["viewers"].pop(viewer_id, None)
            logger.info("camera viewer disconnected: %s vid=%s", session_code, viewer_id)
            await self._send_to_operator(session_code, {
                "type": "viewer_left",
                "viewer_id": viewer_id,
            })

    # ─── メッセージ中継 ──────────────────────────────────────────────────

    async def relay_to_operator(self, session_code: str, message: dict) -> None:
        await self._send_to_operator(session_code, message)

    async def relay_to_device(self, session_code: str, participant_id: str, message: dict) -> None:
        if session_code not in self._sessions:
            return
        device_ws = self._sessions[session_code]["devices"].get(str(participant_id))
        if device_ws:
            try:
                await device_ws.send_text(json.dumps(message))
            except Exception:
                self._sessions[session_code]["devices"].pop(str(participant_id), None)

    async def relay_to_viewer(self, session_code: str, viewer_id: str, message: dict) -> None:
        if session_code not in self._sessions:
            return
        viewer_ws = self._sessions[session_code]["viewers"].get(str(viewer_id))
        if viewer_ws:
            try:
                await viewer_ws.send_text(json.dumps(message))
            except Exception:
                self._sessions[session_code]["viewers"].pop(str(viewer_id), None)

    # ─── 内部ヘルパー ────────────────────────────────────────────────────

    async def _send_to_operator(self, session_code: str, message: dict) -> None:
        if session_code not in self._sessions:
            return
        operator = self._sessions[session_code].get("operator")
        if operator:
            try:
                await operator.send_text(json.dumps(message))
            except Exception:
                self._sessions[session_code]["operator"] = None

    async def _notify_device_list(self, session_code: str) -> None:
        devices = [
            {"participant_id": pid, "status": "connected"}
            for pid in self._sessions.get(session_code, {}).get("devices", {}).keys()
        ]
        await self._send_to_operator(session_code, {
            "type": "device_list_update",
            "devices": devices,
        })


# シングルトン
camera_manager = CameraSignalingManager()


async def ws_camera_handler(
    session_code: str,
    websocket: WebSocket,
    role: Optional[str] = None,
    participant_id: Optional[str] = None,
    viewer_id: Optional[str] = None,
) -> None:
    """WebRTC シグナリング WebSocket ハンドラー"""
    # セッション存在確認（存在しないまたは終了済みセッションへの接続を拒否）
    from backend.db.database import SessionLocal
    from backend.db.models import SharedSession
    _db = SessionLocal()
    try:
        _session = _db.query(SharedSession).filter(
            SharedSession.session_code == session_code,
            SharedSession.is_active.is_(True)
        ).first()
    finally:
        _db.close()
    if not _session:
        await websocket.close(code=4404, reason="セッションが存在しないか終了しています")
        return

    is_operator = role == "operator"
    is_viewer = role == "viewer" and viewer_id

    # 送信デバイスとして接続する場合: participant_id がこのセッションに属することを検証
    if participant_id and not is_operator and not is_viewer:
        from backend.db.database import SessionLocal
        from backend.db.models import SessionParticipant as _SP
        _db2 = SessionLocal()
        try:
            _pid_int = int(participant_id)
            _p = _db2.query(_SP).filter(
                _SP.id == _pid_int,
                _SP.session_id == _session.id,
            ).first()
        except (ValueError, TypeError):
            _p = None
        finally:
            _db2.close()
        if not _p:
            await websocket.close(code=4403, reason="この participant_id はセッションに登録されていません")
            return

    if is_operator:
        await camera_manager.connect_operator(session_code, websocket)
    elif is_viewer:
        await camera_manager.connect_viewer(session_code, viewer_id, websocket)
    elif participant_id:
        await camera_manager.connect_device(session_code, participant_id, websocket)
    else:
        await websocket.close(code=4000)
        return

    # 受信メッセージ数のバースト制限カウンタ (1 秒窓)
    _msg_window_start = _time.monotonic()
    _msg_count = 0

    try:
        while True:
            raw = await websocket.receive_text()
            # 巨大メッセージによるメモリ DoS (CWE-770) を遮断する。
            if len(raw) > _MAX_WS_MESSAGE_BYTES:
                logger.warning("camera WS oversized message session=%s len=%d", session_code, len(raw))
                await websocket.close(code=1009, reason="message too large")
                return
            # flood DoS 対策: 1 秒あたりメッセージ数を制限
            now = _time.monotonic()
            if now - _msg_window_start >= 1.0:
                _msg_window_start = now
                _msg_count = 0
            _msg_count += 1
            if _msg_count > _MAX_WS_MESSAGES_PER_SEC:
                logger.warning("camera WS message flood session=%s", session_code)
                await websocket.close(code=1008, reason="rate limit exceeded")
                return
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if not isinstance(msg, dict):
                continue
            msg_type = msg.get("type", "")

            if is_operator:
                # Operator → 送信デバイスへの中継
                target_pid = str(msg.get("target_participant_id", ""))
                if target_pid and msg_type in (
                    "camera_request", "webrtc_answer", "ice_candidate",
                    "camera_deactivate",
                ):
                    await camera_manager.relay_to_device(session_code, target_pid, msg)

                # Operator → ビューワーへの中継（PC が viewer に offer を送る）
                target_vid = str(msg.get("viewer_id", ""))
                if target_vid and msg_type in (
                    "viewer_webrtc_offer", "viewer_ice_candidate",
                ):
                    await camera_manager.relay_to_viewer(session_code, target_vid, msg)

            elif is_viewer:
                # ビューワー → Operator に中継（answer / ICE）
                msg["viewer_id"] = viewer_id
                if msg_type in ("viewer_webrtc_answer", "viewer_ice_candidate"):
                    await camera_manager.relay_to_operator(session_code, msg)

            else:
                # 送信デバイス → Operator に中継
                msg["participant_id"] = participant_id
                await camera_manager.relay_to_operator(session_code, msg)

                if msg_type == "camera_stop":
                    break

    except WebSocketDisconnect:
        pass
    finally:
        if is_operator:
            camera_manager.disconnect_operator(session_code)
        elif is_viewer and viewer_id:
            await camera_manager.disconnect_viewer(session_code, viewer_id)
        elif participant_id:
            await camera_manager.disconnect_device(session_code, participant_id)
