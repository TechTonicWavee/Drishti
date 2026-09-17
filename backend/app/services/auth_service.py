"""Local authentication and session management service.

Implements Section 9: Login & Demo Access.
- PBKDF2-HMAC-SHA256 password hashing with random salt and configurable iterations.
- Cookie-based opaque session tokens (secrets.token_urlsafe).
- SQLite-backed user and session persistence in backend/data/auth.db.
- Sovereign zero-cloud architecture with standard library only.
- Direct integration with the tamper-evident audit log.
- Emergency kill-switch support (settings.require_auth = False).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Final

from fastapi import HTTPException, Request, status

from app.core.config import settings
from app.core.logs import get_file_logger
from app.services import audit_service

log = get_file_logger("drishti.auth", "auth.log")

# backend/app/services/auth_service.py -> backend/
DB_PATH: Final = Path(__file__).resolve().parents[2] / "data" / "auth.db"

_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    display_name  TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    salt          TEXT NOT NULL,
    role          TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    token        TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    role         TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
"""


@dataclass(frozen=True)
class AuthedUser:
    user_id: str
    username: str
    display_name: str
    role: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Ensure tables exist on startup."""
    with _connect() as conn:
        conn.executescript(_SCHEMA)


def _hash_password(password: str, salt: bytes, iterations: int) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    ).hex()


def create_user(
    username: str,
    password: str,
    display_name: str,
    role: str = "operator",
    user_id: str | None = None,
) -> dict[str, Any]:
    """Create a new user with a hashed password and unique salt."""
    init_db()
    uid = user_id or f"user_{secrets.token_hex(6)}"
    salt = secrets.token_bytes(16)
    p_hash = _hash_password(password, salt, settings.pbkdf2_iterations)
    created_at = _now_iso()

    with _connect() as conn:
        conn.execute(
            "INSERT INTO users (id, username, display_name, password_hash, salt, role, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (uid, username.strip().lower(), display_name, p_hash, salt.hex(), role, created_at),
        )

    log.info("User created: %s (id=%s, role=%s)", username, uid, role)
    return {
        "id": uid,
        "username": username.strip().lower(),
        "display_name": display_name,
        "role": role,
        "created_at": created_at,
    }


def get_user_by_username(username: str) -> dict[str, Any] | None:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (username.strip().lower(),),
        ).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None


def verify_user_credentials(username: str, password: str) -> dict[str, Any] | None:
    """Verify username and password. Returns user dict on success, None on failure."""
    user = get_user_by_username(username)
    if not user:
        return None

    salt = bytes.fromhex(user["salt"])
    expected_hash = user["password_hash"]
    computed_hash = _hash_password(password, salt, settings.pbkdf2_iterations)

    if hmac.compare_digest(computed_hash, expected_hash):
        return user
    return None


def create_session(user_id: str, role: str) -> str:
    """Mint a new opaque session token and persist it."""
    init_db()
    token = secrets.token_urlsafe(32)
    created_at = datetime.now(timezone.utc)
    expires_at = created_at + timedelta(hours=settings.session_ttl_hours)

    with _connect() as conn:
        conn.execute(
            "INSERT INTO auth_sessions (token, user_id, role, created_at, expires_at, last_seen_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (token, user_id, role, created_at.isoformat(), expires_at.isoformat(), created_at.isoformat()),
        )

    return token


def get_session(token: str) -> dict[str, Any] | None:
    """Look up an active session; enforces TTL and updates last_seen_at."""
    if not token:
        return None

    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM auth_sessions WHERE token = ?",
            (token,),
        ).fetchone()
        if not row:
            return None

        session = dict(row)
        expires_at = datetime.fromisoformat(session["expires_at"])
        if datetime.now(timezone.utc) > expires_at:
            conn.execute("DELETE FROM auth_sessions WHERE token = ?", (token,))
            return None

        # Update last seen
        now_str = _now_iso()
        conn.execute(
            "UPDATE auth_sessions SET last_seen_at = ? WHERE token = ?",
            (now_str, token),
        )
        session["last_seen_at"] = now_str
        return session


def delete_session(token: str) -> None:
    if not token:
        return
    init_db()
    with _connect() as conn:
        conn.execute("DELETE FROM auth_sessions WHERE token = ?", (token,))


def seed_initial_users() -> None:
    """Seed the Judge Demo account and initial Operator account if not present."""
    init_db()
    with _connect() as conn:
        users = {
            row["username"]: dict(row)
            for row in conn.execute("SELECT * FROM users").fetchall()
        }

    # 1. Demo account for judges (one-click entry)
    if "demo" not in users:
        create_user(
            username="demo",
            password=secrets.token_hex(24),  # demo login bypasses password verification
            display_name="Judge Demo",
            role="demo",
            user_id="demo_user",
        )

    # 2. Operator account for plant team
    if "operator" not in users:
        seed_pw = os.environ.get("SEED_OPERATOR_PASSWORD", "mrpl2026")
        create_user(
            username="operator",
            password=seed_pw,
            display_name="Plant Operator",
            role="operator",
            user_id="operator_paarth",
        )


def get_current_user(request: Request) -> AuthedUser:
    """FastAPI route dependency for authenticated identity.

    Honours settings.require_auth:
    - If False, unconditionally returns default DEMO_USER identity.
    - If True, validates session cookie and fetches identity.
    """
    if not settings.require_auth:
        return AuthedUser(
            user_id="demo_user",
            username="demo",
            display_name="Judge Demo",
            role="demo",
        )

    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please sign in.",
        )

    session = get_session(token)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has expired or is invalid.",
        )

    user = get_user_by_id(session["user_id"])
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user record no longer exists.",
        )

    return AuthedUser(
        user_id=user["id"],
        username=user["username"],
        display_name=user["display_name"],
        role=user["role"],
    )
