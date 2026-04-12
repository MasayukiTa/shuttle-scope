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
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


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

    if is_operator:
        await camera_manager.connect_operator(session_code, websocket)
    elif is_viewer:
        await camera_manager.connect_viewer(session_code, viewer_id, websocket)
    elif participant_id:
        await camera_manager.connect_device(session_code, participant_id, websocket)
    else:
        await websocket.close(code=4000)
        return

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
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
