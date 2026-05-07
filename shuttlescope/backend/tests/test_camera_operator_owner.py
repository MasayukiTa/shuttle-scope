"""3rd-review #1a/#1b/#4 fix のユニットテスト

connect_operator の slot/owner check と accept 順序を直接検証する。
WS の TestClient + threading に頼らず、CameraSignalingManager を直接呼ぶ。
"""
import asyncio
import pytest

from backend.ws.camera import CameraSignalingManager


class _FakeWebSocket:
    """ws.accept() / ws.close() を記録するだけの async-mock。"""

    def __init__(self) -> None:
        self.accepted = False
        self.closed = False
        self.close_code: int | None = None
        self.close_reason: str | None = None
        self.sent: list[str] = []

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = True
        self.close_code = code
        self.close_reason = reason

    async def send_text(self, data: str) -> None:
        self.sent.append(data)


@pytest.fixture
def manager():
    return CameraSignalingManager()


# ─── #1a: accept 順序 ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_first_operator_accepts_and_owns(manager):
    """最初の operator は accept されてオーナーとして登録される"""
    ws = _FakeWebSocket()
    ok = await manager.connect_operator("S1", ws, user_id=42)
    assert ok is True
    assert ws.accepted is True
    assert ws.closed is False
    assert manager._sessions["S1"]["operator"] is ws
    assert manager._operator_owners["S1"] == 42


@pytest.mark.asyncio
async def test_second_concurrent_operator_rejected_without_accept(manager):
    """既に operator がいるセッションへの 2 人目は accept されずに close される (#1a)"""
    ws1 = _FakeWebSocket()
    ws2 = _FakeWebSocket()
    ok1 = await manager.connect_operator("S2", ws1, user_id=10)
    assert ok1 is True

    ok2 = await manager.connect_operator("S2", ws2, user_id=10)
    assert ok2 is False
    # 重要: 2 つ目は accept されてはならない (slot check 後に accept する規律)
    assert ws2.accepted is False
    assert ws2.closed is True
    assert ws2.close_code == 1013


# ─── #1b/#4: session-owner consistency ───────────────────────────────────────

@pytest.mark.asyncio
async def test_owner_persists_after_disconnect(manager):
    """operator が一度切断されても session_code の owner は記録され続ける"""
    ws = _FakeWebSocket()
    await manager.connect_operator("S3", ws, user_id=7)
    await manager.disconnect_operator("S3")
    assert manager._sessions["S3"]["operator"] is None
    # owner は残る (再接続時の identity check 用)
    assert manager._operator_owners["S3"] == 7


@pytest.mark.asyncio
async def test_different_user_cannot_take_over_owned_session(manager):
    """別ユーザは operator slot が空いていてもセッションを奪えない (#1b/#4)"""
    ws_owner = _FakeWebSocket()
    await manager.connect_operator("S4", ws_owner, user_id=100)
    await manager.disconnect_operator("S4")

    ws_intruder = _FakeWebSocket()
    ok = await manager.connect_operator("S4", ws_intruder, user_id=200)
    assert ok is False
    assert ws_intruder.accepted is False
    assert ws_intruder.closed is True
    assert ws_intruder.close_code == 4403


@pytest.mark.asyncio
async def test_same_user_can_reconnect_to_owned_session(manager):
    """元のオーナーは disconnect 後に再接続可能"""
    ws1 = _FakeWebSocket()
    await manager.connect_operator("S5", ws1, user_id=55)
    await manager.disconnect_operator("S5")

    ws2 = _FakeWebSocket()
    ok = await manager.connect_operator("S5", ws2, user_id=55)
    assert ok is True
    assert ws2.accepted is True
    assert manager._sessions["S5"]["operator"] is ws2


@pytest.mark.asyncio
async def test_user_id_none_skips_owner_check(manager):
    """loopback (token なし) で user_id=None ならオーナーチェックを skip する"""
    ws_owner = _FakeWebSocket()
    await manager.connect_operator("S6", ws_owner, user_id=42)
    await manager.disconnect_operator("S6")

    # 緊急時のローカル復帰経路: user_id 不明でも operator になれる必要がある
    ws_local = _FakeWebSocket()
    ok = await manager.connect_operator("S6", ws_local, user_id=None)
    assert ok is True
    assert ws_local.accepted is True


@pytest.mark.asyncio
async def test_new_session_first_user_id_none_does_not_lock_owner(manager):
    """user_id=None で初回接続したセッションは別ユーザの参加を妨げない"""
    ws1 = _FakeWebSocket()
    ok1 = await manager.connect_operator("S7", ws1, user_id=None)
    assert ok1 is True
    # オーナーは登録されない (None は記録しない)
    assert "S7" not in manager._operator_owners

    await manager.disconnect_operator("S7")

    ws2 = _FakeWebSocket()
    ok2 = await manager.connect_operator("S7", ws2, user_id=33)
    assert ok2 is True
    assert manager._operator_owners["S7"] == 33
