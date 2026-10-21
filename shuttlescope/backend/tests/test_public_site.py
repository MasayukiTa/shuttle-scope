from fastapi.testclient import TestClient

from backend.config import settings

from backend.db.database import get_db
from backend.db.models import PublicInquiry
from backend.main import app


def test_public_preview_page_is_available(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        resp = client.get("/public-preview")
        assert resp.status_code == 200
        assert "ShuttleScope" in resp.text
        assert "お問い合わせ" in resp.text
    finally:
        app.dependency_overrides.clear()


def test_public_contact_submission_persists_inquiry(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        resp = client.post(
            "/api/public/contact",
            json={
                "name": "Test User",
                "organization": "Demo Team",
                "role": "coach",
                "contact_reference": "chat handle",
                "message": "I would like to learn more about ShuttleScope for team review workflows.",
                "website": "",
            },
        )
        assert resp.status_code == 200
        item = db_session.query(PublicInquiry).one()
        assert item.name == "Test User"
        assert item.status == "new"
    finally:
        app.dependency_overrides.clear()


def test_admin_can_list_and_update_inquiries(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        inquiry = PublicInquiry(
            name="Inbox User",
            organization="Admin Team",
            role="analyst",
            contact_reference="inbox-handle",
            message="Please tell me more about the service.",
            status="new",
        )
        db_session.add(inquiry)
        db_session.commit()

        client = TestClient(app)
        list_resp = client.get("/api/public/inquiries", headers={"X-Role": "admin"})
        assert list_resp.status_code == 200
        rows = list_resp.json()["data"]
        assert any(row["name"] == "Inbox User" for row in rows)

        count_resp = client.get("/api/public/inquiries/unread-count", headers={"X-Role": "admin"})
        assert count_resp.status_code == 200
        assert count_resp.json()["data"]["count"] >= 1

        update_resp = client.patch(
            f"/api/public/inquiries/{inquiry.id}",
            headers={"X-Role": "admin"},
            json={"status": "reviewed", "admin_note": "Follow up in app"},
        )
        assert update_resp.status_code == 200

        db_session.refresh(inquiry)
        assert inquiry.status == "reviewed"
        assert inquiry.admin_note == "Follow up in app"
    finally:
        app.dependency_overrides.clear()


def test_non_admin_cannot_access_inquiries(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        resp = client.get("/api/public/inquiries", headers={"X-Role": "coach"})
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()


def _get_contact(monkeypatch, path: str, enabled: int) -> str:
    monkeypatch.setattr(settings, "ss_registration_enabled", enabled, raising=False)
    resp = TestClient(app).get(path)
    assert resp.status_code == 200
    return resp.text


def test_contact_page_ja_has_no_limited_offer_or_internal_notes(monkeypatch):
    html = _get_contact(monkeypatch, "/public-preview/contact", 1)
    assert "限定提供" not in html
    assert "管理画面" not in html
    assert "ご賛同" not in html
    # 訪問者に必要なこと: 何を書くか・返信先・登録もできること
    assert "ご記入の連絡先へ返信します" in html
    assert "https://app.shuttle-scope.com/#/register" in html


def test_contact_page_en_has_no_limited_offer_or_internal_notes(monkeypatch):
    html = _get_contact(monkeypatch, "/public-preview/en/contact", 1)
    assert "limited-availability" not in html
    assert "administration interface" not in html
    assert "We will reply there." in html
    assert "https://app.shuttle-scope.com/#/register" in html


def test_contact_page_hides_registration_when_disabled(monkeypatch):
    for path in ("/public-preview/contact", "/public-preview/en/contact"):
        html = _get_contact(monkeypatch, path, 0)
        assert "無料で登録して試す" not in html
        assert "sign up free</a>" not in html
        assert "お問い合わせなしで" not in html


def test_contact_language_toggle_has_localized_accessible_name(monkeypatch):
    html = _get_contact(monkeypatch, "/public-preview/contact", 1)
    assert 'data-label-ja="言語を切り替える(English)"' in html
    assert 'data-label-en="Switch language (日本語)"' in html
    assert "getAttribute('data-label-'+lang)" in html
