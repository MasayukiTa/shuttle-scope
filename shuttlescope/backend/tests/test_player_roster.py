"""backend/utils/player_roster.py のユニットテスト (DB 不要・スタブ)。"""
from __future__ import annotations

from backend.utils.player_roster import (
    ROLE_KEYS,
    match_role_to_player_id,
    resolve_player_uuid,
    load_match_roster_uuids,
)


class _Match:
    def __init__(self, a=None, b=None, pa=None, pb=None):
        self.player_a_id = a
        self.player_b_id = b
        self.partner_a_id = pa
        self.partner_b_id = pb


class _Player:
    def __init__(self, uuid):
        self.uuid = uuid


class _FakeDB:
    """`.get(Model, pk)` のみ実装する最小スタブ。Match/Player をクラス名で振り分ける。"""

    def __init__(self, match, players: dict):
        self._match = match
        self._players = players  # {id: _Player}

    def get(self, model, pk):
        if model.__name__ == "Match":
            return self._match if pk == 1 else None
        if model.__name__ == "Player":
            return self._players.get(pk)
        return None


def test_match_role_to_player_id():
    m = _Match(a=10, b=20, pa=30, pb=40)
    assert match_role_to_player_id(m, "player_a") == 10
    assert match_role_to_player_id(m, "player_b") == 20
    assert match_role_to_player_id(m, "partner_a") == 30
    assert match_role_to_player_id(m, "partner_b") == 40
    assert match_role_to_player_id(m, "other") is None
    assert match_role_to_player_id(m, "bogus") is None


def test_resolve_player_uuid():
    roster = {"player_a": "uuid-A", "player_b": "uuid-B"}
    assert resolve_player_uuid(roster, "player_a") == "uuid-A"
    assert resolve_player_uuid(roster, "player_b") == "uuid-B"
    assert resolve_player_uuid(roster, "partner_a") is None  # 未登録
    assert resolve_player_uuid(roster, "other") is None
    assert resolve_player_uuid(roster, None) is None


def test_load_roster_doubles(monkeypatch):
    import backend.db.models as _models  # noqa: F401  (import 可能性確認)

    m = _Match(a=10, b=20, pa=30, pb=40)
    db = _FakeDB(m, {10: _Player("ua"), 20: _Player("ub"), 30: _Player("upa"), 40: _Player("upb")})
    roster = load_match_roster_uuids(db, 1)
    assert roster == {"player_a": "ua", "player_b": "ub", "partner_a": "upa", "partner_b": "upb"}


def test_load_roster_singles_omits_partners():
    m = _Match(a=10, b=20, pa=None, pb=None)
    db = _FakeDB(m, {10: _Player("ua"), 20: _Player("ub")})
    roster = load_match_roster_uuids(db, 1)
    assert roster == {"player_a": "ua", "player_b": "ub"}
    assert "partner_a" not in roster


def test_load_roster_missing_match():
    db = _FakeDB(None, {})
    assert load_match_roster_uuids(db, 1) == {}


def test_load_roster_player_without_uuid():
    m = _Match(a=10, b=20)

    class _NoUuid:
        uuid = None

    db = _FakeDB(m, {10: _NoUuid(), 20: _Player("ub")})
    roster = load_match_roster_uuids(db, 1)
    assert roster == {"player_b": "ub"}  # uuid 無しは除外
