"""Canonical RBAC catalog, legacy permission migration, and role helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

STAFF_ROLES: tuple[str, ...] = (
    "junior_employee",
    "employee",
    "senior_employee",
    "manager",
    "developer",
)

ROLE_RANK: dict[str, int] = {
    role: index for index, role in enumerate(STAFF_ROLES)
}

PERMISSION_CATALOG: tuple[str, ...] = (
    "dashboard.view",
    "media.view",
    "media.create",
    "media.update",
    "media.delete",
    "media.status.update",
    "spec.claimable.view",
    "spec.sessions.self.view",
    "spec.claim.main",
    "spec.claim.probation",
    "spec.unclaim.self",
    "spec.unclaim.any",
    "assistants.view",
    "assistants.assignment.update",
    "assistants.logs.view",
    "assistants.sessions.view",
    "assistants.sessions.manage",
    "assistants.points.update",
    "assistants.sanctions.manage",
    "assistants.warnings.manage",
    "assistants.weekly.view",
    "assistants.weekly.manage",
    "events.view",
    "events.create",
    "events.update",
    "events.runtime.manage",
    "events.spec_requests.create",
    "events.spec_requests.review",
    "events.participation.self.join",
    "events.participation.self.leave",
    "events.participation.any.leave",
    "returns.queue.view",
    "returns.history.view",
    "returns.create",
    "returns.process",
    "returns.manage.self",
    "returns.manage.any",
    "complaints.queue.view",
    "complaints.history.view",
    "complaints.create",
    "complaints.issue",
    "complaints.manage.self",
    "complaints.manage.any",
    "removals.queue.view",
    "removals.history.view",
    "removals.create",
    "removals.issue",
    "removals.manage.self",
    "removals.manage.any",
    "logs.assistant_actions.view",
    "logs.admin.view",
    "game_servers.view",
    "game_servers.settings.view",
    "game_servers.settings.update",
    "game_servers.templates.view",
    "game_servers.templates.update",
    "game_servers.rates.view",
    "game_servers.rates.update",
    "admin.panel.view",
    "admin.users.create",
    "admin.users.role.update",
    "admin.users.deactivate",
    "rbac.view",
    "rbac.update",
    "site.maintenance.view",
    "site.maintenance.update",
    "maintenance.bypass",
    "monitoring.view",
    "notifications.render",
)

PERMISSION_IMPLICATIONS: dict[str, list[str]] = {
    "media.create": ["media.view"],
    "media.update": ["media.view"],
    "media.delete": ["media.view"],
    "media.status.update": ["media.view"],
    "spec.claim.main": ["spec.claimable.view"],
    "spec.claim.probation": ["spec.claimable.view"],
    "spec.unclaim.self": ["spec.sessions.self.view"],
    "assistants.assignment.update": ["assistants.view"],
    "assistants.logs.view": ["assistants.view"],
    "assistants.sessions.view": ["assistants.view"],
    "assistants.sessions.manage": [
        "assistants.sessions.view",
        "assistants.view",
        "admin.panel.view",
    ],
    "assistants.points.update": ["assistants.view", "admin.panel.view"],
    "assistants.sanctions.manage": ["assistants.view", "admin.panel.view"],
    "assistants.warnings.manage": ["assistants.view", "admin.panel.view"],
    "assistants.weekly.view": ["assistants.view"],
    "assistants.weekly.manage": [
        "assistants.weekly.view",
        "assistants.view",
        "admin.panel.view",
    ],
    "events.create": ["events.view", "admin.panel.view"],
    "events.update": ["events.view"],
    "events.runtime.manage": ["events.view"],
    "events.spec_requests.create": ["events.view"],
    "events.spec_requests.review": ["events.view", "admin.panel.view"],
    "events.participation.self.join": ["events.view"],
    "events.participation.self.leave": ["events.view"],
    "events.participation.any.leave": ["events.view"],
    "returns.create": ["returns.queue.view"],
    "returns.process": ["returns.queue.view"],
    "returns.manage.self": ["returns.queue.view"],
    "returns.manage.any": ["returns.queue.view"],
    "complaints.create": ["complaints.queue.view"],
    "complaints.issue": ["complaints.queue.view"],
    "complaints.manage.self": ["complaints.queue.view"],
    "complaints.manage.any": ["complaints.queue.view"],
    "removals.create": ["removals.queue.view"],
    "removals.issue": ["removals.queue.view"],
    "removals.manage.self": ["removals.queue.view"],
    "removals.manage.any": ["removals.queue.view"],
    "game_servers.settings.view": ["game_servers.view", "admin.panel.view"],
    "game_servers.settings.update": [
        "game_servers.settings.view",
        "game_servers.view",
        "admin.panel.view",
    ],
    "game_servers.templates.view": ["game_servers.view", "admin.panel.view"],
    "game_servers.templates.update": [
        "game_servers.templates.view",
        "game_servers.view",
        "admin.panel.view",
    ],
    "game_servers.rates.view": ["game_servers.view", "admin.panel.view"],
    "game_servers.rates.update": [
        "game_servers.rates.view",
        "game_servers.view",
        "admin.panel.view",
    ],
    "admin.users.create": ["admin.panel.view"],
    "admin.users.role.update": ["assistants.view", "admin.panel.view"],
    "admin.users.deactivate": ["assistants.view", "admin.panel.view"],
    "rbac.view": ["admin.panel.view"],
    "rbac.update": ["rbac.view", "admin.panel.view"],
    "site.maintenance.view": ["admin.panel.view"],
    "site.maintenance.update": ["site.maintenance.view", "admin.panel.view"],
    "monitoring.view": ["admin.panel.view"],
}

SERVICE_IMPLIED_PERMISSION_STRIP: tuple[str, ...] = (
    "admin.panel.view",
)

LEGACY_PERMISSION_RENAMES: dict[str, tuple[str, ...]] = {
    "streamers.view": ("media.view",),
    "streamers.create": ("media.create",),
    "streamers.update": ("media.update",),
    "streamers.delete": ("media.delete",),
    "streamers.status.update": ("media.status.update",),
    "guild.view": ("game_servers.view",),
    "guild.settings.view": ("game_servers.settings.view",),
    "guild.settings.update": ("game_servers.settings.update",),
    "guild.templates.view": ("game_servers.templates.view",),
    "guild.templates.update": ("game_servers.templates.update",),
    "guild.rates.view": ("game_servers.rates.view",),
    "guild.rates.update": ("game_servers.rates.update",),
    "events.manage": ("events.runtime.manage",),
    "events.spec.request": ("events.spec_requests.create",),
    "events.spec.manage": ("events.spec_requests.review",),
    "events.join.self": ("events.participation.self.join",),
    "events.leave.self": ("events.participation.self.leave",),
    "events.leave.any": ("events.participation.any.leave",),
    "assistants.update": ("assistants.assignment.update",),
    "assistants.points.manage": ("assistants.points.update",),
    "assistants.create": ("admin.users.create", "admin.users.role.update"),
    "assistants.delete": ("admin.users.deactivate",),
    "logs.pr_actions.view": ("logs.assistant_actions.view",),
    "returns.view": ("returns.queue.view",),
    "returns.execute": ("returns.process",),
    "complaints.view": ("complaints.queue.view",),
    "complaints.execute": ("complaints.issue",),
    "removals.view": ("removals.queue.view",),
    "removals.execute": ("removals.issue",),
    "site.settings.view": ("rbac.view", "site.maintenance.view"),
    "site.settings.update": ("rbac.update", "site.maintenance.update"),
    "system.maintenance.bypass": ("maintenance.bypass",),
}

SITE_SETTINGS_REQUIRED_PERMISSIONS: tuple[str, ...] = (
    "rbac.update",
    "site.maintenance.update",
)

_ROLE_BUNDLES: dict[str, set[str]] = {
    "junior_employee": {
        "dashboard.view",
        "media.view",
        "assistants.view",
        "assistants.logs.view",
        "events.view",
        "events.spec_requests.create",
        "events.participation.self.join",
        "events.participation.self.leave",
        "spec.claimable.view",
        "spec.sessions.self.view",
        "spec.claim.main",
        "spec.claim.probation",
        "spec.unclaim.self",
        "returns.queue.view",
        "returns.history.view",
        "returns.create",
        "returns.process",
        "returns.manage.self",
        "complaints.queue.view",
        "complaints.history.view",
        "complaints.create",
        "complaints.issue",
        "complaints.manage.self",
        "removals.queue.view",
        "removals.history.view",
        "removals.create",
        "removals.issue",
        "removals.manage.self",
        "logs.assistant_actions.view",
    },
    "employee": {
        "dashboard.view",
        "media.view",
        "assistants.view",
        "assistants.logs.view",
        "events.view",
        "events.spec_requests.create",
        "events.participation.self.join",
        "events.participation.self.leave",
        "spec.claimable.view",
        "spec.sessions.self.view",
        "spec.claim.main",
        "spec.unclaim.self",
        "returns.queue.view",
        "returns.history.view",
        "returns.create",
        "returns.process",
        "returns.manage.self",
        "complaints.queue.view",
        "complaints.history.view",
        "complaints.create",
        "complaints.issue",
        "complaints.manage.self",
        "removals.queue.view",
        "removals.history.view",
        "removals.create",
        "removals.issue",
        "removals.manage.self",
        "logs.assistant_actions.view",
    },
    "senior_employee": {
        "dashboard.view",
        "media.view",
        "assistants.view",
        "assistants.logs.view",
        "events.view",
        "events.create",
        "events.spec_requests.create",
        "events.participation.self.join",
        "events.participation.self.leave",
        "spec.claimable.view",
        "spec.sessions.self.view",
        "spec.claim.main",
        "spec.unclaim.self",
        "returns.queue.view",
        "returns.history.view",
        "returns.create",
        "returns.process",
        "returns.manage.self",
        "complaints.queue.view",
        "complaints.history.view",
        "complaints.create",
        "complaints.issue",
        "complaints.manage.self",
        "removals.queue.view",
        "removals.history.view",
        "removals.create",
        "removals.issue",
        "removals.manage.self",
        "logs.assistant_actions.view",
        "admin.panel.view",
    },
    "manager": {
        "dashboard.view",
        "media.view",
        "media.create",
        "media.update",
        "media.delete",
        "spec.claimable.view",
        "spec.sessions.self.view",
        "spec.claim.main",
        "spec.claim.probation",
        "spec.unclaim.self",
        "spec.unclaim.any",
        "assistants.view",
        "assistants.assignment.update",
        "assistants.logs.view",
        "assistants.sessions.view",
        "assistants.sessions.manage",
        "assistants.points.update",
        "assistants.sanctions.manage",
        "assistants.warnings.manage",
        "assistants.weekly.view",
        "assistants.weekly.manage",
        "events.view",
        "events.create",
        "events.update",
        "events.runtime.manage",
        "events.spec_requests.create",
        "events.spec_requests.review",
        "events.participation.self.join",
        "events.participation.self.leave",
        "events.participation.any.leave",
        "returns.queue.view",
        "returns.history.view",
        "returns.create",
        "returns.process",
        "returns.manage.self",
        "returns.manage.any",
        "complaints.queue.view",
        "complaints.history.view",
        "complaints.create",
        "complaints.issue",
        "complaints.manage.self",
        "complaints.manage.any",
        "removals.queue.view",
        "removals.history.view",
        "removals.create",
        "removals.issue",
        "removals.manage.self",
        "removals.manage.any",
        "logs.assistant_actions.view",
        "logs.admin.view",
        "game_servers.view",
        "game_servers.settings.view",
        "game_servers.settings.update",
        "game_servers.templates.view",
        "game_servers.templates.update",
        "game_servers.rates.view",
        "game_servers.rates.update",
        "admin.panel.view",
        "admin.users.create",
        "admin.users.role.update",
        "admin.users.deactivate",
        "maintenance.bypass",
    },
    "developer": {
        "dashboard.view",
        "media.view",
        "media.create",
        "media.update",
        "media.delete",
        "media.status.update",
        "spec.claimable.view",
        "spec.sessions.self.view",
        "spec.claim.main",
        "spec.claim.probation",
        "spec.unclaim.self",
        "spec.unclaim.any",
        "assistants.view",
        "assistants.assignment.update",
        "assistants.logs.view",
        "assistants.sessions.view",
        "assistants.sessions.manage",
        "assistants.points.update",
        "assistants.sanctions.manage",
        "assistants.warnings.manage",
        "assistants.weekly.view",
        "assistants.weekly.manage",
        "events.view",
        "events.create",
        "events.update",
        "events.runtime.manage",
        "events.spec_requests.create",
        "events.spec_requests.review",
        "events.participation.self.join",
        "events.participation.self.leave",
        "events.participation.any.leave",
        "returns.queue.view",
        "returns.history.view",
        "returns.create",
        "returns.process",
        "returns.manage.self",
        "returns.manage.any",
        "complaints.queue.view",
        "complaints.history.view",
        "complaints.create",
        "complaints.issue",
        "complaints.manage.self",
        "complaints.manage.any",
        "removals.queue.view",
        "removals.history.view",
        "removals.create",
        "removals.issue",
        "removals.manage.self",
        "removals.manage.any",
        "logs.assistant_actions.view",
        "logs.admin.view",
        "game_servers.view",
        "game_servers.settings.view",
        "game_servers.settings.update",
        "game_servers.templates.view",
        "game_servers.templates.update",
        "game_servers.rates.view",
        "game_servers.rates.update",
        "admin.panel.view",
        "admin.users.create",
        "admin.users.role.update",
        "admin.users.deactivate",
        "rbac.view",
        "rbac.update",
        "site.maintenance.view",
        "site.maintenance.update",
        "maintenance.bypass",
        "monitoring.view",
        "notifications.render",
    },
}


def get_permission_catalog() -> tuple[str, ...]:
    return PERMISSION_CATALOG


def get_permission_implications() -> dict[str, list[str]]:
    return {key: list(value) for key, value in PERMISSION_IMPLICATIONS.items()}


def is_valid_role(role: str | None) -> bool:
    return str(role or "") in ROLE_RANK


def is_admin_role(role: str | None) -> bool:
    return str(role or "") in {"manager", "developer"}


def get_manageable_roles(actor_role: str | None) -> tuple[str, ...]:
    if not is_valid_role(actor_role):
        return ()
    if str(actor_role) == "developer":
        return STAFF_ROLES
    actor_rank = ROLE_RANK[str(actor_role)]
    return tuple(role for role in STAFF_ROLES if ROLE_RANK[role] < actor_rank)


def can_create_role(actor_role: str | None, target_role: str | None) -> bool:
    if not is_valid_role(actor_role) or not is_valid_role(target_role):
        return False
    if str(actor_role) == "developer":
        return True
    return ROLE_RANK[str(target_role)] < ROLE_RANK[str(actor_role)]


def can_manage_target_account(
    actor_role: str | None,
    target_current_role: str | None,
    target_new_role: str | None = None,
    *,
    is_self: bool = False,
) -> bool:
    if not is_valid_role(actor_role):
        return False
    if not is_valid_role(target_current_role):
        return False
    if str(actor_role) == "developer":
        return target_new_role is None or is_valid_role(target_new_role)
    if not is_self and ROLE_RANK[str(target_current_role)] >= ROLE_RANK[str(actor_role)]:
        return False
    if target_new_role is not None:
        if not is_valid_role(target_new_role):
            return False
        if ROLE_RANK[str(target_new_role)] > ROLE_RANK[str(actor_role)]:
            return False
        if not is_self and ROLE_RANK[str(target_new_role)] >= ROLE_RANK[str(actor_role)]:
            return False
    return True


def translate_permission_key(permission: str) -> tuple[str, ...]:
    normalized = str(permission or "").strip()
    if not normalized:
        return ()
    if normalized in PERMISSION_CATALOG:
        return (normalized,)
    return LEGACY_PERMISSION_RENAMES.get(normalized, ())


def translate_permission_map(
    permissions: Mapping[str, bool] | None,
) -> dict[str, bool]:
    translated: dict[str, bool] = {}
    if not permissions:
        return translated
    for raw_key, raw_value in permissions.items():
        if not raw_value:
            continue
        for key in translate_permission_key(str(raw_key)):
            translated[key] = True
    return translated


def normalize_permission_flags(
    permissions: Mapping[str, bool] | None,
) -> dict[str, bool]:
    normalized: dict[str, bool] = {}
    if not permissions:
        return normalized
    for raw_key, raw_value in permissions.items():
        targets = translate_permission_key(str(raw_key))
        if not targets:
            continue
        value = bool(raw_value)
        for key in targets:
            if value:
                normalized[key] = True
            else:
                normalized.setdefault(key, False)
    return normalized


def _expand_permission_flags(
    granted: Mapping[str, bool] | Sequence[str] | None,
) -> set[str]:
    if granted is None:
        active: dict[str, bool] = {}
    elif isinstance(granted, Mapping):
        active = {
            key: value
            for key, value in normalize_permission_flags(granted).items()
            if value
        }
    else:
        active = {
            key: True
            for raw_key in granted
            for key in translate_permission_key(str(raw_key))
        }

    expanded = {key for key, value in active.items() if value}
    queue = list(expanded)
    while queue:
        current = queue.pop()
        for implied in PERMISSION_IMPLICATIONS.get(current, []):
            if implied in expanded:
                continue
            expanded.add(implied)
            queue.append(implied)
    return expanded


def build_dense_permission_map(
    permissions: Mapping[str, bool] | Sequence[str] | None,
) -> dict[str, bool]:
    expanded = _expand_permission_flags(permissions)
    return {permission: permission in expanded for permission in PERMISSION_CATALOG}


def build_dense_service_permission_map(
    permissions: Mapping[str, bool] | Sequence[str] | None,
) -> dict[str, bool]:
    explicit: set[str]
    if permissions is None:
        explicit = set()
    elif isinstance(permissions, Mapping):
        explicit = {
            key
            for key, value in normalize_permission_flags(permissions).items()
            if value
        }
    else:
        explicit = {
            key
            for raw_key in permissions
            for key in translate_permission_key(str(raw_key))
        }

    dense = build_dense_permission_map(permissions)
    for permission in SERVICE_IMPLIED_PERMISSION_STRIP:
        if permission not in explicit:
            dense[permission] = False
    return dense


def get_default_role_permissions() -> dict[str, dict[str, bool]]:
    return {
        role: build_dense_permission_map(_ROLE_BUNDLES.get(role, set()))
        for role in STAFF_ROLES
    }
