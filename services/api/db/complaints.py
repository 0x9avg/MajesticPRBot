from __future__ import annotations

from .core import Any, Dict, List, Optional, _msk_now, datetime


class ComplaintsMixin:
    async def create_complaint(
        self,
        *,
        assistant_id: int,
        assistant_name: str,
        server: int,
        complaint_link: Optional[str],
        media: Optional[str],
        incident_at: datetime,
        target_status: str,
        punishments: list[dict[str, Any]],
    ) -> Optional[dict]:
        if not punishments:
            return None
        reviewed_at = _msk_now() if target_status == "pending" else None
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO complaints (
                            assistant_id,
                            assistant_name,
                            status,
                            server,
                            complaint_link,
                            media,
                            incident_at,
                            reviewed_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            int(assistant_id),
                            assistant_name,
                            target_status,
                            int(server),
                            complaint_link,
                            media,
                            incident_at,
                            reviewed_at,
                        ),
                    )
                    complaint_id = int(cursor.lastrowid)
                    for punishment in punishments:
                        await cursor.execute(
                            """
                            INSERT INTO complaint_punishments (
                                complaint_id,
                                punishment_type,
                                violator_static,
                                duration_value,
                                reason
                            )
                            VALUES (%s, %s, %s, %s, %s)
                            """,
                            (
                                complaint_id,
                                punishment.get("punishment_type"),
                                int(punishment.get("violator_static") or 0),
                                punishment.get("duration_value"),
                                punishment.get("reason"),
                            ),
                        )
                    await conn.commit()
            return await self.get_complaint(complaint_id)
        except Exception as e:
            self.logger.error(f"Failed to create complaint: {e}", exc_info=True)
            return None

    async def _load_complaint_punishments(
        self,
        cursor,
        complaint_ids: list[int],
    ) -> dict[int, list[dict[str, Any]]]:
        if not complaint_ids:
            return {}

        placeholders = ", ".join(["%s"] * len(complaint_ids))
        await cursor.execute(
            f"""
            SELECT
                id,
                complaint_id,
                punishment_type,
                violator_static AS `static`,
                duration_value AS duration,
                reason,
                created_at,
                updated_at
            FROM complaint_punishments
            WHERE complaint_id IN ({placeholders})
            ORDER BY complaint_id ASC, id ASC
            """,
            tuple(int(complaint_id) for complaint_id in complaint_ids),
        )
        grouped: dict[int, list[dict[str, Any]]] = {}
        for row in await cursor.fetchall() or []:
            normalized = dict(row)
            grouped.setdefault(int(normalized.get("complaint_id") or 0), []).append(normalized)
        return grouped

    async def get_complaint(self, complaint_id: int) -> Optional[dict]:
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
                            status,
                            server,
                            complaint_link,
                            media,
                            incident_at,
                            created_at,
                            updated_at,
                            reviewed_at,
                            issued_at,
                            claimed_at,
                            completed_at,
                            cancelled_at
                        FROM complaints
                        WHERE id = %s
                        LIMIT 1
                        """,
                        (int(complaint_id),),
                    )
                    complaint = await cursor.fetchone()
                    if not complaint:
                        return None
                    complaint_data = dict(complaint)
                    punishments_map = await self._load_complaint_punishments(cursor, [int(complaint_id)])
                    complaint_data["punishments"] = punishments_map.get(int(complaint_id), [])
                    complaint_data["punishment_count"] = len(complaint_data["punishments"])
                    return complaint_data
        except Exception as e:
            self.logger.error(f"Failed to get complaint: {e}", exc_info=True)
            return None

    async def list_complaints_queue(self, actor_id: int) -> list[dict]:
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT
                            c.id,
                            c.assistant_id,
                            c.assistant_name,
                            c.issuer_id,
                            c.issuer_name,
                            c.status,
                            c.server,
                            c.complaint_link,
                            c.media,
                            c.incident_at,
                            c.created_at,
                            c.updated_at,
                            c.reviewed_at,
                            c.issued_at,
                            counts.punishments_count AS punishment_count
                        FROM complaints c
                        INNER JOIN (
                            SELECT complaint_id, COUNT(*) AS punishments_count
                            FROM complaint_punishments
                            GROUP BY complaint_id
                        ) counts ON counts.complaint_id = c.id
                        WHERE (c.assistant_id = %s AND c.status = 'draft')
                           OR c.status = 'pending'
                        ORDER BY
                            CASE
                                WHEN c.assistant_id = %s AND c.status = 'draft' THEN 0
                                ELSE 1
                            END ASC,
                            CASE
                                WHEN c.status = 'draft' THEN c.updated_at
                                ELSE NULL
                            END DESC,
                            CASE
                                WHEN c.status = 'pending' THEN COALESCE(c.reviewed_at, c.created_at)
                                ELSE NULL
                            END ASC,
                            c.id DESC
                        """,
                        (int(actor_id), int(actor_id)),
                    )
                    rows = [dict(row) for row in await cursor.fetchall() or []]
                    punishments_map = await self._load_complaint_punishments(
                        cursor,
                        [int(row.get("id") or 0) for row in rows],
                    )
                    for row in rows:
                        complaint_id = int(row.get("id") or 0)
                        row["punishments"] = punishments_map.get(complaint_id, [])
                        row["punishment_count"] = int(row.get("punishment_count") or len(row["punishments"]))
                    return rows
        except Exception as e:
            self.logger.error(f"Failed to list complaints queue: {e}", exc_info=True)
            return []

    async def update_complaint(
        self,
        complaint_id: int,
        *,
        header_updates: dict[str, Any] | None = None,
        punishments: Optional[list[dict[str, Any]]] = None,
        target_status: Optional[str] = None,
    ) -> Optional[dict]:
        header_updates = header_updates or {}
        allowed_header_updates = {
            key: value
            for key, value in header_updates.items()
            if key in {"server", "complaint_link", "media", "incident_at"}
        }

        if target_status is None and not allowed_header_updates and punishments is None:
            return await self.get_complaint(complaint_id)

        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT id FROM complaints WHERE id = %s LIMIT 1",
                        (int(complaint_id),),
                    )
                    existing = await cursor.fetchone()
                    if not existing:
                        return None

                    if target_status is not None:
                        allowed_header_updates["status"] = target_status
                        if target_status == "draft":
                            allowed_header_updates["reviewed_at"] = None
                        elif target_status == "pending":
                            allowed_header_updates["reviewed_at"] = _msk_now()

                    if allowed_header_updates:
                        column_map = {
                            "server": "server",
                            "complaint_link": "complaint_link",
                            "media": "media",
                            "incident_at": "incident_at",
                            "status": "status",
                            "reviewed_at": "reviewed_at",
                        }
                        set_parts: list[str] = []
                        params: list[Any] = []
                        for key, value in allowed_header_updates.items():
                            set_parts.append(f"{column_map[key]} = %s")
                            params.append(value)
                        params.append(int(complaint_id))
                        await cursor.execute(
                            f"""
                            UPDATE complaints
                            SET {", ".join(set_parts)}
                            WHERE id = %s
                            """,
                            tuple(params),
                        )

                    if punishments is not None:
                        await cursor.execute(
                            """
                            SELECT id
                            FROM complaint_punishments
                            WHERE complaint_id = %s
                            """,
                            (int(complaint_id),),
                        )
                        existing_rows = await cursor.fetchall() or []
                        existing_ids = {int(row.get("id") or 0) for row in existing_rows}
                        kept_ids: set[int] = set()

                        for punishment in punishments:
                            raw_id = punishment.get("id")
                            if raw_id is None:
                                await cursor.execute(
                                    """
                                    INSERT INTO complaint_punishments (
                                        complaint_id,
                                        punishment_type,
                                        violator_static,
                                        duration_value,
                                        reason
                                    )
                                    VALUES (%s, %s, %s, %s, %s)
                                    """,
                                    (
                                        int(complaint_id),
                                        punishment.get("punishment_type"),
                                        int(punishment.get("violator_static") or 0),
                                        punishment.get("duration_value"),
                                        punishment.get("reason"),
                                    ),
                                )
                                continue

                            punishment_id = int(raw_id)
                            if punishment_id not in existing_ids:
                                await conn.rollback()
                                return None
                            kept_ids.add(punishment_id)
                            await cursor.execute(
                                """
                                UPDATE complaint_punishments
                                SET
                                    punishment_type = %s,
                                    violator_static = %s,
                                    duration_value = %s,
                                    reason = %s
                                WHERE id = %s
                                  AND complaint_id = %s
                                """,
                                (
                                    punishment.get("punishment_type"),
                                    int(punishment.get("violator_static") or 0),
                                    punishment.get("duration_value"),
                                    punishment.get("reason"),
                                    punishment_id,
                                    int(complaint_id),
                                ),
                            )

                        stale_ids = existing_ids - kept_ids
                        if stale_ids:
                            placeholders = ", ".join(["%s"] * len(stale_ids))
                            await cursor.execute(
                                f"""
                                DELETE FROM complaint_punishments
                                WHERE complaint_id = %s
                                  AND id IN ({placeholders})
                                """,
                                (int(complaint_id), *sorted(stale_ids)),
                            )

                    await conn.commit()
            return await self.get_complaint(complaint_id)
        except Exception as e:
            self.logger.error(f"Failed to update complaint: {e}", exc_info=True)
            return None

    async def delete_complaint(self, complaint_id: int) -> bool:
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "DELETE FROM complaint_punishments WHERE complaint_id = %s",
                        (int(complaint_id),),
                    )
                    await cursor.execute(
                        "DELETE FROM complaints WHERE id = %s",
                        (int(complaint_id),),
                    )
                    deleted = cursor.rowcount > 0
                    await conn.commit()
                    return deleted
        except Exception as e:
            self.logger.error(f"Failed to delete complaint: {e}", exc_info=True)
            return False

    async def delete_complaint_punishment(self, complaint_id: int, punishment_id: int) -> bool:
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        DELETE FROM complaint_punishments
                        WHERE complaint_id = %s
                          AND id = %s
                        """,
                        (int(complaint_id), int(punishment_id)),
                    )
                    deleted = cursor.rowcount > 0
                    await conn.commit()
                    return deleted
        except Exception as e:
            self.logger.error(f"Failed to delete complaint punishment: {e}", exc_info=True)
            return False

    async def issue_complaint(
        self,
        complaint_id: int,
        *,
        issuer_id: int,
        issuer_name: str,
    ) -> Optional[dict]:
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        UPDATE complaints
                        SET
                            status = 'issued',
                            issuer_id = %s,
                            issuer_name = %s,
                            issued_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                          AND status = 'pending'
                        """,
                        (int(issuer_id), issuer_name, int(complaint_id)),
                    )
                    updated = cursor.rowcount > 0
                    await conn.commit()
            if not updated:
                return None
            return await self.get_complaint(complaint_id)
        except Exception as e:
            self.logger.error(f"Failed to issue complaint: {e}", exc_info=True)
            return None

    async def get_complaints_history(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        filters: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        filters = filters or {}
        where_clauses = ["c.status = 'issued'"]
        params: list[Any] = []

        if filters.get("violator_static") is not None:
            where_clauses.append(
                """
                EXISTS (
                    SELECT 1
                    FROM complaint_punishments p_filter
                    WHERE p_filter.complaint_id = c.id
                      AND p_filter.violator_static = %s
                )
                """
            )
            params.append(int(filters["violator_static"]))
        if filters.get("server") is not None:
            where_clauses.append("c.server = %s")
            params.append(int(filters["server"]))
        if filters.get("punishment_type"):
            where_clauses.append(
                """
                EXISTS (
                    SELECT 1
                    FROM complaint_punishments p_filter
                    WHERE p_filter.complaint_id = c.id
                      AND p_filter.punishment_type = %s
                )
                """
            )
            params.append(filters["punishment_type"])
        if filters.get("assistant_name"):
            where_clauses.append("c.assistant_name LIKE %s")
            params.append(f"%{filters['assistant_name']}%")
        if filters.get("issuer_name"):
            where_clauses.append("c.issuer_name LIKE %s")
            params.append(f"%{filters['issuer_name']}%")
        if filters.get("date_from"):
            where_clauses.append("c.issued_at >= %s")
            params.append(filters["date_from"])
        if filters.get("date_to"):
            where_clauses.append("c.issued_at <= %s")
            params.append(filters["date_to"])

        where_sql = "WHERE " + " AND ".join(where_clauses)
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        f"""
                        SELECT COUNT(*) AS total
                        FROM complaints c
                        {where_sql}
                        """,
                        tuple(params),
                    )
                    total_row = await cursor.fetchone() or {}
                    total = int(total_row.get("total") or 0)

                    await cursor.execute(
                        f"""
                        SELECT
                            c.id,
                            c.assistant_id,
                            c.assistant_name,
                            c.issuer_id,
                            c.issuer_name,
                            c.status,
                            c.server,
                            c.complaint_link,
                            c.media,
                            c.incident_at,
                            c.created_at,
                            c.updated_at,
                            c.reviewed_at,
                            c.issued_at,
                            counts.punishments_count AS punishment_count
                        FROM complaints c
                        INNER JOIN (
                            SELECT complaint_id, COUNT(*) AS punishments_count
                            FROM complaint_punishments
                            GROUP BY complaint_id
                        ) counts ON counts.complaint_id = c.id
                        {where_sql}
                        ORDER BY c.issued_at DESC, c.id DESC
                        LIMIT %s OFFSET %s
                        """,
                        tuple(params) + (int(limit), int(offset)),
                    )
                    rows = [dict(row) for row in await cursor.fetchall() or []]
                    punishments_map = await self._load_complaint_punishments(
                        cursor,
                        [int(row.get("id") or 0) for row in rows],
                    )
                    for row in rows:
                        complaint_id = int(row.get("id") or 0)
                        row["punishments"] = punishments_map.get(complaint_id, [])
                        row["punishment_count"] = int(row.get("punishment_count") or len(row["punishments"]))
                    return {
                        "items": rows,
                        "total": total,
                    }
        except Exception as e:
            self.logger.error(f"Failed to get complaints history: {e}", exc_info=True)
            return {"items": [], "total": 0}
