"""
Auth routes for API.
Handles login (with HttpOnly cookie), refresh, logout, and session management.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from db import Database
    from fastapi.security import HTTPAuthorizationCredentials
    from services.auth import AuthService

from datetime import datetime, timezone, timedelta

MSK = timezone(timedelta(hours=3))

from config import Config
from dependencies import (
    AuthErrorCode,
    _auth_error,
    enforce_site_maintenance_for_login,
    get_current_user as get_authenticated_user,
    get_current_user_allow_maintenance,
)
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPBearer
from schemas.auth import LoginRequest, LoginResponse, UserResponse
from services.rbac import get_manageable_roles

router = APIRouter(prefix="/auth", tags=["Authentication"])
security = HTTPBearer()


def get_db(request: Request):
    """Get database from app state."""
    return request.app.state.database


def get_auth(request: Request):
    """Get auth service from app state."""
    return request.app.state.auth


def _set_refresh_cookie(response: Response, raw_token: str, expires_at: datetime) -> None:
    """Set the refresh token as an HttpOnly cookie."""
    max_age = int((expires_at - datetime.now(MSK)).total_seconds())
    if max_age < 0:
        max_age = 0

    response.set_cookie(
        key="refresh_token",
        value=raw_token,
        httponly=True,
        secure=Config.cookie_secure,
        samesite=Config.cookie_samesite,
        path=Config.cookie_path,
        max_age=max_age,
        **({"domain": Config.cookie_domain} if Config.cookie_domain else {}),
    )


def _clear_refresh_cookie(response: Response) -> None:
    """Clear the refresh token cookie."""
    response.delete_cookie(
        key="refresh_token",
        httponly=True,
        secure=Config.cookie_secure,
        samesite=Config.cookie_samesite,
        path=Config.cookie_path,
        **({"domain": Config.cookie_domain} if Config.cookie_domain else {}),
    )


# =============================================================================
# POST /auth/login
# =============================================================================

@router.post("/login", response_model=LoginResponse)
async def login(
    request: Request,
    response: Response,
    login_data: LoginRequest,
    db: "Database" = Depends(get_db),
    auth: "AuthService" = Depends(get_auth),
):
    """Authenticate user, set refresh token as HttpOnly cookie, return access token."""
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent", "")

    # Get user
    user = await db.get_user_by_username(login_data.username)
    await enforce_site_maintenance_for_login(db, user)

    if user:
        # Check lockout using account_lockout_duration
        if user["failed_login_attempts"] >= Config.max_login_attempts:
            last_failed = user["last_failed_login"]
            if last_failed:
                if getattr(last_failed, "tzinfo", None) is None:
                    last_failed = last_failed.replace(tzinfo=MSK)
                else:
                    last_failed = last_failed.astimezone(MSK)
                time_passed = (datetime.now(MSK) - last_failed).total_seconds()

                if time_passed > Config.account_lockout_duration:
                    await db.reset_failed_login(user["discord_id"])
                else:
                    remaining = int(Config.account_lockout_duration - time_passed)
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail=f"Слишком много попыток входа. Повторите через {remaining} секунд.",
                    )
            else:
                await db.reset_failed_login(user["discord_id"])

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
                user["discord_id"],
                login_data.username,
                "login_failed",
                client_ip,
                user_agent,
            )
            if attempts_after_fail >= Config.max_login_attempts:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Слишком много попыток входа. Повторите через {Config.account_lockout_duration} секунд.",
                )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
        )

    # Login successful
    await db.reset_failed_login(user["discord_id"])

    # Generate tokens
    raw_refresh, refresh_hash, expires_at = auth.create_refresh_token(user["discord_id"])
    family_id = auth.generate_family_id()

    session_id = await db.create_session(
        user["discord_id"],
        refresh_hash,
        family_id,
        expires_at,
        client_ip,
        user_agent,
    )

    access_token = auth.create_access_token(
        user["discord_id"],
        user["username"],
        user.get("role") or "employee",
        sid=session_id,
    )

    await db.log_auth_event(
        user["discord_id"],
        user["username"],
        "login_success",
        client_ip,
        user_agent,
    )

    # Set refresh token as HttpOnly cookie
    _set_refresh_cookie(response, raw_refresh, expires_at)

    return LoginResponse(access_token=access_token)


# =============================================================================
# POST /auth/refresh
# =============================================================================

@router.post("/refresh")
async def refresh_token(
    request: Request,
    response: Response,
    db: "Database" = Depends(get_db),
    auth: "AuthService" = Depends(get_auth),
    refresh_token: str | None = Cookie(default=None),
):
    """
    Rotate refresh token: validate cookie, issue new tokens, set new cookie.
    Implements reuse detection: if a previously-used token is presented,
    revoke the entire family and require re-login.
    """
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent", "")

    if not refresh_token:
        await enforce_site_maintenance_for_login(db, None)
        raise _auth_error(AuthErrorCode.TOKEN_INVALID, "Refresh token отсутствует.")

    # Find session by hash
    token_hash = auth.hash_token(refresh_token)
    session = await db.find_session_by_refresh_hash(token_hash)

    if not session:
        await enforce_site_maintenance_for_login(db, None)
        raise _auth_error(AuthErrorCode.TOKEN_INVALID, "Невалидный refresh token.")

    # Check if session was already replaced or revoked -> REUSE DETECTION
    replaced_by_hash = session.get("replaced_by_hash")
    if (replaced_by_hash is not None and str(replaced_by_hash).strip() != "") or session.get("revoked"):
        # Revoke the entire family
        await db.revoke_session_family(session["family_id"])
        await db.log_auth_event(
            session["user_id"],
            "",
            "token_refresh",
            client_ip,
            f"REUSE_DETECTED family={session['family_id']}",
        )
        _clear_refresh_cookie(response)
        raise _auth_error(
            AuthErrorCode.REFRESH_REUSE_DETECTED,
            "Обнаружено повторное использование токена. Все сессии отозваны.",
        )

    # Check expiration
    expires_at = session["expires_at"]
    if getattr(expires_at, "tzinfo", None) is None:
        expires_at = expires_at.replace(tzinfo=MSK)
    if datetime.now(MSK) >= expires_at:
        _clear_refresh_cookie(response)
        raise _auth_error(AuthErrorCode.SESSION_EXPIRED, "Сессия истекла. Требуется повторный вход.")

    user = await db.get_user_by_id(session["user_id"])
    if not user:
        _clear_refresh_cookie(response)
        raise _auth_error(AuthErrorCode.TOKEN_INVALID, "Пользователь не найден.")
    await enforce_site_maintenance_for_login(db, user)

    # Generate new tokens
    new_raw, new_hash, new_expires = auth.create_refresh_token(session["user_id"])

    # Atomic rotation
    new_session_id = await db.rotate_session(
        old_session_id=session["id"],
        old_token_hash=token_hash,
        new_token_hash=new_hash,
        new_expires_at=new_expires,
        new_ip=client_ip,
        new_user_agent=user_agent,
    )

    if new_session_id is None:
        # Race condition or reuse detected during rotation
        await db.revoke_session_family(session["family_id"])
        _clear_refresh_cookie(response)
        raise _auth_error(
            AuthErrorCode.REFRESH_REUSE_DETECTED,
            "Ошибка ротации токена. Все сессии отозваны.",
        )

    access_token = auth.create_access_token(
        user["discord_id"],
        user["username"],
        user.get("role") or "employee",
        sid=new_session_id,
    )

    await db.log_auth_event(
        user["discord_id"],
        user["username"],
        "token_refresh",
        client_ip,
        user_agent,
    )

    # Set new refresh cookie
    _set_refresh_cookie(response, new_raw, new_expires)

    return {"access_token": access_token, "token_type": "bearer"}


# =============================================================================
# POST /auth/logout/current — logout current device only
# =============================================================================

@router.post("/logout/current")
async def logout_current(
    request: Request,
    response: Response,
    db: "Database" = Depends(get_db),
    user: dict = Depends(get_current_user_allow_maintenance),
):
    """Logout current session only (current device)."""
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent", "")

    session_id = user.get("_session_id")
    if session_id:
        await db.revoke_session(session_id)

    await db.log_auth_event(
        user["discord_id"],
        user.get("username", ""),
        "logout",
        client_ip,
        user_agent,
    )

    _clear_refresh_cookie(response)
    return {"message": "Выход выполнен успешно"}


# =============================================================================
# POST /auth/logout — legacy: revoke ALL sessions
# =============================================================================

@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    db: "Database" = Depends(get_db),
    auth: "AuthService" = Depends(get_auth),
    credentials: "HTTPAuthorizationCredentials" = Depends(security),
):
    """Logout user and revoke all sessions (legacy behavior)."""
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
    except Exception:
        pass

    _clear_refresh_cookie(response)
    return {"message": "Выход выполнен успешно"}


# =============================================================================
# GET /auth/me
# =============================================================================

@router.get("/me", response_model=UserResponse)
async def get_current_user(
    user: dict = Depends(get_authenticated_user),
):
    """Get current authenticated user info."""
    return UserResponse(
        id=user["discord_id"],
        discord_id=str(user["discord_id"]),
        username=user["username"],
        nickname=user["nickname"],
        role=user["role"],
        require_password_change=bool(user["require_password_change"]),
        permissions=user.get("permissions", {}),
        manageable_roles=list(get_manageable_roles(user.get("role"))),
    )


# =============================================================================
# GET /auth/sessions — list active sessions for the current user
# =============================================================================

@router.get("/sessions")
async def list_sessions(
    db: "Database" = Depends(get_db),
    user: dict = Depends(get_authenticated_user),
):
    """List active sessions for the current user (device management)."""
    sessions = await db.get_user_sessions(user["discord_id"])
    current_sid = user.get("_session_id")

    result = []
    for s in sessions:
        result.append({
            "id": s["id"],
            "ip_address": s.get("ip_address"),
            "last_ip": s.get("last_ip"),
            "user_agent": s.get("user_agent"),
            "device_label": s.get("device_label"),
            "created_at": s.get("created_at"),
            "expires_at": s.get("expires_at"),
            "is_current": s["id"] == current_sid,
        })
    return {"sessions": result}


# =============================================================================
# POST /auth/sessions/{sid}/revoke — revoke a specific session
# =============================================================================

@router.post("/sessions/{sid}/revoke")
async def revoke_session(
    sid: int,
    request: Request,
    db: "Database" = Depends(get_db),
    user: dict = Depends(get_authenticated_user),
):
    """Revoke a specific session. Users can only revoke their own sessions."""
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent", "")

    # Check ownership
    owner_id = await db.get_session_owner(sid)
    if owner_id is None or owner_id != user["discord_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нет доступа к этой сессии.",
        )

    success = await db.revoke_session(sid)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Сессия не найдена или уже отозвана.",
        )

    await db.log_auth_event(
        user["discord_id"],
        user.get("username", ""),
        "logout",
        client_ip,
        f"revoked_session={sid}",
    )

    return {"message": f"Сессия {sid} отозвана."}
