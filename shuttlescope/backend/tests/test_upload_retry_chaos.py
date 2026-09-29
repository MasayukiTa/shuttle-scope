"""P2 concurrency/retry chaos tests for the upload endpoint."""
from __future__ import annotations

import asyncio
import io
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

from backend.routers import uploads


class _FakeDb:
    def __init__(self, session):
        self.session = session
        self.commits = 0

    def get(self, _model, upload_id):
        return self.session if upload_id == self.session.id else None

    def commit(self):
        self.commits += 1


@pytest.fixture(autouse=True)
def _clean_upload_locks():
    uploads._upload_locks.clear()
    uploads._upload_lock_refs.clear()
    yield
    uploads._upload_locks.clear()
    uploads._upload_lock_refs.clear()


def _normal_session(upload_id: str):
    return SimpleNamespace(
        id=upload_id,
        status="uploading",
        user_id=7,
        participant_id=None,
        streaming=False,
        total_size=32,
        chunk_size=16,
        total_chunks=2,
        received_bitmap=b"",
        received_count=0,
        updated_at=None,
    )


def _upload_file(data: bytes) -> UploadFile:
    return UploadFile(filename="chunk.bin", file=io.BytesIO(data))


@pytest.mark.asyncio
async def test_duplicate_same_chunk_is_idempotent_under_concurrency(tmp_path, monkeypatch):
    upload_id = "00000000-0000-0000-0000-000000000071"
    session = _normal_session(upload_id)
    db = _FakeDb(session)
    part = tmp_path / f"{upload_id}.part"
    part.write_bytes(b"\x00" * session.total_size)

    monkeypatch.setattr(uploads, "_part_path", lambda _id: part)
    monkeypatch.setattr(
        uploads,
        "_resolve_upload_actor",
        lambda *_a, **_k: SimpleNamespace(user_id=7, participant_id=None),
    )
    monkeypatch.setattr(uploads, "_require_upload_owner", lambda *_a, **_k: None)
    sem = asyncio.Semaphore(8)
    monkeypatch.setattr(uploads, "_get_global_sem", lambda: sem)

    # Valid MP4-like first chunk: ftyp at byte offset 4.
    payload = b"\x00\x00\x00\x10ftyp" + b"A" * 8
    gate = asyncio.Event()

    async def send_once():
        await gate.wait()
        return await uploads.upload_chunk(
            request=SimpleNamespace(headers={}),
            upload_id=upload_id,
            chunk_index=0,
            chunk=_upload_file(payload),
            db=db,
            ctx=SimpleNamespace(role="player", user_id=7),
        )

    t1 = asyncio.create_task(send_once())
    t2 = asyncio.create_task(send_once())
    gate.set()
    results = await asyncio.gather(t1, t2)

    assert sorted(r["already_received"] for r in results) == [False, True]
    assert session.received_count == 1
    assert uploads._bitmap_get(session.received_bitmap, 0)
    assert part.read_bytes()[:16] == payload
    assert part.stat().st_size == 32
    # Only the first physical write updates metadata/commits.
    assert db.commits == 1


@pytest.mark.asyncio
async def test_out_of_order_chunk_is_rejected_before_file_write(tmp_path, monkeypatch):
    upload_id = "00000000-0000-0000-0000-000000000072"
    session = _normal_session(upload_id)
    db = _FakeDb(session)
    part = tmp_path / f"{upload_id}.part"
    initial = b"Z" * session.total_size
    part.write_bytes(initial)

    monkeypatch.setattr(uploads, "_part_path", lambda _id: part)
    monkeypatch.setattr(
        uploads,
        "_resolve_upload_actor",
        lambda *_a, **_k: SimpleNamespace(user_id=7, participant_id=None),
    )
    monkeypatch.setattr(uploads, "_require_upload_owner", lambda *_a, **_k: None)
    sem = asyncio.Semaphore(8)
    monkeypatch.setattr(uploads, "_get_global_sem", lambda: sem)

    with pytest.raises(HTTPException) as exc:
        await uploads.upload_chunk(
            request=SimpleNamespace(headers={}),
            upload_id=upload_id,
            chunk_index=1,
            chunk=_upload_file(b"B" * 16),
            db=db,
            ctx=SimpleNamespace(role="player", user_id=7),
        )

    assert exc.value.status_code == 409
    assert session.received_count == 0
    assert session.received_bitmap == b""
    assert part.read_bytes() == initial
    assert db.commits == 0


@pytest.mark.asyncio
async def test_retry_of_second_chunk_does_not_append_or_shift_bytes(tmp_path, monkeypatch):
    upload_id = "00000000-0000-0000-0000-000000000073"
    session = _normal_session(upload_id)
    session.received_bitmap = uploads._bitmap_set(b"", 0, 2)
    session.received_count = 1
    db = _FakeDb(session)
    part = tmp_path / f"{upload_id}.part"
    first = b"\x00\x00\x00\x10ftyp" + b"A" * 8
    part.write_bytes(first + b"\x00" * 16)

    monkeypatch.setattr(uploads, "_part_path", lambda _id: part)
    monkeypatch.setattr(
        uploads,
        "_resolve_upload_actor",
        lambda *_a, **_k: SimpleNamespace(user_id=7, participant_id=None),
    )
    monkeypatch.setattr(uploads, "_require_upload_owner", lambda *_a, **_k: None)
    sem = asyncio.Semaphore(8)
    monkeypatch.setattr(uploads, "_get_global_sem", lambda: sem)

    second = b"C" * 16
    first_result = await uploads.upload_chunk(
        request=SimpleNamespace(headers={}),
        upload_id=upload_id,
        chunk_index=1,
        chunk=_upload_file(second),
        db=db,
        ctx=SimpleNamespace(role="player", user_id=7),
    )
    retry_result = await uploads.upload_chunk(
        request=SimpleNamespace(headers={}),
        upload_id=upload_id,
        chunk_index=1,
        chunk=_upload_file(second),
        db=db,
        ctx=SimpleNamespace(role="player", user_id=7),
    )

    assert first_result["already_received"] is False
    assert retry_result["already_received"] is True
    assert session.received_count == 2
    assert part.read_bytes() == first + second
    assert part.stat().st_size == 32
    assert db.commits == 1



@pytest.mark.asyncio
async def test_streaming_retry_after_response_loss_is_idempotent(tmp_path, monkeypatch):
    """Server commit may succeed even when the client never receives the response."""
    upload_id = "00000000-0000-0000-0000-000000000074"
    session = _normal_session(upload_id)
    session.streaming = True
    # Streaming total_chunks is only an initial estimate; bitmap grows by index.
    session.total_chunks = 1
    db = _FakeDb(session)
    part = tmp_path / f"{upload_id}.part"
    part.write_bytes(b"")

    monkeypatch.setattr(uploads, "_part_path", lambda _id: part)
    monkeypatch.setattr(
        uploads,
        "_resolve_upload_actor",
        lambda *_a, **_k: SimpleNamespace(user_id=7, participant_id=None),
    )
    monkeypatch.setattr(uploads, "_require_upload_owner", lambda *_a, **_k: None)
    monkeypatch.setattr(uploads, "_get_global_sem", lambda: asyncio.Semaphore(8))

    payload = b"\x00\x00\x00\x10ftyp" + b"A" * 8

    # First request is committed. In the real failure mode the HTTP response is
    # then lost in transit, so the client retries the exact same chunk/index.
    first_result = await uploads.upload_chunk(
        request=SimpleNamespace(headers={}),
        upload_id=upload_id,
        chunk_index=0,
        chunk=_upload_file(payload),
        db=db,
        ctx=SimpleNamespace(role="player", user_id=7),
    )
    retry_result = await uploads.upload_chunk(
        request=SimpleNamespace(headers={}),
        upload_id=upload_id,
        chunk_index=0,
        chunk=_upload_file(payload),
        db=db,
        ctx=SimpleNamespace(role="player", user_id=7),
    )

    assert first_result["already_received"] is False
    assert retry_result["already_received"] is True
    assert session.received_count == 1
    assert uploads._bitmap_get(session.received_bitmap, 0)
    assert part.read_bytes() == payload
    assert db.commits == 1
