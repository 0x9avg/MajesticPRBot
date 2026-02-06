"""Admin routes for system management."""

from __future__ import annotations

import secrets
import string
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from database import Database
    from services.auth import AuthService

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from middleware import get_trace_id
from schemas.admin import UserCreate
from schemas.envelope import success_envelope
from config import Config

router = APIRouter(prefix="/admin", tags=["Admin"])


def get_db(request: Request):
    """Get database from app state."""
    return request.app.state.database


def get_auth(request: Request):
    """Get auth service from app state."""
    return request.app.state.auth


def generate_password(length=12):
    """Generate a secure random password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(secrets.choice(alphabet) for i in range(length))


from dependencies import get_current_user

@router.post("/users")
async def create_user(
    request: Request,
    user_data: UserCreate,
    db: "Database" = Depends(get_db),
    auth: "AuthService" = Depends(get_auth),
    current_user: dict = Depends(get_current_user),
):

    #TODO: Add explicit permission check if not handled globally.
    trace_id = get_trace_id(request)

    # Check if user already exists
    existing_user = await db.get_user_by_username(user_data.username)
    if existing_user:
        raise HTTPException(
            status_code=400,
            detail=f"Пользователь с логином '{user_data.username}' уже существует"
        )
    
    existing_assistant = await db.get_assistant(user_data.discord_id)
    if existing_assistant:
         raise HTTPException(
            status_code=400,
            detail=f"Сотрудник с ID {user_data.discord_id} уже существует"
        )

    # Generate password
    password = generate_password()
    password_hash = auth.hash_password(password)

    try:
        # Create web auth user
        await db.create_user(
            discord_id=user_data.discord_id,
            username=user_data.username,
            password_hash=password_hash
        )

        # Create/Update assistant profile
        await db.create_or_update_assistant(
            pr_id=user_data.discord_id,
            nickname=user_data.nickname,
            role=user_data.role
        )

        # Log action
        await db.log_admin_action(
            admin_name=current_user["nickname"],
            action="reg_user",
            admin_role=current_user.get("role"),
            target_type="user",
            target_id=user_data.nickname,
            details={
                "nickname": user_data.nickname,
                "login": user_data.username,
                "discord_user_id": user_data.discord_id
            },
            ip_address=request.client.host if request.client else None
        )

        return JSONResponse(
            content=success_envelope(
                data={
                    "username": user_data.username,
                    "password": password,
                    "nickname": user_data.nickname,
                    "role": user_data.role
                },
                message=f"Пользователь {user_data.username} успешно создан",
                code="USER_CREATED",
                trace_id=trace_id
            )
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при создании пользователя: {str(e)}"
        )
