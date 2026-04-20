from fastapi.testclient import TestClient

from backend.config import settings
from backend.db.database import get_db
from backend.db.models import User
from backend.main import app


def test_bootstrap_status_reports_missing_admin_and_missing_password(db_session, monkeypatch):
    db_session.query(User).delete()
    db_session.commit()
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_USERNAME", "admin", raising=False)
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_DISPLAY_NAME", "Admin", raising=False)
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_PASSWORD", "", raising=False)
    app.dependency_overrides[get_db] = lambda: db_session

    try:
        client = TestClient(app)
        resp = client.get("/api/auth/bootstrap-status")
        assert resp.status_code == 200
        assert resp.json() == {
            "has_admin": False,
            "bootstrap_configured": False,
            "bootstrap_username": "admin",
            "bootstrap_display_name": "Admin",
        }
    finally:
        app.dependency_overrides.clear()


def test_password_login_bootstraps_first_admin_from_env(db_session, monkeypatch):
    db_session.query(User).delete()
    db_session.commit()
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_USERNAME", "admin", raising=False)
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_DISPLAY_NAME", "Bootstrap Admin", raising=False)
    monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_PASSWORD", "temporary-secret", raising=False)
    app.dependency_overrides[get_db] = lambda: db_session

    try:
        client = TestClient(app)
        resp = client.post(
            "/api/auth/login",
            json={
                "grant_type": "password",
                "username": "admin",
                "password": "temporary-secret",
            },
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["role"] == "admin"
        assert payload["display_name"] == "Bootstrap Admin"

        admin = db_session.query(User).filter(User.role == "admin").one()
        assert admin.username == "admin"
        assert admin.display_name == "Bootstrap Admin"
        assert admin.hashed_credential
    finally:
        app.dependency_overrides.clear()
