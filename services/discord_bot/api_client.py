"""
API Client for Discord Bot.
HTTP client for communicating with the central API service.
Полностью независимый - не импортирует из других сервисов.
"""

import aiohttp
from typing import Optional, List, Dict, Any
import logging


class APIClient:
    """HTTP client for API communication."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        api_token: Optional[str] = None,
        timeout: int = 30,
        logger: Optional[logging.Logger] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.logger = logger or logging.getLogger(__name__)
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            headers = {"Content-Type": "application/json"}
            if self.api_token:
                headers["Authorization"] = f"Bearer {self.api_token}"
            self._session = aiohttp.ClientSession(
                timeout=self.timeout,
                headers=headers,
            )
        return self._session

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self.logger.debug("API client session closed")

    async def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
    ) -> Optional[Dict]:
        """Make HTTP request to API."""
        session = await self._get_session()
        url = f"{self.base_url}/api{endpoint}"

        try:
            async with session.request(method, url, json=data, params=params) as resp:
                if resp.status == 204:
                    return {"status": "success"}

                result = await resp.json()
                if not isinstance(result, (dict, list)) and result is not None:
                    self.logger.warning(f"API returned non-structured JSON: {type(result)} val: {result} for {url}")

                if resp.status >= 400:
                    # 4xx = expected business logic (conflict, not found, etc.)
                    # 5xx = actual server errors
                    if resp.status >= 500:
                        self.logger.error(f"API error {resp.status}: {result}")
                    else:
                        self.logger.warning(f"API response {resp.status}: {result}")
                    return result  # Return error details

                return result
        except aiohttp.ClientError as e:
            self.logger.error(f"API request failed: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error in API request: {e}")
            return None

    # =========================================================================
    # Streamers API
    # =========================================================================

    async def list_all_streamers(self) -> List[Dict]:
        """Get all streamers."""
        result = await self._request("GET", "/streamers")
        if result and "streamers" in result:
            return result["streamers"]
        return result if isinstance(result, list) else []

    async def get_streamer(self, twitch_id: int) -> Optional[Dict]:
        """Get a specific streamer."""
        return await self._request("GET", f"/streamers/{twitch_id}")

    async def add_streamer(
        self,
        twitch_url: str,
        priority: int = 0,
        added_by_id: int = 0,
    ) -> Optional[Dict]:
        """Add a streamer (API resolves Twitch ID)."""
        return await self._request(
            "POST",
            "/streamers",
            data={
                "twitch_url": twitch_url,
                "priority": priority,
            },
            params={"added_by_id": added_by_id},
        )

    async def update_streamer(
        self,
        streamer_id: int,
        priority: Optional[int] = None,
    ) -> Optional[Dict]:
        """Update streamer settings (priority/paid status)."""
        data = {}
        if priority is not None:
            data["priority"] = priority

        return await self._request("PATCH", f"/streamers/{streamer_id}", data=data)

    async def delete_streamer(self, twitch_id: int) -> bool:
        """Delete a streamer."""
        result = await self._request("DELETE", f"/streamers/{twitch_id}")
        return result is not None and result.get("status") == "success"

    async def streamer_exists(self, twitch_id: int) -> bool:
        """Check if streamer exists."""
        result = await self.get_streamer(twitch_id)
        return result is not None and "detail" not in result

    # =========================================================================
    # Guild Settings API
    # =========================================================================

    async def get_guild_settings(self) -> Optional[Dict]:
        """Get guild settings."""
        return await self._request("GET", "/guild")

    async def update_guild_settings(self, **kwargs) -> Optional[Dict]:
        """Update guild settings."""
        return await self._request("PATCH", "/guild", data=kwargs)

    async def update_guild_templates(self, templates: Dict[str, str]) -> Optional[Dict]:
        """Update notification templates."""
        # Map template names to schema fields if necessary
        # Schema expects: template_stream_online, etc.
        # But UI might pass { "stream_online": "tmpl" }
        # Mapping generic event types to schema fields
        data = {}
        for k, v in templates.items():
            if not k.startswith("template_"):
                data[f"template_{k}"] = v
            else:
                data[k] = v
        return await self._request("PATCH", "/guild/templates", data=data)

    async def update_guild_rates(
        self,
        p0_rate: Optional[float] = None,
        p1_rate: Optional[float] = None,
        p2_rate: Optional[float] = None,
        p3_rate: Optional[float] = None,
    ) -> Optional[Dict]:
        """Update guild point rates."""
        data = {}
        if p0_rate is not None:
            data["p0_rate"] = p0_rate
        if p1_rate is not None:
            data["p1_rate"] = p1_rate
        if p2_rate is not None:
            data["p2_rate"] = p2_rate
        if p3_rate is not None:
            data["p3_rate"] = p3_rate

        return await self._request("PATCH", "/guild/rates", data=data)

    # =========================================================================
    # Spec System API
    # =========================================================================

    async def claim_streamer(self, streamer_id: int, pr_id: int) -> Optional[Dict]:
        """Claim a streamer."""
        return await self._request(
            "POST",
            "/spec/claim",
            data={
                "streamer_id": streamer_id,
                "pr_id": pr_id,
            },
        )

    async def unclaim_streamer(
        self, streamer_id: int, reason: str = "manual"
    ) -> Optional[Dict]:
        """Unclaim a streamer."""
        return await self._request(
            "POST",
            "/spec/unclaim",
            data={
                "streamer_id": streamer_id,
                "reason": reason,
            },
        )

    async def transfer_streamer(
        self, streamer_id: int, from_pr_id: int, to_pr_id: int
    ) -> Optional[Dict]:
        """Transfer a streamer."""
        return await self._request(
            "POST",
            "/spec/transfer",
            data={
                "streamer_id": streamer_id,
                "from_pr_id": from_pr_id,
                "to_pr_id": to_pr_id,
            },
        )

    async def swap_streamers(self, pr1_id: int, pr2_id: int) -> Optional[Dict]:
        """Swap streamers between two PRs."""
        return await self._request(
            "POST",
            "/spec/swap",
            data={
                "pr1_id": pr1_id,
                "pr2_id": pr2_id,
            },
        )

    async def get_active_specs(self) -> List[Dict]:
        """Get all active spec sessions."""
        result = await self._request("GET", "/spec/active")
        return result if isinstance(result, list) else []

    async def get_current_streamer_for_pr(self, pr_id: int) -> Optional[Dict]:
        """Get raw response for PR current streamer (includes 'assigned' flag)."""
        return await self._request("GET", f"/spec/by-pr/{pr_id}")

    async def get_pr_current_streamer(self, pr_id: int) -> Optional[Dict]:
        """Get the streamer currently assigned to a PR."""
        result = await self._request("GET", f"/spec/by-pr/{pr_id}")
        if result and result.get("assigned"):
            return result.get("streamer")
        return None

    # =========================================================================
    # Assistants API
    # =========================================================================

    async def get_assistants(self) -> List[Dict]:
        """Get all assistants."""
        result = await self._request("GET", "/assistants")
        return result if isinstance(result, list) else []

    async def get_assistant_stats(self, user_id: int) -> Optional[Dict]:
        """Get assistant stats."""
        return await self._request("GET", f"/assistants/{user_id}/stats")

    async def add_assistant_time(self, user_id: int, seconds: int) -> Optional[Dict]:
        """Add time to assistant's total."""
        return await self._request(
            "POST", f"/assistants/{user_id}/add-time", params={"seconds": seconds}
        )

    async def subtract_assistant_time(
        self, user_id: int, seconds: int
    ) -> Optional[Dict]:
        """Subtract time from assistant's total."""
        return await self._request(
            "POST", f"/assistants/{user_id}/subtract-time", params={"seconds": seconds}
        )

    # =========================================================================
    # Monitoring API
    # =========================================================================

    async def refresh_monitoring(self, force: bool = False) -> Optional[Dict]:
        """Request monitoring refresh."""
        return await self._request("POST", "/monitoring/refresh", data={"force": force})

    async def get_dashboard_status(self) -> Optional[Dict]:
        """Get dashboard status."""
        return await self._request("GET", "/dashboard/status")

    async def get_leaderboard(self, limit: int = 10) -> Optional[Dict]:
        """Get PR leaderboard."""
        return await self._request("GET", "/stats/leaderboard", params={"limit": limit})

    # =========================================================================
    # Event API
    # =========================================================================

    async def create_event(
        self,
        name: str,
        description: str,
        required_pr_count: int,
        channel_id: int,
        created_by: int,
        guild_id: str,
        start_time: Optional[str] = None,
    ) -> Optional[Dict]:
        """Create a new event."""
        data = {
            "name": name,
            "description": description,
            "required_pr_count": required_pr_count,
            "channel_id": channel_id,
            "created_by": created_by,
            "guild_id": guild_id,
        }
        if start_time:
            data["start_time"] = start_time

        return await self._request("POST", "/events", data=data)

    async def get_active_events(self, guild_id: str) -> List[Dict]:
        """Get active events."""
        result = await self._request(
            "GET", "/events/active", params={"guild_id": guild_id}
        )
        return result if isinstance(result, list) else []

    async def get_scheduled_events(self) -> List[Dict]:
        """Get scheduled events starting now."""
        result = await self._request("GET", "/events/scheduled")
        return result if isinstance(result, list) else []

    async def join_event(self, event_id: int, user_id: int) -> Optional[Dict]:
        """Join an event."""
        return await self._request(
            "POST", f"/events/{event_id}/join", data={"user_id": user_id}
        )

    async def leave_event(self, event_id: int, user_id: int) -> Optional[Dict]:
        """Leave an event."""
        return await self._request(
            "POST", f"/events/{event_id}/leave", data={"user_id": user_id}
        )

    async def end_event(self, event_id: int) -> Optional[Dict]:
        """End an event."""
        return await self._request("POST", f"/events/{event_id}/end")

    async def mark_event_notification_sent(self, event_id: int) -> bool:
        """Mark event notification as sent."""
        result = await self._request("PATCH", f"/events/{event_id}/notification-sent")
        return result is not None

    async def update_event_message(self, event_id: int, message_id: int) -> bool:
        """Update event message ID."""
        result = await self._request(
            "PATCH", f"/events/{event_id}/message", params={"message_id": message_id}
        )
        return result is not None

    async def get_user_active_event(self, user_id: int) -> Optional[Dict]:
        """Get user's active event."""
        return await self._request("GET", f"/events/user/{user_id}/active")

    async def get_event(self, event_id: int) -> Optional[Dict]:
        """Get a specific event by ID."""
        return await self._request("GET", f"/events/{event_id}")

    async def get_event_participants(self, event_id: int) -> List[Dict]:
        """Get event participants."""
        result = await self._request("GET", f"/events/{event_id}/participants")
        return result if isinstance(result, list) else []

    # =========================================================================
    # Extended Streamers API
    # =========================================================================

    async def update_streamer_priority(self, streamer_id: int, priority: int) -> bool:
        """Update streamer priority."""
        result = await self._request(
            "PATCH", f"/streamers/{streamer_id}", data={"priority": priority}
        )
        return result is not None and "detail" not in result

    async def get_available_gta_streamers(self) -> List[Dict]:
        """Get online GTA streamers without assigned PR."""
        result = await self._request("GET", "/streamers/available-gta")
        return result if isinstance(result, list) else []

    async def get_streamer_assigned_pr(self, streamer_id: int) -> Optional[int]:
        """Get the PR ID assigned to a streamer."""
        streamer = await self.get_streamer(streamer_id)
        if streamer:
            return streamer.get("assigned_pr_id")
        return None

    # =========================================================================
    # Extended Assistants API
    # =========================================================================

    async def get_pr_total_time(self, pr_id: int) -> int:
        """Get total spec time for a PR in seconds."""
        result = await self._request("GET", f"/assistants/{pr_id}")
        if result and "total_spec_seconds" in result:
            return result["total_spec_seconds"]
        return 0

    async def get_top_assistants(self, limit: int = 10) -> List[Dict]:
        """Get top assistants by spec time."""
        result = await self._request("GET", "/assistants/top", params={"limit": limit})
        return result if isinstance(result, list) else []

    async def reset_assistant_stats(self, user_id: int) -> bool:
        """Reset assistant statistics."""
        result = await self._request("POST", f"/assistants/{user_id}/reset")
        return result is not None and "detail" not in result

    async def get_daily_stats(
        self, pr_id: Optional[int] = None, date_str: Optional[str] = None
    ) -> List[Dict]:
        """Get daily statistics with optional filters."""
        params = {}
        if pr_id:
            params["pr_id"] = pr_id
        if date_str:
            params["date"] = date_str
        result = await self._request(
            "GET", "/stats/daily", params=params if params else None
        )
        return result if isinstance(result, list) else []

    async def update_daily_stats_manual(
        self,
        pr_id: int,
        date_str: str,
        p0: int,
        p1: int,
        p2: int,
        p3: int,
        total_points: float,
    ) -> bool:
        """Manually update daily stats for a PR."""
        result = await self._request(
            "PUT",
            f"/assistants/{pr_id}/daily-stats",
            data={
                "date": date_str,
                "p0_seconds": p0,
                "p1_seconds": p1,
                "p2_seconds": p2,
                "p3_seconds": p3,
                "total_points": total_points,
            },
        )
        return result is not None and "detail" not in result

    # =========================================================================
    # Extended Guild API
    # =========================================================================

    async def get_pr_actions_channel(self, guild_id: str) -> Optional[int]:
        """Get PR actions channel ID."""
        settings = await self.get_guild_settings()
        if settings:
            return settings.get("pr_actions_channel_id")
        return None

    async def get_points_config(self) -> Dict[int, float]:
        """Get point rates configuration."""
        settings = await self.get_guild_settings()
        if settings:
            return {
                0: settings.get("p0_rate", 0.25),
                1: settings.get("p1_rate", 0.4),
                2: settings.get("p2_rate", 0.5),
                3: settings.get("p3_rate", 0.6),
            }
        return {0: 0.25, 1: 0.4, 2: 0.5, 3: 0.6}

    async def set_points_config(self, rates: Dict[int, float]) -> bool:
        """Set point rates configuration."""
        data = {}
        for k, v in rates.items():
            data[f"p{k}_rate"] = v
        result = await self._request("PATCH", "/guild/rates", data=data)
        return result is not None

    async def get_notification_template(self, event_type: str) -> str:
        """Get notification template for event type."""
        result = await self._request("GET", f"/guild/templates/{event_type}")
        if result and "template" in result:
            return result["template"]
        return ""

    async def update_notification_template(
        self, event_type: str, template: str
    ) -> bool:
        """Update notification template."""
        data = {f"template_{event_type}": template}
        result = await self._request("PATCH", "/guild/templates", data=data)
        return result is not None

    # =========================================================================
    # Channel Management API
    # =========================================================================

    async def set_notification_channel(self, guild_id: str, channel_id: int) -> bool:
        """Set notification channel."""
        result = await self.update_guild_settings(notification_channel_id=channel_id)
        return result is not None

    async def set_monitoring_channel(self, guild_id: str, channel_id: int) -> bool:
        """Set monitoring channel."""
        result = await self.update_guild_settings(monitoring_channel_id=channel_id)
        return result is not None

    async def set_pr_actions_channel(self, guild_id: str, channel_id: int) -> bool:
        """Set PR actions channel."""
        result = await self.update_guild_settings(pr_actions_channel_id=channel_id)
        return result is not None
