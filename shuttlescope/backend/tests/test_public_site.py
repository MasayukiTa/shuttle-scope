from fastapi.testclient import TestClient

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
