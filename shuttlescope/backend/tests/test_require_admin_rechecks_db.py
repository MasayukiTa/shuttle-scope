"""S-11: `require_admin` が DB の現在状態を見ることのテスト。

旧実装は MFA ゲートが有効なときだけ DB を引き、しかも `totp_enabled` しか
見ていなかった。そのため:

  - `ss_require_admin_mfa=0` にすると **DB を一切見ず、token の主張だけで admin**
  - ゲートが有効でも **降格 / ロック / 承認待ちは素通り**

access token は 15 分なので、admin を外した相手がその間 admin のままでいられる。

`backend.main` を import しないので Python 3.10 でも走る。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

import backend.utils.auth as auth_mod
from backend.db.models import Base, User
from backend.utils.auth import AuthCtx, require_admin


@pytest.fixture()
def db():
    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture()
def admin_user(db):
    user = User(username="adm", role="admin", totp_enabled=True)
    db.add(user)
    db.flush()
    db.commit()
    return user


@pytest.fixture()
def as_admin(monkeypatch, admin_user):
    """MFA challenge を通過した admin token 相当のコンテキストを返す。"""
    monkeypatch.setattr(
        auth_mod, "get_auth",
        lambda request: AuthCtx(
            role="admin", player_id=None, user_id=admin_user.id, admin_mfa_ok=True,
        ),
    )
    return admin_user


def _denied(db) -> int:
    with pytest.raises(HTTPException) as exc:
        require_admin(None, db)
    return exc.value.status_code


class TestRequireAdminRechecksDb:
    def test_healthy_admin_passes(self, db, as_admin):
        """一番大事なケース。拒否だけ足して全員締め出していたら、
        それも同じだけ欠陥なので必ず一緒に確かめる。"""
        assert require_admin(None, db) is not None

    def test_demoted_in_db_is_rejected(self, db, as_admin):
        as_admin.role = "coach"
        db.commit()
        assert _denied(db) == 403

    def test_locked_account_is_rejected(self, db, as_admin):
        as_admin.locked_until = datetime.utcnow() + timedelta(minutes=30)
        db.commit()
        assert _denied(db) == 403

    def test_expired_lock_does_not_reject(self, db, as_admin):
        """ロック期間が過ぎていれば通す (過剰拒否しない)。"""
        as_admin.locked_until = datetime.utcnow() - timedelta(minutes=1)
        db.commit()
        assert require_admin(None, db) is not None

    def test_awaiting_approval_is_rejected(self, db, as_admin):
        as_admin.awaiting_admin_approval = True
        db.commit()
        assert _denied(db) == 403

    def test_deleted_user_is_rejected(self, db, as_admin):
        db.delete(as_admin)
        db.commit()
        assert _denied(db) == 403

    def test_db_is_checked_even_when_the_mfa_gate_is_off(self, db, as_admin, monkeypatch):
        """ここが旧実装の穴。ゲートを切ると DB を見なくなっていた。"""
        from backend.config import settings
        monkeypatch.setattr(settings, "ss_require_admin_mfa", False, raising=False)
        as_admin.role = "coach"
        db.commit()
        assert _denied(db) == 403

    def test_unenrolled_admin_rejected_only_while_the_gate_is_on(self, db, as_admin, monkeypatch):
        from backend.config import settings
        as_admin.totp_enabled = False
        db.commit()

        monkeypatch.setattr(settings, "ss_require_admin_mfa", True, raising=False)
        assert _denied(db) == 403

        monkeypatch.setattr(settings, "ss_require_admin_mfa", False, raising=False)
        assert require_admin(None, db) is not None


class TestCalledDirectlyWithoutDb:
    """`require_admin(request)` と直接呼ぶ経路 (リポジトリ内に 42 箇所)。

    その呼び方だと `db` は **`Depends` の既定値オブジェクトのまま**渡ってくる。
    DB を引くのが MFA ゲート有効時だけだった頃はテスト (ゲート off) で
    表面化しなかったが、常に DB を見るようにした途端
    `'Depends' object has no attribute 'get'` で 500 になった。CI が検出。
    """

    @pytest.fixture(autouse=True)
    def _point_session_local_at_this_db(self, db, monkeypatch):
        """直接呼び出しの経路は SessionLocal を自分で開くので、
        テスト用の engine に向けておく。"""
        import backend.db.database as database
        monkeypatch.setattr(database, "SessionLocal", lambda: db)

    def test_direct_call_passes_for_a_healthy_admin(self, db, as_admin):
        assert require_admin(None) is not None

    def test_direct_call_still_refuses_a_demoted_admin(self, db, as_admin):
        as_admin.role = "coach"
        db.commit()
        with pytest.raises(HTTPException) as exc:
            require_admin(None)
        assert exc.value.status_code == 403
