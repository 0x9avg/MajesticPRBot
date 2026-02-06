from typing import TYPE_CHECKING
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from config import Config

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
    try:
        token = credentials.credentials
        payload = auth.verify_token(token)
    except Exception:
         raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невалидный токен или срок действия истек",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # We assume get_user_by_id exists in Database (used by auth routes)
    user = await db.get_user_by_id(payload["user_id"])
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
        
    return user
