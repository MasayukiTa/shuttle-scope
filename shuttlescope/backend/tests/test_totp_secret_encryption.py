"""users.totp_secret の保存時暗号化。

背景: MFA の共有秘密が平文で保存されており、DB 単体の流出 (バックアップ /
論理ダンプ / データディレクトリ奪取) だけで攻撃者が有効な TOTP を生成できた。
EncryptedText に載せ替えたので、
  1. DB に入る実体が暗号文であること (ORM 経由では透過復号されるので raw SQL で見る)
  2. 鍵が壊れたときに「コードが違う」ではなく「MFA 利用不可」として扱われること
を固定する。
"""
import time
from datetime import datetime

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from backend.db.models import User
from backend.routers.auth import _hotp_value, _totp_secret_usable, _verify_totp
from backend.utils import field_crypto

_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"


@pytest.fixture()
def with_key(monkeypatch):
    """有効な鍵を設定し、Fernet キャッシュをテストごとに作り直す。"""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("SS_FIELD_ENCRYPTION_KEY", key)
    monkeypatch.setattr(field_crypto, "_fernet_cache", None, raising=False)
    from backend.config import settings
    monkeypatch.setattr(settings, "ss_field_encryption_key", key, raising=False)
    yield key
    monkeypatch.setattr(field_crypto, "_fernet_cache", None, raising=False)


def _current_code(secret: str) -> str:
    return f"{_hotp_value(secret, int(time.time()) // 30):06d}"


# ── 保存形式 ────────────────────────────────────────────────────────────────

def test_secret_is_ciphertext_in_the_database(db_session, with_key):
    """DB の実体が暗号文で、平文が現れないこと。"""
    user = User(username="enc_user", role="analyst", totp_secret=_SECRET,
                totp_enabled=True)
    db_session.add(user)
    db_session.commit()

    raw = db_session.execute(
        text("SELECT totp_secret FROM users WHERE id = :i"), {"i": user.id}
    ).scalar()

    assert raw != _SECRET, "平文のまま保存されている"
    assert raw.startswith("v1:"), raw[:16]
    assert _SECRET not in raw
    assert len(raw) > 64, "旧 VARCHAR(64) に収まる長さ = 暗号化されていない疑い"


def test_orm_read_returns_plaintext(db_session, with_key):
    """アプリ層は平文として扱えること (透過復号)。"""
    user = User(username="enc_user2", role="analyst", totp_secret=_SECRET)
    db_session.add(user)
    db_session.commit()
    db_session.expire_all()

    assert db_session.get(User, user.id).totp_secret == _SECRET


def test_totp_still_verifies_after_encryption(db_session, with_key):
    """暗号化しても TOTP 検証が通ること。"""
    user = User(username="enc_user3", role="analyst", totp_secret=_SECRET,
                totp_enabled=True)
    db_session.add(user)
    db_session.commit()
    db_session.expire_all()

    stored = db_session.get(User, user.id).totp_secret
    assert _verify_totp(stored, _current_code(_SECRET))


def test_legacy_plaintext_is_still_readable(db_session, with_key):
    """移行前の平文行もそのまま読めること (バックフィル前でもアプリが動く)。"""
    # raw SQL で「暗号化されていない行」を作る (EncryptedText を経由させない)
    db_session.execute(text(
        "INSERT INTO users (username, role, totp_secret, totp_enabled, "
        "failed_attempts, consent_required, awaiting_admin_approval, is_test, "
        "created_at) "
        "VALUES ('legacy_user', 'analyst', :s, 1, 0, 0, 0, 0, :now)"
    ), {"s": _SECRET, "now": datetime.utcnow()})
    db_session.commit()

    user = db_session.query(User).filter(User.username == "legacy_user").one()
    assert user.totp_secret == _SECRET
    assert _verify_totp(user.totp_secret, _current_code(_SECRET))


# ── 鍵が壊れたとき ──────────────────────────────────────────────────────────

def test_wrong_key_is_not_treated_as_a_wrong_code(db_session, with_key, monkeypatch):
    """別の鍵に差し替わったら「不一致」ではなく「使用不可」と判定されること。"""
    user = User(username="enc_user4", role="analyst", totp_secret=_SECRET)
    db_session.add(user)
    db_session.commit()

    # 鍵を別物に差し替える (= 鍵の取り違え / ローテ事故)
    other = Fernet.generate_key().decode()
    monkeypatch.setenv("SS_FIELD_ENCRYPTION_KEY", other)
    monkeypatch.setattr(field_crypto, "_fernet_cache", None, raising=False)
    from backend.config import settings
    monkeypatch.setattr(settings, "ss_field_encryption_key", other, raising=False)

    db_session.expire_all()
    stored = db_session.get(User, user.id).totp_secret
    assert stored == "[ENCRYPTED:INVALID]"
    assert not _totp_secret_usable(stored)
    # センチネルを渡しても例外にならず False (500 にしない)
    assert _verify_totp(stored, "000000") is False


def test_sentinels_are_rejected():
    for bad in ("[ENCRYPTED:KEY_MISSING]", "[ENCRYPTED:INVALID]",
                "[ENCRYPTED:ERROR]", "", None):
        assert not _totp_secret_usable(bad), bad
    assert _totp_secret_usable(_SECRET)


# ── 鍵の健全性検証 ──────────────────────────────────────────────────────────

def test_verify_key_roundtrip_passes_with_valid_key(with_key):
    field_crypto.verify_key_roundtrip()  # 例外が出なければ OK


def test_verify_key_roundtrip_fails_without_key(monkeypatch):
    monkeypatch.setenv("SS_FIELD_ENCRYPTION_KEY", "")
    monkeypatch.setattr(field_crypto, "_fernet_cache", None, raising=False)
    from backend.config import settings
    monkeypatch.setattr(settings, "ss_field_encryption_key", "", raising=False)
    with pytest.raises(field_crypto.FieldKeyError):
        field_crypto.verify_key_roundtrip()


def test_can_decrypt_distinguishes_key_mismatch(with_key, monkeypatch):
    """can_decrypt は 'v1:' 前置だけでなく実際の復号可否を見ること。"""
    token = field_crypto.encrypt_field(_SECRET)
    assert field_crypto.can_decrypt(token)
    assert not field_crypto.can_decrypt(_SECRET)  # 平文

    other = Fernet.generate_key().decode()
    monkeypatch.setenv("SS_FIELD_ENCRYPTION_KEY", other)
    monkeypatch.setattr(field_crypto, "_fernet_cache", None, raising=False)
    from backend.config import settings
    monkeypatch.setattr(settings, "ss_field_encryption_key", other, raising=False)
    # 前置は 'v1:' のままでも、別鍵では復号できない = 二重暗号化を防げる
    assert not field_crypto.can_decrypt(token)
