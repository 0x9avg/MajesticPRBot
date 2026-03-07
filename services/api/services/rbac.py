"""RBAC helpers for role-based authorization checks."""

from __future__ import annotations

from typing import Any


ROLE_RANK: dict[str, int] = {
    "junior_employee": 0,
    "employee": 1,
    "senior_employee": 2,
    "manager": 3,
    "developer": 4,
}


def is_valid_role(role: str) -> bool:
    """Check whether a role exists in hierarchy."""
    return role in ROLE_RANK


def is_admin_role(role: str | None) -> bool:
    """Check whether role has admin panel access."""
    return role in {"manager", "developer"}


def can_register_users(current_user: dict[str, Any]) -> bool:
    """Compatibility helper: check user-creation permission."""
    permissions = current_user.get("permissions") or {}
    return bool(permissions.get("admin.users.create", False))


def can_create_role(creator_role: str, target_role: str) -> bool:
    """
    Check if creator can create target role.

    Policy:
    - developer can create any role, including developer.
    - all other roles can create only strictly lower roles.
    """
    if not is_valid_role(creator_role) or not is_valid_role(target_role):
        return False

    if creator_role == "developer":
        return True

    return ROLE_RANK[target_role] < ROLE_RANK[creator_role]
