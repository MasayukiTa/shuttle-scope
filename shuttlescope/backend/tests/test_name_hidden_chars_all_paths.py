"""D5: 名前に不可視 / 双方向制御文字が入る経路を全部塞ぐ。

以前は Player.name / 表示名に至る経路のうち、選手の作成・更新 API だけが検証していた。
次の経路は検証なしで保存されていた:
  1. 公開登録 / 招待受諾の display_name (-> ensure_player_record で Player.name になる)
  2. クイックスタートの opponent_name (-> Player.name)
  3. .sspkg / JSON パッケージ取り込みの選手名 (-> Player.name)
また検査が 3 か所に別実装で、文字集合も LRM / RLM / WJ 等が欠けていた。
ここでは 1 つの共通関数 (backend.utils.text_sanitize) がすべての経路で効くことを固定する。
"""
from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import datetime

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.db import models as M
from backend.db.database import get_db
from backend.main import app
from backend.services.import_package import import_package
from backend.tests.test_cross_team_write_scope import _seed, tok
from backend.utils.text_sanitize import reject_bidi_only, reject_ctrl_and_bidi

# 主対象 (LRM / RTLO / ZWSP) と、今回文字集合へ加えたもの (RLM / ALM / WJ / SHY)
HIDDEN = [
    "\u200e",  # LRM
    "\u202e",  # RLO
    "\u200b",  # ZWSP
    "\u200f",  # RLM
    "\u061c",  # ALM
    "\u2060",  # WJ
    "\u00ad",  # SHY
]
GOOD_NAMES = ["山田太郎", "Taro Yamada", "テスト 1", "O'Brien-Smith"]


def _bad(ch: str) -> str:
    return f"Taro{ch}Yamada"


# ── 共通関数そのもの ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("ch", HIDDEN)
def test_shared_validator_rejects_each_hidden_char(ch):
    with pytest.raises(HTTPException) as e1:
        reject_ctrl_and_bidi(_bad(ch), "name", max_len=100)
    assert e1.value.status_code == 422
    with pytest.raises(HTTPException) as e2:
        reject_bidi_only(_bad(ch), "notes", max_len=100)
    assert e2.value.status_code == 422


@pytest.mark.parametrize("name", GOOD_NAMES)
def test_shared_validator_accepts_normal_names(name):
    assert reject_ctrl_and_bidi(name, "name", max_len=100) == name


def test_legacy_duplicates_now_delegate_to_the_shared_set():
    # auth.py の旧実装は LRM / RLM を通していた
    from backend.routers.auth import _reject_control_chars

    for ch in HIDDEN:
        with pytest.raises(HTTPException):
            _reject_control_chars(_bad(ch), "display_name")


# ── 経路 1: 公開登録 / 招待受諾 ───────────────────────────────────────────────
@pytest.fixture
def api(db_session, monkeypatch):
    monkeypatch.setenv("SS_REGISTRATION_ENABLED", "1")
    from backend.config import settings

    monkeypatch.setattr(settings, "ss_registration_enabled", 1, raising=False)
    app.dependency_overrides[get_db] = lambda: db_session
    c = TestClient(app, raise_server_exceptions=False, client=("203.0.113.77", 50000))
    try:
        yield c
    finally:
        app.dependency_overrides.clear()


def _register(api, username, display_name):
    return api.post("/api/auth/register", json={
        "username": username,
        "email": f"{username}@example.com",
        "password": "Str0ng-Passw0rd-Here",
        "display_name": display_name,
        "turnstile_token": None,
    })


@pytest.mark.parametrize("ch", HIDDEN)
def test_register_rejects_hidden_chars_in_display_name(api, db_session, ch):
    before = db_session.query(M.Player).count()
    r = _register(api, "hid_reg_bad", _bad(ch))
    assert r.status_code == 422, r.text
    assert db_session.query(M.Player).count() == before
    assert db_session.query(M.User).filter_by(username="hid_reg_bad").first() is None


def test_register_still_accepts_a_normal_japanese_name(api, db_session):
    r = _register(api, "hid_reg_ok", "山田太郎")
    assert r.status_code == 201, r.text
    user = db_session.get(M.User, r.json()["data"]["user_id"])
    assert db_session.get(M.Player, user.player_id).name == "山田太郎"


@pytest.mark.parametrize("ch", HIDDEN)
def test_invitation_accept_rejects_hidden_chars_before_touching_the_token(api, ch):
    r = api.post("/api/auth/invitation/accept", json={
        "token": "x" * 20,
        "username": "hid_inv_bad",
        "password": "Str0ng-Passw0rd-Here",
        "display_name": _bad(ch),
    })
    assert r.status_code == 422, r.text


def test_invitation_accept_passes_the_name_check_for_a_normal_name(api):
    # 名前の検査は通り、その先のトークン検査で 400 になる (= 名前では弾かれない)
    r = api.post("/api/auth/invitation/accept", json={
        "token": "x" * 20,
        "username": "hid_inv_ok",
        "password": "Str0ng-Passw0rd-Here",
        "display_name": "山田太郎",
    })
    assert r.status_code == 400, r.text


def test_ensure_player_record_never_copies_a_hidden_char_name(db_session):
    # 過去に保存された値 (入口検証より前のデータ) が Player.name に写らないこと
    from backend.routers.auth import _hash_password, ensure_player_record

    u = M.User(username="legacy_hidden", role="player", display_name=_bad("\u200e"),
               hashed_credential=_hash_password("pw"))
    db_session.add(u)
    db_session.flush()
    pid = ensure_player_record(db_session, u)
    assert db_session.get(M.Player, pid).name == "legacy_hidden"


# ── 経路 2: クイックスタートの相手選手名 ─────────────────────────────────────
@pytest.fixture
def qs_client(db_session):
    _seed(db_session)
    app.dependency_overrides[get_db] = lambda: db_session
    c = TestClient(app, raise_server_exceptions=False, client=("203.0.113.9", 50000))
    try:
        yield c
    finally:
        app.dependency_overrides.clear()


def _quick_start(client, name):
    body = dict(player_a_id=1, opponent_name=name, opponent_team="Other Club")
    return client.post("/api/matches/quick-start", json=body, headers=tok("cA"))


@pytest.mark.parametrize("ch", HIDDEN)
def test_quick_start_rejects_hidden_chars_in_opponent_name(qs_client, db_session, ch):
    before = db_session.query(M.Player).count()
    r = _quick_start(qs_client, _bad(ch))
    assert r.status_code == 422, r.text
    assert db_session.query(M.Player).count() == before


@pytest.mark.parametrize("name", GOOD_NAMES)
def test_quick_start_still_accepts_normal_names(qs_client, db_session, name):
    r = _quick_start(qs_client, name)
    assert r.status_code == 201, r.text
    pid = r.json()["data"]["match"]["player_b_id"]
    assert db_session.get(M.Player, pid).name == name


# ── 経路 3: パッケージ取り込み ───────────────────────────────────────────────
def _sspkg(players: list[dict]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("players.json", json.dumps(players))
    return buf.getvalue()


def _player_rec(pk: int, name: str) -> dict:
    return {
        "id": pk,
        "uuid": str(uuid.uuid4()),
        "name": name,
        "dominant_hand": "R",
        "updated_at": datetime.utcnow().isoformat(),
    }


@pytest.mark.parametrize("ch", HIDDEN)
def test_sspkg_import_skips_a_hidden_char_name_with_a_record_error(db_session, ch):
    bad = _player_rec(1, _bad(ch))
    good = _player_rec(2, "山田太郎")
    summary = import_package(db_session, _sspkg([bad, good]), dry_run=False,
                             importer_team_id=None)
    # 不正な 1 件だけが記録付きでスキップされ、取り込み全体は止まらない
    assert any("players[" in e and bad["uuid"] in e for e in summary.errors), summary.errors
    assert db_session.query(M.Player).filter_by(uuid=bad["uuid"]).first() is None
    assert db_session.query(M.Player).filter_by(uuid=good["uuid"]).first() is not None
    assert summary.added == 1


def test_sspkg_dry_run_also_reports_the_hidden_char_name(db_session):
    bad = _player_rec(1, _bad("\u200e"))
    summary = import_package(db_session, _sspkg([bad]), dry_run=True, importer_team_id=None)
    assert summary.added == 0
    assert summary.errors


@pytest.mark.parametrize("ch", HIDDEN)
def test_json_package_rejects_a_hidden_char_player_name(ch):
    from backend.routers.data_package import _validate_imported_player_names

    with pytest.raises(HTTPException) as e:
        _validate_imported_player_names({"uuid": str(uuid.uuid4()), "name": _bad(ch)})
    assert e.value.status_code == 422
    with pytest.raises(HTTPException):
        _validate_imported_player_names(
            {"uuid": str(uuid.uuid4()), "name": "Taro", "name_en": _bad(ch)}
        )


@pytest.mark.parametrize("name", GOOD_NAMES)
def test_json_package_accepts_normal_player_names(name):
    from backend.routers.data_package import _validate_imported_player_names

    _validate_imported_player_names({"uuid": str(uuid.uuid4()), "name": name, "name_en": None})
