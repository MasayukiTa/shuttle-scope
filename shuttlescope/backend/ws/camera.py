"""WebRTC カメラシグナリング WebSocket

iOS/タブレット ↔ PC Operator 間の WebRTC シグナリングを中継する。
映像データは流れない。SDP offer/answer と ICE candidate のみ。

エンドポイント: /ws/camera/{session_code}
  ?role=operator       → PC オペレーター接続
  ?participant_id={id} → iOS / デバイス接続

プロトコル（JSON メッセージ）:

デバイス → サーバー → Operator:
  device_hello    {participant_id, device_name, device_type}
  camera_accept   {participant_id}
  camera_decline  {participant_id}
  webrtc_offer    {participant_id, sdp}
  ice_candidate   {participant_id, candidate, sdp_mid, sdp_m_line_index}
  camera_stop     {participant_id}

Operator → サーバー → デバイス:
  camera_request  {target_participant_id}
  webrtc_answer   {target_participant_id, sdp}
  ice_candidate   {target_participant_id, candidate, sdp_mid, sdp_m_line_index}

サーバー → Operator（自動通知）:
  device_list_update  {devices: [{participant_id, device_name, device_type, status}]}
"""
import json
import logging
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class CameraSignalingManager:
    """セッションコード → {operator, devices} のインメモリ管理"""

    def __init__(self):
        # { session_code: {"operator": WebSocket | None, "devices": {str(pid): WebSocket}} }
        self._sessions: dict[str, dict] = {}

    def _ensure_session(self, session_code: str) -> None:
        if session_code not in self._sessions:
            self._sessions[session_code] = {"operator": None, "devices": {}}

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
        # Operator に接続デバイスリストを通知
        await self._notify_device_list(session_code)

    def disconnect_operator(self, session_code: str) -> None:
        if session_code in self._sessions:
            self._sessions[session_code]["operator"] = None
            logger.info("camera operator disconnected: %s", session_code)

    async def disconnect_device(self, session_code: str, participant_id: str) -> None:
        if session_code in self._sessions:
            self._sessions[session_code]["devices"].pop(participant_id, None)
            logger.info("camera device disconnected: %s pid=%s", session_code, participant_id)
            await self._notify_device_list(session_code)

    async def relay_to_operator(self, session_code: str, message: dict) -> None:
        """デバイスから Operator へメッセージを中継"""
        if session_code not in self._sessions:
            return
        operator = self._sessions[session_code].get("operator")
        if operator:
            try:
                await operator.send_text(json.dumps(message))
            except Exception:
                self._sessions[session_code]["operator"] = None

    async def relay_to_device(self, session_code: str, participant_id: str, message: dict) -> None:
        """Operator から特定デバイスへメッセージを中継"""
        if session_code not in self._sessions:
            return
        device_ws = self._sessions[session_code]["devices"].get(str(participant_id))
        if device_ws:
            try:
                await device_ws.send_text(json.dumps(message))
            except Exception:
                self._sessions[session_code]["devices"].pop(str(participant_id), None)

    async def _notify_device_list(self, session_code: str) -> None:
        """Operator に接続デバイスリストを通知"""
        if session_code not in self._sessions:
            return
        operator = self._sessions[session_code].get("operator")
        if not operator:
            return
        devices = [
            {"participant_id": pid, "status": "connected"}
            for pid in self._sessions[session_code]["devices"].keys()
        ]
        try:
            await operator.send_text(json.dumps({
                "type": "device_list_update",
                "devices": devices,
            }))
        except Exception:
            self._sessions[session_code]["operator"] = None


# シングルトン
camera_manager = CameraSignalingManager()


async def ws_camera_handler(
    session_code: str,
    websocket: WebSocket,
    role: Optional[str] = None,
    participant_id: Optional[str] = None,
) -> None:
    """WebRTC シグナリング WebSocket ハンドラー"""
    is_operator = role == "operator"

    if is_operator:
        await camera_manager.connect_operator(session_code, websocket)
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
                # Operator → 特定デバイスへ中継
                target_pid = str(msg.get("target_participant_id", ""))
                if target_pid:
                    await camera_manager.relay_to_device(session_code, target_pid, msg)
            else:
                # デバイス → Operator へ中継（participant_id を付与）
                msg["participant_id"] = participant_id
                await camera_manager.relay_to_operator(session_code, msg)

                # camera_stop 時はデバイスが自発的に切断
                if msg_type == "camera_stop":
                    break

    except WebSocketDisconnect:
        pass
    finally:
        if is_operator:
            camera_manager.disconnect_operator(session_code)
        elif participant_id:
            await camera_manager.disconnect_device(session_code, participant_id)
