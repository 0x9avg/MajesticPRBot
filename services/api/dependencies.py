from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

if TYPE_CHECKING:
    from database import Database
    from services.auth import AuthService

security = HTTPBearer()


def get_db(request: Request):
    """Get database from app state."""
    return request.app.state.database


def get_auth(request: Request):
    """Get auth service from app state."""
    return request.app.state.auth


async def get_current_user(
    db: "Database" = Depends(get_db),
    auth: "AuthService" = Depends(get_auth),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Get current authenticated user.
    Validates JWT token and fetches user from DB.
    """
    token = credentials.credentials
    payload = auth.verify_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невалидный токен или срок действия истек",
            headers={"WWW-Authenticate": "Bearer"},
        )

    sid = payload.get("sid")
    user_id = payload.get("user_id")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невалидный токен доступа.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if sid is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Сессия в токене не найдена. Требуется повторный вход.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        session_id = int(sid)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невалидная сессия токена. Требуется повторный вход.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not await db.is_session_active(user_id, session_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Сессия отозвана или истекла. Требуется повторный вход.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # We assume get_user_by_id exists in Database (used by auth routes)
    user = await db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    return user
