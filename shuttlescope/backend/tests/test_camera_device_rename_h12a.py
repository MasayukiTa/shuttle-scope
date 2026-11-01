"""h12a: device_rename と device_list 通知に device_name を含めること。

背景:
  カメラセッションでは participant の device_name が WS 接続時に一度読まれるだけで、
  device_list_update には含まれていなかった。participant が自分の端末名を変更できる
  device_rename を追加し、更新を device_list 通知に集約する。

行は API を通さず直接 ORM で作るので、default の無い NOT NULL 列を全て埋める。
"""
from __future__ import annotations

import asyncio
import json
from datetime import date

import pytest

from backend.db import database as db_module
from backend.db.models import Match, Player, SharedSession, SessionParticipant
from backend.ws.camera import CameraSignalingManager, camera_manager


@pytest.fixture(autouse=True)
def _clean_state():
    yield
    camera_manager._sessions.clear()
    camera_manager._operator_owners.clear()


class _FakeWS:
    def __init__(self):
        self.sent: list[dict] = []
        self.closed_with = None

    async def accept(self):
        pass

    async def send_text(self, text):
        self.sent.append(json.loads(text))

    async def close(self, code=1000, reason=""):
        self.closed_with = (code, reason)


def _make_session_and_participant(code, device_name):
    """active session と participant を作り (session_id, participant_id) を返す。default の無い NOT NULL 列を全て埋める。"""
    db = db_module.SessionLocal()
    try:
        pa = Player(name=f"{code}_A")
        pb = Player(name=f"{code}_B")
        db.add_all([pa, pb])
        db.flush()
        match = Match(
            tournament="PT Test", tournament_level="IC", round="R1",
            date=date(2026, 8, 15), format="singles",
            player_a_id=pa.id, player_b_id=pb.id, result="win",
        )
        db.add(match)
        db.flush()
        session = SharedSession(
            match_id=match.id, session_code=code, created_by_role="analyst",
            is_active=True,
        )
        db.add(session)
        db.flush()
        participant = SessionParticipant(
            session_id=session.id, role="viewer", device_name=device_name,
        )
        db.add(participant)
        db.commit()
        return session.id, participant.id
    finally:
        db.close()


def _device_name_in_db(participant_id):
    db = db_module.SessionLocal()
    try:
        row = db.query(SessionParticipant.device_name).filter(
            SessionParticipant.id == participant_id
        ).first()
        return row[0] if row else None
    finally:
        db.close()


def test_rename_strips_and_stores_and_notifies():
    code = "RENAME1"
    _sid, pid = _make_session_and_participant(code, "old name")

    async def scenario():
        mgr = CameraSignalingManager()
        operator = _FakeWS()
        device = _FakeWS()
        mgr._ensure_session(code)
        mgr._sessions[code]["operator"] = operator
        await mgr.connect_device(code, str(pid), device)
        operator.sent.clear()
        stored = await mgr.apply_device_rename(code, str(pid), "  Court 1 iPad  ")
        return stored, operator

    stored, operator = asyncio.run(scenario())
    assert stored == "Court 1 iPad"
    assert _device_name_in_db(pid) == "Court 1 iPad"
    updates = [m for m in operator.sent if m.get("type") == "device_list_update"]
    assert updates, "device_list_update が operator に届いていない"
    dev = updates[-1]["devices"][0]
    assert dev["participant_id"] == str(pid)
    assert dev["device_name"] == "Court 1 iPad"


def test_rename_rejects_empty_or_whitespace_only():
    code = "RENAME2"
    _sid, pid = _make_session_and_participant(code, "keep me")

    async def scenario():
        mgr = CameraSignalingManager()
        mgr._ensure_session(code)
        r1 = await mgr.apply_device_rename(code, str(pid), "   ")
        r2 = await mgr.apply_device_rename(code, str(pid), "")
        r3 = await mgr.apply_device_rename(code, str(pid), None)
        return r1, r2, r3

    r1, r2, r3 = asyncio.run(scenario())
    assert r1 is None and r2 is None and r3 is None
    assert _device_name_in_db(pid) == "keep me"


def test_rename_is_length_limited():
    code = "RENAME3"
    _sid, pid = _make_session_and_participant(code, None)

    async def scenario():
        mgr = CameraSignalingManager()
        mgr._ensure_session(code)
        return await mgr.apply_device_rename(code, str(pid), "x" * 500)

    stored = asyncio.run(scenario())
    assert stored is not None
    assert len(stored) == 100
    assert len(_device_name_in_db(pid)) == 100


def test_rename_refuses_a_participant_from_another_session():
    """自分の session に属さない participant は変更できない。"""
    code_a = "RENAMEA"
    code_b = "RENAMEB"
    _sid_a, pid_a = _make_session_and_participant(code_a, "a-name")
    _sid_b, pid_b = _make_session_and_participant(code_b, "b-name")

    async def scenario():
        mgr = CameraSignalingManager()
        mgr._ensure_session(code_a)
        return await mgr.apply_device_rename(code_a, str(pid_b), "hijack")

    result = asyncio.run(scenario())
    assert result is None
    assert _device_name_in_db(pid_b) == "b-name"


def test_device_list_notification_includes_device_name():
    code = "DLNAME1"
    _sid, pid = _make_session_and_participant(code, "Baseline Cam")

    async def scenario():
        mgr = CameraSignalingManager()
        operator = _FakeWS()
        device = _FakeWS()
        mgr._ensure_session(code)
        mgr._sessions[code]["operator"] = operator
        operator.sent.clear()
        await mgr.connect_device(code, str(pid), device)
        return operator

    operator = asyncio.run(scenario())
    updates = [m for m in operator.sent if m.get("type") == "device_list_update"]
    assert updates, "device_list_update が届いていない"
    dev = updates[-1]["devices"][0]
    assert "device_name" in dev, "通知に device_name が含まれていない"
    assert dev["device_name"] == "Baseline Cam"
