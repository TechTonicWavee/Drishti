"""Deterministic tests for Section 9 Authentication & Judge Demo Access.

Tests password hashing, credentials verification, session lifecycle,
cookie management, kill switches, and audit trail integration.

Run:
    pytest backend/tests/test_auth.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.services import audit_service, auth_service  # noqa: E402


@pytest.fixture(autouse=True)
def setup_auth_db(tmp_path):
    """Ensure isolated tables exist and seeded accounts are populated before each test."""
    orig_auth_db = auth_service.DB_PATH
    orig_audit_db = audit_service.DB_PATH
    orig_audit_wm = audit_service.WATERMARK_PATH

    auth_service.DB_PATH = tmp_path / "auth.db"
    audit_service.DB_PATH = tmp_path / "audit.db"
    audit_service.WATERMARK_PATH = tmp_path / ".audit_watermark"

    auth_service.init_db()
    auth_service.seed_initial_users()
    orig_require_auth = settings.require_auth
    orig_demo_enabled = settings.demo_login_enabled
    yield
    settings.require_auth = orig_require_auth
    settings.demo_login_enabled = orig_demo_enabled

    auth_service.DB_PATH = orig_auth_db
    audit_service.DB_PATH = orig_audit_db
    audit_service.WATERMARK_PATH = orig_audit_wm


def test_seed_initial_users():
    """Verify demo and operator accounts are seeded with proper metadata."""
    demo = auth_service.get_user_by_username("demo")
    assert demo is not None
    assert demo["id"] == "demo_user"
    assert demo["role"] == "demo"
    assert demo["display_name"] == "Judge Demo"

    operator = auth_service.get_user_by_username("operator")
    assert operator is not None
    assert operator["role"] == "operator"
    assert operator["display_name"] == "Plant Operator"


def test_password_hashing_and_verification():
    """Verify PBKDF2-HMAC-SHA256 password hashing and timing-safe matching."""
    # Test operator password (default mrpl2026 or env)
    verified = auth_service.verify_user_credentials("operator", "mrpl2026")
    assert verified is not None
    assert verified["username"] == "operator"

    # Wrong password must fail
    wrong = auth_service.verify_user_credentials("operator", "wrong_password_123")
    assert wrong is None

    # Non-existent user must fail
    non_existent = auth_service.verify_user_credentials("ghost_engineer", "any_password")
    assert non_existent is None


def test_session_lifecycle():
    """Verify session minting, retrieval, and explicit deletion."""
    token = auth_service.create_session("demo_user", "demo")
    assert token is not None
    assert len(token) >= 32

    # Lookup
    session = auth_service.get_session(token)
    assert session is not None
    assert session["user_id"] == "demo_user"
    assert session["role"] == "demo"

    # Deletion
    auth_service.delete_session(token)
    assert auth_service.get_session(token) is None


def test_session_expiry():
    """Verify expired sessions are purged upon lookup."""
    token = auth_service.create_session("demo_user", "demo")

    # Manually expire the session in auth.db
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    with auth_service._connect() as conn:
        conn.execute("UPDATE auth_sessions SET expires_at = ? WHERE token = ?", (past, token))

    # Lookup must detect expiration, delete row, and return None
    assert auth_service.get_session(token) is None


def test_login_endpoint_success_and_failure():
    """Test POST /auth/login with valid vs invalid credentials."""
    client = TestClient(app)

    # 1. Failed login
    res_fail = client.post("/auth/login", json={"username": "operator", "password": "bad_password"})
    assert res_fail.status_code == 401
    assert "Invalid username or password" in res_fail.json()["detail"]
    assert settings.session_cookie_name not in res_fail.cookies

    # 2. Successful login
    res_ok = client.post("/auth/login", json={"username": "operator", "password": "mrpl2026"})
    assert res_ok.status_code == 200
    data = res_ok.json()
    assert data["username"] == "operator"
    assert data["role"] == "operator"
    assert settings.session_cookie_name in res_ok.cookies


def test_demo_login_endpoint():
    """Test POST /auth/demo: instant one-click judge access with no password."""
    client = TestClient(app)
    settings.demo_login_enabled = True

    res = client.post("/auth/demo")
    assert res.status_code == 200
    data = res.json()
    assert data["user_id"] == "demo_user"
    assert data["role"] == "demo"
    assert data["display_name"] == "Judge Demo"
    assert settings.session_cookie_name in res.cookies

    # Calling twice in a row must succeed cleanly (judges click twice)
    res2 = client.post("/auth/demo")
    assert res2.status_code == 200
    assert settings.session_cookie_name in res2.cookies


def test_auth_me_and_logout_flow():
    """Test GET /auth/me and POST /auth/logout flow."""
    client = TestClient(app)
    settings.require_auth = True

    # Anonymous request without cookie must be 401
    res_anon = client.get("/auth/me")
    assert res_anon.status_code == 401

    # Login as demo (sets cookie on client)
    login_res = client.post("/auth/demo")
    assert login_res.status_code == 200

    # Authenticated /auth/me (cookie is sent automatically)
    res_me = client.get("/auth/me")
    assert res_me.status_code == 200
    assert res_me.json()["user_id"] == "demo_user"

    # Logout (clears cookie on client and invalidates session)
    res_logout = client.post("/auth/logout")
    assert res_logout.status_code == 200
    assert res_logout.json()["status"] == "logged_out"

    # After logout, request must be 401
    res_after = client.get("/auth/me")
    assert res_after.status_code == 401


def test_emergency_kill_switch():
    """When require_auth=False, all protected routes must allow access as DEMO_USER."""
    client = TestClient(app)
    settings.require_auth = False

    # GET /auth/me without cookies returns demo user
    res = client.get("/auth/me")
    assert res.status_code == 200
    assert res.json()["user_id"] == "demo_user"

    # GET /threads without cookies returns 200
    threads_res = client.get("/threads")
    assert threads_res.status_code == 200


def test_audit_integrity_after_auth():
    """Verify that all auth actions record into the audit log and the hash chain remains intact."""
    client = TestClient(app)

    # Perform a sequence of auth actions
    client.post("/auth/login", json={"username": "operator", "password": "mrpl2026"})
    client.post("/auth/login", json={"username": "intruder", "password": "wrong"})
    client.post("/auth/demo")
    client.post("/auth/logout")

    # Verify audit chain integrity
    integrity = audit_service.verify_chain_integrity()
    assert integrity["intact"] is True
    assert integrity["total_rows"] > 0
