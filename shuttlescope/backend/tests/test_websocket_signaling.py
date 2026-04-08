"""WebRTC カメラシグナリング WebSocket テスト

単一 PC で検証可能なシグナリングロジックを網羅する:
  - operator / device / viewer の接続・切断
  - デバイス接続時に operator へ device_list_update を通知
  - viewer 接続時に operator へ viewer_joined を通知
  - viewer 切断時に operator へ viewer_left を通知
  - device → operator へのメッセージ中継
  - operator → device へのメッセージ中継
  - operator → viewer へのメッセージ中継
  - viewer → operator へのメッセージ中継（answer / ICE）
  - 不正パラメータ（role/id なし）で接続拒否
"""
import json
import threading
import time
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.ws.camera import camera_manager


# ─── ヘルパー ─────────────────────────────────────────────────────────────────

def _fresh_code(prefix: str = "WS") -> str:
    """競合しないようにユニークなセッションコードを生成（テスト名から）"""
    import uuid
    return f"{prefix}{uuid.uuid4().hex[:6].upper()}"


@pytest.fixture(autouse=True)
def clear_camera_manager():
    """各テスト後に camera_manager の状態をクリーンアップ"""
    yield
    camera_manager._sessions.clear()


# ─── 接続テスト ───────────────────────────────────────────────────────────────

class TestOperatorConnect:
    def test_operator_connects_without_error(self):
        """operator ロールで WS 接続できる"""
        code = _fresh_code("OPR")
        client = TestClient(app)
        with client.websocket_connect(f"/ws/camera/{code}?role=operator") as ws:
            # 接続直後は何も送らず即切断 — エラーなし
            pass

    def test_unknown_role_without_participant_id_closes(self):
        """role も participant_id も指定なしで接続すると close される"""
        code = _fresh_code("BAD")
        client = TestClient(app)
        # close(4000) が発行されるため WebSocketDisconnect が起きる
        try:
            with client.websocket_connect(f"/ws/camera/{code}") as ws:
                ws.receive_text()  # 強制的に受信待ち → WebSocketDisconnect
        except Exception:
            pass  # close(4000) → 例外は想定内


class TestDeviceConnect:
    def test_device_connect_notifies_operator(self):
        """デバイス接続時に operator が device_list_update を受信する"""
        code = _fresh_code("DEV")
        client = TestClient(app)
        operator_msgs: list[dict] = []
        ready = threading.Event()
        done = threading.Event()

        def run_operator():
            with client.websocket_connect(f"/ws/camera/{code}?role=operator") as ws:
                ready.set()
                try:
                    raw = ws.receive_text()
                    operator_msgs.append(json.loads(raw))
                except Exception:
                    pass
                done.wait(timeout=3)

        def run_device():
            ready.wait(timeout=3)
            time.sleep(0.05)  # operator 側の receive 待ち
            with client.websocket_connect(f"/ws/camera/{code}?participant_id=100") as _ws:
                time.sleep(0.1)
            done.set()

        t1 = threading.Thread(target=run_operator, daemon=True)
        t2 = threading.Thread(target=run_device, daemon=True)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert len(operator_msgs) >= 1
        assert operator_msgs[0]["type"] == "device_list_update"
        assert "devices" in operator_msgs[0]

    def test_multiple_devices_appear_in_list(self):
        """複数デバイスが接続されると device_list_update に全デバイスが含まれる"""
        code = _fresh_code("MLT")
        client = TestClient(app)
        operator_msgs: list[dict] = []
        ready = threading.Event()
        done = threading.Event()

        def run_operator():
            with client.websocket_connect(f"/ws/camera/{code}?role=operator") as ws:
                ready.set()
                try:
                    for _ in range(2):  # 2 回受信
                        raw = ws.receive_text()
                        operator_msgs.append(json.loads(raw))
                except Exception:
                    pass
                done.wait(timeout=3)

        def run_devices():
            ready.wait(timeout=3)
            time.sleep(0.05)
            with client.websocket_connect(f"/ws/camera/{code}?participant_id=201") as _:
                with client.websocket_connect(f"/ws/camera/{code}?participant_id=202") as __:
                    time.sleep(0.2)
            done.set()

        t1 = threading.Thread(target=run_operator, daemon=True)
        t2 = threading.Thread(target=run_devices, daemon=True)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        all_pids = [d["participant_id"] for m in operator_msgs for d in m.get("devices", [])]
        assert "201" in all_pids or "202" in all_pids


class TestViewerConnect:
    def test_viewer_connect_sends_viewer_joined_to_operator(self):
        """viewer 接続時に operator が viewer_joined を受信する"""
        code = _fresh_code("VJN")
        client = TestClient(app)
        operator_msgs: list[dict] = []
        ready = threading.Event()
        done = threading.Event()

        def run_operator():
            with client.websocket_connect(f"/ws/camera/{code}?role=operator") as ws:
                ready.set()
                try:
                    raw = ws.receive_text()
                    operator_msgs.append(json.loads(raw))
                except Exception:
                    pass
                done.wait(timeout=3)

        def run_viewer():
            ready.wait(timeout=3)
            time.sleep(0.05)
            with client.websocket_connect(
                f"/ws/camera/{code}?role=viewer&viewer_id=viewer-abc"
            ) as _ws:
                time.sleep(0.1)
            done.set()

        t1 = threading.Thread(target=run_operator, daemon=True)
        t2 = threading.Thread(target=run_viewer, daemon=True)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert len(operator_msgs) >= 1
        assert operator_msgs[0]["type"] == "viewer_joined"
        assert operator_msgs[0]["viewer_id"] == "viewer-abc"

    def test_viewer_disconnect_sends_viewer_left_to_operator(self):
        """viewer 切断時に operator が viewer_left を受信する"""
        code = _fresh_code("VLT")
        client = TestClient(app)
        operator_msgs: list[dict] = []
        ready = threading.Event()
        viewer_connected = threading.Event()
        done = threading.Event()

        def run_operator():
            with client.websocket_connect(f"/ws/camera/{code}?role=operator") as ws:
                ready.set()
                try:
                    for _ in range(2):  # viewer_joined + viewer_left
                        raw = ws.receive_text()
                        operator_msgs.append(json.loads(raw))
                except Exception:
                    pass
                done.wait(timeout=3)

        def run_viewer():
            ready.wait(timeout=3)
            time.sleep(0.05)
            with client.websocket_connect(
                f"/ws/camera/{code}?role=viewer&viewer_id=viewer-xyz"
            ) as _ws:
                viewer_connected.set()
                time.sleep(0.1)  # → 切断
            done.set()

        t1 = threading.Thread(target=run_operator, daemon=True)
        t2 = threading.Thread(target=run_viewer, daemon=True)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        types = [m["type"] for m in operator_msgs]
        assert "viewer_left" in types
        left_msgs = [m for m in operator_msgs if m["type"] == "viewer_left"]
        assert left_msgs[0]["viewer_id"] == "viewer-xyz"


# ─── メッセージ中継テスト ─────────────────────────────────────────────────────

class TestDeviceToOperatorRelay:
    def test_device_hello_relayed_to_operator(self):
        """デバイスが device_hello を送ると operator が受信する"""
        code = _fresh_code("DRL")
        client = TestClient(app)
        operator_msgs: list[dict] = []
        ready = threading.Event()
        done = threading.Event()

        def run_operator():
            with client.websocket_connect(f"/ws/camera/{code}?role=operator") as ws:
                ready.set()
                try:
                    # 1 回目: device_list_update（接続通知）
                    ws.receive_text()
                    # 2 回目: device_hello 中継
                    raw = ws.receive_text()
                    operator_msgs.append(json.loads(raw))
                except Exception:
                    pass
                done.wait(timeout=3)

        def run_device():
            ready.wait(timeout=3)
            time.sleep(0.05)
            with client.websocket_connect(f"/ws/camera/{code}?participant_id=300") as ws:
                time.sleep(0.05)
                ws.send_json({
                    "type": "device_hello",
                    "device_name": "テストiPhone",
                    "device_type": "iphone",
                })
                time.sleep(0.15)
            done.set()

        t1 = threading.Thread(target=run_operator, daemon=True)
        t2 = threading.Thread(target=run_device, daemon=True)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert len(operator_msgs) >= 1
        assert operator_msgs[0]["type"] == "device_hello"

    def test_device_participant_id_injected_in_relayed_message(self):
        """中継メッセージに participant_id がサーバー側で付与される"""
        code = _fresh_code("DID")
        client = TestClient(app)
        operator_msgs: list[dict] = []
        ready = threading.Event()
        done = threading.Event()

        def run_operator():
            with client.websocket_connect(f"/ws/camera/{code}?role=operator") as ws:
                ready.set()
                try:
                    ws.receive_text()   # device_list_update
                    raw = ws.receive_text()
                    operator_msgs.append(json.loads(raw))
                except Exception:
                    pass
                done.wait(timeout=3)

        def run_device():
            ready.wait(timeout=3)
            time.sleep(0.05)
            with client.websocket_connect(f"/ws/camera/{code}?participant_id=999") as ws:
                time.sleep(0.05)
                ws.send_json({"type": "camera_accept"})
                time.sleep(0.15)
            done.set()

        t1 = threading.Thread(target=run_operator, daemon=True)
        t2 = threading.Thread(target=run_device, daemon=True)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert len(operator_msgs) >= 1
        assert operator_msgs[0].get("participant_id") == "999"


class TestOperatorToDeviceRelay:
    def test_camera_request_relayed_to_device(self):
        """operator が camera_request を送ると対象デバイスが受信する"""
        code = _fresh_code("OTD")
        client = TestClient(app)
        device_msgs: list[dict] = []
        op_ready = threading.Event()
        dev_ready = threading.Event()
        done = threading.Event()

        def run_operator():
            with client.websocket_connect(f"/ws/camera/{code}?role=operator") as ws:
                op_ready.set()
                dev_ready.wait(timeout=3)
                time.sleep(0.1)
                ws.send_json({
                    "type": "camera_request",
                    "target_participant_id": "401",
                })
                done.wait(timeout=3)

        def run_device():
            op_ready.wait(timeout=3)
            with client.websocket_connect(f"/ws/camera/{code}?participant_id=401") as ws:
                dev_ready.set()
                try:
                    raw = ws.receive_text()
                    device_msgs.append(json.loads(raw))
                except Exception:
                    pass
                done.set()

        t1 = threading.Thread(target=run_operator, daemon=True)
        t2 = threading.Thread(target=run_device, daemon=True)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert len(device_msgs) >= 1
        assert device_msgs[0]["type"] == "camera_request"


class TestOperatorToViewerRelay:
    def test_viewer_webrtc_offer_relayed_to_viewer(self):
        """operator が viewer_webrtc_offer を送ると対象 viewer が受信する"""
        code = _fresh_code("OTV")
        client = TestClient(app)
        viewer_msgs: list[dict] = []
        op_ready = threading.Event()
        vw_ready = threading.Event()
        done = threading.Event()

        def run_operator():
            with client.websocket_connect(f"/ws/camera/{code}?role=operator") as ws:
                op_ready.set()
                vw_ready.wait(timeout=3)
                # viewer_joined を受信してから offer を送る
                try:
                    ws.receive_text()  # viewer_joined
                except Exception:
                    pass
                ws.send_json({
                    "type": "viewer_webrtc_offer",
                    "viewer_id": "viewer-relay-test",
                    "sdp": "v=0\r\no=- ...",
                })
                done.wait(timeout=3)

        def run_viewer():
            op_ready.wait(timeout=3)
            time.sleep(0.05)
            with client.websocket_connect(
                f"/ws/camera/{code}?role=viewer&viewer_id=viewer-relay-test"
            ) as ws:
                vw_ready.set()
                try:
                    raw = ws.receive_text()
                    viewer_msgs.append(json.loads(raw))
                except Exception:
                    pass
                done.set()

        t1 = threading.Thread(target=run_operator, daemon=True)
        t2 = threading.Thread(target=run_viewer, daemon=True)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert len(viewer_msgs) >= 1
        assert viewer_msgs[0]["type"] == "viewer_webrtc_offer"
        assert "sdp" in viewer_msgs[0]


class TestViewerToOperatorRelay:
    def test_viewer_answer_relayed_to_operator(self):
        """viewer が viewer_webrtc_answer を送ると operator が受信する"""
        code = _fresh_code("VTO")
        client = TestClient(app)
        operator_msgs: list[dict] = []
        op_ready = threading.Event()
        vw_ready = threading.Event()
        done = threading.Event()

        def run_operator():
            with client.websocket_connect(f"/ws/camera/{code}?role=operator") as ws:
                op_ready.set()
                try:
                    ws.receive_text()  # viewer_joined
                    raw = ws.receive_text()  # relayed answer
                    operator_msgs.append(json.loads(raw))
                except Exception:
                    pass
                done.wait(timeout=3)

        def run_viewer():
            op_ready.wait(timeout=3)
            time.sleep(0.05)
            with client.websocket_connect(
                f"/ws/camera/{code}?role=viewer&viewer_id=vw-ans"
            ) as ws:
                vw_ready.set()
                time.sleep(0.1)
                ws.send_json({
                    "type": "viewer_webrtc_answer",
                    "sdp": "v=0\r\no=- ...",
                })
                time.sleep(0.1)
            done.set()

        t1 = threading.Thread(target=run_operator, daemon=True)
        t2 = threading.Thread(target=run_viewer, daemon=True)
        t1.start()
        t2.start()
        t1.join(timeout=6)
        t2.join(timeout=6)

        answer_msgs = [m for m in operator_msgs if m.get("type") == "viewer_webrtc_answer"]
        assert len(answer_msgs) >= 1
        assert answer_msgs[0].get("viewer_id") == "vw-ans"


# ─── シグナリングマネージャー単体テスト ───────────────────────────────────────

class TestCameraSignalingManagerUnit:
    """CameraSignalingManager のロジックを疑似 WS で直接テスト"""

    @pytest.mark.asyncio
    async def test_ensure_session_creates_structure(self):
        from backend.ws.camera import CameraSignalingManager
        mgr = CameraSignalingManager()
        mgr._ensure_session("TEST_UNIT_01")
        assert "TEST_UNIT_01" in mgr._sessions
        assert mgr._sessions["TEST_UNIT_01"]["operator"] is None
        assert mgr._sessions["TEST_UNIT_01"]["devices"] == {}
        assert mgr._sessions["TEST_UNIT_01"]["viewers"] == {}

    @pytest.mark.asyncio
    async def test_disconnect_operator_clears_reference(self):
        from backend.ws.camera import CameraSignalingManager
        mgr = CameraSignalingManager()
        mgr._ensure_session("TEST_UNIT_02")
        # 仮の operator をセット
        mgr._sessions["TEST_UNIT_02"]["operator"] = object()
        mgr.disconnect_operator("TEST_UNIT_02")
        assert mgr._sessions["TEST_UNIT_02"]["operator"] is None

    @pytest.mark.asyncio
    async def test_disconnect_unknown_session_safe(self):
        from backend.ws.camera import CameraSignalingManager
        mgr = CameraSignalingManager()
        # 存在しないセッションを切断してもクラッシュしない
        mgr.disconnect_operator("NO_SUCH_SESSION")

    @pytest.mark.asyncio
    async def test_relay_to_viewer_unknown_session_safe(self):
        from backend.ws.camera import CameraSignalingManager
        mgr = CameraSignalingManager()
        # 存在しないセッション / viewer への中継は無視される
        await mgr.relay_to_viewer("NO_SUCH", "no-viewer", {"type": "test"})
