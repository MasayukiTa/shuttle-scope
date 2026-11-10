"""問い合わせと承認待ちユーザを、同じメールで結び付ける。"""
from __future__ import annotations

from backend.db.models import PublicInquiry, User
from backend.services.inquiry_link import (
    inquiries_by_email,
    normalize_email,
    pending_users_by_email,
    requested_role_from_text,
)


def test_normalize_email():
    assert normalize_email("  Foo@Example.COM ") == "foo@example.com"
    assert normalize_email("line: foo") is None
    assert normalize_email(None) is None


def test_requested_role_from_text():
    assert requested_role_from_text("analyst") == "analyst"
    assert requested_role_from_text("アナリスト") == "analyst"
    assert requested_role_from_text("Coach") == "coach"
    assert requested_role_from_text("選手") == "player"
    assert requested_role_from_text("コーチ兼選手") is None
    assert requested_role_from_text("") is None
    assert requested_role_from_text("助手") is None


def test_inquiry_and_pending_user_are_matched_by_normalized_email(db_session):
    db_session.add(PublicInquiry(
        name="Taro", role="analyst", contact_reference=" Taro@Example.com ", message="hello hello",
    ))
    db_session.add(PublicInquiry(
        name="Other", role="coach", contact_reference="other@example.com", message="hello hello",
    ))
    db_session.add(User(
        username="taro", role="player", email="TARO@example.com",
        awaiting_admin_approval=True, is_test=True,
    ))
    db_session.add(User(
        username="done", role="player", email="other@example.com",
        awaiting_admin_approval=False, is_test=True,
    ))
    db_session.commit()

    emails = ["taro@example.com", "other@example.com"]
    inquiries = inquiries_by_email(db_session, emails)
    assert [i.name for i in inquiries["taro@example.com"]] == ["Taro"]

    pending = pending_users_by_email(db_session, emails)
    assert set(pending) == {"taro@example.com"}
    assert pending["taro@example.com"].username == "taro"
