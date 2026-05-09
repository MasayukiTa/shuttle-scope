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
import re
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
        # ws #9 fix: per-session asyncio.Lock。device disconnect / operator 再接続が
        # 同一 session に対して同時に起きると _sessions[session_code] dict の状態が
        # 競合する。state mutate 系の操作はこの lock 経由で直列化する。
        self._session_locks: dict[str, "asyncio.Lock"] = {}
        # 3rd-review #1b/4 fix: operator session-owner check。
        # main.py:1730-1738 の JWT role-claim ガードは privileged role かどうかは見るが、
        # 同一 role の他ユーザが他人のセッションを乗っ取れる問題は塞げていない。
        # session_code 単位で「最初に operator として claim した user_id」を覚え、
        # 以降 operator 接続は同じ user_id しか受け付けない。
        # session 終了 (is_active=False) で disconnect された後も entry は残し、
        # 万一 session が再活性化しても同じ owner だけが復帰可能にする。
        #
        # Round 258 R18 P0 fix (R18a-2 P0-1): 旧コードでは _gc_session_if_empty が
        # _operator_owners を pop しなかったため、認証済 operator が大量の random
        # session_code に touch する → entry が永続的に積み上がり、process RAM を
        # 食い潰す DoS 経路が成立していた。
        # 修正: dict ではなく **LRU OrderedDict** にし、上限 4096 件で古い順に evict。
        # session-owner consistency の意図 (再活性化時の owner 維持) は短期間の
        # 再接続なら確実に守られる。極めて長期間アクセスが無かった session が
        # evict 後に他 operator から再請求されるケースだけは、実運用上既に
        # is_active=False の archived state なので問題にならない。
        from collections import OrderedDict
        self._operator_owners: "OrderedDict[str, int]" = OrderedDict()
        self._OPERATOR_OWNERS_MAX = 4096

    def _slock(self, session_code: str) -> "asyncio.Lock":
        import asyncio as _aio
        lk = self._session_locks.get(session_code)
        if lk is None:
            lk = _aio.Lock()
            self._session_locks[session_code] = lk
        return lk

    def _ensure_session(self, session_code: str) -> None:
        if session_code not in self._sessions:
            self._sessions[session_code] = {"operator": None, "devices": {}, "viewers": {}}

    # ─── 接続 ────────────────────────────────────────────────────────────

    async def connect_operator(self, session_code: str, ws: WebSocket, user_id: Optional[int] = None) -> bool:
        # ws #4 fix: 旧コードは前任者を黙って上書きしており、operator 役乗っ取りが
        # 成立していた。既に operator が接続中なら新規接続を拒否する。
        # 3rd-review #1a fix: ws.accept() を slot/owner check の **後** に移動。
        # live.py の cap-check-inside-lock + accept-on-success パターンに揃え、
        # 認証通過直後の handshake までは行うが、slot 拒否の場合は accept せずに
        # WebSocket close handshake (HTTP 4xx) で帰す。返値で呼び出し側が分岐する。
        # 3rd-review #1b/4 fix: session-owner consistency check。
        # session_code 単位で先着 user_id を覚え、それ以降 operator は同じ user_id だけ。
        # user_id が None (loopback 緩和) のときは owner check をスキップする。
        async with self._slock(session_code):
            self._ensure_session(session_code)
            existing = self._sessions[session_code].get("operator")
            if existing is not None:
                # 既に他 ws が operator として接続中
                logger.warning("camera operator reject (slot taken): %s", session_code)
                try:
                    await ws.close(code=1013, reason="operator slot already taken")
                except Exception:
                    pass
                return False
            # session-owner consistency
            owner = self._operator_owners.get(session_code)
            if owner is not None and user_id is not None and owner != user_id:
                logger.warning(
                    "camera operator reject (owner mismatch): session=%s owner=%s requester=%s",
                    session_code, owner, user_id,
                )
                try:
                    await ws.close(code=4403, reason="operator owned by another user")
                except Exception:
                    pass
                return False
            # ここまで通れば accept してから slot に入れる
            await ws.accept()
            self._sessions[session_code]["operator"] = ws
            if user_id is not None and owner is None:
                # Round 258 R18 P0 fix (R18a-2 P0-1): LRU evict + bounded insert
                self._operator_owners[session_code] = user_id
                self._operator_owners.move_to_end(session_code)
                while len(self._operator_owners) > self._OPERATOR_OWNERS_MAX:
                    evicted_code, _ = self._operator_owners.popitem(last=False)
                    logger.info(
                        "camera _operator_owners LRU evict: %s (size now %d)",
                        evicted_code, len(self._operator_owners),
                    )
            elif owner is not None:
                # 既存 owner も touch しておくことで、active な session ほど
                # LRU の末尾に維持されるようにする (random session_code touch 攻撃で
                # 正規 owner の entry が evict される攻撃の緩和)。
                self._operator_owners.move_to_end(session_code)
        logger.info("camera operator connected: %s user_id=%s", session_code, user_id)
        return True

    # Round 258 R7 P2 fix (Codex review):
    # camera WS には live.py の MAX_CONN_PER_SESSION=20 相当の総量 cap が無く、
    # 認証済 user / loopback 経路から大量 viewer / device 接続で memory + socket
    # を膨らませる DoS 経路があった。session 単位 + 全体 cap を導入する。
    MAX_VIEWERS_PER_SESSION = 30
    MAX_DEVICES_PER_SESSION = 10
    MAX_TOTAL_CAMERA_SESSIONS = 100
    MAX_TOTAL_CAMERA_CONNECTIONS = 500

    def _total_active_connections(self) -> int:
        n = 0
        for s in self._sessions.values():
            if s.get("operator") is not None:
                n += 1
            n += len(s.get("devices") or {})
            n += len(s.get("viewers") or {})
        return n

    async def connect_device(self, session_code: str, participant_id: str, ws: WebSocket) -> None:
        # rereview ws #9 fix: ensure_session + dict mutation を _slock で直列化
        # Round 258 R7 P2 fix: per-session + 全体 cap を accept() 前に確認
        async with self._slock(session_code):
            self._ensure_session(session_code)
            sess = self._sessions[session_code]
            if len(sess["devices"]) >= self.MAX_DEVICES_PER_SESSION:
                logger.warning("camera device reject (per-session cap): %s", session_code)
                await ws.close(code=1013, reason="device per-session cap reached")
                return
            if len(self._sessions) > self.MAX_TOTAL_CAMERA_SESSIONS:
                logger.warning("camera device reject (total session cap): %s", session_code)
                await ws.close(code=1013, reason="too many sessions")
                return
            if self._total_active_connections() >= self.MAX_TOTAL_CAMERA_CONNECTIONS:
                logger.warning("camera device reject (total conn cap): %s", session_code)
                await ws.close(code=1013, reason="too many connections")
                return
            await ws.accept()
            sess["devices"][participant_id] = ws
            logger.info("camera device connected: %s pid=%s", session_code, participant_id)
        await self._notify_device_list(session_code)

    async def connect_viewer(self, session_code: str, viewer_id: str, ws: WebSocket) -> None:
        # rereview ws #9 fix: 同上 — viewer 接続も lock で直列化
        # Round 258 R7 P2 fix: per-session + 全体 cap を accept() 前に確認
        async with self._slock(session_code):
            self._ensure_session(session_code)
            sess = self._sessions[session_code]
            if len(sess["viewers"]) >= self.MAX_VIEWERS_PER_SESSION:
                logger.warning("camera viewer reject (per-session cap): %s", session_code)
                await ws.close(code=1013, reason="viewer per-session cap reached")
                return
            if len(self._sessions) > self.MAX_TOTAL_CAMERA_SESSIONS:
                logger.warning("camera viewer reject (total session cap): %s", session_code)
                await ws.close(code=1013, reason="too many sessions")
                return
            if self._total_active_connections() >= self.MAX_TOTAL_CAMERA_CONNECTIONS:
                logger.warning("camera viewer reject (total conn cap): %s", session_code)
                await ws.close(code=1013, reason="too many connections")
                return
            await ws.accept()
            sess["viewers"][viewer_id] = ws
            logger.info("camera viewer connected: %s vid=%s", session_code, viewer_id)
        # Operator に viewer 参加を通知（Operator が WebRTC offer を送る）
        await self._send_to_operator(session_code, {
            "type": "viewer_joined",
            "viewer_id": viewer_id,
        })

    # ─── 切断 ────────────────────────────────────────────────────────────

    def _gc_session_if_empty(self, session_code: str) -> None:
        """Round 258 R3 P1 fix: 全 connection が無くなったら session entry を pop。
        旧来は operator が None になっても _sessions / _session_locks が永続化し
        attacker が多数の session_code に touch してメモリを膨らませられた。
        ※ caller は self._slock(session_code) を保持していること。
        """
        sess = self._sessions.get(session_code)
        if sess is None:
            return
        if sess.get("operator") is None and not sess.get("devices") and not sess.get("viewers"):
            self._sessions.pop(session_code, None)
            self._session_locks.pop(session_code, None)
            logger.info("camera session entry GC'd: %s", session_code)

    async def disconnect_operator(self, session_code: str) -> None:
        # rereview ws #9 fix: 同期版だった disconnect_operator を async + lock 化
        async with self._slock(session_code):
            if session_code in self._sessions:
                self._sessions[session_code]["operator"] = None
                logger.info("camera operator disconnected: %s", session_code)
                self._gc_session_if_empty(session_code)

    async def disconnect_device(self, session_code: str, participant_id: str) -> None:
        # ws #9 fix: lock で session state の mutation を直列化
        async with self._slock(session_code):
            if session_code in self._sessions:
                self._sessions[session_code]["devices"].pop(participant_id, None)
                logger.info("camera device disconnected: %s pid=%s", session_code, participant_id)
                self._gc_session_if_empty(session_code)
        await self._notify_device_list(session_code)

    async def disconnect_viewer(self, session_code: str, viewer_id: str) -> None:
        # rereview ws #9 fix: lock 経由で dict 操作を直列化
        async with self._slock(session_code):
            if session_code in self._sessions:
                self._sessions[session_code]["viewers"].pop(viewer_id, None)
                logger.info("camera viewer disconnected: %s vid=%s", session_code, viewer_id)
                self._gc_session_if_empty(session_code)
        # 通知は lock 外で実行 (operator への送信は別ロック経路)
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
                # 3rd-review LOW: 失敗時の dict mutate を _slock 経由に揃える
                async with self._slock(session_code):
                    if session_code in self._sessions:
                        self._sessions[session_code]["devices"].pop(str(participant_id), None)

    async def relay_to_viewer(self, session_code: str, viewer_id: str, message: dict) -> None:
        if session_code not in self._sessions:
            return
        viewer_ws = self._sessions[session_code]["viewers"].get(str(viewer_id))
        if viewer_ws:
            try:
                await viewer_ws.send_text(json.dumps(message))
            except Exception:
                # 3rd-review LOW: 失敗時の dict mutate を _slock 経由に揃える
                async with self._slock(session_code):
                    if session_code in self._sessions:
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
    # Round 258 R3 P1 fix: query string 由来の任意長 ID で memory exhaustion を避ける。
    # viewer_id / participant_id は dict のキーになるため、長大値や制御文字を含む値は
    # accept() 前に拒否する。許容: ASCII alphanum / '-' / '_' / 64 文字以下。
    import re as _re_cam_id
    _id_re = _re_cam_id.compile(r"^[A-Za-z0-9_-]{1,64}$")
    if viewer_id is not None and not _id_re.match(viewer_id):
        await websocket.close(code=4400, reason="viewer_id が不正")
        return
    if participant_id is not None and not _id_re.match(participant_id):
        await websocket.close(code=4400, reason="participant_id が不正")
        return
    if session_code is None or not _re_cam_id.compile(r"^[A-Za-z0-9_-]{1,64}$").match(session_code):
        await websocket.close(code=4400, reason="session_code が不正")
        return

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
        # 3rd-review #1b/4: JWT から user_id を抽出し session-owner check に渡す。
        # main.py の WS ガード側で role claim 検証は済んでいるが、user_id を
        # 改めて取り出して session_code 単位で「先着勝ち」のオーナーシップを敷く。
        # loopback (ALLOW_LOOPBACK_NO_AUTH=1) で token が無いケースは
        # owner check をスキップする (user_id=None)。
        from backend.utils.jwt_utils import verify_token as _verify_token
        _operator_user_id: Optional[int] = None
        _token = websocket.query_params.get("token", "")
        if _token:
            _payload = _verify_token(_token)
            if isinstance(_payload, dict):
                _sub = _payload.get("sub")
                try:
                    _operator_user_id = int(_sub) if _sub is not None else None
                except (ValueError, TypeError):
                    _operator_user_id = None
        ok = await camera_manager.connect_operator(session_code, websocket, user_id=_operator_user_id)
        if not ok:
            return
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

    # Round 258 R19 P2 fix (R18a-2 P2-2): WS は accept 時に 1 度だけ JWT を検証
    # していた。長時間接続中に admin が当該ユーザの token を mass_revoke / 個別
    # revoke / role 降格しても WS は切れず、operator 権限を **保持し続ける** 経路が
    # あった。修正: 60s 毎に同じ token を再検証し、無効化を検知したら close する。
    # `?token=` が空 (loopback 経路) の場合は再検証スキップ (= 元から JWT 不要)。
    #
    # Round 258 R20 P1 fix (R20 P1-2): R19 は `await websocket.receive_text()` の
    # **return 後**に再検証していたため、idle な operator (送信無し) は永久に
    # reverify が走らず、revoke しても slot を持ち続ける逆ザル状態だった。
    # 修正: asyncio.wait_for で 60s timeout を設定し、timeout 経由でも reverify を
    # 駆動する。
    import asyncio as _asyncio_cam
    _saved_token = websocket.query_params.get("token", "") if is_operator else ""
    _reverify_interval = 60.0
    _last_reverify = _time.monotonic()

    async def _do_reverify_and_close_if_invalid() -> bool:
        """token 検証。無効なら close して True を返す (= 呼び出し側は return する)。"""
        if not _saved_token:
            return False
        try:
            from backend.utils.jwt_utils import verify_token as _reverify
            if not isinstance(_reverify(_saved_token), dict):
                logger.warning("camera operator WS reverify failed; closing session=%s", session_code)
                try:
                    await websocket.close(code=4401, reason="token revoked or expired")
                except Exception:
                    pass
                return True
        except Exception as _exc:
            logger.debug("camera operator reverify error: %s", _exc)
        return False

    try:
        while True:
            try:
                raw = await _asyncio_cam.wait_for(
                    websocket.receive_text(),
                    timeout=_reverify_interval,
                )
            except _asyncio_cam.TimeoutError:
                # idle: 何も送られてこなかった → 再検証だけ実施して continue
                _last_reverify = _time.monotonic()
                if await _do_reverify_and_close_if_invalid():
                    return
                continue
            # 受信成功時は interval 単位でだけ再検証 (busy traffic でも DB 負荷を抑える)
            if (_time.monotonic() - _last_reverify) >= _reverify_interval:
                _last_reverify = _time.monotonic()
                if await _do_reverify_and_close_if_invalid():
                    return
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
                # Round 258 R15 P1 fix (deep audit NEW-3): operator が relay する
                # target ID も regex で検証する。connect 時の query string check は
                # 既に入っているが、message 経由で渡される target_*id は別経路なので
                # ここでも検証して dict key injection / 異常 ID で _sessions[code]
                # を膨らませる経路を遮断する。
                # なお relay_to_* は session_code-scoped なので、operator が他 session
                # の device を打つことは構造上不可能 (intentional design: operator は
                # 自 session のオーナー)。ここで追加するのは「異常 ID」のサニタイズ。
                #
                # Round 258 R17 P2 fix (NEW-3): Python の str.isalnum() は Unicode-aware
                # で、`ⅰ` (Roman numeral one U+2170) や `０` (full-width digit U+FF10)、
                # Arabic-Indic digits 等の "見た目数字に化ける文字" を全て True にする。
                # 攻撃者が participant_id に Unicode look-alike を仕込み、内部 dict
                # の key を ASCII の participant_id と区別困難な形でフォーク登録する
                # 経路 (関連監査・ログ confusion / homoglyph spoofing) を防ぐため、
                # **ASCII のみを許容する regex** に置換する。
                _ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
                def _id_ok(s: str) -> bool:
                    return bool(s) and bool(_ID_RE.fullmatch(s))

                # Operator → 送信デバイスへの中継
                target_pid = str(msg.get("target_participant_id", ""))
                if _id_ok(target_pid) and msg_type in (
                    "camera_request", "webrtc_answer", "ice_candidate",
                    "camera_deactivate",
                ):
                    await camera_manager.relay_to_device(session_code, target_pid, msg)

                # Operator → ビューワーへの中継（PC が viewer に offer を送る）
                target_vid = str(msg.get("viewer_id", ""))
                if _id_ok(target_vid) and msg_type in (
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
            await camera_manager.disconnect_operator(session_code)
        elif is_viewer and viewer_id:
            await camera_manager.disconnect_viewer(session_code, viewer_id)
        elif participant_id:
            await camera_manager.disconnect_device(session_code, participant_id)
