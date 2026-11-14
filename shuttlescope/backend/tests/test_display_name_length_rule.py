"""display_name 6\u301c24 \u6587\u5b57\u30eb\u30fc\u30eb (\u8981\u671b 6-24) \u306e\u56de\u5e30\u30c6\u30b9\u30c8\u3002\u5024\u306f\u3059\u3079\u3066\u67b6\u7a7a\u3002

\u30eb\u30fc\u30eb\u306f backend.utils.text_sanitize \u306b\u4e00\u672c\u5316\u3055\u308c\u3066\u304a\u308a\u3001\u5404\u30a8\u30f3\u30c8\u30ea\u30dd\u30a4\u30f3\u30c8
(admin create / admin update / \u516c\u958b\u767b\u9332 / \u62db\u5f85\u53d7\u8afe) \u304c\u540c\u3058\u95a2\u6570\u3092\u547c\u3076\u3002

- \u6587\u5b57\u6570\u306f trim \u5f8c\u306e Unicode \u30b3\u30fc\u30c9\u30dd\u30a4\u30f3\u30c8\u6570 (\u5168\u89d2\u3082 1 \u6587\u5b57)\u3002
- \u5236\u5fa1 / BIDI / \u30bc\u30ed\u5e45\u6587\u5b57\u306f 422\u3002
- \u30eb\u30fc\u30eb\u5c0e\u5165\u524d\u306e\u975e\u9069\u5408\u540d\u306f display_name_conforms=False \u3067\u30de\u30fc\u30af\u3055\u308c\u308b\u3002
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import User
from backend.main import app
from backend.utils.jwt_utils import create_access_token
from backend.utils.text_sanitize import (
    DISPLAY_NAME_MIN_LENGTH,
    DISPLAY_NAME_MAX_LENGTH,
    display_name_conforms,
    trim_display_name,
    validate_admin_display_name,
    validate_display_name,
)


# \u2500\u2500 \u30e6\u30cb\u30c3\u30c8\u30c6\u30b9\u30c8 (\u30b5\u30fc\u30d0\u30fc\u4e0d\u8981) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def test_rule_bounds_are_6_and_24():
    assert DISPLAY_NAME_MIN_LENGTH == 6
    assert DISPLAY_NAME_MAX_LENGTH == 24


@pytest.mark.parametrize("value", [
    "abcdef",            # 6 ASCII
    "a" * 24,            # 24 ASCII
    "\u5c71\u7530\u592a\u90ce\u3055\u3093",        # 6 \u5168\u89d2
    "\u5c71\u7530 \u592a\u90ce \u82b1\u5b50",     # \u5185\u90e8\u7a7a\u767d\u542b\u3080 8 \u6587\u5b57
])
def test_valid_names_pass_and_are_returned_trimmed(value):
    out = validate_display_name(value, "display_name")
    assert out == trim_display_name(value)
    assert display_name_conforms(value) is True


@pytest.mark.parametrize("value", [
    "abcde",             # 5 ASCII
    "a" * 5,
    "\u5c71\u7530\u592a\u90ce\u3055",          # 5 \u5168\u89d2
    "a" * 25,            # 25 ASCII
    "\u5c71" * 25,           # 25 \u5168\u89d2
    "   ",               # \u7a7a\u767d\u306e\u307f \u2192 trim \u3067\u7a7a
])
def test_out_of_range_names_raise_422(value):
    with pytest.raises(HTTPException) as e:
        validate_display_name(value, "display_name")
    assert e.value.status_code == 422
    assert display_name_conforms(value) is False


def test_full_width_counts_as_one_char():
    # 6 \u5168\u89d2 = 6 \u6587\u5b57\u3068\u3057\u3066 OK (byte \u6570\u3084 UTF-16 \u5358\u4f4d\u3067\u306f\u306a\u3044)
    assert validate_display_name("\u30c6\u30b9\u30c8\u30e6\u30fc\u30b6", "d") == "\u30c6\u30b9\u30c8\u30e6\u30fc\u30b6"
    # 24 \u5168\u89d2\u307e\u3067 OK
    v = "\u3042" * 24
    assert validate_display_name(v, "d") == v


def test_surrounding_whitespace_is_trimmed_before_count():
    # ASCII / \u8868\u610f\u7a7a\u767d\u3069\u3061\u3089\u3082 trim
    assert validate_display_name("  abcdef  ", "d") == "abcdef"
    assert validate_display_name("\u3000\u3000\u3042\u3044\u3046\u3048\u304a\u304b\u3000", "d") == "\u3042\u3044\u3046\u3048\u304a\u304b"


@pytest.mark.parametrize("bad", [
    "abcd\x00ef",        # NUL
    "abcd\u200bef",      # ZWSP
    "abcd\u202eef",      # RLO (BIDI)
    "abcd\ufeffef",      # BOM
])
def test_control_and_hidden_chars_raise_422(bad):
    with pytest.raises(HTTPException) as e:
        validate_display_name(bad, "display_name")
    assert e.value.status_code == 422
    assert display_name_conforms(bad) is False


def test_none_is_rejected_by_validator_but_conforms_false():
    with pytest.raises(HTTPException):
        validate_display_name(None, "display_name")
    assert display_name_conforms(None) is False


# \u2500\u2500 \u30a8\u30f3\u30c9\u30dd\u30a4\u30f3\u30c8\u30c6\u30b9\u30c8 (admin create / update) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

ADMIN_ID = 99


def _admin_headers():
    tok = create_access_token(user_id=ADMIN_ID, role="admin", player_id=None, team_name=None, team_id=None)
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def client(db_session):
    # _require_admin \u306f DB \u3092\u518d\u78ba\u8a8d\u3059\u308b\u306e\u3067\u3001token \u306e user_id \u3068\u4e00\u81f4\u3059\u308b
    # admin User \u884c\u3092\u5b9f\u5728\u3055\u305b\u308b (totp \u306f conftest \u306e SS_REQUIRE_ADMIN_MFA=0 \u3067\u4e0d\u8981)\u3002
    admin = User(
        id=ADMIN_ID, username="admin_seed", role="admin",
        display_name="Seed Admin", hashed_credential=None,
        awaiting_admin_approval=False,
    )
    db_session.add(admin)
    db_session.commit()
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def _create_payload(display_name):
    return {
        "role": "analyst",
        "display_name": display_name,
        "username": "newanalyst",
        "password": "Abcd1234!xyz",
        "team_name": "T",
    }


@pytest.mark.parametrize("name", ["abcde", "a" * 25, "\u5c71\u7530\u592a"])
def test_create_user_rejects_non_conforming_display_name(client, name):
    r = client.post("/api/auth/users", json=_create_payload(name), headers=_admin_headers())
    assert r.status_code == 422, r.text


def test_create_user_accepts_conforming_and_trims(client, db_session):
    r = client.post("/api/auth/users", json=_create_payload("  \u5c71\u7530\u592a\u90ce\u3055\u3093  "), headers=_admin_headers())
    assert r.status_code == 201, r.text
    created = db_session.query(User).filter(User.username == "newanalyst").first()
    assert created is not None
    assert created.display_name == "\u5c71\u7530\u592a\u90ce\u3055\u3093"  # trim \u6e08\u307f


def test_update_user_allows_admin_to_set_short_legacy_name(client, db_session):
    # admin の明示的な rename は 6～24 を課さない。レガシーな短い名 (4 文字)
    # への変更を admin は行える (200)。登録時の 6～24 ルールとは別。
    target = User(username="target1", role="analyst", display_name="Conforming Name", team_name="T")
    db_session.add(target)
    db_session.commit()
    r = client.put(
        f"/api/auth/users/{target.id}",
        json={"display_name": "Yuki"},  # 4 文字 (< 6)
        headers=_admin_headers(),
    )
    assert r.status_code == 200, r.text
    db_session.refresh(target)
    assert target.display_name == "Yuki"  # admin は短い名を設定できる
    # この名は 6～24 ルールには非適合なのでマーカーは False。
    assert display_name_conforms("Yuki") is False


def test_update_user_still_rejects_control_chars_on_change(client, db_session):
    # admin 変更でも技術的に危険な制御 / ゼロ幅文字は 422 のまま。
    target = User(username="target1b", role="analyst", display_name="Conforming Name", team_name="T")
    db_session.add(target)
    db_session.commit()
    r = client.put(
        f"/api/auth/users/{target.id}",
        json={"display_name": "Ab\u200bcd"},  # ZWSP 混入
        headers=_admin_headers(),
    )
    assert r.status_code == 422, r.text
    db_session.refresh(target)
    assert target.display_name == "Conforming Name"  # 変更なし


def test_update_user_resend_same_legacy_name_is_ok(client, db_session):
    # stored がレガシー短名 (3 文字) のユーザーに、同値の display_name を
    # そのまま再送しても (UI が全 field を PUT するケース) 422 にならず通る。
    legacy = User(username="legacy_resend", role="analyst", display_name="Bob", team_name="T")
    db_session.add(legacy)
    db_session.commit()
    r = client.put(
        f"/api/auth/users/{legacy.id}",
        json={"display_name": "Bob", "team_name": "T2"},
        headers=_admin_headers(),
    )
    assert r.status_code == 200, r.text
    db_session.refresh(legacy)
    assert legacy.display_name == "Bob"
    assert legacy.team_name == "T2"


def test_update_user_none_display_name_is_change_nothing(client, db_session):
    target = User(username="target2", role="analyst", display_name="Conforming Name", team_name="T")
    db_session.add(target)
    db_session.commit()
    r = client.put(
        f"/api/auth/users/{target.id}",
        json={"team_name": "T2"},  # display_name \u672a\u6307\u5b9a
        headers=_admin_headers(),
    )
    assert r.status_code == 200, r.text
    db_session.refresh(target)
    assert target.display_name == "Conforming Name"


def test_user_list_marks_legacy_non_conforming_names(client, db_session):
    # \u30eb\u30fc\u30eb\u5c0e\u5165\u524d\u306e\u77ed\u3044\u540d\u3092\u76f4\u63a5 DB \u306b\u633f\u5165 (\u30d0\u30ea\u30c7\u30fc\u30bf\u3092\u901a\u3055\u306a\u3044)
    legacy = User(username="legacy1", role="analyst", display_name="Bob", team_name="T")
    good = User(username="good1", role="analyst", display_name="Conforming Name", team_name="T")
    db_session.add_all([legacy, good])
    db_session.commit()
    r = client.get("/api/auth/users", headers=_admin_headers())
    assert r.status_code == 200, r.text
    rows = {row["username"]: row for row in r.json()["data"]}
    assert rows["legacy1"]["display_name_conforms"] is False
    assert rows["good1"]["display_name_conforms"] is True
