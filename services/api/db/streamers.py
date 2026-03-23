from __future__ import annotations

from .core import Any, Dict, List, Optional, aiomysql, datetime, json, timezone


class StreamersMixin:
    async def create_streamer(
        self,
        streamer_id: int,
        streamer_name: str,
        is_online: bool = False,
        started_at: Optional[str] = None,
        priority: int = 0,
        pr_slots: int = 1,
        allow_juniors: bool = True,
        added_by_id: int = 0,
        game_id: Optional[int] = None,
        game_name: Optional[str] = None,
        stream_title: Optional[str] = None,
        stream_thumbnail_url: Optional[str] = None,
        profile_image_url: Optional[str] = None,
        outbox_events: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """

        Создание или обновление стримера в базе данных.

        Args:
            streamer_id: Twitch ID стримера
            streamer_name: Имя пользователя Twitch
            is_online: Статус онлайн
            started_at: Время начала стрима
            priority: Приоритет (0-3)
            pr_slots: Количество слотов для PR ассистентов (1-10)
            added_by_id: ID пользователя Discord, добавившего стримера
            game_id: ID игры на Twitch
            game_name: Название игры
            stream_title: Название стрима
            stream_thumbnail_url: URL превью стрима
            profile_image_url: URL аватара стримера
        """

        try:
            self.logger.debug(
                f"Creating/updating streamer: {streamer_name} (ID: {streamer_id}, profile_image: {profile_image_url[:50] if profile_image_url else 'None'}...)"
            )
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT streamer_id FROM streamers WHERE streamer_name = %s",
                        (streamer_name,),
                    )
                    existing_by_name = await cursor.fetchone()

                    if (
                        existing_by_name
                        and existing_by_name["streamer_id"] != streamer_id
                    ):
                        old_id = existing_by_name["streamer_id"]
                        new_name_old = f"old_{old_id}"
                        self.logger.warning(
                            f"Streamer Name Collision: '{streamer_name}' is taken by ID {old_id}. "
                            f"Renaming {old_id} to '{new_name_old}' to insert new ID {streamer_id}."
                        )
                        await cursor.execute(
                            "UPDATE streamers SET streamer_name = %s WHERE streamer_id = %s",
                            (new_name_old, old_id),
                        )

                    await cursor.execute(
                        """
                        INSERT INTO streamers (
                            streamer_id, streamer_name, is_online, stream_started_at, priority, pr_slots,
                            allow_juniors, added_at, added_by_id, stream_game_id, stream_game_name, stream_title, 
                            stream_thumbnail_url, profile_image_url
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, %s, %s, %s, %s, %s, %s) AS new_data
                        ON DUPLICATE KEY UPDATE 
                            streamer_name = new_data.streamer_name,
                            is_online = new_data.is_online,
                            stream_started_at = new_data.stream_started_at,
                            priority = new_data.priority,
                            pr_slots = new_data.pr_slots,
                            allow_juniors = new_data.allow_juniors,
                            added_by_id = new_data.added_by_id,
                            stream_game_id = new_data.stream_game_id,
                            stream_game_name = new_data.stream_game_name,
                            stream_title = new_data.stream_title,
                            stream_thumbnail_url = new_data.stream_thumbnail_url,
                            profile_image_url = new_data.profile_image_url
                        """,
                        (
                            streamer_id,
                            streamer_name,
                            is_online,
                            started_at,
                            priority,
                            pr_slots,
                            allow_juniors,
                            added_by_id,
                            game_id,
                            game_name,
                            stream_title,
                            stream_thumbnail_url,
                            profile_image_url,
                        ),
                    )
                    await self._enqueue_outbox_messages_with_cursor(cursor, outbox_events)
                    await conn.commit()
            self.logger.debug(f"✓ Streamer {streamer_name} saved")
        except Exception as e:
            self.logger.error(
                f"Failed to create streamer {streamer_name}: {e}", exc_info=True
            )
            raise

    async def get_streamer(self, streamer_id: int) -> Optional[Dict[str, Any]]:
        """
        Получение информации о стримере по ID с поддержкой множественных назначений.

        Returns dict with 'assignments' list containing Main and Probation slots.
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT 
                            streamer_id, streamer_name, is_online, is_pinned,
                            allow_juniors,
                            stream_title, stream_thumbnail_url,
                            profile_image_url,
                            stream_game_id as game_id, stream_game_name as game_name, stream_started_at as started_at,
                            priority, pr_slots,
                            priority_override AS current_stream_priority_override,
                            pr_slots_override AS current_stream_pr_slots_override,
                            added_at, added_by_id, updated_at
                        FROM streamers
                        WHERE streamer_id = %s
                        """,
                        (streamer_id,),
                    )
                    streamer = await cursor.fetchone()
                    self.logger.debug(
                        f"get_streamer({streamer_id}) raw result: {streamer is not None}"
                    )
                    if not streamer:
                        return None

                    await cursor.execute(
                        """
                        SELECT 
                            act.pr_id,
                            a.nickname,
                            act.is_probation,
                            act.started_at as assigned_at
                        FROM active_assignments_v act
                        LEFT JOIN assistants a ON a.pr_id = act.pr_id
                        WHERE act.target_type = 'streamer' AND act.target_id = %s
                        """,
                        (streamer_id,),
                    )
                    assignments = await cursor.fetchall()

                    result = dict(streamer)
                    result["assignments"] = (
                        [
                            {
                                "pr_id": str(a["pr_id"]),
                                "nickname": a["nickname"],
                                "is_probation": a.get("is_probation", False),
                                "assigned_at": a.get("assigned_at"),
                            }
                            for a in assignments
                        ]
                        if assignments
                        else []
                    )

                    return result
        except Exception as e:
            self.logger.error(
                f"Failed to get streamer {streamer_id}: {e}", exc_info=True
            )
            raise

    async def update_streamer_status(
        self,
        streamer_id: int,
        is_online: bool,
        started_at: Optional[str] = None,
        game_id: Optional[int] = None,
        game_name: Optional[str] = None,
        stream_title: Optional[str] = None,
        stream_thumbnail_url: Optional[str] = None,
        profile_image_url: Optional[str] = None,
        outbox_trace_id: Optional[str] = None,
        outbox_events: Optional[List[Dict[str, Any]]] = None,
    ) -> tuple[dict, dict]:
        """
        Атомарное обновление статуса стримера с блокировкой строки.

        Использует SELECT ... FOR UPDATE для предотвращения гонок.
        Возвращает (old_state, new_state) для определения изменений.

        Returns:
            Tuple of (old_state, new_state) dicts with keys:
            - is_online, game_id, game_name, stream_title, streamer_name
        """

        try:
            self.logger.debug(
                f"Atomic update streamer {streamer_id}: online={is_online} game_id={game_id}"
            )

            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Lock the row and get current state atomically
                    await cursor.execute(
                        """
                        SELECT 
                            streamer_name, is_online, 
                            stream_game_id as game_id, stream_game_name as game_name,
                            stream_title
                        FROM streamers 
                        WHERE streamer_id = %s 
                        FOR UPDATE
                        """,
                        (streamer_id,),
                    )
                    row = await cursor.fetchone()

                    if not row:
                        # Streamer not found
                        return (None, None)

                    old_state = {
                        "streamer_name": row["streamer_name"],
                        "is_online": row["is_online"],
                        "game_id": str(row["game_id"]) if row["game_id"] else None,
                        "game_name": row["game_name"],
                        "stream_title": row["stream_title"],
                    }

                    # Build dynamic SET clause
                    set_parts = ["is_online = %s"]
                    params = [is_online]

                    set_parts.append("stream_started_at = %s")
                    params.append(started_at)
                    set_parts.append("stream_game_id = %s")
                    params.append(game_id)
                    set_parts.append("stream_game_name = %s")
                    params.append(game_name)
                    set_parts.append("stream_title = %s")
                    params.append(stream_title)
                    set_parts.append("stream_thumbnail_url = %s")
                    params.append(stream_thumbnail_url)

                    if profile_image_url is not None:
                        set_parts.append("profile_image_url = %s")
                        params.append(profile_image_url)

                    if is_online is False:
                        set_parts.append("is_pinned = FALSE")
                        set_parts.append("priority_override = NULL")
                        set_parts.append("pr_slots_override = NULL")

                    params.append(streamer_id)

                    query = f"UPDATE streamers SET {', '.join(set_parts)} WHERE streamer_id = %s"
                    await cursor.execute(query, tuple(params))

                    staged_outbox_events: List[Dict[str, Any]] = list(outbox_events or [])
                    if outbox_trace_id:
                        if is_online and not bool(old_state.get("is_online")):
                            staged_outbox_events.append(
                                {
                                    "routing_key": "stream.state.online",
                                    "payload": {
                                        "event": "online",
                                        "streamer_id": streamer_id,
                                        "streamer_name": old_state.get("streamer_name"),
                                        "is_online": True,
                                        "game_id": game_id,
                                        "game_name": game_name,
                                        "stream_title": stream_title,
                                        "thumbnail_url": stream_thumbnail_url,
                                        "trace_id": outbox_trace_id,
                                    },
                                }
                            )
                        elif not is_online and bool(old_state.get("is_online")):
                            staged_outbox_events.append(
                                {
                                    "routing_key": "stream.state.offline",
                                    "payload": {
                                        "event": "offline",
                                        "streamer_id": streamer_id,
                                        "streamer_name": old_state.get("streamer_name"),
                                        "is_online": False,
                                        "trace_id": outbox_trace_id,
                                    },
                                }
                            )
                        elif (
                            is_online
                            and bool(old_state.get("is_online"))
                            and old_state.get("game_id") != (str(game_id) if game_id else None)
                        ):
                            staged_outbox_events.append(
                                {
                                    "routing_key": "stream.state.category",
                                    "payload": {
                                        "event": "category_change",
                                        "streamer_id": streamer_id,
                                        "streamer_name": old_state.get("streamer_name"),
                                        "old_game_id": old_state.get("game_id"),
                                        "new_game_id": str(game_id) if game_id else None,
                                        "new_game_name": game_name,
                                        "stream_title": stream_title,
                                        "thumbnail_url": stream_thumbnail_url,
                                        "trace_id": outbox_trace_id,
                                    },
                                }
                            )
                    await self._enqueue_outbox_messages_with_cursor(
                        cursor,
                        staged_outbox_events,
                    )
                    await conn.commit()

                    new_state = {
                        "streamer_name": old_state["streamer_name"],
                        "is_online": is_online,
                        "game_id": str(game_id) if game_id else None,
                        "game_name": game_name,
                        "stream_title": stream_title,
                    }

                    return (old_state, new_state)

        except Exception as e:
            self.logger.error(
                f"Failed to update streamer {streamer_id}: {e}", exc_info=True
            )
            raise

    async def update_streamers_status_bulk(
        self,
        updates: List[Dict[str, Any]],
    ) -> int:
        """
        Bulk update streamer statuses (max 100 per call).
        Only updates fields that are explicitly provided in each update dict.

        Args:
            updates: List of dicts with keys:
                - streamer_id (required)
                - is_online (required)
                - started_at (optional)
                - game_id (optional)
                - game_name (optional)
                - stream_title (optional)
                - stream_thumbnail_url (optional)
                - profile_image_url (optional) - only updated if provided

        Returns:
            Number of streamers updated
        """
        if not updates:
            return 0

        if len(updates) > 100:
            self.logger.warning("Bulk update limited to 100 streamers, truncating")
            updates = updates[:100]

        try:
            updated_count = 0
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    for update in updates:
                        streamer_id = update.get("streamer_id")
                        if not streamer_id:
                            continue

                        set_parts = ["is_online = %s"]
                        params = [update.get("is_online", False)]

                        set_parts.append("stream_started_at = %s")
                        params.append(update.get("started_at"))
                        set_parts.append("stream_game_id = %s")
                        params.append(update.get("game_id"))
                        set_parts.append("stream_game_name = %s")
                        params.append(update.get("game_name"))
                        set_parts.append("stream_title = %s")
                        params.append(update.get("stream_title"))
                        set_parts.append("stream_thumbnail_url = %s")
                        params.append(update.get("stream_thumbnail_url"))

                        # Only update profile_image_url if provided
                        if (
                            "profile_image_url" in update
                            and update["profile_image_url"] is not None
                        ):
                            set_parts.append("profile_image_url = %s")
                            params.append(update["profile_image_url"])

                        # Reset overrides when streamer goes offline (same as update_streamer_status)
                        if not update.get("is_online", False):
                            set_parts.append("is_pinned = FALSE")
                            set_parts.append("priority_override = NULL")
                            set_parts.append("pr_slots_override = NULL")

                        params.append(streamer_id)

                        query = f"UPDATE streamers SET {', '.join(set_parts)} WHERE streamer_id = %s"
                        await cursor.execute(query, tuple(params))

                        if cursor.rowcount > 0:
                            updated_count += 1

                    await conn.commit()

            self.logger.info(f"✓ Bulk updated {updated_count} streamers")
            return updated_count
        except Exception as e:
            self.logger.error(f"Failed to bulk update streamers: {e}", exc_info=True)
            raise

    async def update_streamer(
        self,
        streamer_id: int,
        priority: Optional[int] = None,
        pr_slots: Optional[int] = None,
        is_pinned: Optional[bool] = None,
        allow_juniors: Optional[bool] = None,
        priority_override: Optional[int] = None,
        pr_slots_override: Optional[int] = None,
        outbox_events: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """Обновление настроек стримера."""
        try:
            set_parts = []
            params = []

            if priority is not None:
                set_parts.append("priority = %s")
                params.append(priority)

            if pr_slots is not None:
                set_parts.append("pr_slots = %s")
                params.append(pr_slots)

            if is_pinned is not None:
                set_parts.append("is_pinned = %s")
                params.append(is_pinned)

            if allow_juniors is not None:
                set_parts.append("allow_juniors = %s")
                params.append(allow_juniors)

            if priority_override is not None:
                set_parts.append("priority_override = %s")
                params.append(priority_override)

            if pr_slots_override is not None:
                set_parts.append("pr_slots_override = %s")
                params.append(pr_slots_override)

            if not set_parts:
                return False

            params.append(streamer_id)

            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        f"UPDATE streamers SET {', '.join(set_parts)} WHERE streamer_id = %s",
                        tuple(params),
                    )
                    await self._enqueue_outbox_messages_with_cursor(cursor, outbox_events)
                    await conn.commit()
                    return cursor.rowcount > 0
        except Exception as e:
            self.logger.error(
                f"Failed to update streamer {streamer_id}: {e}", exc_info=True
            )
            return False

    async def recalc_target_active_sessions(
        self,
        target_type: str,
        target_id: int,
    ) -> int:
        """Recalculate priority_auto, rate_auto, priority_override, rate_override
        for ALL active sessions on a given target (streamer or event).

        Reads the current priority state from the target entity (streamers or events),
        calculates the matching rates from settings, and updates all non-probation
        active sessions.

        Returns number of sessions updated.
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    # 1. Read the current priority state of the target
                    if target_type == "streamer":
                        await cursor.execute(
                            "SELECT priority, priority_override FROM streamers WHERE streamer_id = %s",
                            (target_id,),
                        )
                    elif target_type == "event":
                        await cursor.execute(
                            "SELECT priority, NULL AS priority_override FROM events WHERE id = %s",
                            (target_id,),
                        )
                    else:
                        return 0

                    target_row = await cursor.fetchone()
                    if not target_row:
                        return 0

                    new_priority_auto = int(target_row.get("priority") or 0)
                    new_priority_override = target_row.get("priority_override")

                    # 2. Find all active sessions on this target
                    await cursor.execute(
                        """
                        SELECT id, is_probation
                        FROM spec_sessions
                        WHERE target_type = %s
                          AND target_id = %s
                          AND ended_at IS NULL
                          AND deleted_at IS NULL
                        """,
                        (target_type, target_id),
                    )
                    active_sessions = await cursor.fetchall()

                    if not active_sessions:
                        return 0

                    # 3. Read rates from settings
                    config = await self._get_points_config()
                    probation_rate = await self._get_probation_rate()

                    new_rate_auto = config.get(new_priority_auto, 0.5)

                    updated = 0
                    for session in active_sessions:
                        if session.get("is_probation"):
                            # Probation sessions keep their own rate
                            continue

                        if new_priority_override is not None:
                            new_rate_override = config.get(int(new_priority_override), 0.5)
                            await cursor.execute(
                                """
                                UPDATE spec_sessions
                                SET priority_auto = %s, rate_auto = %s,
                                    priority_override = %s, rate_override = %s
                                WHERE id = %s
                                """,
                                (
                                    new_priority_auto,
                                    new_rate_auto,
                                    int(new_priority_override),
                                    new_rate_override,
                                    session["id"],
                                ),
                            )
                        else:
                            await cursor.execute(
                                """
                                UPDATE spec_sessions
                                SET priority_auto = %s, rate_auto = %s,
                                    priority_override = NULL, rate_override = NULL
                                WHERE id = %s
                                """,
                                (new_priority_auto, new_rate_auto, session["id"]),
                            )
                        updated += 1

                    await conn.commit()

                    self.logger.info(
                        f"Recalc target sessions: {updated} sessions on "
                        f"{target_type}:{target_id} updated "
                        f"(priority_auto={new_priority_auto}, priority_override={new_priority_override})"
                    )
                    return updated
        except Exception as e:
            self.logger.error(
                f"Failed recalc_target_active_sessions for {target_type}:{target_id}: {e}",
                exc_info=True,
            )
            return 0

    async def remove_streamer(
        self,
        streamer_id: int,
        outbox_events: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """

        Удаление стримера из базы данных.

        Returns:
            True если удален, False если не найден
        """
        try:
            self.logger.debug(f"Deleting streamer {streamer_id}")
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "DELETE FROM streamers WHERE streamer_id = %s",
                        (streamer_id,),
                    )
                    await self._enqueue_outbox_messages_with_cursor(cursor, outbox_events)
                    await conn.commit()
            self.logger.debug(f"✓ Streamer {streamer_id} deleted")
        except Exception as e:
            self.logger.error(
                f"Failed to delete streamer {streamer_id}: {e}", exc_info=True
            )
            raise

    async def list_all_streamers(
        self,
        include_assignments: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Получение всех стримеров из базы данных.
        By default returns basic streamer data without assignments.
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    if not include_assignments:
                        await cursor.execute(
                            """
                            SELECT 
                                s.streamer_id, s.streamer_name, s.is_online, s.stream_title, s.stream_thumbnail_url,
                                s.is_pinned, s.allow_juniors, s.profile_image_url,
                                s.stream_game_id as game_id, s.stream_game_name as game_name, s.stream_started_at as started_at,
                                s.priority, s.pr_slots,
                                s.priority_override AS current_stream_priority_override,
                                s.pr_slots_override AS current_stream_pr_slots_override,
                                s.added_at, s.added_by_id, s.updated_at
                            FROM streamers s
                            ORDER BY s.priority DESC, s.streamer_name ASC
                            """
                        )
                        return await cursor.fetchall()

                    await cursor.execute(
                        """
                        SELECT 
                            s.streamer_id, s.streamer_name, s.is_online, s.stream_title, s.stream_thumbnail_url,
                            s.is_pinned, s.allow_juniors, s.profile_image_url,
                            s.stream_game_id as game_id, s.stream_game_name as game_name, s.stream_started_at as started_at,
                            s.priority, s.pr_slots,
                            s.priority_override AS current_stream_priority_override,
                            s.pr_slots_override AS current_stream_pr_slots_override,
                            s.added_at, s.added_by_id, s.updated_at,
                            MIN(act.pr_id) as assigned_pr_id,
                            COALESCE(
                                JSON_ARRAYAGG(
                                    CASE WHEN a.pr_id IS NOT NULL THEN
                                        JSON_OBJECT(
                                            'pr_id', CAST(a.pr_id AS CHAR),
                                            'nickname', a.nickname,
                                            'is_probation', COALESCE(act.is_probation, FALSE),
                                            'assigned_at', act.started_at
                                        )
                                    ELSE NULL END
                                ),
                                JSON_ARRAY()
                            ) as assignments
                        FROM streamers s
                        LEFT JOIN active_assignments_v act ON act.target_type = 'streamer'
                             AND act.target_id = s.streamer_id
                        LEFT JOIN assistants a ON a.pr_id = act.pr_id
                        GROUP BY s.streamer_id
                        ORDER BY s.is_pinned DESC, s.priority DESC, s.streamer_name ASC
                        """
                    )
                    results = await cursor.fetchall()
                    for row in results:
                        if isinstance(row.get("assignments"), str):
                            row["assignments"] = json.loads(row["assignments"])
                        if row.get("assignments"):
                            row["assignments"] = [
                                assignment
                                for assignment in row["assignments"]
                                if assignment is not None
                            ]
                    return results
        except Exception as e:
            self.logger.error(f"Failed to list streamers: {e}", exc_info=True)
            raise

    async def list_online_streamers(self) -> List[Dict[str, Any]]:
        """
        Получение списка всех онлайн стримеров с агрегированными назначениями.
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT 
                            s.streamer_id, s.streamer_name, s.is_online, s.stream_title, s.stream_thumbnail_url,
                            s.is_pinned, s.allow_juniors, s.profile_image_url,
                            s.stream_game_id as game_id, s.stream_game_name as game_name, s.stream_started_at as started_at,
                            s.priority, s.pr_slots,
                            s.priority_override AS current_stream_priority_override,
                            s.pr_slots_override AS current_stream_pr_slots_override,
                            s.added_at, s.added_by_id, s.updated_at,
                            MIN(act.pr_id) as assigned_pr_id,
                            COALESCE(
                                JSON_ARRAYAGG(
                                    CASE WHEN a.pr_id IS NOT NULL THEN
                                        JSON_OBJECT(
                                            'pr_id', CAST(a.pr_id AS CHAR),
                                            'nickname', a.nickname,
                                            'is_probation', COALESCE(act.is_probation, FALSE),
                                            'assigned_at', act.started_at
                                        )
                                    ELSE NULL END
                                ),
                                JSON_ARRAY()
                            ) as assignments
                        FROM streamers s
                        LEFT JOIN active_assignments_v act ON act.target_type = 'streamer' 
                             AND act.target_id = s.streamer_id 
                        LEFT JOIN assistants a ON a.pr_id = act.pr_id
                        WHERE s.is_online = TRUE
                        GROUP BY s.streamer_id
                        ORDER BY s.is_pinned DESC, s.priority DESC, s.streamer_name ASC
                        """
                    )
                    results = await cursor.fetchall()
                    for r in results:
                        if isinstance(r.get("assignments"), str):
                            r["assignments"] = json.loads(r["assignments"])
                        if r.get("assignments"):
                            r["assignments"] = [
                                x for x in r["assignments"] if x is not None
                            ]
                    return results
        except Exception as e:
            self.logger.error(f"Failed to list online streamers: {e}", exc_info=True)
            raise
