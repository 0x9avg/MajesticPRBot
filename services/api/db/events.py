from __future__ import annotations

from .core import Any, Dict, List, Optional, aiomysql, datetime, timedelta, timezone


class EventsMixin:
    async def create_event(
        self,
        name: str,
        description: str,
        created_by: int,
        start_time=None,
        required_pr_count=1,
        notification_sent=False,
        pr_slots: int = 1,
        priority: int = 0,
        is_pinned: bool = False,
        points: Optional[float] = None,
        outbox_trace_id: Optional[str] = None,
        outbox_events: Optional[List[Dict[str, Any]]] = None,
    ) -> int:
        """Создание нового события."""
        try:
            if start_time is not None:
                # Validate that start_time is not in the past
                if isinstance(start_time, str):
                    start_time = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                if start_time.tzinfo is None:
                    start_time = start_time.replace(tzinfo=timezone(timedelta(hours=3)))
                if start_time < datetime.now(timezone(timedelta(hours=3))):
                    raise ValueError("Время начала события не может быть в прошлом")
            else:
                start_time = datetime.now(timezone(timedelta(hours=3)))

            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO events (
                            name, description,
                            required_pr_count, created_by, start_time, notification_sent,
                            pr_slots, priority, is_pinned, points
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            name,
                            description,
                            required_pr_count,
                            created_by,
                            start_time,
                            notification_sent,
                            pr_slots,
                            priority,
                            is_pinned,
                            points,
                        ),
                    )
                    event_id = int(cursor.lastrowid)
                    staged_outbox_events: List[Dict[str, Any]] = list(outbox_events or [])
                    if outbox_trace_id:
                        staged_outbox_events.append(
                            {
                                "routing_key": "event.added",
                                "payload": {
                                    "event": "event.added",
                                    "event_id": event_id,
                                    "event_name": name,
                                    "trace_id": outbox_trace_id,
                                },
                            }
                        )
                    await self._enqueue_outbox_messages_with_cursor(
                        cursor,
                        staged_outbox_events,
                    )
                    await conn.commit()
                    return event_id
        except Exception as e:
            self.logger.error(f"Failed to create event: {e}", exc_info=True)
            return None

    async def get_all_events(self) -> list:
        """Получение всех событий (активных и неактивных)."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        """
                        SELECT id, name, description, created_at, start_time, is_active, created_by, notification_sent,
                               required_pr_count, priority, pr_slots, is_pinned, points,
                               event_kind, approval_status, requested_by, approved_by, approved_at, rejected_by, rejected_at
                        FROM events
                        ORDER BY is_active DESC, is_pinned DESC, created_at DESC
                        """
                    )
                    events = await cursor.fetchall()
                    for event in events:
                        await cursor.execute(
                            """
                            SELECT act.pr_id, a.nickname
                            FROM active_assignments_v act
                            LEFT JOIN assistants a ON a.pr_id = act.pr_id
                            WHERE act.target_type = 'event' AND act.target_id = %s
                            """,
                            (event["id"],),
                        )
                        participants = await cursor.fetchall()
                        event["current_participants"] = len(participants)
                        event["participants"] = [
                            {"pr_id": str(p["pr_id"]), "nickname": p.get("nickname")}
                            for p in participants
                        ]

                    return events
        except Exception as e:
            self.logger.error(f"Failed to get all events: {e}", exc_info=True)
            return []

    async def get_active_events(self) -> list:
        """Получение активных событий гильдии."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        """
                        SELECT id, name, description, created_at, start_time, is_active, created_by, notification_sent,
                               required_pr_count, priority, pr_slots, is_pinned, points,
                               event_kind, approval_status, requested_by, approved_by, approved_at, rejected_by, rejected_at
                        FROM events
                        WHERE is_active = TRUE
                        ORDER BY is_pinned DESC, priority DESC, start_time ASC
                        """
                    )
                    events = await cursor.fetchall()
                    for event in events:
                        # Active participants (spec started)
                        await cursor.execute(
                            """
                            SELECT act.pr_id, a.nickname, 'active' as status
                            FROM active_assignments_v act
                            LEFT JOIN assistants a ON a.pr_id = act.pr_id
                            WHERE act.target_type = 'event' AND act.target_id = %s
                            """,
                            (event["id"],),
                        )
                        active_participants = await cursor.fetchall() or []

                        # Reserved participants (waiting for event start)
                        await cursor.execute(
                            """
                            SELECT ep.pr_id, a.nickname, 'reserved' as status
                            FROM event_participants ep
                            LEFT JOIN assistants a ON a.pr_id = ep.pr_id
                            WHERE ep.event_id = %s
                            """,
                            (event["id"],),
                        )
                        reserved_participants = await cursor.fetchall() or []

                        all_participants = list(active_participants) + list(reserved_participants)
                        event["current_participants"] = len(all_participants)
                        event["participants"] = [
                            {"pr_id": str(p["pr_id"]), "nickname": p.get("nickname"), "status": p.get("status", "active")}
                            for p in all_participants
                        ]

                    return events
        except Exception as e:
            self.logger.error(f"Failed to get active events: {e}", exc_info=True)
            return []

    async def get_event(self, event_id: int) -> dict:
        """Получение события по ID."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        """
                        SELECT
                            id, name, description, created_at, start_time, is_active, created_by,
                            notification_sent, required_pr_count, priority, pr_slots, is_pinned,
                            points, event_kind, approval_status, requested_by,
                            approved_by, approved_at, rejected_by, rejected_at
                        FROM events
                        WHERE id = %s
                        """,
                        (event_id,),
                    )
                    event = await cursor.fetchone()
                    if not event:
                        return None

                    await cursor.execute(
                        """
                        SELECT act.pr_id, a.nickname, 'active' AS status
                        FROM active_assignments_v act
                        LEFT JOIN assistants a ON a.pr_id = act.pr_id
                        WHERE act.target_type = 'event' AND act.target_id = %s
                        """,
                        (event_id,),
                    )
                    active_participants = await cursor.fetchall() or []

                    await cursor.execute(
                        """
                        SELECT ep.pr_id, a.nickname, 'reserved' AS status
                        FROM event_participants ep
                        LEFT JOIN assistants a ON a.pr_id = ep.pr_id
                        WHERE ep.event_id = %s
                        """,
                        (event_id,),
                    )
                    reserved_participants = await cursor.fetchall() or []

                    participants = list(active_participants) + list(reserved_participants)
                    event["current_participants"] = len(participants)
                    event["participants"] = [
                        {
                            "pr_id": str(p["pr_id"]),
                            "nickname": p.get("nickname"),
                            "status": p.get("status", "active"),
                        }
                        for p in participants
                    ]
                    return event
        except Exception as e:
            self.logger.error(f"Failed to get event {event_id}: {e}", exc_info=True)
            return None

    async def end_event(
        self,
        event_id: int,
        outbox_trace_id: Optional[str] = None,
        outbox_events: Optional[List[Dict[str, Any]]] = None,
    ) -> list:
        """Завершение события и возврат списка участников с длительностью участия."""
        try:
            now = datetime.now(timezone(timedelta(hours=3)))
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    self.logger.debug(f"Attempting to end event {event_id}.")

                    await cursor.execute(
                        """
                        SELECT id, pr_id, started_at
                        FROM spec_sessions
                        WHERE target_type = 'event' AND target_id = %s AND ended_at IS NULL AND deleted_at IS NULL
                        FOR UPDATE
                        """,
                        (event_id,),
                    )
                    participants = await cursor.fetchall()
                    self.logger.debug(f"Found {len(participants)} active participants for event {event_id}.")

                    await cursor.execute(
                        "SELECT start_time, name FROM events WHERE id = %s",
                        (event_id,),
                    )
                    event_data = await cursor.fetchone()
                    if not event_data:
                        self.logger.warning(f"Event {event_id} not found during end_event operation.")
                        return []

                    event_start_time = (
                        event_data["start_time"].replace(tzinfo=timezone(timedelta(hours=3)))
                        if event_data["start_time"]
                        else now
                    )
                    event_name = event_data.get("name") or "Unknown"

                    await cursor.execute(
                        """
                        UPDATE events 
                        SET is_active = FALSE 
                        WHERE id = %s
                        """,
                        (event_id,),
                    )
                    self.logger.debug(f"Event {event_id} marked as inactive.")

                    await cursor.execute(
                        """
                        UPDATE spec_sessions 
                        SET ended_at = GREATEST(
                                DATE_ADD(started_at, INTERVAL 1 SECOND),
                                CURRENT_TIMESTAMP
                            ),
                            end_reason = 'event_end'
                        WHERE target_type = 'event' AND target_id = %s AND ended_at IS NULL AND deleted_at IS NULL
                        """,
                        (event_id,),
                    )
                    self.logger.debug(f"Closed active spec sessions for event {event_id}.")

                    session_ids = [int(p["id"]) for p in participants]
                    if session_ids:
                        await self._recalc_points_for_sessions(
                            conn, session_ids, lock=False
                        )
                        self.logger.debug(f"Recalculated points for sessions: {session_ids}.")

                    results = []
                    for p in participants:
                        user_id = p["pr_id"]
                        started_at = p["started_at"]
                        if started_at.tzinfo is None:
                            started_at = started_at.replace(tzinfo=timezone(timedelta(hours=3)))

                        effective_start = max(started_at, event_start_time)

                        duration = int((now - effective_start).total_seconds())
                        if duration < 0:
                            duration = 0

                        results.append({"pr_id": user_id, "duration": duration})

                    staged_outbox_events: List[Dict[str, Any]] = list(outbox_events or [])
                    if outbox_trace_id:
                        for participant in results:
                            staged_outbox_events.append(
                                {
                                    "routing_key": "event.left",
                                    "payload": {
                                        "event": "event.left",
                                        "event_id": event_id,
                                        "event_name": event_name,
                                        "pr_id": participant.get("pr_id"),
                                        "duration_seconds": participant.get("duration", 0),
                                        "ended_at": None,
                                        "trace_id": outbox_trace_id,
                                    },
                                }
                            )
                        staged_outbox_events.append(
                            {
                                "routing_key": "event.ended",
                                "payload": {
                                    "event": "event.ended",
                                    "event_id": event_id,
                                    "event_name": event_name,
                                    "trace_id": outbox_trace_id,
                                },
                            }
                        )
                    await self._enqueue_outbox_messages_with_cursor(
                        cursor,
                        staged_outbox_events,
                    )
                await conn.commit()
                self.logger.debug(
                    f"Event {event_id} ended. Processed {len(results)} participant sessions. "
                    f"Participant results: {results}"
                )
                return results
        except Exception as e:
            self.logger.error(f"Failed to end event {event_id}: {e}", exc_info=True)
            return []

    async def join_event(
        self,
        event_id: int,
        user_id: int,
        outbox_trace_id: Optional[str] = None,
        outbox_events: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Добавление пользователя в событие с проверкой лимита слотов."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    self.logger.debug(f"User {user_id} attempting to join event {event_id}.")

                    # Check if already has active session
                    await cursor.execute(
                        """
                        SELECT id FROM spec_sessions 
                        WHERE pr_id = %s AND ended_at IS NULL AND deleted_at IS NULL
                        """,
                        (user_id,),
                    )
                    active = await cursor.fetchone()
                    if active:
                        self.logger.debug(f"User {user_id} already has active session {active['id']}.")
                        return {"status": "error", "detail": "Already in an active session"}

                    # Also check if already reserved for THIS event
                    await cursor.execute(
                        "SELECT pr_id FROM event_participants WHERE event_id = %s AND pr_id = %s",
                        (event_id, user_id)
                    )
                    if await cursor.fetchone():
                        self.logger.debug(f"User {user_id} already reserved for event {event_id}.")
                        return {"status": "error", "detail": "Already reserved for this event"}

                    # Capacity check: count current participants (active + reserved) vs pr_slots
                    await cursor.execute(
                        "SELECT name, pr_slots, priority, start_time, event_kind, requested_by FROM events WHERE id = %s AND is_active = TRUE",
                        (event_id,),
                    )
                    event = await cursor.fetchone()
                    if not event:
                        self.logger.debug(f"Event {event_id} not found or inactive for user {user_id}.")
                        return {"status": "error", "detail": "Event not found or inactive"}

                    # Block non-creators from joining spec_request events
                    if event.get("event_kind") == "spec_request" and event.get("requested_by") != user_id:
                        self.logger.debug(f"User {user_id} tried to join spec_request {event_id} but is not the creator.")
                        return {"status": "error", "detail": "Cannot join another user's spec request"}

                    event_name = event.get("name", f"Событие #{event_id}")
                    pr_slots = event.get("pr_slots", 1)
                    event_priority = event.get("priority", 0)
                    start_time = event.get("start_time")
                    
                    # Count active
                    await cursor.execute(
                        """
                        SELECT COUNT(*) as cnt FROM spec_sessions
                        WHERE target_type = 'event' AND target_id = %s 
                          AND ended_at IS NULL AND deleted_at IS NULL
                        """,
                        (event_id,),
                    )
                    count_active_row = await cursor.fetchone()
                    active_count = count_active_row["cnt"] if count_active_row else 0
                    
                    # Count reserved
                    await cursor.execute(
                        "SELECT COUNT(*) as cnt FROM event_participants WHERE event_id = %s",
                        (event_id,)
                    )
                    count_reserved_row = await cursor.fetchone()
                    reserved_count = count_reserved_row["cnt"] if count_reserved_row else 0

                    self.logger.debug(f"Event {event_id} slots: {active_count} active, {reserved_count} reserved, {pr_slots} total.")
                    if (active_count + reserved_count) >= pr_slots:
                        self.logger.debug(f"Event {event_id} has no available slots for user {user_id}.")
                        return {"status": "error", "detail": "No slots available"}

                    # Snapshot rate from config
                    config = await self._get_points_config()
                    rate_auto = config.get(event_priority, 0.5)

                    # Ensure assistant exists
                    await cursor.execute(
                        "INSERT INTO assistants (pr_id) VALUES (%s) ON DUPLICATE KEY UPDATE pr_id = pr_id",
                        (user_id,),
                    )

                    # Determine if we insert into spec_sessions or event_participants
                    now = datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None) # Start time in DB is naiive UTC
                    if not start_time or start_time <= now:
                        # Event has started - join directly
                        try:
                            await cursor.execute(
                                """
                                INSERT INTO spec_sessions 
                                    (pr_id, target_type, target_id, target_name, started_at, priority_auto, rate_auto)
                                VALUES (%s, 'event', %s, %s, CURRENT_TIMESTAMP, %s, %s)
                                """,
                                (user_id, event_id, event_name, event_priority, rate_auto),
                            )
                            staged_outbox_events: List[Dict[str, Any]] = list(outbox_events or [])
                            if outbox_trace_id:
                                staged_outbox_events.append(
                                    {
                                        "routing_key": "event.joined",
                                        "payload": {
                                            "event": "event.joined",
                                            "event_id": event_id,
                                            "event_name": event_name,
                                            "pr_id": user_id,
                                            "trace_id": outbox_trace_id,
                                        },
                                    }
                                )
                            await self._enqueue_outbox_messages_with_cursor(
                                cursor,
                                staged_outbox_events,
                            )
                            await conn.commit()
                            self.logger.debug(
                                f"User {user_id} joined active event {event_id} ('{event_name}'). "
                                f"State AFTER: joined spec_sessions with priority {event_priority}."
                            )
                            return {"status": "joined", "detail": "Joined active event"}
                        except Exception as e:
                            if "uq_one_active_session_per_pr" in str(e):
                                self.logger.warning(f"User {user_id} tried to join event {event_id} but already has an active session (DB constraint).")
                                return {"status": "error", "detail": "Already in an active session"}
                            raise
                    else:
                        # Event has not started - reserve slot
                        await cursor.execute(
                            "INSERT INTO event_participants (event_id, pr_id) VALUES (%s, %s)",
                            (event_id, user_id)
                        )
                        staged_outbox_events = list(outbox_events or [])
                        if outbox_trace_id:
                            staged_outbox_events.append(
                                {
                                    "routing_key": "event.updated",
                                    "payload": {
                                        "event": "event.updated",
                                        "event_id": event_id,
                                        "event_name": event_name,
                                        "trace_id": outbox_trace_id,
                                    },
                                }
                            )
                        await self._enqueue_outbox_messages_with_cursor(
                            cursor,
                            staged_outbox_events,
                        )
                        await conn.commit()
                        self.logger.debug(f"User {user_id} reserved slot for future event {event_id} ('{event_name}').")
                        return {"status": "reserved", "detail": "Reserved slot for future event"}

        except Exception as e:
            self.logger.error(f"Failed to join event: {e}", exc_info=True)
            return {"status": "error", "detail": "Internal database error"}

    async def leave_event(
        self,
        event_id: int,
        user_id: int,
        end_reason: str = "manual_unclaim",
        outbox_trace_id: Optional[str] = None,
        outbox_events: Optional[List[Dict[str, Any]]] = None,
    ) -> int:
        """Удаление пользователя из события и возврат длительности."""
        try:
            # Fail-safe: ensure end_reason is valid for ENUM
            allowed_reasons = set(SPEC_SESSION_END_REASONS)
            if end_reason not in allowed_reasons:
                self.logger.warning(f"Invalid end_reason '{end_reason}' passed to leave_event. Fallback to 'unknown'.")
                end_reason = SPEC_SESSION_END_REASON_UNKNOWN

            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    self.logger.debug(f"User {user_id} attempting to leave event {event_id}. Reason: {end_reason}.")

                    # 0. Check if user is in reserved state
                    await cursor.execute(
                        "SELECT name FROM events WHERE id = %s",
                        (event_id,),
                    )
                    event_row = await cursor.fetchone() or {}
                    event_name = event_row.get("name", "Unknown")

                    await cursor.execute(
                        "DELETE FROM event_participants WHERE event_id = %s AND pr_id = %s",
                        (event_id, user_id)
                    )
                    if cursor.rowcount > 0:
                        staged_outbox_events: List[Dict[str, Any]] = list(outbox_events or [])
                        if outbox_trace_id:
                            staged_outbox_events.append(
                                {
                                    "routing_key": "event.updated",
                                    "payload": {
                                        "event": "event.updated",
                                        "event_id": event_id,
                                        "event_name": event_name,
                                        "trace_id": outbox_trace_id,
                                    },
                                }
                            )
                        await self._enqueue_outbox_messages_with_cursor(
                            cursor,
                            staged_outbox_events,
                        )
                        await conn.commit()
                        self.logger.debug(f"User {user_id} was in reserved state for event {event_id} and removed.")
                        return 0

                    # 1. Lock active session row for this participant
                    await cursor.execute(
                        """
                        SELECT id
                        FROM spec_sessions 
                        WHERE target_type = 'event' AND target_id = %s AND pr_id = %s 
                          AND ended_at IS NULL AND deleted_at IS NULL
                        FOR UPDATE
                        """,
                        (event_id, user_id),
                    )
                    result = await cursor.fetchone()

                    if not result:
                        self.logger.debug(f"User {user_id} not found in active sessions for event {event_id}.")
                        return 0

                    session_id = result["id"]
                    self.logger.debug(f"Found active session {session_id} for user {user_id} in event {event_id}.")

                    # 2. Close session using DB time and guarantee ended_at > started_at
                    await cursor.execute(
                        """
                        UPDATE spec_sessions 
                        SET ended_at = GREATEST(
                                DATE_ADD(started_at, INTERVAL 1 SECOND),
                                CURRENT_TIMESTAMP
                            ),
                            end_reason = %s
                        WHERE id = %s
                        """,
                        (end_reason, session_id),
                    )
                    self.logger.debug(f"Session {session_id} for user {user_id} in event {event_id} marked as ended.")

                    await self._recalc_session_points_delta(conn, session_id, lock=False)
                    self.logger.debug(f"Points recalculated for session {session_id}.")

                    await cursor.execute(
                        """
                        SELECT COALESCE(duration_seconds, 0) AS duration_seconds
                        FROM spec_sessions
                        WHERE id = %s
                        """,
                        (session_id,),
                    )
                    duration_row = await cursor.fetchone()

                    # Auto-end spec_request events if 0 participants remain
                    await cursor.execute(
                        "SELECT event_kind FROM events WHERE id = %s",
                        (event_id,),
                    )
                    ev = await cursor.fetchone()
                    if ev and ev.get("event_kind") == "spec_request":
                        await cursor.execute(
                            """
                            SELECT COUNT(*) as cnt FROM spec_sessions
                            WHERE target_type = 'event' AND target_id = %s
                              AND ended_at IS NULL AND deleted_at IS NULL
                            """,
                            (event_id,),
                        )
                        cnt_row = await cursor.fetchone()
                        if cnt_row and cnt_row["cnt"] == 0:
                            await cursor.execute(
                                "UPDATE events SET is_active = FALSE WHERE id = %s",
                                (event_id,),
                            )
                            self.logger.debug(f"Spec request event {event_id} auto-marked as inactive due to 0 participants.")

                    staged_outbox_events = list(outbox_events or [])
                    if outbox_trace_id:
                        if duration_row and int(duration_row.get("duration_seconds") or 0) > 0:
                            staged_outbox_events.append(
                                {
                                    "routing_key": "event.left",
                                    "payload": {
                                        "event": "event.left",
                                        "event_id": event_id,
                                        "event_name": event_name,
                                        "pr_id": user_id,
                                        "duration_seconds": int(duration_row.get("duration_seconds") or 0),
                                        "ended_at": None,
                                        "trace_id": outbox_trace_id,
                                    },
                                }
                            )
                        else:
                            staged_outbox_events.append(
                                {
                                    "routing_key": "event.updated",
                                    "payload": {
                                        "event": "event.updated",
                                        "event_id": event_id,
                                        "event_name": event_name,
                                        "trace_id": outbox_trace_id,
                                    },
                                }
                            )
                    await self._enqueue_outbox_messages_with_cursor(
                        cursor,
                        staged_outbox_events,
                    )
                    await conn.commit()
                    duration = (
                        int(duration_row["duration_seconds"]) if duration_row else 0
                    )
                    self.logger.debug(
                        f"User {user_id} left event {event_id}. Reason: {end_reason}. "
                        f"Session ID {session_id} ended. Duration: {duration}s."
                    )
                    return max(duration, 0)
        except Exception as e:
            self.logger.error(f"Failed to leave event {event_id}: {e}", exc_info=True)
            return 0

    async def create_spec_request(
        self,
        name: str,
        description: str,
        requested_by: int,
        priority: int = 0,
        outbox_trace_id: Optional[str] = None,
        outbox_events: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[int]:
        """Create a spec_request event and auto-join the creator."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    # Check if user already has an active session
                    await cursor.execute(
                        """
                        SELECT id FROM spec_sessions
                        WHERE pr_id = %s AND ended_at IS NULL AND deleted_at IS NULL
                        """,
                        (requested_by,),
                    )
                    if await cursor.fetchone():
                        raise ValueError("У вас уже есть активная сессия")

                    # Snapshot rate from config
                    config = await self._get_points_config()
                    rate_auto = config.get(priority, 0.5)

                    # Ensure assistant exists
                    await cursor.execute(
                        "INSERT INTO assistants (pr_id) VALUES (%s) ON DUPLICATE KEY UPDATE pr_id = pr_id",
                        (requested_by,),
                    )

                    # Create event
                    await cursor.execute(
                        """
                        INSERT INTO events (
                            name, description, created_by, requested_by,
                            start_time, notification_sent,
                            pr_slots, priority, required_pr_count,
                            event_kind, approval_status, is_active
                        ) VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, TRUE, 1, %s, 1, 'spec_request', 'pending', TRUE)
                        """,
                        (name, description, requested_by, requested_by, priority),
                    )
                    event_id = cursor.lastrowid

                    # Auto-join: create spec_session immediately
                    await cursor.execute(
                        """
                        INSERT INTO spec_sessions
                            (pr_id, target_type, target_id, target_name, started_at, priority_auto, rate_auto)
                        VALUES (%s, 'event', %s, %s, CURRENT_TIMESTAMP, %s, %s)
                        """,
                        (requested_by, event_id, name, priority, rate_auto),
                    )

                    staged_outbox_events: List[Dict[str, Any]] = list(outbox_events or [])
                    if outbox_trace_id:
                        staged_outbox_events.append(
                            {
                                "routing_key": "event.joined",
                                "payload": {
                                    "event": "event.joined",
                                    "event_id": event_id,
                                    "event_name": name,
                                    "pr_id": requested_by,
                                    "trace_id": outbox_trace_id,
                                },
                            }
                        )
                    await self._enqueue_outbox_messages_with_cursor(
                        cursor,
                        staged_outbox_events,
                    )
                    await conn.commit()
                    return event_id
        except ValueError:
            raise
        except Exception as e:
            self.logger.error(f"Failed to create spec request: {e}", exc_info=True)
            return None

    async def update_pending_spec_request(
        self,
        event_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        priority: Optional[int] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> bool:
        """Update a pending spec_request event without approving it."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        """
                        SELECT id, name, approval_status, event_kind FROM events
                        WHERE id = %s FOR UPDATE
                        """,
                        (event_id,),
                    )
                    event = await cursor.fetchone()
                    if not event:
                        raise ValueError("Event not found")
                    if event["event_kind"] != "spec_request":
                        raise ValueError("Event is not a spec_request")
                    if event["approval_status"] != "pending":
                        raise ValueError("Event is not pending")

                    # Build dynamic update for events table
                    set_parts = []
                    params: list = []

                    if name is not None:
                        set_parts.append("name = %s")
                        params.append(name)
                    if description is not None:
                        set_parts.append("description = %s")
                        params.append(description)
                    if priority is not None:
                        set_parts.append("priority = %s")
                        params.append(priority)

                    if set_parts:
                        params.append(event_id)
                        await cursor.execute(
                            f"UPDATE events SET {', '.join(set_parts)} WHERE id = %s",
                            tuple(params),
                        )

                    # If priority was changed, update the session rate/priority snapshot
                    if priority is not None:
                        config = await self._get_points_config()
                        new_rate = config.get(priority, 0.5)
                        await cursor.execute(
                            """
                            UPDATE spec_sessions
                            SET priority_auto = %s, rate_auto = %s
                            WHERE target_type = 'event' AND target_id = %s
                              AND deleted_at IS NULL
                            """,
                            (priority, new_rate, event_id),
                        )

                    # Update session times if provided by admin
                    if start_time is not None or end_time is not None:
                        time_set_parts = []
                        time_params: list = []
                        if start_time is not None:
                            time_set_parts.append("started_at = %s")
                            time_params.append(start_time)
                        if end_time is not None:
                            time_set_parts.append("ended_at = %s")
                            time_params.append(end_time)
                            time_set_parts.append("end_reason = 'admin_closed'")
                        time_params.append(event_id)
                        await cursor.execute(
                            f"""
                            UPDATE spec_sessions
                            SET {', '.join(time_set_parts)}
                            WHERE target_type = 'event' AND target_id = %s
                              AND deleted_at IS NULL
                            """,
                            tuple(time_params),
                        )

                    # Recalculate points for sessions of this event
                    await cursor.execute(
                        """
                        SELECT id FROM spec_sessions
                        WHERE target_type = 'event' AND target_id = %s
                          AND ended_at IS NOT NULL AND deleted_at IS NULL
                        """,
                        (event_id,),
                    )
                    closed_sessions = await cursor.fetchall()
                    if closed_sessions:
                        session_ids = [int(s["id"]) for s in closed_sessions]
                        await self._recalc_points_for_sessions(conn, session_ids, lock=False)

                    await conn.commit()
                    return True
        except ValueError:
            raise
        except Exception as e:
            self.logger.error(f"Failed to update pending spec request {event_id}: {e}", exc_info=True)
            return False

    async def approve_spec_request(
        self,
        event_id: int,
        approved_by: int,
        outbox_trace_id: Optional[str] = None,
        outbox_events: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """Approve a pending spec_request event."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    self.logger.debug(f"Attempting to approve spec request {event_id} by {approved_by}.")

                    await cursor.execute(
                        """
                        SELECT id, name, approval_status, event_kind FROM events
                        WHERE id = %s FOR UPDATE
                        """,
                        (event_id,),
                    )
                    event = await cursor.fetchone()
                    if not event:
                        self.logger.warning(f"Spec request {event_id} not found for approval.")
                        raise ValueError("Event not found")
                    if event["event_kind"] != "spec_request":
                        self.logger.warning(f"Event {event_id} is not a spec_request, cannot approve.")
                        raise ValueError("Event is not a spec_request")
                    if event["approval_status"] != "pending":
                        self.logger.warning(f"Event {event_id} is not pending, current status: {event['approval_status']}.")
                        raise ValueError("Event is not pending")
                    event_name = event.get("name", "Unknown")

                    # Check for sessions that were closed (ended_at is NOT NULL) but still belong to this pending event
                    await cursor.execute(
                        """
                        SELECT id, pr_id, duration_seconds, ended_at
                        FROM spec_sessions
                        WHERE target_type = 'event' AND target_id = %s
                          AND ended_at IS NOT NULL AND deleted_at IS NULL
                        """,
                        (event_id,),
                    )
                    closed_sessions = await cursor.fetchall()
                    self.logger.debug(f"Found {len(closed_sessions)} closed sessions for spec request {event_id}.")

                    # If we found closed sessions, it means the spec request is already finished.
                    # We should mark the event as inactive (is_active = FALSE).
                    is_active_clause = ""
                    if closed_sessions:
                        is_active_clause = ", is_active = FALSE"

                    await cursor.execute(
                        f"""
                        UPDATE events 
                        SET approval_status = 'approved', approved_by = %s, approved_at = CURRENT_TIMESTAMP{is_active_clause}
                        WHERE id = %s
                        """,
                        (approved_by, event_id),
                    )
                    self.logger.debug(f"Spec request {event_id} status updated to 'approved'. is_active set to {not bool(closed_sessions)}.")

                    # Recalculate points for closed sessions now that status is 'approved'
                    if closed_sessions:
                        session_ids = [int(s["id"]) for s in closed_sessions]
                        await self._recalc_points_for_sessions(conn, session_ids, lock=False)
                        self.logger.debug(f"Recalculated points for closed sessions: {session_ids}.")

                    staged_outbox_events: List[Dict[str, Any]] = list(outbox_events or [])
                    if outbox_trace_id and closed_sessions:
                        for session in closed_sessions:
                            staged_outbox_events.append(
                                {
                                    "routing_key": "event.left",
                                    "payload": {
                                        "event": "event.left",
                                        "event_id": event_id,
                                        "event_name": event_name,
                                        "pr_id": session["pr_id"],
                                        "duration_seconds": session.get("duration_seconds", 0),
                                        "ended_at": (
                                            session["ended_at"].isoformat()
                                            if session.get("ended_at")
                                            else None
                                        ),
                                        "trace_id": outbox_trace_id,
                                    },
                                }
                            )
                        staged_outbox_events.append(
                            {
                                "routing_key": "event.ended",
                                "payload": {
                                    "event": "event.ended",
                                    "event_id": event_id,
                                    "event_name": event_name,
                                    "trace_id": outbox_trace_id,
                                },
                            }
                        )
                    await self._enqueue_outbox_messages_with_cursor(
                        cursor,
                        staged_outbox_events,
                    )
                    await conn.commit()
                self.logger.debug(
                    f"Spec Request {event_id} approved by {approved_by}. "
                    f"Closed {len(closed_sessions)} associated sessions. Event is_active={not bool(closed_sessions)}."
                )
                return {
                    "success": True,
                    "closed_sessions": [
                        {
                                "pr_id": s["pr_id"],
                                "duration": s.get("duration_seconds", 0),
                                "ended_at": s["ended_at"].isoformat() if s["ended_at"] else None
                            }
                            for s in closed_sessions
                        ]
                    }
        except ValueError:
            raise
        except Exception as e:
            self.logger.error(f"Failed to approve spec request {event_id}: {e}", exc_info=True)
            return False

    async def reject_spec_request(
        self,
        event_id: int,
        rejected_by: int,
    ) -> bool:
        """Reject a pending spec_request event and close active sessions."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        """
                        SELECT id, approval_status, event_kind FROM events
                        WHERE id = %s FOR UPDATE
                        """,
                        (event_id,),
                    )
                    event = await cursor.fetchone()
                    if not event:
                        raise ValueError("Event not found")
                    if event["event_kind"] != "spec_request":
                        raise ValueError("Event is not a spec_request")
                    if event["approval_status"] != "pending":
                        raise ValueError("Event is not pending")

                    # Mark event as rejected and inactive
                    await cursor.execute(
                        """
                        UPDATE events
                        SET approval_status = 'rejected',
                            rejected_by = %s,
                            rejected_at = CURRENT_TIMESTAMP,
                            is_active = FALSE
                        WHERE id = %s
                        """,
                        (rejected_by, event_id),
                    )

                    # Close active sessions with reason 'event_rejected'
                    await cursor.execute(
                        """
                        UPDATE spec_sessions
                        SET ended_at = GREATEST(
                                DATE_ADD(started_at, INTERVAL 1 SECOND),
                                CURRENT_TIMESTAMP
                            ),
                            end_reason = 'event_rejected'
                        WHERE target_type = 'event' AND target_id = %s
                          AND ended_at IS NULL AND deleted_at IS NULL
                        """,
                        (event_id,),
                    )

                    # No points recalculation needed — rejected sessions
                    # will be excluded by view filter (approval_status != 'approved')

                    await conn.commit()
                    return True
        except ValueError:
            raise
        except Exception as e:
            self.logger.error(f"Failed to reject spec request {event_id}: {e}", exc_info=True)
            return False

    async def get_pending_spec_requests(self) -> list:
        """Get all pending spec_request events with session info for admin review."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        """
                        SELECT
                            e.id, e.name, e.description, e.created_at, e.start_time,
                            e.priority, e.requested_by, e.is_active,
                            a.nickname AS requester_nickname,
                            ss.started_at AS session_started_at,
                            ss.ended_at AS session_ended_at,
                            ss.duration_seconds AS session_duration_seconds
                        FROM events e
                        LEFT JOIN assistants a ON a.pr_id = e.requested_by
                        LEFT JOIN spec_sessions ss
                            ON ss.target_type = 'event' AND ss.target_id = e.id AND ss.deleted_at IS NULL
                        WHERE e.event_kind = 'spec_request'
                          AND e.approval_status = 'pending'
                        ORDER BY e.created_at DESC
                        """
                    )
                    return await cursor.fetchall() or []
        except Exception as e:
            self.logger.error(f"Failed to get pending spec requests: {e}", exc_info=True)
            return []

    async def mark_event_notification_sent(self, event_id: int) -> None:
        """Отметка о отправке уведомления о событии."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "UPDATE events SET notification_sent = TRUE WHERE id = %s",
                        (event_id,),
                    )
                    await conn.commit()
        except Exception as e:
            self.logger.error(
                f"Failed to mark event notification sent: {e}", exc_info=True
            )

    async def get_user_active_event_participation(self, user_id: int) -> Optional[dict]:
        """Проверка участия пользователя в активном событии."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        """
                        SELECT e.id, e.name 
                        FROM spec_sessions ss
                        JOIN events e ON ss.target_id = e.id
                        WHERE ss.pr_id = %s AND ss.target_type = 'event' 
                          AND ss.ended_at IS NULL AND ss.deleted_at IS NULL
                          AND e.is_active = TRUE
                        LIMIT 1
                        """,
                        (user_id,),
                    )
                    return await cursor.fetchone()
        except Exception as e:
            self.logger.error(f"Failed to check user active event: {e}", exc_info=True)
            return None

    async def get_event_participants(self, event_id: int) -> list:
        """Получение списка активных и зарезервированных участников события."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    # Get active
                    await cursor.execute(
                        """
                        SELECT pr_id, started_at as joined_at, 'active' as status
                        FROM active_assignments_v
                        WHERE target_type = 'event' AND target_id = %s
                        """,
                        (event_id,),
                    )
                    active = await cursor.fetchall() or []

                    # Get reserved
                    await cursor.execute(
                        """
                        SELECT pr_id, joined_at, 'reserved' as status
                        FROM event_participants
                        WHERE event_id = %s
                        """,
                        (event_id,)
                    )
                    reserved = await cursor.fetchall() or []

                    return list(active) + list(reserved)
        except Exception as e:
            self.logger.error(f"Failed to get participants: {e}", exc_info=True)
            return []

    async def start_event_sessions(
        self,
        event_id: int,
        outbox_trace_id: Optional[str] = None,
        outbox_events: Optional[List[Dict[str, Any]]] = None,
    ) -> list:
        """
        Migrates reserved participants from `event_participants` to `spec_sessions`.
        Called when an event officially starts.
        Returns a list of PR IDs that were migrated.
        """
        try:
            migrated_pr_ids = []
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    self.logger.debug(f"Attempting to start sessions for event {event_id}.")

                    # Lock rows
                    await cursor.execute(
                        "SELECT pr_id FROM event_participants WHERE event_id = %s FOR UPDATE",
                        (event_id,)
                    )
                    participants = await cursor.fetchall()
                    self.logger.debug(f"Found {len(participants)} reserved participants for event {event_id}.")

                    if not participants:
                        self.logger.debug(f"No reserved participants to migrate for event {event_id}.")
                        return []

                    # Get event details for config
                    await cursor.execute("SELECT name, priority FROM events WHERE id = %s", (event_id,))
                    event = await cursor.fetchone()
                    priority = event.get("priority", 0) if event else 0
                    event_name = event.get("name", f"Событие #{event_id}") if event else f"Событие #{event_id}"
                    config = await self._get_points_config()
                    rate_auto = config.get(priority, 0.5)

                    for p in participants:
                        pr_id = p["pr_id"]
                        
                        # Verify they don't already have an active session
                        await cursor.execute(
                            """
                            SELECT id FROM spec_sessions 
                            WHERE pr_id = %s AND ended_at IS NULL AND deleted_at IS NULL
                            """,
                            (pr_id,)
                        )
                        if not await cursor.fetchone():
                            # Insert into spec
                            await cursor.execute(
                                """
                                INSERT INTO spec_sessions 
                                    (pr_id, target_type, target_id, target_name, started_at, priority_auto, rate_auto)
                                VALUES (%s, 'event', %s, %s, CURRENT_TIMESTAMP, %s, %s)
                                """,
                                (pr_id, event_id, event_name, priority, rate_auto)
                            )
                            migrated_pr_ids.append(pr_id)
                            self.logger.debug(f"Migrated PR {pr_id} to active session for event {event_id}.")
                        else:
                            self.logger.debug(f"PR {pr_id} already has an active session, skipping migration for event {event_id}.")

                    # Delete reserved since they are now migrated or rejected
                    await cursor.execute(
                        "DELETE FROM event_participants WHERE event_id = %s",
                        (event_id,)
                    )
                    staged_outbox_events: List[Dict[str, Any]] = list(outbox_events or [])
                    if outbox_trace_id:
                        for migrated_pr_id in migrated_pr_ids:
                            staged_outbox_events.append(
                                {
                                    "routing_key": "event.joined",
                                    "payload": {
                                        "event": "event.joined",
                                        "event_id": event_id,
                                        "event_name": event_name,
                                        "pr_id": migrated_pr_id,
                                        "trace_id": outbox_trace_id,
                                    },
                                }
                            )
                    await self._enqueue_outbox_messages_with_cursor(
                        cursor,
                        staged_outbox_events,
                    )
                    await conn.commit()
            self.logger.debug(
                f"Event {event_id} started. Migrated {len(migrated_pr_ids)} reserved participants "
                f"to active spec_sessions. IDs: {migrated_pr_ids}"
            )
            return migrated_pr_ids
        except Exception as e:
            self.logger.error(f"Failed to start sessions for event {event_id}: {e}", exc_info=True)
            return []

    async def update_event(
        self,
        event_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        required_pr_count: Optional[int] = None,
        priority: Optional[int] = None,
        is_pinned: Optional[bool] = None,
        points: Optional[float] = None,
        outbox_trace_id: Optional[str] = None,
        outbox_events: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """Update event settings."""
        try:
            set_parts = []
            params = []

            if name is not None:
                set_parts.append("name = %s")
                params.append(name)

            if description is not None:
                set_parts.append("description = %s")
                params.append(description)

            if required_pr_count is not None:
                set_parts.append("required_pr_count = %s")
                params.append(required_pr_count)
                set_parts.append("pr_slots = %s")
                params.append(required_pr_count)

            if priority is not None:
                set_parts.append("priority = %s")
                params.append(priority)

            if is_pinned is not None:
                set_parts.append("is_pinned = %s")
                params.append(is_pinned)

            if points is not None:
                set_parts.append("points = %s")
                params.append(points)

            if not set_parts:
                return False

            params.append(event_id)

            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        f"UPDATE events SET {', '.join(set_parts)} WHERE id = %s",
                        tuple(params),
                    )
                    staged_outbox_events: List[Dict[str, Any]] = list(outbox_events or [])
                    if outbox_trace_id:
                        await cursor.execute(
                            "SELECT name FROM events WHERE id = %s",
                            (event_id,),
                        )
                        event_row = await cursor.fetchone() or {}
                        staged_outbox_events.append(
                            {
                                "routing_key": "event.updated",
                                "payload": {
                                    "event": "event.updated",
                                    "event_id": event_id,
                                    "event_name": event_row.get("name", "Unknown"),
                                    "trace_id": outbox_trace_id,
                                },
                            }
                        )
                    await self._enqueue_outbox_messages_with_cursor(
                        cursor,
                        staged_outbox_events,
                    )
                    await conn.commit()
                    return cursor.rowcount > 0
        except Exception as e:
            self.logger.error(f"Failed to update event {event_id}: {e}", exc_info=True)
            return False

    async def get_scheduled_events(self) -> List[Dict[str, Any]]:
        """Получение событий, которые должны начаться (для уведомлений)."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        """
                        SELECT id, name
                        FROM events 
                        WHERE is_active = TRUE 
                          AND start_time <= CURRENT_TIMESTAMP 
                          AND (notification_sent IS FALSE OR notification_sent IS NULL)
                        """
                    )
                    events = await cursor.fetchall()

            # Add participants to each event
            results = []
            for e in events:
                participants = await self.get_event_participants(e["id"])
                e["participants"] = participants
                results.append(e)

            return results
        except Exception as e:
            self.logger.error(f"Failed to get scheduled events: {e}", exc_info=True)
            return []
