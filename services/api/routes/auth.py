"""
Auth routes for API.
Handles login, logout, and user info.
"""

from datetime import datetime
from jose import JWTError
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from schemas.auth import LoginRequest, TokenResponse, UserResponse
from config import Config

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
    db=Depends(get_db),
    auth=Depends(get_auth),
):
    """Authenticate user and return tokens."""
    # Get user
    user = await db.get_user_by_username(login_data.username)
    
    if user:
        # Check lockout
        if user["failed_login_attempts"] >= Config.MAX_LOGIN_ATTEMPTS:
            last_failed = user["last_failed_login"]
            if last_failed:
                time_passed = (datetime.now() - last_failed).total_seconds()
                
                if time_passed > Config.LOGIN_ATTEMPT_WINDOW:
                    await db.reset_failed_login(user["id"])
                else:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail=f"Слишком много попыток входа. Повторите через {int(Config.LOGIN_ATTEMPT_WINDOW - time_passed)} секунд.",
                    )
            else:
                await db.reset_failed_login(user["id"])
    
    # Check attempts
    attempts = await db.get_failed_login_attempts(login_data.username)
    if attempts >= Config.MAX_LOGIN_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Слишком много попыток входа. Повторите позже.",
        )
    
    # Verify credentials
    success = False
    if user and user["is_active"]:
        if auth.verify_password(login_data.password, user["password_hash"]):
            success = True
    
    if not success:
        if user:
            await db.increment_failed_login(login_data.username)
            await db.log_auth_event(
                user["id"],
                login_data.username,
                "login_failed",
                request.client.host,
                request.headers.get("user-agent", ""),
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
        )
    
    # Login successful
    await db.reset_failed_login(user["id"])
    
    access_token = auth.create_access_token(user["id"], user["username"], user["role"])
    refresh_token, expires_at = auth.create_refresh_token(user["id"])
    
    await db.create_session(
        user["id"],
        refresh_token,
        expires_at,
        request.client.host,
        request.headers.get("user-agent", ""),
    )
    
    await db.log_auth_event(
        user["id"],
        user["username"],
        "login_success",
        request.client.host,
        request.headers.get("user-agent", ""),
    )
    
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/logout")
async def logout(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db=Depends(get_db),
    auth=Depends(get_auth),
):
    """Logout user and revoke all sessions."""
    try:
        token = credentials.credentials
        payload = auth.verify_token(token)
        
        await db.revoke_user_sessions(payload["user_id"])
        
        await db.log_auth_event(
            payload["user_id"],
            payload["username"],
            "logout",
            request.client.host,
            request.headers.get("user-agent", ""),
        )
        
        return {"message": "Выход выполнен успешно"}
    except Exception:
        return {"message": "Выход выполнен успешно"}


@router.get("/me", response_model=UserResponse)
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db=Depends(get_db),
    auth=Depends(get_auth),
):
    """Get current authenticated user info."""
    try:
        token = credentials.credentials
        payload = auth.verify_token(token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невалидный токен или срок действия истек",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user = await db.get_user_by_id(payload["user_id"])
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    return UserResponse(
        id=user["id"],
        discord_id=user["discord_id"],
        username=user["username"],
        nickname=user["nickname"],
        role=user["role"],
        require_password_change=bool(user["require_password_change"]),
    )
