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
async def test_stale_operator_disconnect_does_not_clear_replacement(manager):
    """旧 socket の finally は、既に差し替わった新 operator を消さない。"""
    old_ws = _FakeWebSocket()
    new_ws = _FakeWebSocket()

    await manager.connect_operator("S_STALE", old_ws, user_id=77)

    # 実ネットワークでは old socket の終了処理と再接続が競合し得る。
    # 置換済み状態を直接作り、old_ws の finally を再現する。
    manager._sessions["S_STALE"]["operator"] = new_ws

    await manager.disconnect_operator("S_STALE", old_ws)

    assert manager._sessions["S_STALE"]["operator"] is new_ws


@pytest.mark.asyncio
async def test_owner_persists_after_disconnect(manager):
    """operator が一度切断されても session_code の owner は記録され続ける。

    Round 258 R3 P1 fix: `_gc_session_if_empty` で全 connection が無くなった場合に
    `_sessions[code]` を pop する設計。owner は別 dict (`_operator_owners`) で
    保持しており、再接続時の identity check 用に永続する。テスト assert を新仕様に
    同期: session entry は GC される (KeyError) が _operator_owners は残る。
    """
    ws = _FakeWebSocket()
    await manager.connect_operator("S3", ws, user_id=7)
    await manager.disconnect_operator("S3")
    # session entry は GC 済 (R3 P1 fix)
    assert "S3" not in manager._sessions
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


@pytest.mark.asyncio
async def test_truly_concurrent_operator_connect_has_exactly_one_winner(manager):
    """P2 chaos: simultaneous connect attempts must serialize to one operator slot."""
    ws1 = _FakeWebSocket()
    ws2 = _FakeWebSocket()
    gate = asyncio.Event()

    async def attempt(ws, user_id):
        await gate.wait()
        return await manager.connect_operator("S_RACE", ws, user_id=user_id)

    t1 = asyncio.create_task(attempt(ws1, 501))
    t2 = asyncio.create_task(attempt(ws2, 501))
    gate.set()
    results = await asyncio.gather(t1, t2)

    assert sorted(results) == [False, True]
    accepted = [ws for ws in (ws1, ws2) if ws.accepted]
    rejected = [ws for ws in (ws1, ws2) if ws.closed and not ws.accepted]
    assert len(accepted) == 1
    assert len(rejected) == 1
    assert manager._sessions["S_RACE"]["operator"] is accepted[0]
    assert manager._operator_owners["S_RACE"] == 501


@pytest.mark.asyncio
async def test_concurrent_different_users_cannot_race_owner_assignment(manager):
    """P2 chaos: first slot winner also atomically establishes session ownership."""
    ws1 = _FakeWebSocket()
    ws2 = _FakeWebSocket()
    gate = asyncio.Event()

    async def attempt(ws, user_id):
        await gate.wait()
        return await manager.connect_operator("S_OWNER_RACE", ws, user_id=user_id)

    t1 = asyncio.create_task(attempt(ws1, 601))
    t2 = asyncio.create_task(attempt(ws2, 602))
    gate.set()
    results = await asyncio.gather(t1, t2)

    assert results.count(True) == 1
    owner = manager._operator_owners["S_OWNER_RACE"]
    assert owner in (601, 602)
    winning_ws = ws1 if results[0] else ws2
    losing_ws = ws2 if results[0] else ws1
    assert manager._sessions["S_OWNER_RACE"]["operator"] is winning_ws
    assert losing_ws.accepted is False
    assert losing_ws.closed is True
