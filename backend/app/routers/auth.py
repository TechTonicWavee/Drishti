"""Authentication routes for Drishti Workbench.

Implements Section 9.3:
    POST /auth/login  - credentials verification & session minting
    POST /auth/demo   - one-click judge demo session minting
    POST /auth/logout - session termination & cookie clearance
    GET  /auth/me     - session validation & identity check
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.core.config import settings
from app.services import audit_service, auth_service
from app.services.auth_service import AuthedUser

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class UserResponse(BaseModel):
    user_id: str
    username: str
    display_name: str
    role: str


class LogoutResponse(BaseModel):
    status: str = "logged_out"


def _set_session_cookie(response: Response, token: str) -> None:
    max_age = int(settings.session_ttl_hours * 3600)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=False,  # Required: plain HTTP over local/plant LAN
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        httponly=True,
        samesite="lax",
        secure=False,
    )


@router.post("/login", response_model=UserResponse)
async def login(body: LoginRequest, response: Response) -> UserResponse:
    """Authenticate with username and password."""
    user = auth_service.verify_user_credentials(body.username, body.password)
    if not user:
        audit_service.record_event(
            event_type="auth_login_failed",
            user_id=body.username.strip().lower(),
            summary=f"Failed login attempt for username '{body.username.strip().lower()}'",
            source_component="auth",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )

    token = auth_service.create_session(user["id"], user["role"])
    _set_session_cookie(response, token)

    audit_service.record_event(
        event_type="auth_login",
        user_id=user["id"],
        summary=f"User {user['id']} ({user['username']}) authenticated successfully",
        source_component="auth",
    )

    return UserResponse(
        user_id=user["id"],
        username=user["username"],
        display_name=user["display_name"],
        role=user["role"],
    )


@router.post("/demo", response_model=UserResponse)
async def demo_login(response: Response) -> UserResponse:
    """One-click judge and demo access without credentials."""
    if not settings.demo_login_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo login is currently disabled by administrator configuration.",
        )

    demo_user = auth_service.get_user_by_username("demo")
    if not demo_user:
        # Guarantee demo account exists
        auth_service.seed_initial_users()
        demo_user = auth_service.get_user_by_username("demo")
        if not demo_user:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Demo account could not be initialized.",
            )

    token = auth_service.create_session(demo_user["id"], demo_user["role"])
    _set_session_cookie(response, token)

    audit_service.record_event(
        event_type="auth_login",
        user_id="judge_demo",
        summary="Judge / demo mode session initiated via one-click access",
        source_component="auth",
    )

    return UserResponse(
        user_id=demo_user["id"],
        username=demo_user["username"],
        display_name=demo_user["display_name"],
        role=demo_user["role"],
    )


@router.post("/logout", response_model=LogoutResponse)
async def logout(request: Request, response: Response) -> LogoutResponse:
    """Sign out and invalidate current session."""
    token = request.cookies.get(settings.session_cookie_name)
    user_id = "anonymous"
    if token:
        session = auth_service.get_session(token)
        if session:
            user_id = session["user_id"]
        auth_service.delete_session(token)

    _clear_session_cookie(response)

    audit_service.record_event(
        event_type="auth_logout",
        user_id=user_id,
        summary=f"User {user_id} signed out",
        source_component="auth",
    )

    return LogoutResponse()


@router.get("/me", response_model=UserResponse)
async def me(request: Request) -> UserResponse:
    """Get currently authenticated identity or 401."""
    if not settings.require_auth:
        return UserResponse(
            user_id="demo_user",
            username="demo",
            display_name="Judge Demo",
            role="demo",
        )

    user: AuthedUser = auth_service.get_current_user(request)
    return UserResponse(
        user_id=user.user_id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
    )
