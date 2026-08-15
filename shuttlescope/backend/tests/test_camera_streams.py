"""stream_id によるハブ非依存化と、同一 participant_id の再接続。

背景:
  operator が中継役であることが実装に埋め込まれており、宛先が
  participant_id 直指定だった。中継役を operator 以外へ移せるようにするため、
  宛先を stream_id にしてサーバ側で解決する。

  あわせて、同じ participant_id で繋ぎ直したときの扱いを直す。旧実装は
  `devices[pid] = ws` で黙って上書きし、旧ソケットを閉じないうえ、
  旧ソケットの後始末が pid だけで pop するため **新しいソケットを一覧から
  消していた**。カメラが再接続するたびに自分を消す競合になっていた。
"""
import asyncio

import pytest

from backend.ws.camera import CameraSignalingManager


class _FakeWS:
    """WebSocket の最小の身代わり。送られた JSON を溜める。"""

    def __init__(self, name: str = "ws") -> None:
        self.name = name
        self.sent: list[str] = []
        self.closed_with: tuple[int, str] | None = None

    async def accept(self) -> None:
        return None

    async def send_text(self, data: str) -> None:
        self.sent.append(data)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed_with = (code, reason)


def _run(coro):
    return asyncio.run(coro)


# ── stream_id の採番 ────────────────────────────────────────────────────────

def test_each_connection_gets_its_own_stream_id():
    """接続ごとに新しい stream_id が振られること。"""
    m = CameraSignalingManager()

    async def scenario():
        await m.connect_device("S1", "10", _FakeWS("a"))
        first = m.stream_id_for("S1", "10")
        await m.connect_device("S1", "11", _FakeWS("b"))
        second = m.stream_id_for("S1", "11")
        return first, second

    first, second = _run(scenario())
    assert first and second
    assert first != second, "別カメラが同じ stream_id を持っている"


def test_reconnect_issues_a_new_stream_id_and_drops_the_old():
    """繋ぎ直すと新しい stream_id になり、古い対応は消えること。

    これが無いと operator は「前の映像の残骸」と「新しい映像」を区別できない。
    """
    m = CameraSignalingManager()

    async def scenario():
        await m.connect_device("S2", "10", _FakeWS("old"))
        old = m.stream_id_for("S2", "10")
        await m.connect_device("S2", "10", _FakeWS("new"))
        new = m.stream_id_for("S2", "10")
        return old, new, m.participant_for_stream("S2", old)

    old, new, stale_lookup = _run(scenario())
    assert old != new
    assert stale_lookup is None, "古い stream_id がまだ端末に解決されている"


# ── 再接続の置換 ────────────────────────────────────────────────────────────

def test_reconnect_replaces_and_closes_the_previous_socket():
    """旧ソケットは放置せず閉じること。"""
    m = CameraSignalingManager()
    old_ws, new_ws = _FakeWS("old"), _FakeWS("new")

    async def scenario():
        await m.connect_device("S3", "10", old_ws)
        await m.connect_device("S3", "10", new_ws)
        return m._sessions["S3"]["devices"]["10"]

    registered = _run(scenario())
    assert registered is new_ws
    assert old_ws.closed_with is not None, "旧ソケットが閉じられていない"
    assert old_ws.closed_with[0] == 1012


def test_the_replaced_socket_does_not_remove_the_new_one():
    """置換された旧ソケットの後始末が、新しいソケットを消さないこと。

    旧実装は participant_id だけで pop していたため、再接続直後に旧ソケットの
    finally が走ると、生きている新しい接続が一覧から消えていた。
    """
    m = CameraSignalingManager()
    old_ws, new_ws = _FakeWS("old"), _FakeWS("new")

    async def scenario():
        await m.connect_device("S4", "10", old_ws)
        await m.connect_device("S4", "10", new_ws)
        # 旧ソケットの切断処理が後から走る
        await m.disconnect_device("S4", "10", old_ws)
        return m._sessions.get("S4", {}).get("devices", {})

    devices = _run(scenario())
    assert "10" in devices, "生きている接続が旧ソケットの後始末で消された"
    assert devices["10"] is new_ws


def test_disconnecting_the_current_socket_removes_it():
    m = CameraSignalingManager()
    ws = _FakeWS()

    async def scenario():
        await m.connect_device("S5", "10", ws)
        await m.disconnect_device("S5", "10", ws)
        return m._sessions.get("S5", {}).get("devices", {})

    assert "10" not in _run(scenario())


# ── stream_id 宛の中継 ──────────────────────────────────────────────────────

def test_relay_by_stream_id_reaches_the_right_device():
    """operator が participant_id を知らなくても宛先が解決されること。"""
    m = CameraSignalingManager()
    ws_a, ws_b = _FakeWS("a"), _FakeWS("b")

    async def scenario():
        await m.connect_device("S6", "10", ws_a)
        await m.connect_device("S6", "11", ws_b)
        sid_b = m.stream_id_for("S6", "11")
        await m.relay_to_stream("S6", sid_b, {"type": "camera_request"})

    _run(scenario())
    assert not ws_a.sent, "別のカメラへ届いている"
    assert any("camera_request" in s for s in ws_b.sent)


def test_relay_to_an_ended_stream_is_dropped():
    """終了した stream 宛は黙って捨てること (死んだ端末へ送らない)。"""
    m = CameraSignalingManager()
    ws = _FakeWS()

    async def scenario():
        await m.connect_device("S7", "10", ws)
        sid = m.stream_id_for("S7", "10")
        await m.disconnect_device("S7", "10", ws)
        await m.relay_to_stream("S7", sid, {"type": "camera_request"})

    _run(scenario())
    assert not any("camera_request" in s for s in ws.sent)


# ── operator への通知 ──────────────────────────────────────────────────────

def test_operator_is_told_which_stream_ended():
    """どの映像を畳めばよいか operator に伝えること。

    これが無いと operator は死んだ PeerConnection を抱えたままになる。
    """
    import json

    m = CameraSignalingManager()
    op, dev = _FakeWS("op"), _FakeWS("dev")

    async def scenario():
        await m.connect_operator("S8", op, user_id=1)
        await m.connect_device("S8", "10", dev)
        sid = m.stream_id_for("S8", "10")
        await m.disconnect_device("S8", "10", dev)
        return sid

    sid = _run(scenario())
    ended = [json.loads(s) for s in op.sent if "camera_stream_ended" in s]
    assert ended, "camera_stream_ended が送られていない"
    assert ended[0]["stream_id"] == sid
    assert ended[0]["participant_id"] == "10"


def test_device_list_carries_stream_ids():
    import json

    m = CameraSignalingManager()
    op, dev = _FakeWS("op"), _FakeWS("dev")

    async def scenario():
        await m.connect_operator("S9", op, user_id=1)
        await m.connect_device("S9", "10", dev)

    _run(scenario())
    updates = [json.loads(s) for s in op.sent if "device_list_update" in s]
    assert updates
    entry = updates[-1]["devices"][0]
    assert entry["participant_id"] == "10"
    assert entry["stream_id"], "stream_id が入っていない"


@pytest.mark.parametrize("count", [2, 3, 4])
def test_multiple_cameras_coexist_with_distinct_streams(count: int):
    """複数カメラが同時に別々の stream として並ぶこと。"""
    m = CameraSignalingManager()

    async def scenario():
        for i in range(count):
            await m.connect_device("SM", str(100 + i), _FakeWS(f"d{i}"))
        return [m.stream_id_for("SM", str(100 + i)) for i in range(count)]

    ids = _run(scenario())
    assert all(ids)
    assert len(set(ids)) == count, "stream_id が重複している"
