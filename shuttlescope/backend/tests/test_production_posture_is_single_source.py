"""本番姿勢の判定が 1 箇所に寄っていることを、**実際の本番の形**で検証する。

`main.py:192` が記録しているとおり、実本番は

    PUBLIC_MODE=False / ENVIRONMENT != "production" / HIDE_API_DOCS=1

という形をしている。`is_production_posture` はこれを True と判定するが、
`PUBLIC_MODE or ENVIRONMENT == "production"` を**ローカルに書き直していた**
4 箇所はすべて False のままだった。

2026-09-22 に本番を実測して裏を取った内容:

- NSSM の `AppEnvironmentExtra` が REG_MULTI_SZ ではなく 1 本の文字列に潰れており、
  `ENVIRONMENT=production` を含む 13 変数が 1 変数に化けていた
- その結果、本番の CSP レポートに載っていた `connect-src` は
  `'self' wss: https: http://localhost:*` ＝ **dev 側 fallback** だった

このテストは「posture は True だが ENVIRONMENT は development」という
まさにその状態を作って、各所が本番として振る舞うことを確かめる。
旧実装ではここが全部 dev 扱いになるので落ちる。
"""
from __future__ import annotations

import sqlite3
import sys

import pytest

import backend.utils.control_plane as cp
from backend.config import settings

#: `backend.main` は `typing.NotRequired` を使う insights を読み込むため 3.11+ が要る。
#: このリポジトリの慣習にならい、main を import しないテストは 3.10 でも走らせる。
_NEEDS_MAIN = pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="backend.main は Python 3.11+ が要る (typing.NotRequired)",
)


@pytest.fixture()
def real_production_shape(monkeypatch):
    """実本番と同じ形: posture は True、ただし ENVIRONMENT は development。"""
    monkeypatch.setattr(settings, "PUBLIC_MODE", False, raising=False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "development", raising=False)
    monkeypatch.setattr(settings, "HIDE_API_DOCS", True, raising=False)
    assert settings.is_production_posture is True, (
        "前提が崩れている: HIDE_API_DOCS だけで posture が True にならないなら "
        "このテストは何も検証していない"
    )
    return settings


@pytest.fixture()
def development_shape(monkeypatch):
    """開発機の形。

    ローカルの作業ツリーにも `.env.development` があり `HIDE_API_DOCS=1` が
    入っていることがある（実際に入っていた）。「テスト環境なら posture は
    False のはず」と決め打つと、その前提が崩れた瞬間に **検証していないのに
    緑**になる。明示的に dev の形を作る。
    """
    monkeypatch.setattr(settings, "PUBLIC_MODE", False, raising=False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "development", raising=False)
    monkeypatch.setattr(settings, "HIDE_API_DOCS", False, raising=False)
    monkeypatch.setattr(settings, "HIDE_STACK_TRACES", False, raising=False)
    monkeypatch.setattr(settings, "PUBLIC_HOSTNAME", "", raising=False)
    assert settings.is_production_posture is False
    return settings


class _Req:
    """socket client だけを持つリクエストのスタブ。"""

    class _Client:
        def __init__(self, host):
            self.host = host

    def __init__(self, host: str):
        self.client = self._Client(host)
        self.headers = {}
        self.scope = {"client": (host, 0)}


def test_blank_client_host_is_not_loopback_in_real_production_shape(real_production_shape):
    """ASGI バグ等で `client.host` が空でも loopback 扱いしない。

    旧実装は `ENVIRONMENT` の文字列だけを見ていたので、本番で ENVIRONMENT が
    production に届いていないと **本番が development 扱い**になり、
    空 host / testclient が loopback 認定されていた。
    """
    assert cp.is_loopback_request(_Req("")) is False
    assert cp.is_loopback_request(_Req("testclient")) is False


def test_genuine_loopback_is_still_loopback(real_production_shape):
    """本物の 127.0.0.1 は姿勢に関係なく loopback（機能 DoS を作らない）。"""
    assert cp.is_loopback_request(_Req("127.0.0.1")) is True
    assert cp.is_loopback_request(_Req("::1")) is True
    assert cp.is_loopback_request(_Req("::ffff:127.0.0.1")) is True


def test_development_still_allows_testclient(development_shape):
    """dev/test では従来どおり testclient を loopback として扱う。

    ここが壊れると TestClient を使う既存テストが一斉に 403 になる
    （R22 P1-1 で実際に起きた regression）。
    """
    assert cp.is_loopback_request(_Req("testclient")) is True


@_NEEDS_MAIN
def test_source_maps_are_refused_in_real_production_shape(real_production_shape):
    """`.map` は本番姿勢では配信しない。

    旧実装は許可拡張子の集合を **module import 時に確定**させていたので、
    設定を変えてもプロセスを再起動するまで反映されず、
    この分岐は実行時に一度も検証できなかった。
    """
    from backend.main import _assets_allowed_exts

    assert ".map" not in _assets_allowed_exts()
    assert ".js" in _assets_allowed_exts()


@_NEEDS_MAIN
def test_source_maps_are_allowed_in_development(development_shape):
    from backend.main import _assets_allowed_exts

    assert ".map" in _assets_allowed_exts()


def test_backup_refuses_plaintext_zip_in_real_production_shape(
    real_production_shape, monkeypatch, tmp_path
):
    """passphrase 未設定のまま平文 ZIP へ落ちるのを姿勢で止める。

    旧実装ではこの fail-closed が本番で一度も発動していなかった
    （passphrase が設定済みだったので平文にはならずに済んでいただけ）。
    """
    import backend.services.backup_service as bs

    db = tmp_path / "shuttlescope.db"
    sqlite3.connect(db).close()
    monkeypatch.setattr(bs.settings, "DATABASE_URL", f"sqlite:///{db}", raising=False)
    monkeypatch.setattr(bs, "get_backup_dir", lambda: tmp_path, raising=False)
    # passphrase 未設定を作る
    monkeypatch.setattr(bs, "_passphrase", lambda: None, raising=False)

    with pytest.raises(RuntimeError, match="SS_BACKUP_PASSPHRASE"):
        bs.create_backup()


@_NEEDS_MAIN
def test_csp_connect_src_is_tight_in_real_production_shape(real_production_shape):
    """CSP の `connect-src` を姿勢で決める。

    本番ログに残っていたのは dev 側の
    `connect-src 'self' wss: https: http://localhost:*` で、
    **XSS から任意の https/wss へ exfil できる状態**だった。
    """
    from fastapi.testclient import TestClient

    from backend.main import app

    with TestClient(app) as client:
        res = client.get("/", headers={"host": "app.shuttle-scope.com"})
    csp = res.headers.get("Content-Security-Policy", "")
    assert csp, "HTML レスポンスに CSP が付いていない"
    assert "connect-src 'self' https://app.shuttle-scope.com" in csp, csp
    assert "wss: https:" not in csp, f"dev 側の緩い connect-src が出ている: {csp}"
    assert "http://localhost:" not in csp, csp
