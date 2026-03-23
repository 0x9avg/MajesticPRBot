"""Admin routes for system management."""

from __future__ import annotations

import logging
import secrets
import string
from typing import TYPE_CHECKING

from dependencies import require_permission

if TYPE_CHECKING:
    from db import Database
    from services.auth import AuthService

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from middleware import get_trace_id
from schemas.admin import UserCreate, UserDeactivateRequest, UserRoleUpdate
from schemas.envelope import success_envelope
from services.rbac import (
    ROLE_RANK,
    can_manage_target_account,
    can_create_role,
    get_manageable_roles,
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


def _actor_name(principal: dict) -> str:
    return (
        str(
            principal.get("nickname")
            or principal.get("username")
            or principal.get("service_name")
            or "Unknown"
        ).strip()
        or "Unknown"
    )


def _raise_role_access_denied(actor_role: str, target_role: str) -> None:
    if actor_role == "developer":
        raise HTTPException(
            status_code=403,
            detail="Разработчик может управлять всеми учетными записями",
        )
    actor_rank = ROLE_RANK[actor_role]
    target_rank = ROLE_RANK[target_role]
    if target_rank == actor_rank:
        detail = "Нельзя управлять пользователем с идентичной ролью"
    else:
        detail = "Нельзя управлять пользователем с ролью выше вашей"
    raise HTTPException(status_code=403, detail=detail)


async def _get_manageable_account_or_404(
    *,
    db: "Database",
    discord_id: int,
    current_user: dict,
    next_role: str | None = None,
) -> dict:
    account = await db.get_user_account(discord_id)
    if not account:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if account.get("assistant_pr_id") is None:
        logger.error(
            "RBAC lifecycle target %s has no linked assistant profile",
            discord_id,
        )
        raise HTTPException(
            status_code=409,
            detail="Учетная запись не привязана к профилю ассистента",
        )

    actor_role = str(current_user.get("role") or "")
    target_role = str(account.get("role") or "")
    actor_discord_id = current_user.get("discord_id")
    is_self = actor_discord_id is not None and int(actor_discord_id) == int(discord_id)
    if not is_valid_role(target_role):
        logger.error(
            "RBAC lifecycle target %s has invalid assistant role '%s'",
            discord_id,
            target_role,
        )
        raise HTTPException(
            status_code=409,
            detail="Профиль ассистента имеет недопустимую роль",
        )
    if not can_manage_target_account(
        actor_role,
        target_role,
        next_role,
        is_self=is_self,
    ):
        _raise_role_access_denied(actor_role, target_role)
    return account


async def _ensure_not_last_active_developer(
    db: "Database",
    *,
    account: dict,
) -> None:
    if str(account.get("role") or "") != "developer":
        return
    if not bool(account.get("is_active", True)):
        return
    if account.get("dismissed_at") is not None:
        return
    developers = await db.count_active_users_with_role("developer")
    if developers <= 1:
        raise HTTPException(
            status_code=409,
            detail="Нельзя изменить последнего активного developer",
        )


@router.post("/users")
async def create_user(
    request: Request,
    user_data: UserCreate,
    db: "Database" = Depends(get_db),
    auth: "AuthService" = Depends(get_auth),
    current_user: dict = Depends(require_permission("admin.users.create")),
):
    trace_id = get_trace_id(request)
    creator_role = current_user.get("role", "")

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

    existing_assistant = await db.get_assistant(user_data.discord_id, include_inactive=True)
    if existing_assistant:
        raise HTTPException(
            status_code=400,
            detail=f"Сотрудник с ID {user_data.discord_id} уже существует",
        )

    # Generate password
    password = generate_password()
    password_hash = auth.hash_password(password)

    try:
        await db.create_user_with_assistant(
            discord_id=user_data.discord_id,
            username=user_data.username,
            password_hash=password_hash,
            nickname=user_data.nickname,
            role=user_data.role,
            appointed_at=user_data.appointed_at,
        )

        try:
            await db.log_admin_action_v2(
                actor_name=_actor_name(current_user),
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
        except Exception as e:
            logger.warning(
                "User %s created, but admin log write failed: %s",
                user_data.username,
                e,
                exc_info=True,
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
            if "assistants" in error_text or "pr_id" in error_text:
                raise HTTPException(
                    status_code=400,
                    detail=f"Сотрудник с ID {user_data.discord_id} уже существует",
                )
            raise HTTPException(status_code=400, detail="Пользователь уже существует")

        logger.error("Failed to create user in /admin/users: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка при создании пользователя")


@router.patch("/users/{discord_id}/role")
async def update_user_role(
    request: Request,
    discord_id: int,
    payload: UserRoleUpdate,
    db: "Database" = Depends(get_db),
    current_user: dict = Depends(require_permission("admin.users.role.update")),
):
    trace_id = get_trace_id(request)
    target_role = str(payload.role or "").strip()
    if not is_valid_role(target_role):
        allowed_roles = ", ".join(get_manageable_roles(current_user.get("role")))
        raise HTTPException(
            status_code=400,
            detail=f"Недопустимая роль. Доступные роли: {allowed_roles}",
        )

    account = await _get_manageable_account_or_404(
        db=db,
        discord_id=discord_id,
        current_user=current_user,
        next_role=target_role,
    )
    if str(account.get("role") or "") != target_role and str(account.get("role") or "") == "developer":
        await _ensure_not_last_active_developer(db, account=account)

    if not bool(account.get("is_active", True)):
        raise HTTPException(
            status_code=409,
            detail="Нельзя изменить роль деактивированной учетной записи",
        )

    updated = await db.update_user_role_with_assistant(discord_id, target_role)
    if not updated:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    await db.log_admin_action_v2(
        actor_name=_actor_name(current_user),
        actor_role=current_user.get("role"),
        action="user.role.update",
        target_type="user",
        target_id=str(discord_id),
        details={
            "summary": f"Updated user role for {discord_id}",
            "payload": {
                "previous_role": account.get("role"),
                "role": target_role,
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
                "discord_id": str(discord_id),
                "nickname": updated.get("nickname"),
                "role": target_role,
            },
            message="Роль пользователя обновлена",
            code="USER_ROLE_UPDATED",
            trace_id=trace_id,
        )
    )


@router.post("/users/{discord_id}/deactivate")
async def deactivate_user(
    request: Request,
    discord_id: int,
    payload: UserDeactivateRequest | None = None,
    db: "Database" = Depends(get_db),
    current_user: dict = Depends(require_permission("admin.users.deactivate")),
):
    trace_id = get_trace_id(request)
    account = await _get_manageable_account_or_404(
        db=db,
        discord_id=discord_id,
        current_user=current_user,
    )
    await _ensure_not_last_active_developer(db, account=account)

    if not bool(account.get("is_active", True)):
        raise HTTPException(
            status_code=409,
            detail="Учетная запись уже деактивирована",
        )

    updated = await db.deactivate_user_with_assistant(
        discord_id,
        actor_id=current_user.get("discord_id") or current_user.get("id"),
        reason=payload.reason if payload else None,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    await db.log_admin_action_v2(
        actor_name=_actor_name(current_user),
        actor_role=current_user.get("role"),
        action="user.deactivate",
        target_type="user",
        target_id=str(discord_id),
        details={
            "summary": f"Deactivated user {discord_id}",
            "payload": {
                "reason": payload.reason if payload else None,
                "role": account.get("role"),
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
                "discord_id": str(discord_id),
                "nickname": updated.get("nickname"),
                "deactivated": True,
            },
            message="Учетная запись деактивирована",
            code="USER_DEACTIVATED",
            trace_id=trace_id,
        )
    )
