"""U-10: upload lock の ABA / GC 競合を防ぐ回帰テスト。"""
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from backend.routers import uploads


@pytest.fixture(autouse=True)
def _clean_upload_locks():
    uploads._upload_locks.clear()
    uploads._upload_lock_refs.clear()
    yield
    uploads._upload_locks.clear()
    uploads._upload_lock_refs.clear()


@pytest.mark.asyncio
async def test_waiter_keeps_same_lock_registered_until_it_enters():
    upload_id = "00000000-0000-0000-0000-000000000001"
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    second_entered = asyncio.Event()

    async def first():
        async with uploads._hold_upload_lock(upload_id):
            first_entered.set()
            await release_first.wait()

    async def second():
        await first_entered.wait()
        async with uploads._hold_upload_lock(upload_id):
            second_entered.set()

    t1 = asyncio.create_task(first())
    await first_entered.wait()
    original_lock = uploads._upload_locks[upload_id]

    t2 = asyncio.create_task(second())
    # second() が ref を登録して lock 待ちへ入るまで event loop を回す。
    for _ in range(20):
        if uploads._upload_lock_refs.get(upload_id) == 2:
            break
        await asyncio.sleep(0)

    assert uploads._upload_lock_refs[upload_id] == 2
    assert uploads._upload_locks[upload_id] is original_lock
    assert second_entered.is_set() is False

    release_first.set()
    await asyncio.wait_for(t1, timeout=1)
    await asyncio.wait_for(t2, timeout=1)

    assert second_entered.is_set() is True
    assert upload_id not in uploads._upload_lock_refs
    assert upload_id not in uploads._upload_locks


@pytest.mark.asyncio
async def test_different_upload_ids_do_not_block_each_other():
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    second_entered = asyncio.Event()

    async def first():
        async with uploads._hold_upload_lock("00000000-0000-0000-0000-000000000011"):
            first_entered.set()
            await release_first.wait()

    async def second():
        await first_entered.wait()
        async with uploads._hold_upload_lock("00000000-0000-0000-0000-000000000022"):
            second_entered.set()

    t1 = asyncio.create_task(first())
    t2 = asyncio.create_task(second())

    await asyncio.wait_for(second_entered.wait(), timeout=1)
    assert first_entered.is_set() is True

    release_first.set()
    await asyncio.wait_for(t1, timeout=1)
    await asyncio.wait_for(t2, timeout=1)

class _FakeDb:
    def __init__(self, current):
        self.current = current
        self.expired = []
        self.commits = 0

    def expire(self, obj):
        self.expired.append(obj)

    def get(self, _model, _id):
        return self.current

    def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_gc_rechecks_staleness_after_waiting_for_active_upload(monkeypatch):
    """GC の stale query 後に chunk が再開したら .part を消さない。"""
    upload_id = "00000000-0000-0000-0000-000000000033"
    cutoff = datetime.utcnow() - timedelta(hours=1)
    current = SimpleNamespace(
        id=upload_id,
        status="uploading",
        updated_at=cutoff - timedelta(minutes=5),
    )
    stale_snapshot = current
    db = _FakeDb(current)

    class _FakePart:
        def unlink(self, *, missing_ok=False):
            raise AssertionError("resumed upload must not be deleted by GC")

    monkeypatch.setattr(uploads, "_part_path", lambda _upload_id: _FakePart())

    holder_entered = asyncio.Event()
    release_holder = asyncio.Event()

    async def active_upload():
        async with uploads._hold_upload_lock(upload_id):
            holder_entered.set()
            await release_holder.wait()
            current.updated_at = datetime.utcnow()

    holder = asyncio.create_task(active_upload())
    await holder_entered.wait()

    gc_task = asyncio.create_task(
        uploads._expire_stale_upload_session(db, stale_snapshot, cutoff)
    )
    # Give GC a chance to register as a waiter before the active upload finishes.
    for _ in range(20):
        if uploads._upload_lock_refs.get(upload_id) == 2:
            break
        await asyncio.sleep(0)
    assert uploads._upload_lock_refs.get(upload_id) == 2

    release_holder.set()
    assert await asyncio.wait_for(gc_task, timeout=1) is False
    await asyncio.wait_for(holder, timeout=1)

    assert db.expired == [stale_snapshot]
    assert current.status == "uploading"


@pytest.mark.asyncio
async def test_gc_expires_upload_that_is_still_stale(monkeypatch):
    upload_id = "00000000-0000-0000-0000-000000000044"
    cutoff = datetime.utcnow() - timedelta(hours=1)
    current = SimpleNamespace(
        id=upload_id,
        status="uploading",
        updated_at=cutoff - timedelta(minutes=5),
    )
    db = _FakeDb(current)
    deleted = []

    class _FakePart:
        def unlink(self, *, missing_ok=False):
            deleted.append((upload_id, missing_ok))

    monkeypatch.setattr(uploads, "_part_path", lambda _upload_id: _FakePart())

    result = await uploads._expire_stale_upload_session(db, current, cutoff)

    assert result is True
    assert current.status == "expired"
    assert deleted == [(upload_id, True)]

@pytest.mark.asyncio
async def test_abort_waits_for_active_chunk_lock(monkeypatch):
    """abort は active chunk と競合せず、その完了後にだけ .part を削除する。"""
    upload_id = "00000000-0000-0000-0000-000000000055"
    session = SimpleNamespace(
        id=upload_id,
        status="uploading",
        user_id=7,
        participant_id=None,
        updated_at=datetime.utcnow(),
    )
    db = _FakeDb(session)
    deleted = []

    class _FakePart:
        def unlink(self, *, missing_ok=False):
            deleted.append((upload_id, missing_ok))

    monkeypatch.setattr(uploads, "_part_path", lambda _upload_id: _FakePart())

    holder_entered = asyncio.Event()
    release_holder = asyncio.Event()

    async def active_chunk():
        async with uploads._hold_upload_lock(upload_id):
            holder_entered.set()
            await release_holder.wait()

    holder = asyncio.create_task(active_chunk())
    await holder_entered.wait()

    abort_task = asyncio.create_task(
        uploads.abort_upload(
            upload_id,
            request=SimpleNamespace(headers={}),
            db=db,
            ctx=SimpleNamespace(role="admin", user_id=7),
        )
    )
    for _ in range(20):
        if uploads._upload_lock_refs.get(upload_id) == 2:
            break
        await asyncio.sleep(0)

    assert uploads._upload_lock_refs.get(upload_id) == 2
    assert db.commits == 0
    assert deleted == []

    release_holder.set()
    assert await asyncio.wait_for(abort_task, timeout=1) == {"success": True}
    await asyncio.wait_for(holder, timeout=1)

    assert session.status == "aborted"
    assert db.commits == 1
    assert deleted == [(upload_id, True)]
