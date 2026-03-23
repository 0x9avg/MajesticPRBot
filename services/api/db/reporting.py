from __future__ import annotations

from .core import Config, Dict


class ReportingMixin:
    async def get_dashboard_stats(self) -> Dict[str, int]:
        """Get aggregated statistics for the main dashboard."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # 1. Count assigned PR assistants (active sessions)
                    await cursor.execute(
                        "SELECT COUNT(*) as count FROM active_assignments_v"
                    )
                    assigned_pr_count = (await cursor.fetchone())["count"]

                    # 2. Count online GTA streamers
                    try:
                        await cursor.execute(
                            """
                            SELECT COUNT(*) as count 
                            FROM streamers s
                            WHERE s.is_online = TRUE
                              AND s.stream_game_id = %s
                            """,
                            (Config.gta5_game_id,),
                        )
                        result = await cursor.fetchone()
                        unassigned_media_count = result["count"] if result else 0
                    except Exception:
                        unassigned_media_count = 0

                    # 3. Count events for today
                    try:
                        await cursor.execute(
                            """
                            SELECT COUNT(*) as count FROM events 
                            WHERE is_active = TRUE
                            """
                        )
                        result = await cursor.fetchone()
                        events_today_count = result["count"] if result else 0
                    except Exception:
                        events_today_count = 0

                    return {
                        "assigned_pr_count": assigned_pr_count,
                        "unassigned_media_count": unassigned_media_count,
                        "events_today_count": events_today_count,
                    }
        except Exception as e:
            self.logger.error(f"Failed to get dashboard stats: {e}", exc_info=True)
            return {
                "assigned_pr_count": 0,
                "unassigned_media_count": 0,
                "events_today_count": 0,
            }

    async def get_service_overview_stats(self) -> Dict[str, int]:
        """Get service-facing domain counters for the service overview panel."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT
                            COUNT(*) AS streamers_total,
                            COALESCE(SUM(CASE WHEN is_online = TRUE THEN 1 ELSE 0 END), 0) AS streamers_online,
                            COALESCE(SUM(CASE WHEN is_online = TRUE AND stream_game_id = %s THEN 1 ELSE 0 END), 0) AS gta_online
                        FROM streamers
                        """,
                        (Config.gta5_game_id,),
                    )
                    streamer_stats = await cursor.fetchone() or {}

                    await cursor.execute(
                        """
                        SELECT
                            COUNT(*) AS active_spec_sessions,
                            COALESCE(SUM(CASE WHEN is_probation = TRUE THEN 1 ELSE 0 END), 0) AS probation_sessions
                        FROM active_assignments_v
                        """
                    )
                    spec_stats = await cursor.fetchone() or {}

                    await cursor.execute(
                        "SELECT COUNT(*) AS active_events FROM events WHERE is_active = TRUE"
                    )
                    event_stats = await cursor.fetchone() or {}

                    await cursor.execute(
                        "SELECT COUNT(*) AS assistants_total FROM assistants"
                    )
                    assistant_stats = await cursor.fetchone() or {}

                    await cursor.execute(
                        "SELECT COUNT(*) AS web_users_total FROM web_auth"
                    )
                    user_stats = await cursor.fetchone() or {}

                    await cursor.execute(
                        """
                        SELECT COUNT(*) AS admin_actions_24h
                        FROM admin_logs
                        WHERE created_at >= (UTC_TIMESTAMP() - INTERVAL 1 DAY)
                        """
                    )
                    log_stats = await cursor.fetchone() or {}

                    return {
                        "streamers_total": int(streamer_stats.get("streamers_total", 0)),
                        "streamers_online": int(streamer_stats.get("streamers_online", 0)),
                        "gta_online": int(streamer_stats.get("gta_online", 0)),
                        "active_spec_sessions": int(spec_stats.get("active_spec_sessions", 0)),
                        "probation_sessions": int(spec_stats.get("probation_sessions", 0)),
                        "active_events": int(event_stats.get("active_events", 0)),
                        "assistants_total": int(assistant_stats.get("assistants_total", 0)),
                        "web_users_total": int(user_stats.get("web_users_total", 0)),
                        "admin_actions_24h": int(log_stats.get("admin_actions_24h", 0)),
                    }
        except Exception as e:
            self.logger.error(
                f"Failed to get service overview stats: {e}",
                exc_info=True,
            )
            return {
                "streamers_total": 0,
                "streamers_online": 0,
                "gta_online": 0,
                "active_spec_sessions": 0,
                "probation_sessions": 0,
                "active_events": 0,
                "assistants_total": 0,
                "web_users_total": 0,
                "admin_actions_24h": 0,
            }
