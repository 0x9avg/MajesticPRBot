from __future__ import annotations

from .core import Any, Dict, List, Optional, _msk_now, datetime


class RemovalsMixin:
    async def create_punishment_removal(
        self,
        *,
        assistant_id: int,
        assistant_name: str,
        removal_type: str,
        violator_static: int,
        server: int,
        reason: str,
        message_link: Optional[str],
        target_status: str,
    ) -> Optional[dict]:
        reviewed_at = _msk_now() if target_status == "pending" else None
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO punishment_removals (
                            assistant_id,
                            assistant_name,
                            removal_type,
                            violator_static,
                            server,
                            reason,
                            message_link,
                            status,
                            reviewed_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            int(assistant_id),
                            assistant_name,
                            removal_type,
                            int(violator_static),
                            int(server),
                            reason,
                            message_link,
                            target_status,
                            reviewed_at,
                        ),
                    )
                    removal_id = int(cursor.lastrowid)
                    await conn.commit()
            return await self.get_punishment_removal(removal_id)
        except Exception as e:
            self.logger.error(f"Failed to create punishment removal: {e}", exc_info=True)
            return None

    async def get_punishment_removal(self, removal_id: int) -> Optional[dict]:
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT
                            id,
                            assistant_id,
                            assistant_name,
                            issuer_id,
                            issuer_name,
                            removal_type AS punishment_type,
                            violator_static AS `static`,
                            server,
                            reason,
                            message_link,
                            status,
                            created_at,
                            updated_at,
                            reviewed_at,
                            issued_at
                        FROM punishment_removals
                        WHERE id = %s
                        LIMIT 1
                        """,
                        (int(removal_id),),
                    )
                    row = await cursor.fetchone()
                    return dict(row) if row else None
        except Exception as e:
            self.logger.error(f"Failed to get punishment removal: {e}", exc_info=True)
            return None

    async def list_punishment_removals_queue(self, actor_id: int) -> list[dict]:
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT
                            id,
                            assistant_id,
                            assistant_name,
                            issuer_id,
                            issuer_name,
                            removal_type AS punishment_type,
                            violator_static AS `static`,
                            server,
                            reason,
                            message_link,
                            status,
                            created_at,
                            updated_at,
                            reviewed_at,
                            issued_at
                        FROM punishment_removals
                        WHERE (assistant_id = %s AND status = 'draft')
                           OR status = 'pending'
                        ORDER BY
                            CASE
                                WHEN assistant_id = %s AND status = 'draft' THEN 0
                                ELSE 1
                            END ASC,
                            CASE
                                WHEN status = 'draft' THEN updated_at
                                ELSE NULL
                            END DESC,
                            CASE
                                WHEN status = 'pending' THEN COALESCE(reviewed_at, created_at)
                                ELSE NULL
                            END ASC,
                            id DESC
                        """,
                        (int(actor_id), int(actor_id)),
                    )
                    return [dict(row) for row in await cursor.fetchall() or []]
        except Exception as e:
            self.logger.error(f"Failed to list punishment removals queue: {e}", exc_info=True)
            return []

    async def update_punishment_removal(
        self,
        removal_id: int,
        updates: dict[str, Any],
    ) -> Optional[dict]:
        filtered_updates = {
            key: value
            for key, value in updates.items()
            if key in {"removal_type", "violator_static", "server", "reason", "message_link", "target_status"}
        }
        if not filtered_updates:
            return await self.get_punishment_removal(removal_id)

        column_map = {
            "removal_type": "removal_type",
            "violator_static": "violator_static",
            "server": "server",
            "reason": "reason",
            "message_link": "message_link",
        }
        set_parts: list[str] = []
        params: list[Any] = []
        for key in ["removal_type", "violator_static", "server", "reason", "message_link"]:
            if key in filtered_updates:
                set_parts.append(f"{column_map[key]} = %s")
                params.append(filtered_updates[key])

        if "target_status" in filtered_updates:
            target_status = str(filtered_updates["target_status"])
            set_parts.append("status = %s")
            params.append(target_status)
            if target_status == "draft":
                set_parts.append("reviewed_at = %s")
                params.append(None)
            elif target_status == "pending":
                set_parts.append("reviewed_at = %s")
                params.append(_msk_now())

        params.append(int(removal_id))

        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        f"""
                        UPDATE punishment_removals
                        SET {", ".join(set_parts)}
                        WHERE id = %s
                        """,
                        tuple(params),
                    )
                    await conn.commit()
            return await self.get_punishment_removal(removal_id)
        except Exception as e:
            self.logger.error(f"Failed to update punishment removal: {e}", exc_info=True)
            return None

    async def delete_punishment_removal(self, removal_id: int) -> bool:
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "DELETE FROM punishment_removals WHERE id = %s",
                        (int(removal_id),),
                    )
                    deleted = cursor.rowcount > 0
                    await conn.commit()
                    return deleted
        except Exception as e:
            self.logger.error(f"Failed to delete punishment removal: {e}", exc_info=True)
            return False

    async def issue_punishment_removal(
        self,
        removal_id: int,
        *,
        issuer_id: int,
        issuer_name: str,
    ) -> Optional[dict]:
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        UPDATE punishment_removals
                        SET
                            status = 'issued',
                            issuer_id = %s,
                            issuer_name = %s,
                            issued_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                          AND status = 'pending'
                        """,
                        (int(issuer_id), issuer_name, int(removal_id)),
                    )
                    updated = cursor.rowcount > 0
                    await conn.commit()
            if not updated:
                return None
            return await self.get_punishment_removal(removal_id)
        except Exception as e:
            self.logger.error(f"Failed to issue punishment removal: {e}", exc_info=True)
            return None

    async def get_punishment_removals_history(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        filters: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        filters = filters or {}
        where_clauses = ["status = 'issued'"]
        params: list[Any] = []

        if filters.get("violator_static") is not None:
            where_clauses.append("violator_static = %s")
            params.append(int(filters["violator_static"]))
        if filters.get("server") is not None:
            where_clauses.append("server = %s")
            params.append(int(filters["server"]))
        if filters.get("removal_type"):
            where_clauses.append("removal_type = %s")
            params.append(filters["removal_type"])
        if filters.get("assistant_name"):
            where_clauses.append("assistant_name LIKE %s")
            params.append(f"%{filters['assistant_name']}%")
        if filters.get("issuer_name"):
            where_clauses.append("issuer_name LIKE %s")
            params.append(f"%{filters['issuer_name']}%")
        if filters.get("date_from"):
            where_clauses.append("issued_at >= %s")
            params.append(filters["date_from"])
        if filters.get("date_to"):
            where_clauses.append("issued_at <= %s")
            params.append(filters["date_to"])

        where_sql = "WHERE " + " AND ".join(where_clauses)
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        f"""
                        SELECT COUNT(*) AS total
                        FROM punishment_removals
                        {where_sql}
                        """,
                        tuple(params),
                    )
                    total_row = await cursor.fetchone() or {}
                    total = int(total_row.get("total") or 0)

                    await cursor.execute(
                        f"""
                        SELECT
                            id,
                            assistant_id,
                            assistant_name,
                            issuer_id,
                            issuer_name,
                            removal_type AS punishment_type,
                            violator_static AS `static`,
                            server,
                            reason,
                            message_link,
                            status,
                            created_at,
                            updated_at,
                            reviewed_at,
                            issued_at
                        FROM punishment_removals
                        {where_sql}
                        ORDER BY issued_at DESC, id DESC
                        LIMIT %s OFFSET %s
                        """,
                        tuple(params) + (int(limit), int(offset)),
                    )
                    return {
                        "items": [dict(row) for row in await cursor.fetchall() or []],
                        "total": total,
                    }
        except Exception as e:
            self.logger.error(f"Failed to get punishment removals history: {e}", exc_info=True)
            return {"items": [], "total": 0}
