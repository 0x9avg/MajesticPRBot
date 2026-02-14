"""
Auth routes for API.
Handles login, logout, and user info.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from database import Database
    from fastapi.security import HTTPAuthorizationCredentials
    from services.auth import AuthService

from datetime import datetime, timezone

from config import Config
from dependencies import get_current_user as get_authenticated_user
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer
from schemas.auth import LoginRequest, TokenResponse, UserResponse

router = APIRouter(prefix="/auth", tags=["Authentication"])
security = HTTPBearer()


def get_db(request: Request):
    """Get database from app state."""
    return request.app.state.database


def get_auth(request: Request):
    """Get auth service from app state."""
    return request.app.state.auth


@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    login_data: LoginRequest,
    db: "Database" = Depends(get_db),
    auth: "AuthService" = Depends(get_auth),
):
    """Authenticate user and return tokens."""
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent", "")

    # Get user
    user = await db.get_user_by_username(login_data.username)

    if user:
        # Check lockout
        if user["failed_login_attempts"] >= Config.max_login_attempts:
            last_failed = user["last_failed_login"]
            if last_failed:
                if getattr(last_failed, "tzinfo", None) is None:
                    last_failed = last_failed.replace(tzinfo=timezone.utc)
                else:
                    last_failed = last_failed.astimezone(timezone.utc)
                time_passed = (datetime.now(timezone.utc) - last_failed).total_seconds()

                if time_passed > Config.login_attempt_window:
                    await db.reset_failed_login(user["id"])
                else:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail=f"Слишком много попыток входа. Повторите через {int(Config.login_attempt_window - time_passed)} секунд.",
                    )
            else:
                await db.reset_failed_login(user["id"])

    # Verify credentials
    success = False
    if user and user["is_active"]:
        if auth.verify_password(login_data.password, user["password_hash"]):
            success = True

    if not success:
        if user:
            attempts_after_fail = int(user.get("failed_login_attempts") or 0) + 1
            await db.increment_failed_login(login_data.username)
            await db.log_auth_event(
                user["id"],
                login_data.username,
                "login_failed",
                client_ip,
                user_agent,
            )
            if attempts_after_fail >= Config.max_login_attempts:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Слишком много попыток входа. Повторите через {Config.login_attempt_window} секунд.",
                )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
        )

    # Login successful
    await db.reset_failed_login(user["id"])

    refresh_token, expires_at = auth.create_refresh_token(user["id"])

    session_id = await db.create_session(
        user["id"],
        refresh_token,
        expires_at,
        client_ip,
        user_agent,
    )

    access_token = auth.create_access_token(
        user["id"], user["username"], user.get("role") or "employee", sid=session_id
    )

    await db.log_auth_event(
        user["id"],
        user["username"],
        "login_success",
        client_ip,
        user_agent,
    )

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/logout")
async def logout(
    request: Request,
    db: "Database" = Depends(get_db),
    auth: "AuthService" = Depends(get_auth),
    credentials: "HTTPAuthorizationCredentials" = Depends(security),
):
    """Logout user and revoke all sessions."""
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent", "")
    try:
        token = credentials.credentials
        payload = auth.verify_token(token)

        await db.revoke_user_sessions(payload["user_id"])

        await db.log_auth_event(
            payload["user_id"],
            payload["username"],
            "logout",
            client_ip,
            user_agent,
        )

        return {"message": "Выход выполнен успешно"}
    except Exception:
        return {"message": "Выход выполнен успешно"}


@router.get("/me", response_model=UserResponse)
async def get_current_user(
    user: dict = Depends(get_authenticated_user),
):
    """Get current authenticated user info."""
    return UserResponse(
        id=user["id"],
        discord_id=str(user["discord_id"]),
        username=user["username"],
        nickname=user["nickname"],
        role=user["role"],
        require_password_change=bool(user["require_password_change"]),
        permissions=user.get("permissions", {}),
    )
