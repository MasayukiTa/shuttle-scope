"""S-11: 失効チェックが DB エラーで fail-open しないことのテスト。

旧実装:
  - `_is_token_revoked` は例外時に **False (= 失効していない)** を返していた
  - `_get_mass_revoke_timestamp` は例外時に **None (= 一斉失効は無い)** を返し、
    しかもその None を 5 秒キャッシュしていた

どちらも「失効しているか確認できなかった」を「失効していない」に読み替える。
**封じ込め策が、最も必要な瞬間 (incident 対応中) に開く。**

DB が落ちていればどの経路も動かないので、拒否側に倒しても可用性の実損は無い。
このファイルは `backend.main` を import しないので Python 3.10 でも走る。
"""
from __future__ import annotations

import pytest

import backend.db.database as database
import backend.utils.jwt_utils as jwt_utils


class _Boom(Exception):
    pass


@pytest.fixture()
def db_down(monkeypatch):
    """SessionLocal() が必ず例外を投げる状態にする。"""
    def _boom(*args, **kwargs):
        raise _Boom("db down")
    monkeypatch.setattr(database, "SessionLocal", _boom)
    # キャッシュは各テストで明示的に組み立てる
    monkeypatch.setitem(jwt_utils._MASS_REVOKE_CACHE, "ts", 0.0)
    monkeypatch.setitem(jwt_utils._MASS_REVOKE_CACHE, "value", None)
    return monkeypatch


def test_revoked_check_denies_when_db_unavailable(db_down):
    assert jwt_utils._is_token_revoked("any-jti") is True, (
        "失効照会ができないときに「失効していない」を返すと、"
        "DB を落とせる相手は失効を無効化できる"
    )


def test_mass_revoke_denies_everything_when_never_cached(db_down):
    """一度も成功していない状態で DB が落ちていたら全拒否 (fail closed)。

    呼び出し側は `iat < mass_revoke_at` で拒否するので、十分未来の値を返せば
    すべての token が落ちる。
    """
    assert jwt_utils._get_mass_revoke_timestamp() == jwt_utils._DENY_ALL_TS


def test_mass_revoke_does_not_poison_the_cache_on_error(db_down):
    jwt_utils._get_mass_revoke_timestamp()
    assert jwt_utils._MASS_REVOKE_CACHE["ts"] == 0.0
    assert jwt_utils._MASS_REVOKE_CACHE["value"] is None


def test_mass_revoke_falls_back_to_last_successful_value(db_down):
    """直近の成功値があるなら、それを使う (無用に全拒否しない)。

    ts を十分古くして TTL 切れにしても、DB エラー時は最後の値を返す。
    """
    db_down.setitem(jwt_utils._MASS_REVOKE_CACHE, "ts", 1.0)
    db_down.setitem(jwt_utils._MASS_REVOKE_CACHE, "value", 1_234_567)
    assert jwt_utils._get_mass_revoke_timestamp() == 1_234_567


def test_deny_all_sentinel_is_in_the_future():
    """番兵が過去だと「全拒否」にならず、静かに全許可へ戻る。"""
    import time
    assert jwt_utils._DENY_ALL_TS > int(time.time()) + 365 * 24 * 3600
