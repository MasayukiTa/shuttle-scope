"""S-6 残件: デバイス→operator のメッセージ種別と、承認取り消しの即時切断。

## 何が開いていたか

`ws_camera_handler` は operator と viewer の枝には許可リストを持っていたのに、
**送信デバイスからのメッセージは type を問わずそのまま operator に流していた**。

operator 側 (`src/hooks/session/useCameraHub.ts`) は `viewer_joined` /
`viewer_left` / `viewer_webrtc_answer` / `viewer_ice_candidate` を処理する。
これらが持つ `viewer_id` は、device 経路ではサーバが上書きしない
（上書きするのは `participant_id` と `stream_id` だけ）。したがって:

- `{"type":"viewer_joined","viewer_id":"X"}` を送れば、operator に
  **任意の viewer へ映像を offer させられる**
- `{"type":"viewer_left","viewer_id":"X"}` を送れば、**他の viewer の接続を落とせる**

承認済みの端末 1 台で viewer 側の配信経路を乗っ取れた。

## 取り消しの即時性

拒否ボタンは DB を書くだけで、既存の WS には何もしていなかった。切断は
camera WS の **60s ごとの再検査**に相乗りしており、最大 1 分は繋がったまま。
さらに **WS を閉じるだけでは確立済みの WebRTC は止まらない**（映像は peer 間を
直接流れる）。operator に `camera_stream_ended` が届いて `closeStream` が
`RTCPeerConnection` を閉じて初めて止まる。

`backend.main` を import しないので Python 3.10 でも走る。
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import re

from backend.ws.camera import (
    _DEVICE_TO_OPERATOR_TYPES,
    CameraSignalingManager,
)

_CAMERA_PY = pathlib.Path(__file__).resolve().parents[1] / "ws" / "camera.py"
_HUB_TS = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src" / "hooks" / "session" / "useCameraHub.ts"
)


# ─── 許可リストの中身を「写し」ではなく導出で確かめる ─────────────────────────

def _types_the_server_emits() -> set[str]:
    """`camera.py` がサーバとして発行するメッセージ種別を拾う。"""
    src = _CAMERA_PY.read_text(encoding="utf-8")
    return set(re.findall(r'"type":\s*"([a-z_]+)"', src))


def _operator_handled_types_carrying_viewer_id() -> set[str]:
    """operator クライアントが処理する種別のうち `viewer_id` を読むもの。"""
    src = _HUB_TS.read_text(encoding="utf-8")
    handled = re.findall(r"type === '([a-z_]+)'", src)
    # `viewer_` で始まる種別と `viewer_joined` / `viewer_left` が該当する。
    return {t for t in handled if t.startswith("viewer_")}


def test_the_allowlist_excludes_everything_the_server_itself_emits():
    """サーバが発行する制御メッセージをデバイスに名乗らせない。"""
    server_types = _types_the_server_emits()
    assert server_types, "camera.py からサーバ発行の種別が読めていない"
    overlap = _DEVICE_TO_OPERATOR_TYPES & server_types
    assert not overlap, f"デバイスがサーバの制御メッセージを騙れる: {sorted(overlap)}"


def test_the_allowlist_excludes_everything_that_carries_a_viewer_id():
    """`viewer_id` を運ぶ種別は device 経路で上書きされないので通さない。"""
    viewer_types = _operator_handled_types_carrying_viewer_id()
    assert viewer_types, "useCameraHub.ts から viewer 系の種別が読めていない"
    overlap = _DEVICE_TO_OPERATOR_TYPES & viewer_types
    assert not overlap, f"デバイスが viewer 経路を操作できる: {sorted(overlap)}"


def test_the_allowlist_still_covers_what_the_sender_actually_sends():
    """送信端末が実際に送る種別が落ちていないこと（機能を壊さない）。"""
    sender = (
        pathlib.Path(__file__).resolve().parents[2]
        / "src" / "pages" / "CameraSenderPage.tsx"
    ).read_text(encoding="utf-8")
    sent = set(re.findall(r"type:\s*'([a-z_]+)'", sender))
    # 送信側のファイルには WebRTC ローカル用の 'offer'/'answer' 等も出てくるので、
    # シグナリングで送っているものだけを対象にする。
    signalling = {t for t in sent if t.startswith(("camera_", "webrtc_", "ice_", "device_"))}
    missing = signalling - _DEVICE_TO_OPERATOR_TYPES
    assert not missing, f"送信端末が送る種別が許可リストから落ちている: {sorted(missing)}"


# ─── 承認取り消しの即時切断 ───────────────────────────────────────────────────

class _FakeWS:
    def __init__(self):
        self.sent: list[dict] = []
        self.closed_with: tuple | None = None

    async def accept(self):
        pass

    async def send_text(self, text: str):
        self.sent.append(json.loads(text))

    async def close(self, code: int = 1000, reason: str = ""):
        self.closed_with = (code, reason)


def test_revoking_a_device_closes_its_socket_and_tells_the_operator_to_close_the_media():
    """WS を閉じるだけでは映像は止まらない。`camera_stream_ended` まで届くこと。"""
    async def scenario():
        mgr = CameraSignalingManager()
        code = "ABC123"
        operator = _FakeWS()
        device = _FakeWS()

        mgr._ensure_session(code)
        mgr._sessions[code]["operator"] = operator
        await mgr.connect_device(code, "7", device)
        assert mgr.stream_id_for(code, "7") is not None

        operator.sent.clear()
        revoked = await mgr.revoke_device(code, "7", "rejected by operator")
        return device, operator, revoked, mgr, code

    device, operator, revoked, mgr, code = asyncio.run(scenario())

    assert revoked is True
    assert device.closed_with is not None, "デバイスの WS が閉じていない"
    assert device.closed_with[0] == 1008

    ended = [m for m in operator.sent if m.get("type") == "camera_stream_ended"]
    assert ended, (
        "operator に camera_stream_ended が届いていない。"
        "これが無いと operator は RTCPeerConnection を閉じないので、"
        "WS を切っても映像は流れ続ける"
    )
    assert ended[0]["participant_id"] == "7"
    assert mgr.stream_id_for(code, "7") is None


def test_revoking_an_unknown_device_is_a_no_op():
    async def scenario():
        mgr = CameraSignalingManager()
        mgr._ensure_session("ABC123")
        return await mgr.revoke_device("ABC123", "999")

    assert asyncio.run(scenario()) is False


def test_threadsafe_revoke_without_a_running_loop_does_not_raise():
    """REST 側を落とさない。届かなければ 60s ループが従来どおり拾う。"""
    mgr = CameraSignalingManager()
    mgr.revoke_device_threadsafe("ABC123", "7")  # loop 未設定


def test_reject_endpoint_asks_for_an_immediate_disconnect():
    """拒否ハンドラが DB を書くだけで終わっていないこと。"""
    src = (
        pathlib.Path(__file__).resolve().parents[1] / "routers" / "sessions.py"
    ).read_text(encoding="utf-8")
    body = src[src.index("def reject_device("):]
    body = body[: body.index("\n@router.")]
    assert "revoke_device_threadsafe" in body, (
        "拒否しても既存の WS はそのまま。60s の再検査を待つことになる"
    )
