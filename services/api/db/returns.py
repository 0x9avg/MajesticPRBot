from __future__ import annotations

from .core import Any, Dict, List, Optional


class ReturnsMixin:
    async def create_punishment_return(
        self,
        *,
        punishment_type: str,
        static: int,
        server: int,
        duration: int,
        remove_reason: str,
        discord_message_url: Optional[str],
        removed_by_id: int,
        removed_by_name: str,
    ) -> Optional[dict]:
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO punishment_returns (
                            punishment_type,
                            `static`,
                            server,
                            duration,
                            remove_reason,
                            discord_message_url,
                            removed_by_id,
                            removed_by_name
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            punishment_type,
                            int(static),
                            int(server),
                            int(duration),
                            remove_reason,
                            discord_message_url,
                            int(removed_by_id),
                            removed_by_name,
                        ),
                    )
                    return_id = cursor.lastrowid
                    await conn.commit()

            return await self.get_punishment_return(return_id)
        except Exception as e:
            self.logger.error(f"Failed to create punishment return: {e}", exc_info=True)
            return None

    async def get_punishment_return(self, return_id: int) -> Optional[dict]:
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT
                            id,
                            punishment_type,
                            `static`,
                            server,
                            duration,
                            remove_reason,
                            discord_message_url,
                            removed_by_id,
                            removed_by_name,
                            removed_at,
                            claimed_by_id,
                            claimed_by_name,
                            claimed_at,
                            completed_by_id,
                            completed_by_name,
                            completed_at,
                            status,
                            created_at,
                            updated_at
                        FROM punishment_returns
                        WHERE id = %s
                        LIMIT 1
                        """,
                        (int(return_id),),
                    )
                    row = await cursor.fetchone()
                    return dict(row) if row else None
        except Exception as e:
            self.logger.error(f"Failed to get punishment return: {e}", exc_info=True)
            return None

    async def list_punishment_returns_queue(self) -> list[dict]:
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT
                            id,
                            punishment_type,
                            `static`,
                            server,
                            duration,
                            remove_reason,
                            discord_message_url,
                            removed_by_id,
                            removed_by_name,
                            removed_at,
                            claimed_by_id,
                            claimed_by_name,
                            claimed_at,
                            completed_by_id,
                            completed_by_name,
                            completed_at,
                            status,
                            created_at,
                            updated_at
                        FROM punishment_returns
                        WHERE status IN ('pending', 'claimed')
                        ORDER BY
                            CASE
                                WHEN status = 'pending'
                                  AND TIMESTAMPADD(HOUR, 12, removed_at) <= CURRENT_TIMESTAMP THEN 0
                                WHEN status = 'claimed' THEN 1
                                ELSE 2
                            END ASC,
                            removed_at ASC,
                            id ASC
                        """
                    )
                    rows = await cursor.fetchall() or []
                    return [dict(row) for row in rows]
        except Exception as e:
            self.logger.error(
                f"Failed to list punishment returns queue: {e}",
                exc_info=True,
            )
            return []

    async def claim_punishment_return(
        self,
        return_id: int,
        *,
        claimed_by_id: int,
        claimed_by_name: str,
    ) -> Optional[dict]:
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        UPDATE punishment_returns
                        SET
                            status = 'claimed',
                            claimed_by_id = %s,
                            claimed_by_name = %s,
                            claimed_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                          AND status = 'pending'
                          AND TIMESTAMPADD(HOUR, 12, removed_at) <= CURRENT_TIMESTAMP
                        """,
                        (int(claimed_by_id), claimed_by_name, int(return_id)),
                    )
                    updated = cursor.rowcount > 0
                    await conn.commit()

            if not updated:
                return None
            return await self.get_punishment_return(return_id)
        except Exception as e:
            self.logger.error(f"Failed to claim punishment return: {e}", exc_info=True)
            return None

    async def complete_punishment_return(
        self,
        return_id: int,
        *,
        completed_by_id: int,
        completed_by_name: str,
        claimer_only: bool = True,
    ) -> Optional[dict]:
        try:
            params: list[Any] = [int(completed_by_id), completed_by_name, int(return_id)]
            where_sql = "status = 'claimed'"
            if claimer_only:
                where_sql += " AND claimed_by_id = %s"
                params.append(int(completed_by_id))

            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        f"""
                        UPDATE punishment_returns
                        SET
                            status = 'completed',
                            completed_by_id = %s,
                            completed_by_name = %s,
                            completed_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                          AND {where_sql}
                        """,
                        tuple(params),
                    )
                    updated = cursor.rowcount > 0
                    await conn.commit()

            if not updated:
                return None
            return await self.get_punishment_return(return_id)
        except Exception as e:
            self.logger.error(
                f"Failed to complete punishment return: {e}",
                exc_info=True,
            )
            return None

    async def release_punishment_return(
        self,
        return_id: int,
        *,
        claimed_by_id: int,
        claimer_only: bool = True,
    ) -> Optional[dict]:
        try:
            params: list[Any] = [int(return_id)]
            where_sql = "status = 'claimed'"
            if claimer_only:
                where_sql += " AND claimed_by_id = %s"
                params.append(int(claimed_by_id))

            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        f"""
                        UPDATE punishment_returns
                        SET
                            status = 'pending',
                            claimed_by_id = NULL,
                            claimed_by_name = NULL,
                            claimed_at = NULL
                        WHERE id = %s
                          AND {where_sql}
                        """,
                        tuple(params),
                    )
                    updated = cursor.rowcount > 0
                    await conn.commit()

            if not updated:
                return None
            return await self.get_punishment_return(return_id)
        except Exception as e:
            self.logger.error(
                f"Failed to release punishment return: {e}",
                exc_info=True,
            )
            return None

    async def update_punishment_return(
        self,
        return_id: int,
        updates: dict[str, Any],
    ) -> Optional[dict]:
        filtered_updates = {
            key: value
            for key, value in updates.items()
            if key
            in {
                "punishment_type",
                "static",
                "server",
                "duration",
                "remove_reason",
                "discord_message_url",
            }
        }
        if not filtered_updates:
            return await self.get_punishment_return(return_id)

        column_map = {
            "punishment_type": "punishment_type",
            "static": "`static`",
            "server": "server",
            "duration": "duration",
            "remove_reason": "remove_reason",
            "discord_message_url": "discord_message_url",
        }

        set_parts: list[str] = []
        params: list[Any] = []
        for key, value in filtered_updates.items():
            set_parts.append(f"{column_map[key]} = %s")
            params.append(value)
        params.append(int(return_id))

        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        f"""
                        UPDATE punishment_returns
                        SET {", ".join(set_parts)}
                        WHERE id = %s
                        """,
                        tuple(params),
                    )
                    await conn.commit()

            # MySQL may report rowcount=0 for a no-op update even when the row exists.
            return await self.get_punishment_return(return_id)
        except Exception as e:
            self.logger.error(f"Failed to update punishment return: {e}", exc_info=True)
            return None

    async def delete_punishment_return(self, return_id: int) -> bool:
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "DELETE FROM punishment_returns WHERE id = %s",
                        (int(return_id),),
                    )
                    deleted = cursor.rowcount > 0
                    await conn.commit()
                    return deleted
        except Exception as e:
            self.logger.error(f"Failed to delete punishment return: {e}", exc_info=True)
            return False

    async def get_punishment_return_history(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        filters: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        filters = filters or {}
        where_clauses = ["status = 'completed'"]
        params: list[Any] = []

        if filters.get("static") is not None:
            where_clauses.append("`static` = %s")
            params.append(int(filters["static"]))

        if filters.get("server") is not None:
            where_clauses.append("server = %s")
            params.append(int(filters["server"]))

        if filters.get("punishment_type"):
            where_clauses.append("punishment_type = %s")
            params.append(filters["punishment_type"])

        if filters.get("removed_by_name"):
            where_clauses.append("removed_by_name LIKE %s")
            params.append(f"%{filters['removed_by_name']}%")

        if filters.get("completed_by_name"):
            where_clauses.append("completed_by_name LIKE %s")
            params.append(f"%{filters['completed_by_name']}%")

        if filters.get("date_from"):
            where_clauses.append("completed_at >= %s")
            params.append(filters["date_from"])

        if filters.get("date_to"):
            where_clauses.append("completed_at <= %s")
            params.append(filters["date_to"])

        where_sql = "WHERE " + " AND ".join(where_clauses)

        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        f"""
                        SELECT COUNT(*) AS total
                        FROM punishment_returns
                        {where_sql}
                        """,
                        tuple(params),
                    )
                    total_row = await cursor.fetchone() or {}
                    total = int(total_row.get("total", 0))

                    await cursor.execute(
                        f"""
                        SELECT
                            id,
                            punishment_type,
                            `static`,
                            server,
                            duration,
                            remove_reason,
                            discord_message_url,
                            removed_by_id,
                            removed_by_name,
                            removed_at,
                            claimed_by_id,
                            claimed_by_name,
                            claimed_at,
                            completed_by_id,
                            completed_by_name,
                            completed_at,
                            status,
                            created_at,
                            updated_at
                        FROM punishment_returns
                        {where_sql}
                        ORDER BY completed_at DESC, id DESC
                        LIMIT %s OFFSET %s
                        """,
                        tuple(params) + (int(limit), int(offset)),
                    )
                    rows = await cursor.fetchall() or []
                    return {
                        "items": [dict(row) for row in rows],
                        "total": total,
                    }
        except Exception as e:
            self.logger.error(
                f"Failed to get punishment return history: {e}",
                exc_info=True,
            )
            return {"items": [], "total": 0}
