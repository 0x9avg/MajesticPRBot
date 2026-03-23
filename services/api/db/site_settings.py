from __future__ import annotations

from .core import (
    Any,
    Config,
    Dict,
    List,
    Optional,
    SITE_SETTINGS_REQUIRED_PERMISSIONS,
    STAFF_ROLES,
    _default_role_permissions,
    _permission_catalog,
    build_dense_permission_map,
    build_dense_service_permission_map,
    hashlib,
    json,
    normalize_permission_flags,
)


class SiteSettingsMixin:
    @staticmethod
    def _plan_service_principal_token_hash_dedup(
        rows: list[Dict[str, Any]],
        configured_names: set[str],
    ) -> tuple[list[dict[str, str]], int]:
        """
        Build deterministic dedup updates for conflicting service_principals.token_hash rows.

        For each duplicate token_hash group:
        - keeper priority: configured service name, otherwise lexicographically smallest name
        - all non-keepers are moved to a unique legacy shadow hash and should be deactivated
        """
        grouped: dict[str, list[dict[str, str]]] = {}
        used_hashes: set[str] = set()

        for raw in rows or []:
            token_hash = str(raw.get("token_hash") or "").strip()
            name = str(raw.get("name") or "").strip()
            if not token_hash or not name:
                continue
            used_hashes.add(token_hash)
            grouped.setdefault(token_hash, []).append({"name": name, "token_hash": token_hash})

        updates: list[dict[str, str]] = []
        conflict_groups = 0
        for token_hash in sorted(grouped.keys()):
            group = grouped[token_hash]
            if len(group) <= 1:
                continue

            conflict_groups += 1
            configured_candidates = sorted(
                row["name"] for row in group if row["name"] in configured_names
            )
            keeper_name = (
                configured_candidates[0]
                if configured_candidates
                else min(row["name"] for row in group)
            )

            attempt = 1
            for row in sorted(group, key=lambda item: item["name"]):
                if row["name"] == keeper_name:
                    continue

                shadow_hash = hashlib.sha256(
                    f"legacy:{token_hash}:{row['name']}:{attempt}".encode("utf-8")
                ).hexdigest()
                while shadow_hash in used_hashes:
                    attempt += 1
                    shadow_hash = hashlib.sha256(
                        f"legacy:{token_hash}:{row['name']}:{attempt}".encode("utf-8")
                    ).hexdigest()

                used_hashes.add(shadow_hash)
                updates.append(
                    {
                        "name": row["name"],
                        "new_hash": shadow_hash,
                        "old_hash": token_hash,
                    }
                )
                attempt += 1

        return updates, conflict_groups

    @staticmethod
    def _get_default_service_permissions(service_name: str) -> dict[str, bool]:
        """Default least-privilege permissions for built-in service principals."""
        name = service_name.lower()
        discord_scope = {
            "media.create": True,
            "media.update": True,
            "media.delete": True,
            "media.status.update": True,
            "spec.sessions.self.view": True,
            "spec.claim.main": True,
            "spec.claim.probation": True,
            "spec.unclaim.any": True,
            "assistants.view": True,
            "assistants.sessions.manage": True,
            "events.create": True,
            "events.runtime.manage": True,
            "events.participation.any.leave": True,
            "game_servers.view": True,
            "game_servers.settings.update": True,
            "game_servers.templates.update": True,
            "game_servers.rates.update": True,
            "monitoring.view": True,
            "notifications.render": True,
            "dashboard.view": True,
        }
        twitch_scope = {
            "media.create": True,
            "media.status.update": True,
            "spec.unclaim.any": True,
        }
        if "discord" in name:
            return discord_scope
        if "twitch" in name:
            return twitch_scope
        # Deny by default for unknown service principals.
        return {}

    @staticmethod
    def _configured_service_tokens() -> list[tuple[str, str]]:
        """
        Parse configured service tokens into named tuples: (name, token).

        Config contract is strict and validated at startup.
        """
        return list(Config.service_token_map.items())

    @staticmethod
    def _hash_service_token(token: str) -> str:
        """Hash service bearer token for lookup/storage."""
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _coerce_permissions_dict(value: Any) -> dict[str, bool]:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                value = {}
        if not isinstance(value, dict):
            return {}
        return {str(key): bool(flag) for key, flag in value.items()}

    @staticmethod
    def _sorted_permission_catalog() -> list[str]:
        return sorted(_permission_catalog())

    @staticmethod
    def _role_sort_key(role: str) -> tuple[int, str]:
        role_order = STAFF_ROLES
        try:
            return (role_order.index(role), role)
        except ValueError:
            return (len(role_order), role)

    @classmethod
    def _normalize_role_permissions_for_catalog(
        cls,
        permissions: dict[str, bool],
    ) -> dict[str, bool]:
        normalized = cls._coerce_permissions_dict(permissions)
        return build_dense_permission_map(normalized)

    @classmethod
    def _build_role_permissions_snapshot(
        cls,
        rows: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        default_permissions = _default_role_permissions()
        rows_by_role = {
            str(row.get("role")): cls._coerce_permissions_dict(row.get("permissions"))
            for row in (rows or [])
            if row.get("role")
        }
        ordered_roles = sorted(
            set(default_permissions.keys()) | set(rows_by_role.keys()),
            key=cls._role_sort_key,
        )
        return [
            {
                "role": role,
                "permissions": cls._normalize_role_permissions_for_catalog(
                    rows_by_role.get(role, default_permissions.get(role, {}))
                ),
            }
            for role in ordered_roles
        ]

    @staticmethod
    def _validate_role_permissions_lockout(
        items: list[dict[str, Any]],
    ) -> None:
        for permission in SITE_SETTINGS_REQUIRED_PERMISSIONS:
            if any(
                bool((item.get("permissions") or {}).get(permission, False))
                for item in items
            ):
                continue
            raise ValueError(
                f"Нельзя сохранить роли без хотя бы одного назначения '{permission}'"
            )

    async def _get_site_maintenance_enabled_locked(self, cursor) -> bool:
        await cursor.execute(
            "SELECT site_maintenance_enabled FROM settings WHERE id = 1 LIMIT 1"
        )
        row = await cursor.fetchone()
        return bool(row.get("site_maintenance_enabled")) if row else False

    async def _list_role_permissions_snapshot_locked(
        self,
        cursor,
    ) -> list[dict[str, Any]]:
        await cursor.execute(
            """
            SELECT role, permissions
            FROM role_permissions
            ORDER BY role ASC
            """
        )
        rows = await cursor.fetchall() or []
        return self._build_role_permissions_snapshot(rows)

    async def get_role_permissions(self, role: str) -> dict:
        """Get permissions for a role from role_permissions table."""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT permissions FROM role_permissions WHERE role = %s", (role,)
                )
                row = await cursor.fetchone()
                if row:
                    return self._normalize_role_permissions_for_catalog(
                        row.get("permissions", {})
                    )
                defaults = _default_role_permissions()
                return self._normalize_role_permissions_for_catalog(
                    defaults.get(role, {})
                )

    async def _list_role_permissions_snapshot(self) -> list[dict[str, Any]]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                snapshot = await self._list_role_permissions_snapshot_locked(cursor)
                await conn.commit()
                return snapshot

    async def replace_role_permissions_snapshot(
        self,
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not items:
            raise ValueError("Нужно передать полный снимок role_permissions")

        normalized_items: list[dict[str, Any]] = []
        seen_roles: set[str] = set()
        catalog = set(self._sorted_permission_catalog())
        allowed_roles = set(STAFF_ROLES)
        for item in items:
            role = str(item.get("role") or "").strip()
            if not role:
                raise ValueError("role обязателен")
            if role in seen_roles:
                raise ValueError("role_permissions содержит дублирующиеся роли")
            if role not in allowed_roles:
                raise ValueError(f"Неизвестная роль: {role}")
            raw_permissions = self._coerce_permissions_dict(item.get("permissions") or {})
            unknown_permissions = sorted(
                permission for permission in raw_permissions.keys() if permission not in catalog
            )
            if unknown_permissions:
                raise ValueError(
                    "Неизвестные permissions: " + ", ".join(unknown_permissions)
                )
            normalized_items.append(
                {
                    "role": role,
                    "permissions": self._normalize_role_permissions_for_catalog(
                        raw_permissions
                    ),
                }
            )
            seen_roles.add(role)

        missing_roles = sorted(allowed_roles - seen_roles)
        if missing_roles:
            raise ValueError(
                "role_permissions snapshot must include all staff roles"
            )

        self._validate_role_permissions_lockout(normalized_items)

        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT role FROM role_permissions ORDER BY role ASC")
                existing_rows = await cursor.fetchall() or []
                existing_roles = {
                    str(row.get("role"))
                    for row in existing_rows
                    if row.get("role")
                }
                snapshot_roles = {item["role"] for item in normalized_items}
                missing_roles = sorted(existing_roles - snapshot_roles)
                if missing_roles:
                    raise ValueError(
                        "role_permissions snapshot must include all existing roles"
                    )

                for item in normalized_items:
                    payload = json.dumps(item["permissions"])
                    await cursor.execute(
                        """
                        INSERT INTO role_permissions (role, permissions)
                        VALUES (%s, %s)
                        ON DUPLICATE KEY UPDATE
                            permissions = VALUES(permissions),
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        (item["role"], payload),
                    )
                await conn.commit()
                return await self._list_role_permissions_snapshot()

    async def is_site_maintenance_enabled(self) -> bool:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                enabled = await self._get_site_maintenance_enabled_locked(cursor)
                await conn.commit()
                return enabled

    async def set_site_maintenance_enabled(self, enabled: bool) -> bool:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO settings (id, site_maintenance_enabled)
                    VALUES (1, %s)
                    ON DUPLICATE KEY UPDATE
                        site_maintenance_enabled = VALUES(site_maintenance_enabled)
                    """,
                    (bool(enabled),),
                )
                await conn.commit()
                return bool(enabled)

    async def get_site_settings_snapshot(self) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                maintenance_enabled = await self._get_site_maintenance_enabled_locked(cursor)
                role_permissions = await self._list_role_permissions_snapshot_locked(cursor)
                await conn.commit()
                return {
                    "site_maintenance_enabled": maintenance_enabled,
                    "permission_catalog": self._sorted_permission_catalog(),
                    "role_permissions": role_permissions,
                }

    async def get_service_principal_by_token(self, token: str) -> Optional[dict]:
        """Get active service principal by bearer token."""
        normalized_token = (token or "").strip()
        if not normalized_token:
            return None
        token_hash = self._hash_service_token(normalized_token)
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                try:
                    await cursor.execute(
                        """
                        SELECT name, permissions, is_active
                        FROM service_principals
                        WHERE token_hash = %s
                        LIMIT 1
                        """,
                        (token_hash,),
                    )
                    row = await cursor.fetchone()
                except Exception as e:
                    self.logger.error(
                        f"Service principal lookup failed (hash-only path): {e}",
                        exc_info=True,
                    )
                    return None
                if not row or not row.get("is_active", True):
                    return None

                raw_permissions = row.get("permissions") or {}
                permissions: dict[str, bool]
                if isinstance(raw_permissions, str):
                    try:
                        permissions = json.loads(raw_permissions)
                    except json.JSONDecodeError:
                        permissions = {}
                elif isinstance(raw_permissions, dict):
                    permissions = raw_permissions
                else:
                    permissions = {}

                return {
                    "principal_type": "service",
                    "service_name": row.get("name"),
                    "permissions": build_dense_service_permission_map(permissions),
                }
