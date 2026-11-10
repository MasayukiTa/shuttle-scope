"""一斉失効 (mass revoke) のあとに発行された refresh token が拒否され続けない検査。

2026-10-21: 4/29 に一斉失効の sentinel が書かれて以降、sentinel が消えないため、
rotate_refresh_token は「sentinel が一つでもあれば全 refresh を拒否」していた。
再ログインで発行された新しい refresh も 15 分後の rotation で 401 になり、
管理者は access token の寿命 (15 分) ごとにログイン画面へ戻されていた。
失効より **前に発行された** refresh だけを拒否するのが正しい。

このファイルは `backend.main` を import しない。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import backend.db.database as database
import backend.utils.jwt_utils as jwt_utils
from backend.db.models import RefreshToken


def _epoch(dt: datetime) -> int:
    return int(dt.replace(tzinfo=timezone.utc).timestamp())


@pytest.fixture()
def refresh_db(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    RefreshToken.__table__.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(database, "SessionLocal", factory)
    return factory


def _issue(factory, user_id: int, issued_at: datetime) -> str:
    raw, jti, _ = jwt_utils.create_refresh_token(user_id)
    with factory() as db:
        db.add(RefreshToken(
            jti=jti,
            user_id=user_id,
            token_hash=jwt_utils._hash_refresh_token(raw),
            issued_at=issued_at,
            expires_at=issued_at + timedelta(days=7),
        ))
        db.commit()
    return raw


def _sentinel_at(monkeypatch, dt: datetime):
    monkeypatch.setattr(jwt_utils, "_get_mass_revoke_timestamp", lambda: _epoch(dt))


def test_refresh_issued_after_mass_revoke_is_accepted(refresh_db, monkeypatch):
    revoke_at = datetime.utcnow() - timedelta(days=100)
    _sentinel_at(monkeypatch, revoke_at)
    raw = _issue(refresh_db, 1, datetime.utcnow() - timedelta(minutes=10))

    rotated = jwt_utils.rotate_refresh_token(raw)

    assert rotated is not None, (
        "一斉失効のあとに再ログインして発行された refresh を拒否すると、"
        "access token の寿命ごとにログイン画面へ戻される"
    )
    assert rotated["user_id"] == 1
    assert rotated["new_token"] and rotated["new_token"] != raw


def test_refresh_issued_before_mass_revoke_is_rejected(refresh_db, monkeypatch):
    revoke_at = datetime.utcnow() - timedelta(days=1)
    _sentinel_at(monkeypatch, revoke_at)
    raw = _issue(refresh_db, 1, revoke_at - timedelta(hours=1))

    assert jwt_utils.rotate_refresh_token(raw) is None


def test_refresh_is_rejected_when_the_sentinel_cannot_be_read(refresh_db, monkeypatch):
    """DB 障害時の番兵 (遠い未来) では、どの refresh も拒否される (fail closed)。"""
    monkeypatch.setattr(
        jwt_utils, "_get_mass_revoke_timestamp", lambda: jwt_utils._DENY_ALL_TS
    )
    raw = _issue(refresh_db, 1, datetime.utcnow())

    assert jwt_utils.rotate_refresh_token(raw) is None


def test_refresh_without_any_mass_revoke_still_rotates(refresh_db, monkeypatch):
    monkeypatch.setattr(jwt_utils, "_get_mass_revoke_timestamp", lambda: None)
    raw = _issue(refresh_db, 1, datetime.utcnow())

    assert jwt_utils.rotate_refresh_token(raw) is not None


def test_issued_at_equal_to_the_revoke_second_is_rejected():
    now = datetime.utcnow().replace(microsecond=0)
    assert jwt_utils._predates_mass_revoke(now, _epoch(now)) is True
    assert jwt_utils._predates_mass_revoke(now + timedelta(seconds=1), _epoch(now)) is False
    assert jwt_utils._predates_mass_revoke(None, _epoch(now)) is True
