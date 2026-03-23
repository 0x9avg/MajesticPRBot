from __future__ import annotations

from .core import (
    Any,
    Config,
    Dict,
    List,
    MSK,
    Optional,
    SPEC_SESSION_END_REASON_UNKNOWN,
    Set,
    aiomysql,
    date,
    datetime,
    timedelta,
    timezone,
)


class SpecRuntimeMixin:
    @staticmethod
    def _month_start_for(value: date) -> date:
        return value.replace(day=1)

    @staticmethod
    def _normalize_db_datetime(value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is not None:
            return value.replace(tzinfo=None)
        return value

    @classmethod
    def _approved_session_start(
        cls,
        started_at: Optional[datetime],
        approved_at: Optional[datetime],
    ) -> Optional[datetime]:
        normalized_started = cls._normalize_db_datetime(started_at)
        normalized_approved = cls._normalize_db_datetime(approved_at)
        if normalized_started is None:
            return None
        if normalized_approved is None:
            return normalized_started
        return max(normalized_started, normalized_approved)

    @staticmethod
    def _round_points(value: float) -> float:
        return round(float(value), 4)

    @staticmethod
    def _normalize_msk_datetime(value: Optional[datetime]) -> Optional[datetime]:
        """Normalize any datetime to naive MSK for MySQL."""
        if value is None:
            return None
        if value.tzinfo is None:
            return value
        return value.astimezone(MSK).replace(tzinfo=None)

    @staticmethod
    def _current_msk_date() -> date:
        return datetime.now(MSK).date()

    @classmethod
    def _iter_interval_dates(
        cls,
        started_at: Optional[datetime],
        ended_at: Optional[datetime],
    ) -> Set[date]:
        start = cls._normalize_msk_datetime(started_at)
        end = cls._normalize_msk_datetime(ended_at)
        if start is None:
            return set()
        effective_end = end or datetime.combine(cls._current_msk_date() + timedelta(days=1), datetime.min.time())
        if effective_end <= start:
            return set()

        dates: Set[date] = set()
        cursor = start
        while cursor < effective_end:
            dates.add(cursor.date())
            cursor = datetime.combine(cursor.date() + timedelta(days=1), datetime.min.time())
        return dates

    def _compute_session_points(self, session_row: Dict[str, Any]) -> float:
        """Compute deterministic points contribution for a single session row."""
        if not session_row:
            return 0.0
        ended_at = self._normalize_db_datetime(session_row.get("ended_at"))
        if ended_at is None:
            return 0.0
        if session_row.get("deleted_at") is not None:
            return 0.0

        duration_seconds = float(session_row.get("duration_seconds") or 0.0)

        # User-requested pending time must never count retroactively.
        if session_row.get("event_kind") == "spec_request":
            if session_row.get("approval_status") != "approved":
                return 0.0

            effective_start = self._approved_session_start(
                session_row.get("started_at"),
                session_row.get("approved_at"),
            )
            if effective_start is None or effective_start >= ended_at:
                return 0.0
            duration_seconds = max(
                int((ended_at - effective_start).total_seconds()),
                0,
            )

        applied_rate = float(session_row.get("applied_hourly_rate") or 0.0)
        return self._round_points((duration_seconds / 3600.0) * applied_rate)

    async def _recalc_session_points_delta(
        self, conn, session_id: int, lock: bool = True
    ) -> float:
        """
        Recalculate one session and apply ONLY delta to assistant auto points.
        Returns applied delta.
        """
        lock_sql = "FOR UPDATE" if lock else ""
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                f"""
                SELECT ss.id, ss.pr_id, ss.ended_at, ss.deleted_at, ss.duration_seconds,
                       ss.started_at, ss.applied_hourly_rate, ss.credited_points,
                       ss.target_type, ss.target_id,
                       e.event_kind, e.approval_status, e.approved_at
                FROM spec_sessions ss
                LEFT JOIN events e ON ss.target_type = 'event' AND ss.target_id = e.id
                WHERE ss.id = %s
                {lock_sql}
                """,
                (session_id,),
            )
            row = await cursor.fetchone()
            if not row:
                return 0.0

            new_points = self._compute_session_points(row)
            old_points = float(row.get("credited_points") or 0.0)
            delta = self._round_points(new_points - old_points)

            if abs(delta) < 0.00005:
                delta = 0.0

            if new_points != old_points:
                await cursor.execute(
                    "UPDATE spec_sessions SET credited_points = %s WHERE id = %s",
                    (new_points, session_id),
                )

            return delta

    async def _recalc_points_for_sessions(
        self, conn, session_ids: List[int], lock: bool = True
    ) -> None:
        for session_id in session_ids:
            await self._recalc_session_points_delta(conn, session_id, lock=lock)

    async def assign_pr_to_streamer(
        self,
        streamer_id: int,
        pr_id: int,
        is_probation: bool = False,
        outbox_events: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """
        Назначение PR-ассистента стримеру с поддержкой Probation (Slot Logic).

        Args:
            streamer_id: Twitch ID стримера
            pr_id: Discord ID ассистента
            is_probation: True если это спек стажера (второй слот)

        Returns:
            True если успешно

        Raises:
            ValueError: Если занят слот или PR уже закреплен
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Check if PR already has an active session
                    await cursor.execute(
                        """
                        SELECT id FROM spec_sessions 
                        WHERE pr_id = %s AND ended_at IS NULL AND deleted_at IS NULL
                        """,
                        (pr_id,),
                    )
                    active = await cursor.fetchone()
                    if active:
                        self.logger.warning(
                            f"PR {pr_id} already has active session {active['id']}"
                        )
                        raise ValueError(
                            "Вы уже закреплены за другим стримером или событием"
                        )

                    # Check slot availability
                    await cursor.execute(
                        """
                        SELECT ss.pr_id, ss.is_probation 
                        FROM spec_sessions ss
                        WHERE ss.target_type = 'streamer' 
                          AND ss.target_id = %s 
                          AND ss.ended_at IS NULL
                          AND ss.deleted_at IS NULL
                        """,
                        (streamer_id,),
                    )
                    existing_sessions = await cursor.fetchall()

                    if not is_probation:
                        # Main slot: enforce pr_slots limit
                        await cursor.execute(
                            "SELECT streamer_name, pr_slots, pr_slots_override, priority, priority_override FROM streamers WHERE streamer_id = %s",
                            (streamer_id,),
                        )
                        streamer_row = await cursor.fetchone()
                        streamer_name = streamer_row.get("streamer_name") if streamer_row else "Unknown"
                        pr_slots = (
                            streamer_row.get("pr_slots_override") or streamer_row.get("pr_slots", 1) if streamer_row else 1
                        )
                        streamer_priority = (
                            streamer_row.get("priority", 0) if streamer_row else 0
                        )
                        streamer_priority_override = (
                            streamer_row.get("priority_override") if streamer_row else None
                        )
                        main_count = sum(
                            1 for s in existing_sessions if not s.get("is_probation")
                        )
                        if main_count >= pr_slots:
                            raise ValueError(
                                f"Все основные слоты заняты ({main_count}/{pr_slots})"
                            )
                    else:
                        # Probation slot: only 1 allowed
                        for session in existing_sessions:
                            if session.get("is_probation"):
                                raise ValueError("Слот Probation уже занят")
                        # Still need streamer priority for snapshot
                        await cursor.execute(
                            "SELECT streamer_name, priority, priority_override FROM streamers WHERE streamer_id = %s",
                            (streamer_id,),
                        )
                        streamer_row = await cursor.fetchone()
                        streamer_name = streamer_row.get("streamer_name") if streamer_row else "Unknown"
                        streamer_priority = (
                            streamer_row.get("priority", 0) if streamer_row else 0
                        )
                        streamer_priority_override = (
                            streamer_row.get("priority_override") if streamer_row else None
                        )

                    # Snapshot the rate from config
                    config = await self._get_points_config()
                    if is_probation:
                        rate_auto = await self._get_probation_rate()
                    else:
                        rate_auto = config.get(streamer_priority, 0.5)

                    # Calculate override rate if streamer has priority_override
                    session_priority_override = None
                    session_rate_override = None
                    if streamer_priority_override is not None and not is_probation:
                        session_priority_override = streamer_priority_override
                        session_rate_override = config.get(streamer_priority_override, 0.5)

                    # Ensure assistant exists
                    await cursor.execute(
                        """
                        INSERT INTO assistants (pr_id) VALUES (%s)
                        ON DUPLICATE KEY UPDATE pr_id = pr_id
                        """,
                        (pr_id,),
                    )

                    # Insert session with snapshot
                    try:
                        await cursor.execute(
                            """
                            INSERT INTO spec_sessions 
                                (pr_id, target_type, target_id, target_name, is_probation, started_at,
                                 priority_auto, rate_auto, priority_override, rate_override)
                            VALUES (%s, 'streamer', %s, %s, %s, CURRENT_TIMESTAMP, %s, %s, %s, %s)
                            """,
                            (
                                pr_id,
                                streamer_id,
                                streamer_name,
                                is_probation,
                                streamer_priority,
                                rate_auto,
                                session_priority_override,
                                session_rate_override,
                            ),
                        )
                    except Exception as e:
                        if "uq_one_active_session_per_pr" in str(e):
                            raise ValueError(
                                "Вы уже закреплены за другим стримером или событием"
                            )
                        raise

                    await self._enqueue_outbox_messages_with_cursor(cursor, outbox_events)
                    await conn.commit()
                    slot_name = "Probation" if is_probation else "Main"
                    self.logger.debug(
                        f"✓ PR {pr_id} assigned to streamer {streamer_id} as {slot_name}"
                    )
                    return True
        except Exception as e:
            self.logger.error(
                f"Failed to assign PR {pr_id} to streamer {streamer_id}: {e}",
                exc_info=True,
            )
            raise

    async def unassign_pr_from_streamer(
        self,
        streamer_id: int,
        pr_id: Optional[int] = None,
        end_reason: str = "manual_unclaim",
        outbox_trace_id: Optional[str] = None,
        outbox_events: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Снятие PR-ассистента(ов) со стримера.

        Args:
            streamer_id: Twitch ID стримера
            pr_id: ID ассистента для точечного снятия. Если None - снимает всех.
            end_reason: Причина завершения

        Returns:
            Список словарей с данными сессий
        """
        try:
            # Fail-safe: ensure end_reason is valid for ENUM
            allowed_reasons = set(SPEC_SESSION_END_REASONS)
            if end_reason not in allowed_reasons:
                self.logger.warning(f"Invalid end_reason '{end_reason}' passed to unassign_pr_from_streamer. Fallback to 'unknown'.")
                end_reason = SPEC_SESSION_END_REASON_UNKNOWN

            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    # 1. Find active sessions for this streamer
                    query_base = """
                        SELECT ss.id, ss.pr_id, ss.started_at, ss.is_probation, st.streamer_name
                        FROM spec_sessions ss
                        JOIN streamers st ON st.streamer_id = ss.target_id
                        WHERE ss.target_type = 'streamer' 
                          AND ss.target_id = %s 
                          AND ss.ended_at IS NULL
                          AND ss.deleted_at IS NULL
                    """
                    params = [streamer_id]

                    if pr_id is not None:
                        query_base += " AND ss.pr_id = %s"
                        params.append(pr_id)

                    query = query_base + " FOR UPDATE"

                    await cursor.execute(query, tuple(params))
                    results = await cursor.fetchall()

                    if not results:
                        return []

                    unassigned_sessions = []
                    session_ids = []

                    for res in results:
                        unassigned_sessions.append(
                            {
                                "_session_id": int(res["id"]),
                                "pr_id": res["pr_id"],
                                "duration_seconds": 0,
                                "streamer_name": res["streamer_name"],
                                "is_probation": res.get("is_probation", False),
                            }
                        )
                        session_ids.append(res["id"])

                    # 2. Close Sessions (duration_seconds is auto-computed by generated column)
                    if session_ids:
                        format_strings = ",".join(["%s"] * len(session_ids))
                        await cursor.execute(
                            f"""
                            UPDATE spec_sessions 
                            SET ended_at = GREATEST(
                                    DATE_ADD(started_at, INTERVAL 1 SECOND),
                                    CURRENT_TIMESTAMP
                                ),
                                end_reason = %s
                            WHERE id IN ({format_strings})
                            """,
                            (end_reason, *session_ids),
                        )

                        await self._recalc_points_for_sessions(
                            conn, session_ids, lock=False
                        )

                        await cursor.execute(
                            f"""
                            SELECT id, COALESCE(duration_seconds, 0) AS duration_seconds
                            FROM spec_sessions
                            WHERE id IN ({format_strings})
                            """,
                            tuple(session_ids),
                        )
                        duration_rows = await cursor.fetchall()
                        duration_map = {
                            int(row["id"]): int(row.get("duration_seconds") or 0)
                            for row in duration_rows
                        }
                        for session in unassigned_sessions:
                            sid = session.get("_session_id")
                            session["duration_seconds"] = duration_map.get(int(sid), 0)
                            session.pop("_session_id", None)

                    staged_outbox_events: List[Dict[str, Any]] = list(outbox_events or [])
                    if outbox_trace_id:
                        for session in unassigned_sessions:
                            staged_outbox_events.append(
                                {
                                    "routing_key": "spec.unclaimed",
                                    "payload": {
                                        "event": "spec.unclaimed",
                                        "streamer_id": streamer_id,
                                        "streamer_name": session.get("streamer_name", "Unknown"),
                                        "pr_id": session.get("pr_id"),
                                        "duration_seconds": session.get("duration_seconds", 0),
                                        "reason": end_reason,
                                        "trace_id": outbox_trace_id,
                                    },
                                }
                            )
                    await self._enqueue_outbox_messages_with_cursor(
                        cursor,
                        staged_outbox_events,
                    )
                    await conn.commit()

            return unassigned_sessions

        except Exception as e:
            self.logger.error(
                f"Failed to unassign PR(s) from streamer {streamer_id}: {e}",
                exc_info=True,
            )
            raise

    async def get_pr_current_streamer(self, pr_id: int) -> Optional[Dict[str, Any]]:
        """
        Получение текущей сессии (стримера или события), назначенной PR-ассистенту.

        Args:
            pr_id: Discord ID ассистента

        Returns:
            Словарь с данными стримера/события или None
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT 
                            ss.target_type,
                            ss.target_id,
                            ss.started_at as assigned_at,
                            s.streamer_id, 
                            s.streamer_name, 
                            s.is_online, 
                            s.stream_title, 
                            s.stream_thumbnail_url, 
                            s.stream_game_id, 
                            s.stream_game_name, 
                            s.stream_started_at, 
                            s.priority, 
                            s.added_at, 
                            s.added_by_id, 
                            s.updated_at,
                            e.id as event_id,
                            e.name as event_name,
                            e.is_active as event_is_active
                        FROM spec_sessions ss
                        LEFT JOIN streamers s ON s.streamer_id = ss.target_id AND ss.target_type = 'streamer'
                        LEFT JOIN events e ON e.id = ss.target_id AND ss.target_type = 'event'
                        WHERE ss.pr_id = %s 
                          AND (ss.target_type = 'streamer' OR ss.target_type = 'event')
                          AND ss.ended_at IS NULL AND ss.deleted_at IS NULL
                        """,
                        (pr_id,),
                    )
                    result = await cursor.fetchone()
                    if result:
                        if result["target_type"] == "streamer" and result.get("streamer_id"):
                            result["streamer_id"] = str(result["streamer_id"])
                            if result.get("added_by_id"):
                                result["added_by_id"] = str(result["added_by_id"])
                            if result.get("stream_game_id"):
                                result["stream_game_id"] = str(result["stream_game_id"])
                        elif result["target_type"] == "event" and result.get("event_id"):
                            # Data stays as is, let Python handle integers
                            pass
                        return result

                    # If not currently active in a session, check if they reserved a slot for a future event
                    await cursor.execute(
                        """
                        SELECT
                            'event' as target_type,
                            e.id as target_id,
                            ep.joined_at as assigned_at,
                            e.id as event_id,
                            e.name as event_name,
                            e.is_active as event_is_active
                        FROM event_participants ep
                        JOIN events e ON e.id = ep.event_id
                        WHERE ep.pr_id = %s
                        """,
                        (pr_id,)
                    )
                    return await cursor.fetchone()
        except Exception as e:
            self.logger.error(
                f"Failed to get current session for PR {pr_id}: {e}",
                exc_info=True,
            )
            raise

    async def get_pr_spec_sessions(
        self, pr_id: int, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Получение истории сессий спека для PR ассистента (только стримеры)."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Fetch from spec_sessions, aliasing target_id -> streamer_id
                    # Also calculate duration
                    await cursor.execute(
                        """
                        SELECT id, pr_id, target_type, target_id, started_at, ended_at, end_reason, target_id as streamer_id,
                               TIMESTAMPDIFF(SECOND, started_at, COALESCE(ended_at, CURRENT_TIMESTAMP)) as duration_seconds
                        FROM spec_sessions
                        WHERE pr_id = %s AND target_type = 'streamer'
                        ORDER BY started_at DESC
                        LIMIT %s
                        """,
                        (pr_id, limit),
                    )
                    results = await cursor.fetchall()
                    for r in results:
                        r["pr_id"] = str(r["pr_id"])
                        if r.get("target_id"):
                            r["target_id"] = str(r["target_id"])
                        if r.get("streamer_id"):
                            r["streamer_id"] = str(r["streamer_id"])
                    return results
        except Exception as e:
            self.logger.error(f"Failed to get PR spec sessions: {e}", exc_info=True)
            return []

    async def _get_points_config(self) -> dict:
        """Получение конфигурации баллов для гильдии."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        "SELECT p0_rate, p1_rate, p2_rate, p3_rate FROM settings WHERE id = 1",
                    )
                    result = await cursor.fetchone()
                    if result and result["p0_rate"] is not None:
                        return {
                            0: result["p0_rate"],
                            1: result["p1_rate"],
                            2: result["p2_rate"],
                            3: result["p3_rate"],
                        }

                    # Return defaults if not found
                    return {k: v for k, v in Config.default_points.items()}
        except Exception as e:
            self.logger.error(f"Failed to get points config: {e}")
            return {k: v for k, v in Config.default_points.items()}

    async def _get_probation_rate(self) -> float:
        """Get probation rate from settings."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT probation_rate FROM settings WHERE id = 1"
                    )
                    result = await cursor.fetchone()
                    return result.get("probation_rate", 1.2) if result else 1.2
        except Exception:
            return 1.2
