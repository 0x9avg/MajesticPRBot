from __future__ import annotations

from .core import Any, Dict, List, Optional, Config, json


class GuildsMixin:
    async def create_or_update_guild(
        self,
        notification_channel_id: Optional[int] = None,
        monitoring_channel_id: Optional[int] = None,
        monitoring_message_id: Optional[int] = None,
        monitoring_filter_gta: Optional[bool] = None,
        pr_actions_channel_id: Optional[int] = None,
        control_panel_channel_id: Optional[int] = None,
        control_panel_message_id: Optional[int] = None,
        outbox_events: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Create or update guild settings.

        Args:
            notification_channel_id: Discord channel ID for notifications (optional)
            monitoring_channel_id: Discord channel ID for monitoring (optional)
            monitoring_message_id: Discord message ID for monitoring (optional)
            monitoring_filter_gta: Filter monitoring to GTA streamers only (optional)
            pr_actions_channel_id: Discord channel ID for PR actions (optional)
            control_panel_channel_id: Discord channel ID for control panel (optional)
            control_panel_message_id: Discord message ID for control panel embed (optional)
        """
        try:
            self.logger.debug(
                f"""Saving guild settings: notification channel={notification_channel_id}, monitoring channel={monitoring_channel_id}, 
                PR actions channel={pr_actions_channel_id}, control panel channel={control_panel_channel_id}, control panel message={control_panel_message_id}"""
            )
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # First, get existing settings using the same cursor to ensure consistency
                    await cursor.execute(
                        "SELECT notification_channel_id, monitoring_channel_id, monitoring_message_id, monitoring_filter_gta, pr_actions_channel_id, control_panel_channel_id, control_panel_message_id FROM settings",
                    )
                    existing = await cursor.fetchone()

                    # Use existing values if new ones not provided
                    final_notification = (
                        notification_channel_id
                        if notification_channel_id is not None
                        else (
                            existing.get("notification_channel_id")
                            if existing
                            else None
                        )
                    )
                    final_monitoring_channel = (
                        monitoring_channel_id
                        if monitoring_channel_id is not None
                        else (
                            existing.get("monitoring_channel_id") if existing else None
                        )
                    )

                    final_monitoring_message_id = (
                        monitoring_message_id
                        if monitoring_message_id is not None
                        else (
                            existing.get("monitoring_message_id") if existing else None
                        )
                    )
                    final_pr_actions_channel = (
                        pr_actions_channel_id
                        if pr_actions_channel_id is not None
                        else (
                            existing.get("pr_actions_channel_id") if existing else None
                        )
                    )
                    final_control_panel_channel = (
                        control_panel_channel_id
                        if control_panel_channel_id is not None
                        else (
                            existing.get("control_panel_channel_id")
                            if existing
                            else None
                        )
                    )
                    final_control_panel_message = (
                        control_panel_message_id
                        if control_panel_message_id is not None
                        else (
                            existing.get("control_panel_message_id")
                            if existing
                            else None
                        )
                    )

                    final_filter_gta = (
                        monitoring_filter_gta
                        if monitoring_filter_gta is not None
                        else (
                            existing.get("monitoring_filter_gta") if existing else False
                        )
                    )

                    # 1. Update if exists
                    # Atomic UPSERT to prevent race conditions
                    await cursor.execute(
                        """
                        INSERT INTO settings (
                            id, 
                            notification_channel_id, 
                            monitoring_channel_id, 
                            monitoring_message_id, 
                            monitoring_filter_gta, 
                            pr_actions_channel_id, 
                            control_panel_channel_id, 
                            control_panel_message_id
                        )
                        VALUES (1, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            notification_channel_id = VALUES(notification_channel_id),
                            monitoring_channel_id = VALUES(monitoring_channel_id),
                            monitoring_message_id = VALUES(monitoring_message_id),
                            monitoring_filter_gta = VALUES(monitoring_filter_gta),
                            pr_actions_channel_id = VALUES(pr_actions_channel_id),
                            control_panel_channel_id = VALUES(control_panel_channel_id),
                            control_panel_message_id = VALUES(control_panel_message_id)
                        """,
                        (
                            final_notification,
                            final_monitoring_channel,
                            final_monitoring_message_id,
                            final_filter_gta,
                            final_pr_actions_channel,
                            final_control_panel_channel,
                            final_control_panel_message,
                        ),
                    )
                    await self._enqueue_outbox_messages_with_cursor(cursor, outbox_events)
                    await conn.commit()
                    self.logger.debug("✓ Guild settings saved successfully")

        except Exception as e:
            self.logger.error(f"Failed to save guild: {e}", exc_info=True)
            raise

    async def get_guild(self) -> Optional[Dict[str, Any]]:
        """Get guild settings.

        Returns:
            Guild settings dict or None if not found
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT notification_channel_id, monitoring_channel_id, monitoring_message_id, monitoring_filter_gta, pr_actions_channel_id, control_panel_channel_id, control_panel_message_id, notification_templates, p0_rate, p1_rate, p2_rate, p3_rate, probation_rate FROM settings WHERE id = 1",
                    )
                    return await cursor.fetchone()
        except Exception as e:
            self.logger.error(f"Failed to get guild: {e}", exc_info=True)
            raise

    async def _seed_game_servers(self, cursor) -> None:
        seed_rows = [
            {
                "id": server_id,
                "full_name": f"Majestic #{server_id}",
                "short_name": f"#{server_id}",
                "command_name": f"RU{server_id}",
                "sort_order": server_id,
                "is_active": True,
            }
            for server_id in range(1, 19)
        ]
        for row in seed_rows:
            await cursor.execute(
                """
                INSERT INTO game_servers (
                    id, full_name, short_name, command_name, sort_order, is_active
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE id = id
                """,
                (
                    row["id"],
                    row["full_name"],
                    row["short_name"],
                    row["command_name"],
                    row["sort_order"],
                    row["is_active"],
                ),
            )

    async def _init_game_servers(self, conn) -> None:
        async with conn.cursor() as cursor:
            await self._seed_game_servers(cursor)

    async def _get_game_server_map_locked(
        self,
        cursor,
        *,
        include_inactive: bool = True,
    ) -> dict[int, dict[str, Any]]:
        where_sql = ""
        params: tuple[Any, ...] = ()
        if not include_inactive:
            where_sql = "WHERE is_active = TRUE"
        await cursor.execute(
            f"""
            SELECT
                id,
                full_name,
                short_name,
                command_name,
                sort_order,
                is_active,
                created_at,
                updated_at
            FROM game_servers
            {where_sql}
            ORDER BY sort_order ASC, id ASC
            """,
            params,
        )
        rows = await cursor.fetchall() or []
        return {
            int(row.get("id")): dict(row)
            for row in rows
            if row.get("id") is not None
        }

    async def list_game_servers(
        self,
        *,
        include_inactive: bool = True,
    ) -> List[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                servers = await self._get_game_server_map_locked(
                    cursor,
                    include_inactive=include_inactive,
                )
                await conn.commit()
                return list(servers.values())

    async def get_game_server(
        self,
        server_id: int,
        *,
        include_inactive: bool = True,
    ) -> Optional[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                servers = await self._get_game_server_map_locked(
                    cursor,
                    include_inactive=include_inactive,
                )
                await conn.commit()
                return servers.get(int(server_id))

    async def replace_game_servers(
        self,
        items: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not items:
            raise ValueError("Нужно задать хотя бы один сервер")

        normalized_rows: List[Dict[str, Any]] = []
        explicit_id_rows: List[Dict[str, Any]] = []
        pending_id_rows: List[Dict[str, Any]] = []
        seen_full_names: set[str] = set()
        seen_short_names: set[str] = set()
        seen_command_names: set[str] = set()
        for item in items:
            raw_id = item.get("id")
            full_name = str(item["full_name"] or "").strip()
            short_name = str(item["short_name"] or "").strip()
            command_name = str(item["command_name"] or "").strip()
            sort_order = int(item.get("sort_order") or 0)
            is_active = bool(item.get("is_active", True))
            if not full_name or not short_name or not command_name:
                raise ValueError("game_servers requires full_name, short_name and command_name")
            if (
                full_name in seen_full_names
                or short_name in seen_short_names
                or command_name in seen_command_names
            ):
                raise ValueError("game_servers contains duplicate ids or labels")
            seen_full_names.add(full_name)
            seen_short_names.add(short_name)
            seen_command_names.add(command_name)
            normalized = {
                "id": None if raw_id in (None, "") else int(raw_id),
                "full_name": full_name,
                "short_name": short_name,
                "command_name": command_name,
                "sort_order": sort_order,
                "is_active": is_active,
            }
            if normalized["id"] is None:
                pending_id_rows.append(normalized)
            else:
                if normalized["id"] <= 0 or normalized["id"] > 255:
                    raise ValueError("id должен быть в диапазоне 1..255")
                explicit_id_rows.append(normalized)

        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT id FROM game_servers ORDER BY id ASC"
                )
                existing_rows = await cursor.fetchall() or []
                existing_ids = {int(row.get("id")) for row in existing_rows if row.get("id") is not None}
                snapshot_ids = {row["id"] for row in explicit_id_rows}
                missing_ids = sorted(existing_ids - snapshot_ids)
                if missing_ids:
                    raise ValueError(
                        "game_servers snapshot must include all existing rows"
                    )

                seen_ids = set(snapshot_ids)
                next_server_id = max(existing_ids | snapshot_ids, default=0) + 1
                for row in pending_id_rows:
                    while next_server_id in seen_ids:
                        next_server_id += 1
                    if next_server_id > 255:
                        raise ValueError("Нельзя создать сервер с id > 255")
                    row["id"] = next_server_id
                    seen_ids.add(next_server_id)
                    next_server_id += 1
                normalized_rows = explicit_id_rows + pending_id_rows
                if len(seen_ids) != len(normalized_rows):
                    raise ValueError("game_servers contains duplicate ids or labels")

                for row in normalized_rows:
                    await cursor.execute(
                        """
                        INSERT INTO game_servers (
                            id,
                            full_name,
                            short_name,
                            command_name,
                            sort_order,
                            is_active
                        )
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            full_name = VALUES(full_name),
                            short_name = VALUES(short_name),
                            command_name = VALUES(command_name),
                            sort_order = VALUES(sort_order),
                            is_active = VALUES(is_active),
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        (
                            row["id"],
                            row["full_name"],
                            row["short_name"],
                            row["command_name"],
                            row["sort_order"],
                            row["is_active"],
                        ),
                    )
                await conn.commit()
                return await self.list_game_servers(include_inactive=True)

    async def get_notification_template(self, event_type: str) -> str:
        """
        Получение шаблона уведомления для события.

        Args:
            event_type: Тип события ('stream_online', 'stream_offline' и т.д.)

        Returns:
            Строка шаблона с плейсхолдерами

        Raises:
            ValueError: Если тип события недопустим
        """
        # SQL injection prevention: validate event_type against whitelist
        if event_type not in Config.allowed_event_types:
            self.logger.error(
                f"Invalid event_type '{event_type}' - possible SQL injection attempt"
            )
            raise ValueError(f"Invalid event type: {event_type}")

        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT notification_templates FROM settings WHERE id = 1"
                    )
                    result = await cursor.fetchone()
                    if result and result.get("notification_templates"):
                        templates = json.loads(result["notification_templates"])
                        return templates.get(
                            event_type, Config.template_defaults.get(event_type, "")
                        )
                    return Config.template_defaults.get(event_type, "")
        except Exception as e:
            self.logger.error(f"Failed to get template for guild: {e}", exc_info=True)
            return Config.template_defaults.get(event_type, "")

    async def update_guild_templates(
        self,
        template_stream_online_gta: Optional[str] = None,
        template_stream_online_other: Optional[str] = None,
        template_stream_offline: Optional[str] = None,
        template_category_to_gta: Optional[str] = None,
        template_category_from_gta: Optional[str] = None,
        outbox_events: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """Обновление шаблонов уведомлений гильдии."""
        try:
            guild = await self.get_guild()
            if not guild:  # Guild must exist
                return False

            # Get existing templates from DB
            raw_templates = guild.get("notification_templates")

            # Parse JSON string if needed, otherwise start with empty dict
            if isinstance(raw_templates, str):
                try:
                    current_templates = json.loads(raw_templates)
                except json.JSONDecodeError:
                    current_templates = {}
            elif isinstance(raw_templates, dict):
                current_templates = raw_templates.copy()
            else:
                current_templates = {}

            # Update only the provided fields
            if template_stream_online_gta is not None:
                current_templates["stream_online_gta"] = template_stream_online_gta
            if template_stream_online_other is not None:
                current_templates["stream_online_other"] = template_stream_online_other
            if template_stream_offline is not None:
                current_templates["stream_offline"] = template_stream_offline
            if template_category_to_gta is not None:
                current_templates["category_to_gta"] = template_category_to_gta
            if template_category_from_gta is not None:
                current_templates["category_from_gta"] = template_category_from_gta

            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "UPDATE settings SET notification_templates = %s",
                        (json.dumps(current_templates),),
                    )
                    await self._enqueue_outbox_messages_with_cursor(cursor, outbox_events)
                    await conn.commit()
                    return True
        except Exception as e:
            self.logger.error(f"Failed to update guild templates: {e}", exc_info=True)
            return False

    async def update_guild_rates(
        self,
        p0_rate: Optional[float] = None,
        p1_rate: Optional[float] = None,
        p2_rate: Optional[float] = None,
        p3_rate: Optional[float] = None,
        probation_rate: Optional[float] = None,
        outbox_events: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """Обновление рейтов баллов гильдии."""
        try:
            updates = []
            values = []

            if p0_rate is not None:
                updates.append("p0_rate = %s")
                values.append(p0_rate)
            if p1_rate is not None:
                updates.append("p1_rate = %s")
                values.append(p1_rate)
            if p2_rate is not None:
                updates.append("p2_rate = %s")
                values.append(p2_rate)
            if p3_rate is not None:
                updates.append("p3_rate = %s")
                values.append(p3_rate)
            if probation_rate is not None:
                updates.append("probation_rate = %s")
                values.append(probation_rate)

            if not updates:
                return True

            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        f"UPDATE settings SET {', '.join(updates)}",
                        values,
                    )
                    await self._enqueue_outbox_messages_with_cursor(cursor, outbox_events)
                    await conn.commit()
                    return True
        except Exception as e:
            self.logger.error(f"Failed to update guild rates: {e}", exc_info=True)
            return False
