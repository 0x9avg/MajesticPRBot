"""
Authentication and authorization dependencies for FastAPI routes.
Provides structured 401 error codes, user auth, and service token auth.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from fastapi import Cookie, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

if TYPE_CHECKING:
    from db import Database
    from services.auth import AuthService

security = HTTPBearer()
security_optional = HTTPBearer(auto_error=False)


# =============================================================================
# Structured 401 reason codes (for frontend retry logic)
# =============================================================================

class AuthErrorCode:
    """Standard 401 reason codes returned in `detail` dict."""
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    TOKEN_INVALID = "TOKEN_INVALID"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    SESSION_REVOKED = "SESSION_REVOKED"
    REFRESH_REUSE_DETECTED = "REFRESH_REUSE_DETECTED"


SITE_MAINTENANCE_CODE = "SITE_MAINTENANCE"


def _auth_error(code: str, message: str) -> HTTPException:
    """Build a structured 401 HTTPException."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": code, "message": message},
        headers={"WWW-Authenticate": "Bearer"},
    )


def _site_maintenance_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": SITE_MAINTENANCE_CODE,
            "message": "Сайт временно недоступен из-за технических работ.",
        },
    )


def _has_permission(principal: dict, permission: str) -> bool:
    permissions = principal.get("permissions") or {}
    return bool(permissions.get(permission, False))


def _ensure_active_user(user: Optional[dict]) -> None:
    if not user:
        return
    if bool(user.get("is_active", True)):
        return
    raise _auth_error(
        AuthErrorCode.SESSION_REVOKED,
        "Учетная запись деактивирована. Требуется повторный вход.",
    )


async def enforce_site_maintenance_for_user(
    db: "Database",
    principal: Optional[dict],
) -> None:
    if not principal:
        return
    if principal.get("principal_type") == "service":
        return
    if not await db.is_site_maintenance_enabled():
        return
    if _has_permission(principal, "maintenance.bypass"):
        return
    raise _site_maintenance_error()


async def enforce_site_maintenance_for_login(
    db: "Database",
    user: Optional[dict],
) -> None:
    if not await db.is_site_maintenance_enabled():
        return
    if user:
        permissions = user.get("permissions")
        if not isinstance(permissions, dict):
            role = str(user.get("role") or "employee")
            permissions = await db.get_role_permissions(role)
            user["permissions"] = permissions
        if bool(permissions.get("maintenance.bypass", False)):
            return
    raise _site_maintenance_error()


def _classify_access_token_error(token: str, auth: "AuthService") -> HTTPException:
    """
    Distinguish expired access tokens from invalid tokens.

    - TOKEN_EXPIRED: signature is valid, type is access, exp is in the past.
    - TOKEN_INVALID: malformed/signature-invalid/wrong type/no exp/etc.
    """
    from jose import JWTError, jwt as jose_jwt

    try:
        decoded = jose_jwt.decode(
            token,
            auth.secret_key,
            algorithms=[auth.algorithm],
            options={"verify_exp": False},
        )
    except JWTError:
        return _auth_error(AuthErrorCode.TOKEN_INVALID, "Невалидный токен доступа.")
    except Exception:
        return _auth_error(AuthErrorCode.TOKEN_INVALID, "Невалидный токен доступа.")

    if decoded.get("type") != "access":
        return _auth_error(AuthErrorCode.TOKEN_INVALID, "Невалидный токен доступа.")

    exp_value = decoded.get("exp")
    if exp_value is None:
        return _auth_error(AuthErrorCode.TOKEN_INVALID, "Невалидный токен доступа.")

    try:
        exp_ts = float(exp_value)
    except (TypeError, ValueError):
        return _auth_error(AuthErrorCode.TOKEN_INVALID, "Невалидный токен доступа.")

    if exp_ts <= datetime.now(timezone.utc).timestamp():
        return _auth_error(
            AuthErrorCode.TOKEN_EXPIRED,
            "Токен доступа истёк. Выполните обновление.",
        )

    return _auth_error(AuthErrorCode.TOKEN_INVALID, "Невалидный токен доступа.")


# =============================================================================
# Common app-state helpers
# =============================================================================

def get_db(request: Request):
    """Get database from app state."""
    return request.app.state.database


def get_auth(request: Request):
    """Get auth service from app state."""
    return request.app.state.auth


# =============================================================================
# User authentication dependency
# =============================================================================

async def get_current_user(
    db: "Database" = Depends(get_db),
    auth: "AuthService" = Depends(get_auth),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Get current authenticated user.
    Validates JWT access token, verifies session is active, fetches user from DB.
    Returns structured error codes so the frontend can distinguish
    expiry (retry with refresh) from revocation (hard logout).
    """
    token = credentials.credentials
    payload = auth.verify_access_token(token)

    if not payload:
        raise _classify_access_token_error(token, auth)

    sid = payload.get("sid")
    user_id = payload.get("user_id")

    if user_id is None:
        raise _auth_error(AuthErrorCode.TOKEN_INVALID, "Невалидный токен доступа.")
    if sid is None:
        raise _auth_error(AuthErrorCode.SESSION_REVOKED, "Сессия в токене не найдена. Требуется повторный вход.")

    try:
        session_id = int(sid)
    except (TypeError, ValueError):
        raise _auth_error(AuthErrorCode.SESSION_REVOKED, "Невалидная сессия токена.")

    if not await db.is_session_active(user_id, session_id):
        raise _auth_error(
            AuthErrorCode.SESSION_REVOKED,
            "Сессия отозвана или истекла. Требуется повторный вход.",
        )

    user = await db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    _ensure_active_user(user)

    # Inject session_id into user dict for downstream use (e.g. logout/current)
    user["_session_id"] = session_id
    user["principal_type"] = "user"
    await enforce_site_maintenance_for_user(db, user)
    return user


async def get_current_user_allow_maintenance(
    db: "Database" = Depends(get_db),
    auth: "AuthService" = Depends(get_auth),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Resolve the current authenticated user without maintenance blocking."""
    token = credentials.credentials
    payload = auth.verify_access_token(token)

    if not payload:
        raise _classify_access_token_error(token, auth)

    sid = payload.get("sid")
    user_id = payload.get("user_id")

    if user_id is None:
        raise _auth_error(AuthErrorCode.TOKEN_INVALID, "Невалидный токен доступа.")
    if sid is None:
        raise _auth_error(AuthErrorCode.SESSION_REVOKED, "Сессия в токене не найдена. Требуется повторный вход.")

    try:
        session_id = int(sid)
    except (TypeError, ValueError):
        raise _auth_error(AuthErrorCode.SESSION_REVOKED, "Невалидная сессия токена.")

    if not await db.is_session_active(user_id, session_id):
        raise _auth_error(
            AuthErrorCode.SESSION_REVOKED,
            "Сессия отозвана или истекла. Требуется повторный вход.",
        )

    user = await db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    _ensure_active_user(user)

    user["_session_id"] = session_id
    user["principal_type"] = "user"
    return user


# =============================================================================
# Service token authentication dependency (for bots)
# =============================================================================

async def get_current_service(
    request: Request,
    db: "Database" = Depends(get_db),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_optional),
):
    """
    Authenticate a service (bot) via pre-shared Bearer token.
    Returns a dict with service principal info if valid, raises 401 otherwise.
    """
    if not credentials:
        raise _auth_error(AuthErrorCode.TOKEN_INVALID, "Service token required.")

    token = credentials.credentials

    principal = await db.get_service_principal_by_token(token)
    if not principal:
        raise _auth_error(AuthErrorCode.TOKEN_INVALID, "Unknown service principal.")
    return principal


# =============================================================================
# Flexible auth: user OR service
# =============================================================================

async def get_current_principal(
    request: Request,
    db: "Database" = Depends(get_db),
    auth: "AuthService" = Depends(get_auth),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_optional),
):
    """
    Authenticate either a user or a service principal.
    Returns a dict with 'principal_type' = 'user' | 'service'.
    """
    if not credentials:
        raise _auth_error(AuthErrorCode.TOKEN_INVALID, "Требуется авторизация.")

    token = credentials.credentials

    # Try service principal auth first via DB-backed token scopes.
    principal = await db.get_service_principal_by_token(token)
    if principal:
        return principal

    # Fall back to user JWT auth
    payload = auth.verify_access_token(token)
    if not payload:
        err = _classify_access_token_error(token, auth)
        if (
            isinstance(err.detail, dict)
            and err.detail.get("code") == AuthErrorCode.TOKEN_EXPIRED
        ):
            raise _auth_error(AuthErrorCode.TOKEN_EXPIRED, "Токен доступа истёк.")
        raise _auth_error(AuthErrorCode.TOKEN_INVALID, "Невалидный токен.")

    sid = payload.get("sid")
    user_id = payload.get("user_id")
    if user_id is None or sid is None:
        raise _auth_error(AuthErrorCode.TOKEN_INVALID, "Невалидный токен.")

    try:
        session_id = int(sid)
    except (TypeError, ValueError):
        raise _auth_error(AuthErrorCode.SESSION_REVOKED, "Невалидная сессия.")

    if not await db.is_session_active(user_id, session_id):
        raise _auth_error(AuthErrorCode.SESSION_REVOKED, "Сессия отозвана.")

    user = await db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    _ensure_active_user(user)

    user["_session_id"] = session_id
    user["principal_type"] = "user"
    await enforce_site_maintenance_for_user(db, user)
    return user


# =============================================================================
# Permission checker dependency factory
# =============================================================================

def require_permission(permission: str):
    """
    Create a FastAPI dependency that enforces a specific permission.

    - Services and users both require explicit `permissions[permission] == True`.

    Usage:
        @router.get("/something")
        async def handler(principal = Depends(require_permission("streamers.view"))):
            ...
    """

    async def _check(
        principal: dict = Depends(get_current_principal),
    ) -> dict:
        permissions = principal.get("permissions") or {}
        if not permissions.get(permission, False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Недостаточно прав: требуется '{permission}'",
            )
        return principal

    return _check


def require_any_permission(*required_permissions: str):
    """Create a dependency that allows access when any listed permission is granted."""

    async def _check(
        principal: dict = Depends(get_current_principal),
    ) -> dict:
        permissions = principal.get("permissions") or {}
        if not any(permissions.get(permission, False) for permission in required_permissions):
            required = "', '".join(required_permissions)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Недостаточно прав: требуется одно из '{required}'",
            )
        return principal

    return _check
