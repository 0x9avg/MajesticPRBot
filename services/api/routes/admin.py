"""Admin routes for system management."""

from __future__ import annotations

import logging
import secrets
import string
from typing import TYPE_CHECKING

from dependencies import get_current_user

if TYPE_CHECKING:
    from database import Database
    from services.auth import AuthService

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from middleware import get_trace_id
from schemas.admin import UserCreate
from schemas.envelope import success_envelope
from services.rbac import (
    ROLE_RANK,
    can_create_role,
    can_register_users,
    is_admin_role,
    is_valid_role,
)

router = APIRouter(prefix="/admin", tags=["Admin"])
logger = logging.getLogger("API")


def get_db(request: Request):
    """Get database from app state."""
    return request.app.state.database


def get_auth(request: Request):
    """Get auth service from app state."""
    return request.app.state.auth


def generate_password(length=12):
    """Generate a secure random password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for i in range(length))


@router.post("/users")
async def create_user(
    request: Request,
    user_data: UserCreate,
    db: "Database" = Depends(get_db),
    auth: "AuthService" = Depends(get_auth),
    current_user: dict = Depends(get_current_user),
):
    trace_id = get_trace_id(request)
    creator_role = current_user.get("role", "")

    if not is_admin_role(creator_role):
        raise HTTPException(
            status_code=403,
            detail="Недостаточно прав для доступа к админ-панели",
        )

    if not can_register_users(current_user):
        raise HTTPException(
            status_code=403,
            detail="Недостаточно прав для регистрации пользователей",
        )

    if not is_valid_role(creator_role):
        raise HTTPException(
            status_code=403,
            detail="Недостаточно прав для регистрации пользователей",
        )

    if not is_valid_role(user_data.role):
        allowed_roles = ", ".join(ROLE_RANK.keys())
        raise HTTPException(
            status_code=400,
            detail=f"Недопустимая роль. Доступные роли: {allowed_roles}",
        )

    if not can_create_role(creator_role, user_data.role):
        creator_rank = ROLE_RANK[creator_role]
        target_rank = ROLE_RANK[user_data.role]
        if target_rank == creator_rank:
            detail = "Нельзя создавать пользователя с идентичной ролью"
        else:
            detail = "Нельзя создавать пользователя с ролью выше вашей"
        raise HTTPException(status_code=403, detail=detail)

    # Check if user already exists
    existing_user = await db.get_user_by_username(user_data.username)
    if existing_user:
        raise HTTPException(
            status_code=400,
            detail=f"Пользователь с логином '{user_data.username}' уже существует",
        )

    existing_web_user = await db.get_user_by_discord_id(user_data.discord_id)
    if existing_web_user:
        raise HTTPException(
            status_code=400,
            detail=f"Пользователь с Discord ID {user_data.discord_id} уже существует",
        )

    existing_assistant = await db.get_assistant(user_data.discord_id)
    if existing_assistant:
        raise HTTPException(
            status_code=400,
            detail=f"Сотрудник с ID {user_data.discord_id} уже существует",
        )

    # Generate password
    password = generate_password()
    password_hash = auth.hash_password(password)

    try:
        # Create web auth user
        await db.create_user(
            discord_id=user_data.discord_id,
            username=user_data.username,
            password_hash=password_hash,
        )

        # Create/Update assistant profile
        await db.create_or_update_assistant(
            pr_id=user_data.discord_id,
            nickname=user_data.nickname,
            role=user_data.role,
            appointed_at=user_data.appointed_at,
        )

        # Log action
        await db.log_admin_action_v2(
            actor_name=current_user["nickname"],
            actor_role=current_user.get("role"),
            action="user.create",
            target_type="user",
            target_id=str(user_data.discord_id),
            details={
                "summary": f"Created user {user_data.username}",
                "payload": {
                    "nickname": user_data.nickname,
                    "login": user_data.username,
                    "discord_user_id": user_data.discord_id,
                    "role": user_data.role,
                    "appointed_at": user_data.appointed_at.isoformat()
                    if user_data.appointed_at
                    else None,
                },
                "meta": {
                    "ip": request.client.host if request.client else None,
                    "request_path": str(request.url.path),
                    "method": request.method,
                    "actor_id": current_user.get("id"),
                },
            },
        )

        return JSONResponse(
            content=success_envelope(
                data={
                    "username": user_data.username,
                    "password": password,
                    "nickname": user_data.nickname,
                    "role": user_data.role,
                },
                message=f"Пользователь {user_data.username} успешно создан",
                code="USER_CREATED",
                trace_id=trace_id,
            )
        )

    except HTTPException:
        raise
    except Exception as e:
        error_text = str(e).lower()
        if "duplicate entry" in error_text:
            if "username" in error_text:
                raise HTTPException(
                    status_code=400,
                    detail=f"Пользователь с логином '{user_data.username}' уже существует",
                )
            if "discord_id" in error_text:
                raise HTTPException(
                    status_code=400,
                    detail=f"Пользователь с Discord ID {user_data.discord_id} уже существует",
                )
            raise HTTPException(status_code=400, detail="Пользователь уже существует")

        logger.error("Failed to create user in /admin/users: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка при создании пользователя")
