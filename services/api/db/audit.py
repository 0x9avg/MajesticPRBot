from __future__ import annotations

from .core import Any, Dict, List, Optional, datetime, json


class AuditMixin:
    async def log_admin_action_v2(
        self,
        actor_name: str,
        action: str,
        actor_role: Optional[str] = None,
        actor_id: Optional[int] = None,
        actor_type: Optional[str] = None,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        details: Optional[dict] = None,
        trace_id: Optional[str] = None,
    ) -> None:
        """Write compact universal admin log event."""
        event_details = details or {}
        if not isinstance(event_details, dict):
            event_details = {"payload": {"value": event_details}}

        if "summary" not in event_details:
            event_details["summary"] = action

        meta = event_details.get("meta") or {}
        if actor_id is None:
            try:
                actor_id = int(meta.get("actor_id")) if meta.get("actor_id") is not None else None
            except (TypeError, ValueError):
                actor_id = None
        if actor_type is None:
            actor_type = str(meta.get("actor_type") or "user")
        if trace_id is None:
            trace_id = meta.get("trace_id")

        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO admin_logs
                            (actor_name, actor_role, actor_id, actor_type, trace_id, action, target_type, target_id, details)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            actor_name,
                            actor_role,
                            actor_id,
                            actor_type,
                            trace_id,
                            action,
                            target_type,
                            target_id,
                            json.dumps(event_details, default=str),
                        ),
                    )
                    await conn.commit()
        except Exception as e:
            self.logger.error(f"Failed to log admin action: {e}", exc_info=True)

    @staticmethod
    def _action_matches_kind(action: str, kind: str) -> bool:
        if kind == "other":
            return "." not in action
        prefix = AuditMixin._kind_to_action_prefix(kind)
        if not prefix:
            return False
        return action.startswith(prefix)

    @staticmethod
    def _kind_to_action_prefix(kind: str) -> Optional[str]:
        prefix_map = {
            "user": "user.",
            "streamer": "streamer.",
            "event": "event.",
            "assistant": "assistant.",
            "system": "system.",
            "rbac": "rbac.",
            "spec": "spec.",
            "guild": "guild.",
            "return": "return.",
        }
        return prefix_map.get(kind)

    async def get_admin_logs(
        self,
        limit: int = 100,
        offset: int = 0,
        filters: dict = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ):
        """
        Get admin logs with optional filtering and pagination.

        Args:
            limit: Number of records to fetch
            offset: Offset for pagination
            filters: Optional dictionary with filters:
                - action: str
                - admin_name: str (partial match)
                - start_date: datetime
                - end_date: datetime
                - target_type: str

        Returns:
            List of log dictionaries with admin info
        """
        try:
            filters = filters or {}
            where_clauses = []
            params = []
            allowed_sorts = {
                "created_at": "al.created_at",
                "actor_name": "al.actor_name",
                "admin_name": "al.actor_name",
                "action": "al.action",
                "target_name": "target_name",
            }
            sort_column = allowed_sorts.get(sort_by, "al.created_at")
            sort_dir = "ASC" if sort_order.lower() == "asc" else "DESC"

            if filters.get("action"):
                actions = filters["action"]
                if isinstance(actions, list) and len(actions) > 0:
                    placeholders = ", ".join(["%s"] * len(actions))
                    where_clauses.append(f"al.action IN ({placeholders})")
                    params.extend(actions)
                elif isinstance(actions, str) and actions != "all":
                    where_clauses.append("al.action = %s")
                    params.append(actions)

            actor_name = filters.get("actor_name") or filters.get("admin_name")
            if actor_name:
                where_clauses.append("al.actor_name LIKE %s")
                params.append(f"%{actor_name}%")

            if filters.get("target_type") and filters["target_type"] != "all":
                where_clauses.append("al.target_type = %s")
                params.append(filters["target_type"])

            if filters.get("start_date"):
                where_clauses.append("al.created_at >= %s")
                params.append(filters["start_date"])

            if filters.get("end_date"):
                where_clauses.append("al.created_at <= %s")
                params.append(filters["end_date"])

            kind = filters.get("kind")
            if kind:
                if kind == "other":
                    where_clauses.append("al.action NOT LIKE %s")
                    params.append("%.%")
                else:
                    prefix = self._kind_to_action_prefix(kind)
                    if not prefix:
                        return []
                    where_clauses.append("al.action LIKE %s")
                    params.append(f"{prefix}%")

            where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

            params.append(limit)
            params.append(offset)

            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    sql_query = f"""
                        SELECT 
                            al.id,
                            al.actor_name,
                            al.actor_role,
                            al.action,
                            al.target_type,
                            al.target_id,
                            al.details,
                            al.created_at,
                            CASE 
                                WHEN al.target_type = 'streamer' THEN s.streamer_name
                                WHEN al.target_type = 'event' THEN e.name
                                ELSE al.target_id
                            END as target_name
                        FROM admin_logs al
                        LEFT JOIN streamers s ON al.target_type = 'streamer' AND al.target_id COLLATE utf8mb4_general_ci = CAST(s.streamer_id AS CHAR)
                        LEFT JOIN events e ON al.target_type = 'event' AND al.target_id COLLATE utf8mb4_general_ci = CAST(e.id AS CHAR)
                        {where_sql}
                        ORDER BY {sort_column} {sort_dir}
                        LIMIT %s OFFSET %s
                        """
                    await cursor.execute(sql_query, tuple(params))

                    logs = await cursor.fetchall()
                    result = []

                    for log in logs:
                        log_dict = dict(log)
                        log_dict["kind"] = (
                            log_dict["action"].split(".", 1)[0]
                            if "." in log_dict["action"]
                            else "other"
                        )
                        if log_dict.get("details"):
                            try:
                                if isinstance(log_dict["details"], str):
                                    log_dict["details"] = json.loads(
                                        log_dict["details"]
                                    )
                            except (json.JSONDecodeError, TypeError):
                                pass
                        log_dict["admin_name"] = log_dict.get("actor_name")
                        log_dict["admin_role"] = log_dict.get("actor_role")
                        result.append(log_dict)

                    return result
        except Exception as e:
            self.logger.error(f"Failed to fetch admin logs: {e}", exc_info=True)
            return []

    async def count_admin_logs(self, filters: dict = None) -> int:
        """Count admin logs matching the given filters."""
        try:
            filters = filters or {}
            where_clauses = []
            params = []

            if filters.get("action"):
                actions = filters["action"]
                if isinstance(actions, list) and len(actions) > 0:
                    placeholders = ", ".join(["%s"] * len(actions))
                    where_clauses.append(f"al.action IN ({placeholders})")
                    params.extend(actions)
                elif isinstance(actions, str) and actions != "all":
                    where_clauses.append("al.action = %s")
                    params.append(actions)

            actor_name = filters.get("actor_name") or filters.get("admin_name")
            if actor_name:
                where_clauses.append("al.actor_name LIKE %s")
                params.append(f"%{actor_name}%")

            if filters.get("target_type") and filters["target_type"] != "all":
                where_clauses.append("al.target_type = %s")
                params.append(filters["target_type"])

            if filters.get("start_date"):
                where_clauses.append("al.created_at >= %s")
                params.append(filters["start_date"])

            if filters.get("end_date"):
                where_clauses.append("al.created_at <= %s")
                params.append(filters["end_date"])

            kind = filters.get("kind")
            if kind:
                if kind == "other":
                    where_clauses.append("al.action NOT LIKE %s")
                    params.append("%.%")
                else:
                    prefix = self._kind_to_action_prefix(kind)
                    if not prefix:
                        return 0
                    where_clauses.append("al.action LIKE %s")
                    params.append(f"{prefix}%")

            where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        f"SELECT COUNT(*) as total FROM admin_logs al {where_sql}",
                        tuple(params),
                    )
                    row = await cursor.fetchone()
                    return row["total"] if row else 0
        except Exception as e:
            self.logger.error(f"Failed to count admin logs: {e}", exc_info=True)
            return 0

    def _build_pr_action_filters(self, filters: dict):
        """Build WHERE clauses and params from filters dict for PR action logs."""
        where_parts = []
        params = []

        if filters.get("pr_id"):
            where_parts.append("ss.pr_id = %s")
            params.append(int(filters["pr_id"]))

        if filters.get("priority") is not None:
            where_parts.append("ss.applied_priority_level = %s")
            params.append(int(filters["priority"]))

        if filters.get("target_type") and filters["target_type"] != "all":
            where_parts.append("ss.target_type = %s")
            params.append(filters["target_type"])

        return where_parts, params

    def _build_date_filter_join(self, filters: dict, time_col: str):
        """Build date range filter for a specific time column."""
        parts = []
        params = []
        if filters.get("date_from"):
            parts.append(f"{time_col} >= %s")
            params.append(filters["date_from"])
        if filters.get("date_to"):
            parts.append(f"{time_col} <= %s")
            params.append(filters["date_to"])
        return parts, params

    async def get_pr_action_logs(
        self,
        limit: int = 20,
        offset: int = 0,
        filters: dict = None,
    ) -> dict:
        """
        Get PR action logs (joins/leaves) with pagination and filtering.

        Uses UNION ALL to split spec_sessions into individual join/leave events.
        Returns dict with 'items' and 'total'.
        """
        try:
            filters = filters or {}

            # Build shared WHERE clauses (applied to both halves of UNION)
            base_where, base_params = self._build_pr_action_filters(filters)

            # Date filters applied specifically to each half's time column
            join_date_parts, join_date_params = self._build_date_filter_join(filters, "ss.started_at")
            leave_date_parts, leave_date_params = self._build_date_filter_join(filters, "ss.ended_at")

            # Action type filter
            action_type_filter = filters.get("action_type")  # 'join' | 'leave' | None

            # === Build JOIN half ===
            join_where_parts = list(base_where) + join_date_parts
            join_where_parts.append("ss.deleted_at IS NULL")
            join_params = list(base_params) + join_date_params
            join_where_sql = "WHERE " + " AND ".join(join_where_parts) if join_where_parts else ""

            join_sql = f"""
                SELECT
                    ss.id as session_id,
                    ss.pr_id,
                    ss.target_type,
                    ss.target_id,
                    ss.started_at as action_time,
                    'join' as action_type,
                    NULL as duration_seconds,
                    ss.applied_priority_level as priority,
                    ss.is_probation,
                    ss.end_reason
                FROM spec_sessions ss
                {join_where_sql}
            """

            # === Build LEAVE half ===
            leave_where_parts = list(base_where) + leave_date_parts
            leave_where_parts.append("ss.ended_at IS NOT NULL")
            leave_where_parts.append("ss.deleted_at IS NULL")
            leave_params = list(base_params) + leave_date_params
            leave_where_sql = "WHERE " + " AND ".join(leave_where_parts) if leave_where_parts else ""

            leave_sql = f"""
                SELECT
                    ss.id as session_id,
                    ss.pr_id,
                    ss.target_type,
                    ss.target_id,
                    ss.ended_at as action_time,
                    'leave' as action_type,
                    ss.duration_seconds,
                    ss.applied_priority_level as priority,
                    ss.is_probation,
                    ss.end_reason
                FROM spec_sessions ss
                {leave_where_sql}
            """

            # Combine based on action_type filter
            if action_type_filter == "join":
                union_sql = join_sql
                union_params = join_params
            elif action_type_filter == "leave":
                union_sql = leave_sql
                union_params = leave_params
            else:
                union_sql = f"({join_sql}) UNION ALL ({leave_sql})"
                union_params = join_params + leave_params

            # Wrap in subquery for ordering and pagination, join names
            full_sql = f"""
                SELECT
                    u.session_id,
                    u.pr_id,
                    a.nickname as pr_nickname,
                    a.role as pr_role,
                    u.target_type,
                    u.target_id,
                    CASE
                        WHEN u.target_type = 'streamer' THEN s.streamer_name
                        WHEN u.target_type = 'event' THEN e.name
                        ELSE CAST(u.target_id AS CHAR)
                    END as target_name,
                    s.profile_image_url as target_avatar,
                    s.is_online as target_is_online,
                    u.action_time,
                    u.action_type,
                    u.duration_seconds,
                    u.priority,
                    u.is_probation,
                    u.end_reason
                FROM ({union_sql}) u
                LEFT JOIN assistants a ON u.pr_id = a.pr_id
                LEFT JOIN streamers s ON u.target_type = 'streamer' AND u.target_id = s.streamer_id
                LEFT JOIN events e ON u.target_type = 'event' AND u.target_id = e.id
                ORDER BY u.action_time DESC
                LIMIT %s OFFSET %s
            """
            full_params = tuple(union_params) + (limit, offset)

            # Count query
            count_sql = f"""
                SELECT COUNT(*) as total FROM ({union_sql}) u
            """
            count_params = tuple(union_params)

            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Get total count
                    await cursor.execute(count_sql, count_params)
                    count_result = await cursor.fetchone()
                    total = count_result["total"] if count_result else 0

                    # Get items
                    await cursor.execute(full_sql, full_params)
                    rows = await cursor.fetchall()

                    items = []
                    for row in rows:
                        item = dict(row)
                        item["pr_id"] = str(item["pr_id"]) if item.get("pr_id") else None
                        item["target_id"] = str(item["target_id"]) if item.get("target_id") else None
                        items.append(item)

                    return {
                        "items": items,
                        "total": total,
                    }
        except Exception as e:
            self.logger.error(f"Failed to get PR action logs: {e}", exc_info=True)
            return {"items": [], "total": 0}
