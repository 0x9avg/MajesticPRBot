from __future__ import annotations

from .core import (
    Any,
    Dict,
    List,
    Optional,
    SPEC_SESSION_END_REASON_ADMIN_CLOSED,
    Set,
    aiomysql,
    date,
    datetime,
    timedelta,
    timezone,
)


class AssistantsMixin:
    async def create_manual_spec_session(
        self,
        pr_id: int,
        target_type: str,
        target_id: Optional[int],
        started_at: datetime,
        ended_at: datetime,
        is_probation: bool = False,
        priority: int = 0,
        target_name: Optional[str] = None,
    ) -> bool:
        """
        Создание ручной записи сессии спека (для админских корректировок).
        Сессия всегда создается завершенной по явным границам started_at/ended_at.
        """
        try:
            if target_type not in {"streamer", "event", "manual"}:
                self.logger.warning(
                    "Invalid target_type for manual spec session: %s", target_type
                )
                return False

            start_time = self._normalize_msk_datetime(started_at)
            end_time = self._normalize_msk_datetime(ended_at)
            if start_time is None or end_time is None or end_time <= start_time:
                self.logger.warning(
                    "Invalid manual session window for PR=%s: start=%s end=%s",
                    pr_id,
                    started_at,
                    ended_at,
                )
                return False

            if target_type == "manual":
                target_id_value: Optional[int] = None
            else:
                if target_id is None:
                    self.logger.warning(
                        "Non-manual session requires target_id (PR=%s, type=%s)",
                        pr_id,
                        target_type,
                    )
                    return False
                target_id_value = int(target_id)

            # Snapshot rate from config
            config = await self._get_points_config()
            safe_priority = max(0, min(int(priority), 3))
            if is_probation:
                rate_auto = await self._get_probation_rate()
            else:
                rate_auto = config.get(safe_priority, 0.5)

            affected_dates = sorted(
                day
                for day in self._iter_interval_dates(start_time, end_time)
                if day < self._current_msk_date()
            )

            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Ensure assistant exists
                    await cursor.execute(
                        "INSERT INTO assistants (pr_id) VALUES (%s) ON DUPLICATE KEY UPDATE pr_id = pr_id",
                        (pr_id,),
                    )

                    await cursor.execute(
                        """
                        INSERT INTO spec_sessions 
                        (pr_id, target_type, target_id, target_name, started_at, ended_at, end_reason, 
                         is_probation, priority_auto, rate_auto)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            pr_id,
                            target_type,
                            target_id_value,
                            target_name,
                            start_time,
                            end_time,
                            SPEC_SESSION_END_REASON_ADMIN_CLOSED,
                            is_probation,
                            safe_priority,
                            rate_auto,
                        ),
                    )
                    session_id = cursor.lastrowid
                    await self._recalc_session_points_delta(conn, session_id, lock=False)
                    await conn.commit()

            self.logger.info(
                "Manual spec session created: PR=%s, target_type=%s, target_id=%s, start=%s, end=%s, probation=%s",
                pr_id,
                target_type,
                target_id_value,
                start_time.isoformat(),
                end_time.isoformat(),
                is_probation,
            )
            if affected_dates:
                try:
                    await self._recalculate_assistant_sanction_derivations(
                        assistant_id=pr_id,
                        start_date=affected_dates[0],
                        end_date=affected_dates[-1],
                    )
                except Exception as recalc_exc:
                    self.logger.error(
                        "Failed to auto-recalculate assistant_sanctions after manual spec session create: pr_id=%s, dates=%s, error=%s",
                        pr_id,
                        affected_dates,
                        recalc_exc,
                        exc_info=True,
                    )
            return True

        except Exception as e:
            self.logger.error(
                f"Failed to create manual spec session: {e}", exc_info=True
            )
            return False

    async def update_assistant_session(
        self,
        pr_id: int,
        session_id: int,
        patch: Dict[str, Any],
        outbox_trace_id: Optional[str] = None,
        outbox_events: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Admin patch of one spec session with deterministic points delta recalculation."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        """
                        SELECT
                            id, pr_id, target_type, target_id, target_name, started_at, ended_at,
                            is_probation, priority_override, rate_override,
                            deleted_at, credited_points
                        FROM spec_sessions
                        WHERE id = %s AND pr_id = %s AND deleted_at IS NULL
                        FOR UPDATE
                        """,
                        (session_id, pr_id),
                    )
                    before = await cursor.fetchone()
                    if not before:
                        return None

                    updates: List[str] = []
                    params: List[Any] = []

                    current_target_type = before.get("target_type")
                    current_target_id = before.get("target_id")
                    current_started = self._normalize_msk_datetime(
                        before.get("started_at")
                    )
                    current_ended = self._normalize_msk_datetime(before.get("ended_at"))
                    affected_dates = set(
                        day
                        for day in self._iter_interval_dates(current_started, current_ended)
                        if day < self._current_msk_date()
                    )

                    next_target_type = (
                        patch.get("target_type")
                        if patch.get("target_type") is not None
                        else current_target_type
                    )
                    next_target_id = (
                        patch.get("target_id")
                        if "target_id" in patch
                        else current_target_id
                    )

                    next_started = current_started
                    next_ended = current_ended

                    started_in_patch = (
                        "started_at" in patch and patch.get("started_at") is not None
                    )
                    ended_in_patch = (
                        "ended_at" in patch and patch.get("ended_at") is not None
                    )
                    if started_in_patch != ended_in_patch:
                        raise ValueError(
                            "started_at and ended_at must be provided together"
                        )

                    if started_in_patch and ended_in_patch:
                        next_started = self._normalize_msk_datetime(patch["started_at"])
                        next_ended = self._normalize_msk_datetime(patch["ended_at"])
                        if not next_started or not next_ended or next_ended <= next_started:
                            raise ValueError("ended_at must be greater than started_at")
                        updates.append("started_at = %s")
                        params.append(next_started)
                        updates.append("ended_at = %s")
                        params.append(next_ended)
                        # If session was open and admin is closing it, set end_reason
                        if current_ended is None:
                            updates.append("end_reason = %s")
                            params.append(SPEC_SESSION_END_REASON_ADMIN_CLOSED)

                    if next_target_type == "manual":
                        next_target_id = None
                    elif next_target_type in ("streamer", "event"):
                        if next_target_id is None:
                            raise ValueError(
                                "target_id is required for streamer/event sessions"
                            )
                    else:
                        raise ValueError("Unsupported target_type")

                    if next_target_type != current_target_type:
                        updates.append("target_type = %s")
                        params.append(next_target_type)

                    if next_target_id != current_target_id:
                        updates.append("target_id = %s")
                        params.append(next_target_id)

                    if "target_name" in patch:
                        updates.append("target_name = %s")
                        params.append(patch.get("target_name"))

                    if "is_probation" in patch:
                        updates.append("is_probation = %s")
                        params.append(patch.get("is_probation"))

                    if "priority_override" in patch:
                        updates.append("priority_override = %s")
                        params.append(patch.get("priority_override"))

                    # If is_probation OR priority_override changed, we might need a new rate_override
                    probation_changed = "is_probation" in patch
                    priority_changed = "priority_override" in patch

                    if probation_changed or priority_changed:
                        # Get latest values (considering patch or existing)
                        next_is_probation = patch.get("is_probation") if probation_changed else before.get("is_probation", False)
                        next_priority = patch.get("priority_override") if priority_changed else before.get("priority_override")

                        if next_priority is not None:
                            config = await self._get_points_config()
                            if next_is_probation:
                                auto_rate = await self._get_probation_rate()
                            else:
                                auto_rate = config.get(next_priority, 0.5)
                            updates.append("rate_override = %s")
                            params.append(auto_rate)
                        elif priority_changed:
                            # Specifically clearing priority_override
                            updates.append("rate_override = NULL")
                        # Else: priority stayed None, rate stays as is (likely NULL or auto)

                    # Healing logic: if target_name is NULL but we have target_id, try to fetch it
                    if (
                        "target_name" not in patch
                        and before.get("target_name") is None
                        and next_target_type in ("streamer", "event")
                        and next_target_id is not None
                    ):
                        heal_name = None
                        if next_target_type == "streamer":
                            await cursor.execute("SELECT streamer_name FROM streamers WHERE streamer_id = %s", (next_target_id,))
                            row = await cursor.fetchone()
                            if row:
                                heal_name = row["streamer_name"]
                        else:  # event
                            await cursor.execute("SELECT name FROM events WHERE id = %s", (next_target_id,))
                            row = await cursor.fetchone()
                            if row:
                                heal_name = row["name"]

                        if heal_name:
                            updates.append("target_name = %s")
                            params.append(heal_name)


                    if updates:
                        params.append(session_id)
                        await cursor.execute(
                            f"UPDATE spec_sessions SET {', '.join(updates)} WHERE id = %s",
                            tuple(params),
                        )

                        # Auto-close spec_request events if 0 participants remain after update
                        if next_target_type == "event" and next_target_id is not None:
                            await cursor.execute(
                                "SELECT event_kind FROM events WHERE id = %s",
                                (next_target_id,),
                            )
                            ev = await cursor.fetchone()
                            if ev and ev.get("event_kind") == "spec_request":
                                await cursor.execute(
                                    """
                                    SELECT COUNT(*) as cnt FROM spec_sessions
                                    WHERE target_type = 'event' AND target_id = %s
                                      AND ended_at IS NULL AND deleted_at IS NULL
                                    """,
                                    (next_target_id,),
                                )
                                cnt_row = await cursor.fetchone()
                                if cnt_row and cnt_row["cnt"] == 0:
                                    await cursor.execute(
                                        "UPDATE events SET is_active = FALSE WHERE id = %s",
                                        (next_target_id,),
                                    )
                                    self.logger.debug(f"Spec request event {next_target_id} auto-marked as inactive via admin update.")

                    await self._recalc_session_points_delta(conn, session_id, lock=False)
                    affected_dates.update(
                        day
                        for day in self._iter_interval_dates(next_started, next_ended)
                        if day < self._current_msk_date()
                    )

                    await cursor.execute(
                        """
                        SELECT
                            ss.id, ss.pr_id, ss.target_type, ss.target_id,
                            CASE
                                WHEN ss.target_name IS NOT NULL THEN ss.target_name
                                WHEN ss.target_type = 'streamer' THEN s.streamer_name
                                WHEN ss.target_type = 'event' THEN e.name
                                ELSE NULL
                            END AS target_name,
                            ss.started_at, ss.ended_at,
                            ss.is_probation, ss.priority_override, ss.rate_override,
                            ss.credited_points, ss.duration_seconds
                        FROM spec_sessions ss
                        LEFT JOIN streamers s ON ss.target_type = 'streamer' AND ss.target_id = s.streamer_id
                        LEFT JOIN events e ON ss.target_type = 'event' AND ss.target_id = e.id
                        WHERE ss.id = %s
                        """,
                        (session_id,),
                    )
                    after = await cursor.fetchone()
                    staged_outbox_events: List[Dict[str, Any]] = list(outbox_events or [])
                    if (
                        outbox_trace_id
                        and before.get("ended_at") is None
                        and after
                        and after.get("ended_at") is not None
                    ):
                        target_type = after.get("target_type")
                        target_id = after.get("target_id")
                        target_name = after.get("target_name") or "Unknown"
                        duration = int(after.get("duration_seconds") or 0)
                        if target_type == "streamer" and target_id is not None:
                            staged_outbox_events.append(
                                {
                                    "routing_key": "spec.unclaimed",
                                    "payload": {
                                        "event": "spec.unclaimed",
                                        "streamer_id": int(target_id),
                                        "streamer_name": target_name,
                                        "pr_id": pr_id,
                                        "duration_seconds": duration,
                                        "reason": "admin_closed",
                                        "trace_id": outbox_trace_id,
                                    },
                                }
                            )
                        elif target_type == "event" and target_id is not None:
                            ended_dt = after.get("ended_at")
                            staged_outbox_events.append(
                                {
                                    "routing_key": "event.left",
                                    "payload": {
                                        "event": "event.left",
                                        "event_id": int(target_id),
                                        "event_name": target_name,
                                        "pr_id": pr_id,
                                        "duration_seconds": duration,
                                        "ended_at": (
                                            ended_dt.isoformat()
                                            if hasattr(ended_dt, "isoformat")
                                            else str(ended_dt)
                                        ),
                                        "trace_id": outbox_trace_id,
                                    },
                                }
                            )
                    await self._enqueue_outbox_messages_with_cursor(
                        cursor,
                        staged_outbox_events,
                    )
                    await conn.commit()
                    if affected_dates:
                        try:
                            await self._recalculate_assistant_sanction_derivations(
                                assistant_id=pr_id,
                                start_date=min(affected_dates),
                                end_date=max(affected_dates),
                            )
                        except Exception as recalc_exc:
                            self.logger.error(
                                "Failed to auto-recalculate assistant_sanctions after session patch: pr_id=%s session_id=%s dates=%s error=%s",
                                pr_id,
                                session_id,
                                sorted(affected_dates),
                                recalc_exc,
                                exc_info=True,
                            )
                    return {"session_id": session_id, "before": before, "after": after}
        except ValueError:
            raise
        except Exception as e:
            self.logger.error(
                f"Failed to update assistant session {session_id}: {e}", exc_info=True
            )
            return None

    async def soft_delete_assistant_session(
        self,
        pr_id: int,
        session_id: int,
        deleted_by_id: Optional[int] = None,
        reason: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Soft-delete one session and apply delta recalculation."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        """
                        SELECT
                            id, pr_id, target_type, target_id, started_at, ended_at,
                            credited_points, deleted_at
                        FROM spec_sessions
                        WHERE id = %s AND pr_id = %s AND deleted_at IS NULL
                        FOR UPDATE
                        """,
                        (session_id, pr_id),
                    )
                    before = await cursor.fetchone()
                    if not before:
                        return None
                    affected_dates = sorted(
                        day
                        for day in self._iter_interval_dates(
                            before.get("started_at"),
                            before.get("ended_at"),
                        )
                        if day < self._current_msk_date()
                    )

                    await cursor.execute(
                        """
                        UPDATE spec_sessions
                        SET deleted_at = CURRENT_TIMESTAMP,
                            deleted_by_id = %s,
                            delete_reason = %s
                        WHERE id = %s
                        """,
                        (deleted_by_id, reason or "admin_delete", session_id),
                    )

                    # Auto-close spec_request events if 0 participants remain after deletion
                    target_type = before.get("target_type")
                    target_id = before.get("target_id")
                    if target_type == "event" and target_id is not None:
                        await cursor.execute(
                            "SELECT event_kind FROM events WHERE id = %s",
                            (target_id,),
                        )
                        ev = await cursor.fetchone()
                        if ev and ev.get("event_kind") == "spec_request":
                            await cursor.execute(
                                """
                                SELECT COUNT(*) as cnt FROM spec_sessions
                                WHERE target_type = 'event' AND target_id = %s
                                  AND ended_at IS NULL AND deleted_at IS NULL
                                """,
                                (target_id,),
                            )
                            cnt_row = await cursor.fetchone()
                            if cnt_row and cnt_row["cnt"] == 0:
                                await cursor.execute(
                                    "UPDATE events SET is_active = FALSE WHERE id = %s",
                                    (target_id,),
                                )
                                self.logger.debug(f"Spec request event {target_id} auto-marked as inactive via admin soft-delete.")

                    await self._recalc_session_points_delta(conn, session_id, lock=False)

                    await cursor.execute(
                        """
                        SELECT 
                            ss.id, ss.pr_id, ss.target_type, ss.target_id,
                            CASE
                                WHEN ss.target_name IS NOT NULL THEN ss.target_name
                                WHEN ss.target_type = 'streamer' THEN s.streamer_name
                                WHEN ss.target_type = 'event' THEN e.name
                                ELSE NULL
                            END AS target_name,
                            ss.started_at, ss.ended_at,
                            ss.deleted_at, ss.deleted_by_id, ss.delete_reason, ss.credited_points
                        FROM spec_sessions ss
                        LEFT JOIN streamers s ON ss.target_type = 'streamer' AND ss.target_id = s.streamer_id
                        LEFT JOIN events e ON ss.target_type = 'event' AND ss.target_id = e.id
                        WHERE ss.id = %s
                        """,
                        (session_id,),
                    )
                    after = await cursor.fetchone()
                    await conn.commit()
                    if affected_dates:
                        try:
                            await self._recalculate_assistant_sanction_derivations(
                                assistant_id=pr_id,
                                start_date=affected_dates[0],
                                end_date=affected_dates[-1],
                            )
                        except Exception as recalc_exc:
                            self.logger.error(
                                "Failed to auto-recalculate assistant_sanctions after session delete: pr_id=%s session_id=%s dates=%s error=%s",
                                pr_id,
                                session_id,
                                affected_dates,
                                recalc_exc,
                                exc_info=True,
                            )
                    return {"session_id": session_id, "before": before, "after": after}
        except Exception as e:
            self.logger.error(
                f"Failed to soft-delete session {session_id}: {e}", exc_info=True
            )
            return None

    async def get_all_assistants(
        self,
        *,
        include_inactive: bool = False,
    ) -> List[Dict[str, Any]]:
        """Получение всех ассистентов с активными сессиями и статистикой."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    where_sql = "" if include_inactive else "WHERE a.dismissed_at IS NULL"
                    await cursor.execute(
                        f"""
                        SELECT 
                            a.pr_id, a.nickname, a.role, 
                            GREATEST(
                                DATEDIFF(CURRENT_TIMESTAMP, COALESCE(a.appointed_at, a.added_at, CURRENT_TIMESTAMP)),
                                0
                            ) as experience_days,
                            CASE WHEN act.session_id IS NOT NULL THEN 'assigned' ELSE 'free' END as status,
                            act.target_type as assigned_to_type, act.target_id as assigned_to_id, 
                            COALESCE(stats.total_secs, 0) as total_spec_seconds, 
                            COALESCE(stats.sess_count, 0) as session_count, a.added_at, a.appointed_at, a.updated_at,
                            ROUND(COALESCE(points.auto_points_total, 0) + COALESCE(adj.manual_points_adjustment, 0), 4) as gross_points,
                            ROUND(COALESCE(sb.penalty_points, 0), 4) as active_point_penalty,
                            ROUND(COALESCE(sb.penalty_percent, 0), 4) as active_percent_penalty,
                            ROUND(
                                COALESCE(points.auto_points_total, 0) + COALESCE(adj.manual_points_adjustment, 0) - COALESCE(sb.penalty_points, 0),
                                4
                            ) as net_points,
                            COALESCE(sb.strict_warnings, 0) as active_strict_warnings,
                            COALESCE(sb.oral_warnings, 0) as active_oral_warnings,
                            ROUND(COALESCE(sb.check_marks, 0), 4) as active_checks,
                            COALESCE(s.streamer_name, e.name) as assigned_to_name,
                            ROUND(COALESCE(stats.total_secs, 0) / 3600, 1) as total_spec_hours,
                            ROUND(COALESCE(recent.total_secs_30d, 0) / 3600, 4) as total_spec_hours_30d,
                            ROUND((COALESCE(recent.total_secs_30d, 0) / 3600) / 30.0, 4) as avg_spec_hours_per_day_30d
                        FROM assistants a
                        LEFT JOIN active_assignments_v act ON act.pr_id = a.pr_id
                        LEFT JOIN (
                            SELECT pr_id, SUM(duration_seconds) as total_secs, COUNT(*) as sess_count
                            FROM spec_sessions WHERE deleted_at IS NULL AND ended_at IS NOT NULL
                            GROUP BY pr_id
                        ) stats ON stats.pr_id = a.pr_id
                        LEFT JOIN (
                            SELECT assistant_id, ROUND(SUM(spec_points_auto), 4) AS auto_points_total
                            FROM assistant_day_spec_totals
                            GROUP BY assistant_id
                        ) points ON points.assistant_id = a.pr_id
                        LEFT JOIN (
                            SELECT assistant_id, ROUND(SUM(delta_points), 4) AS manual_points_adjustment
                            FROM assistant_day_point_adjustments
                            GROUP BY assistant_id
                        ) adj ON adj.assistant_id = a.pr_id
                        LEFT JOIN (
                            SELECT
                                assistant_id,
                                ROUND(SUM(CASE WHEN kind = 'point' THEN active_amount ELSE 0 END), 4) AS penalty_points,
                                ROUND(SUM(CASE WHEN kind = 'percent' THEN active_amount ELSE 0 END), 4) AS penalty_percent,
                                ROUND(SUM(CASE WHEN kind = 'check' THEN active_amount ELSE 0 END), 4) AS check_marks,
                                ROUND(SUM(CASE WHEN kind = 'oral' THEN active_amount ELSE 0 END), 4) AS oral_warnings,
                                ROUND(SUM(CASE WHEN kind = 'strict' THEN active_amount ELSE 0 END), 4) AS strict_warnings
                            FROM sanction_balances
                            GROUP BY assistant_id
                        ) sb ON sb.assistant_id = a.pr_id
                        LEFT JOIN (
                            SELECT pr_id, SUM(seconds_in_day) as total_secs_30d
                            FROM spec_session_day_slices
                            WHERE work_date >= DATE_SUB(CURDATE(), INTERVAL 29 DAY)
                            GROUP BY pr_id
                        ) recent ON recent.pr_id = a.pr_id
                        LEFT JOIN streamers s ON act.target_type = 'streamer' AND act.target_id = s.streamer_id
                        LEFT JOIN events e ON act.target_type = 'event' AND act.target_id = e.id
                        {where_sql}
                        ORDER BY total_spec_seconds DESC
                        """
                    )
                    return await cursor.fetchall()
        except Exception as e:
            self.logger.error(f"Failed to get all assistants: {e}", exc_info=True)
            return []

    async def list_assistant_identities(
        self,
        *,
        include_inactive: bool = False,
    ) -> List[Dict[str, Any]]:
        """Get lightweight assistant identity list for filters and pickers."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    where_sql = "" if include_inactive else "WHERE dismissed_at IS NULL"
                    await cursor.execute(
                        f"""
                        SELECT pr_id, nickname
                        FROM assistants
                        {where_sql}
                        ORDER BY nickname ASC, pr_id ASC
                        """
                    )
                    return await cursor.fetchall()
        except Exception as e:
            self.logger.error(
                f"Failed to list assistant identities: {e}",
                exc_info=True,
            )
            return []

    async def get_assistant(
        self,
        user_id: int,
        *,
        include_inactive: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Получение данных ассистента по Discord ID."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    dismissed_filter = "" if include_inactive else "AND a.dismissed_at IS NULL"
                    await cursor.execute(
                        f"""
                        SELECT 
                            a.pr_id, a.nickname, a.role, 
                            GREATEST(
                                DATEDIFF(CURRENT_TIMESTAMP, COALESCE(a.appointed_at, a.added_at, CURRENT_TIMESTAMP)),
                                0
                            ) as experience_days,
                            CASE WHEN act.session_id IS NOT NULL THEN 'assigned' ELSE 'free' END as status,
                            act.target_type as assigned_to_type, act.target_id as assigned_to_id, 
                            COALESCE(stats.total_secs, 0) as total_spec_seconds, 
                            COALESCE(stats.sess_count, 0) as session_count, a.added_at, a.appointed_at, a.updated_at,
                            ROUND(COALESCE(points.auto_points_total, 0) + COALESCE(adj.manual_points_adjustment, 0), 4) as gross_points,
                            ROUND(COALESCE(sb.penalty_points, 0), 4) as active_point_penalty,
                            ROUND(COALESCE(sb.penalty_percent, 0), 4) as active_percent_penalty,
                            ROUND(
                                COALESCE(points.auto_points_total, 0) + COALESCE(adj.manual_points_adjustment, 0) - COALESCE(sb.penalty_points, 0),
                                4
                            ) as net_points,
                            COALESCE(sb.strict_warnings, 0) as active_strict_warnings,
                            COALESCE(sb.oral_warnings, 0) as active_oral_warnings,
                            ROUND(COALESCE(sb.check_marks, 0), 4) as active_checks,
                            COALESCE(s.streamer_name, e.name) as assigned_to_name,
                            ROUND(COALESCE(stats.total_secs, 0) / 3600, 1) as total_spec_hours,
                            ROUND(COALESCE(recent.total_secs_30d, 0) / 3600, 4) as total_spec_hours_30d,
                            ROUND((COALESCE(recent.total_secs_30d, 0) / 3600) / 30.0, 4) as avg_spec_hours_per_day_30d
                        FROM assistants a
                        LEFT JOIN active_assignments_v act ON act.pr_id = a.pr_id
                        LEFT JOIN (
                            SELECT pr_id, SUM(duration_seconds) as total_secs, COUNT(*) as sess_count
                            FROM spec_sessions WHERE deleted_at IS NULL AND ended_at IS NOT NULL
                            GROUP BY pr_id
                        ) stats ON stats.pr_id = a.pr_id
                        LEFT JOIN (
                            SELECT assistant_id, ROUND(SUM(spec_points_auto), 4) AS auto_points_total
                            FROM assistant_day_spec_totals
                            GROUP BY assistant_id
                        ) points ON points.assistant_id = a.pr_id
                        LEFT JOIN (
                            SELECT assistant_id, ROUND(SUM(delta_points), 4) AS manual_points_adjustment
                            FROM assistant_day_point_adjustments
                            GROUP BY assistant_id
                        ) adj ON adj.assistant_id = a.pr_id
                        LEFT JOIN (
                            SELECT
                                assistant_id,
                                ROUND(SUM(CASE WHEN kind = 'point' THEN active_amount ELSE 0 END), 4) AS penalty_points,
                                ROUND(SUM(CASE WHEN kind = 'percent' THEN active_amount ELSE 0 END), 4) AS penalty_percent,
                                ROUND(SUM(CASE WHEN kind = 'check' THEN active_amount ELSE 0 END), 4) AS check_marks,
                                ROUND(SUM(CASE WHEN kind = 'oral' THEN active_amount ELSE 0 END), 4) AS oral_warnings,
                                ROUND(SUM(CASE WHEN kind = 'strict' THEN active_amount ELSE 0 END), 4) AS strict_warnings
                            FROM sanction_balances
                            GROUP BY assistant_id
                        ) sb ON sb.assistant_id = a.pr_id
                        LEFT JOIN (
                            SELECT pr_id, SUM(seconds_in_day) as total_secs_30d
                            FROM spec_session_day_slices
                            WHERE work_date >= DATE_SUB(CURDATE(), INTERVAL 29 DAY)
                            GROUP BY pr_id
                        ) recent ON recent.pr_id = a.pr_id
                        LEFT JOIN streamers s ON act.target_type = 'streamer' AND act.target_id = s.streamer_id
                        LEFT JOIN events e ON act.target_type = 'event' AND act.target_id = e.id
                        WHERE a.pr_id = %s
                          {dismissed_filter}
                        """,
                        (user_id,),
                    )
                    return await cursor.fetchone()
        except Exception as e:
            self.logger.error(f"Failed to get assistant {user_id}: {e}", exc_info=True)
            return None

    async def get_assistant_logs(
        self, pr_id: int, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get assistant activity logs derived from spec_sessions."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    session_limit = max(int(limit), 1)
                    fetch_limit = max(session_limit * 2, session_limit)

                    await cursor.execute(
                        """
                        SELECT
                            ss.id,
                            ss.target_type,
                            ss.started_at,
                            ss.ended_at,
                            ss.duration_seconds,
                            ss.end_reason,
                            CASE
                                WHEN ss.target_type = 'streamer' THEN s.streamer_name
                                WHEN ss.target_type = 'event' THEN e.name
                                ELSE NULL
                            END AS target
                        FROM spec_sessions ss
                        LEFT JOIN streamers s
                            ON ss.target_type = 'streamer'
                            AND ss.target_id = s.streamer_id
                        LEFT JOIN events e
                            ON ss.target_type = 'event'
                            AND ss.target_id = e.id
                        WHERE ss.pr_id = %s
                          AND ss.deleted_at IS NULL
                          AND (ss.target_type != 'event' OR e.approval_status IS NULL OR e.approval_status != 'rejected')
                        ORDER BY COALESCE(ss.ended_at, ss.started_at) DESC
                        LIMIT %s
                        """,
                        (pr_id, fetch_limit),
                    )
                    rows = await cursor.fetchall()

                    logs: List[Dict[str, Any]] = []

                    def format_duration(seconds: Optional[int]) -> Optional[str]:
                        if seconds is None:
                            return None
                        total = max(int(seconds), 0)
                        hours, remainder = divmod(total, 3600)
                        minutes, secs = divmod(remainder, 60)
                        if hours > 0:
                            return f"{hours}h {minutes}m"
                        if minutes > 0:
                            return f"{minutes}m {secs}s"
                        return f"{secs}s"

                    def to_epoch(value: Any) -> float:
                        if value is None:
                            return 0.0
                        if hasattr(value, "timestamp"):
                            try:
                                return float(value.timestamp())
                            except Exception:
                                return 0.0
                        return 0.0

                    for row in rows:
                        session_id = row.get("id")
                        target_type = row.get("target_type")
                        started_at = row.get("started_at")
                        ended_at = row.get("ended_at")
                        end_reason = row.get("end_reason")
                        duration_seconds = row.get("duration_seconds")
                        duration = format_duration(duration_seconds)

                        if target_type == "manual":
                            logs.append(
                                {
                                    "id": f"{session_id}:manual",
                                    "action": "Manual correction",
                                    "target": row.get("target"),
                                    "created_at": ended_at or started_at,
                                    "duration_seconds": duration_seconds,
                                    "duration": duration,
                                }
                            )
                            continue

                        # Assignment event should always remain in history
                        logs.append(
                            {
                                "id": f"{session_id}:assigned",
                                "action": "Assigned",
                                "target": row.get("target"),
                                "created_at": started_at,
                                "duration_seconds": None,
                                "duration": None,
                            }
                        )

                        # Unassignment event appears once session is closed
                        if ended_at is not None:
                            if end_reason and duration:
                                unassign_action = (
                                    f"Unassigned ({end_reason}, {duration})"
                                )
                            elif end_reason:
                                unassign_action = f"Unassigned ({end_reason})"
                            elif duration:
                                unassign_action = f"Unassigned ({duration})"
                            else:
                                unassign_action = "Unassigned"

                            logs.append(
                                {
                                    "id": f"{session_id}:unassigned",
                                    "action": unassign_action,
                                    "target": row.get("target"),
                                    "created_at": ended_at,
                                    "duration_seconds": duration_seconds,
                                    "duration": duration,
                                }
                            )

                    logs.sort(
                        key=lambda item: to_epoch(item.get("created_at")), reverse=True
                    )
                    return logs[:session_limit]
        except Exception as e:
            self.logger.error(
                f"Failed to get assistant logs for {pr_id}: {e}", exc_info=True
            )
            return []

    async def update_assistant_assignment(
        self,
        pr_id: int,
        assigned_to_type: Optional[str],
        assigned_to_id: Optional[int],
        assigned_to_name: Optional[str] = None,
    ) -> bool:
        """Compatibility helper: map assistant assignment updates to spec sessions."""
        try:
            if assigned_to_type is None:
                async with self.pool.acquire() as conn:
                    async with conn.cursor(aiomysql.DictCursor) as cursor:
                        await cursor.execute(
                            """
                            SELECT id
                            FROM spec_sessions
                            WHERE pr_id = %s
                              AND ended_at IS NULL
                              AND deleted_at IS NULL
                            FOR UPDATE
                            """,
                            (pr_id,),
                        )
                        row = await cursor.fetchone()
                        if not row:
                            return True
                        session_id = int(row["id"])
                        await cursor.execute(
                            """
                            UPDATE spec_sessions
                            SET ended_at = GREATEST(
                                    DATE_ADD(started_at, INTERVAL 1 SECOND),
                                    CURRENT_TIMESTAMP
                                ),
                                end_reason = 'manual_unclaim'
                            WHERE id = %s
                            """,
                            (session_id,),
                        )
                        await self._recalc_session_points_delta(
                            conn, session_id, lock=False
                        )
                        await conn.commit()
                        return True

            if assigned_to_id is None:
                return False
            if assigned_to_type == "streamer":
                return await self.assign_pr_to_streamer(assigned_to_id, pr_id)
            if assigned_to_type == "event":
                return await self.join_event(assigned_to_id, pr_id)
            return False
        except Exception as e:
            self.logger.error(
                f"Failed to update assignment for assistant {pr_id}: {e}",
                exc_info=True,
            )
            return False

    async def get_assistant_sessions_detailed(
        self,
        pr_id: int,
        limit: int = 50,
        include_deleted: bool = False,
    ) -> List[Dict[str, Any]]:
        """Get assistant sessions with full admin-editable fields."""
        try:
            limit = max(1, min(int(limit or 50), 200))
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    deleted_clause = "" if include_deleted else "AND ss.deleted_at IS NULL"
                    await cursor.execute(
                        f"""
                        SELECT
                            ss.id,
                            ss.pr_id,
                            ss.target_type,
                            ss.target_id,
                            CASE
                                WHEN ss.target_name IS NOT NULL THEN ss.target_name
                                WHEN ss.target_type = 'streamer' THEN s.streamer_name
                                WHEN ss.target_type = 'event' THEN e.name
                                ELSE NULL
                            END AS target_name,
                            ss.started_at,
                            ss.ended_at,
                            ss.duration_seconds,
                            ss.end_reason,
                            ss.is_probation,
                            ss.priority_auto,
                            ss.priority_override,
                            ss.rate_auto,
                            ss.rate_override,
                            ss.credited_points,
                            ss.deleted_at,
                            ss.delete_reason
                        FROM spec_sessions ss
                        LEFT JOIN streamers s
                            ON ss.target_type = 'streamer' AND ss.target_id = s.streamer_id
                        LEFT JOIN events e
                            ON ss.target_type = 'event' AND ss.target_id = e.id
                        WHERE ss.pr_id = %s
                          AND (ss.target_type <> 'event' OR e.approval_status = 'approved')
                          {deleted_clause}
                        ORDER BY ss.started_at DESC
                        LIMIT %s
                        """,
                        (pr_id, limit),
                    )
                    rows = await cursor.fetchall()
                    for row in rows:
                        row["pr_id"] = str(row["pr_id"])
                        if row.get("target_id") is not None:
                            row["target_id"] = str(row["target_id"])
                    return rows
        except Exception as e:
            self.logger.error(
                f"Failed to get detailed assistant sessions for {pr_id}: {e}",
                exc_info=True,
            )
            return []
