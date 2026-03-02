"""API Client for Discord Bot.

HTTP client for communicating with the central API service.
"""

import json
import logging
from typing import Any, Dict, List, Optional

import aiohttp


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
        session = await self._get_session()
        url = f"{self.base_url}/api{endpoint}"
        if endpoint == "/health":
            url = f"{self.base_url}{endpoint}"

        try:
            async with session.request(method, url, json=data, params=params) as resp:
                if resp.status == 204:
                    return {"status": "success"}

                result = await resp.json()

                # Unwrap API Envelope
                if isinstance(result, dict) and "status" in result and "data" in result:
                    if result["status"] == "success" or resp.status < 400:
                        return result["data"]
                    else:
                        # Envelope with error status
                        error_msg = result.get("message", "Unknown API error")
                        self.logger.warning(f"API Error ({resp.status}): {error_msg}")
                        return result  # Return full envelope for custom error handling if needed

                if not isinstance(result, (dict, list)) and result is not None:
                    self.logger.warning(
                        f"API returned non-structured JSON: {type(result)} val: {result} for {url}"
                    )

                if resp.status >= 400:
                    # 4xx = expected business logic (conflict, not found, etc.)
                    # 5xx = actual server errors
                    if resp.status >= 500:
                        self.logger.error(f"API error {resp.status}: {result}")
                    elif resp.status == 404:
                        self.logger.debug(
                            f"API resource not found {resp.status}: {result}"
                        )
                    else:
                        self.logger.warning(f"API response {resp.status}: {result}")
                    return result  # Return error details

                return result
        except aiohttp.ClientError as e:
            self.logger.error(f"API request failed: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error in API request: {e}", exc_info=True)
            return None

    async def get_health(self) -> Dict[str, Any]:
        """Get API health status."""
        # Assuming there is a /health endpoint not under /api
        # or we just returning a dummy structure if not exists, but better try /health
        try:
            result = await self._request("GET", "/health")
            if result:
                return result
            return {"status": "unknown", "api": "online"}
        except:  # noqa: E722
            return {"status": "unreachable"}

    async def sync_streamers(self) -> Dict[str, Any]:
        """Trigger streamers sync (via refreshing monitoring for now)."""
        # Ideally this would tell Twitch Bot to sync.
        # Fallback to refreshing monitoring.
        return await self.refresh_monitoring(force=True)

    async def list_all_streamers(self) -> List[Dict]:
        """Get all streamers."""
        result = await self._request("GET", "/streamers")
        if result and "streamers" in result:
            return result["streamers"]
        return []

    async def get_streamer(self, twitch_id: int) -> Optional[Dict]:
        return await self._request("GET", f"/streamers/{twitch_id}")

    async def add_streamer(
        self,
        twitch_url: str,
        priority: int = 0,
        added_by_id: int = 0,
    ) -> Optional[Dict]:
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
        result = await self._request("DELETE", f"/streamers/{twitch_id}")
        return result is not None and result.get("status") == "success"

    async def streamer_exists(self, twitch_id: int) -> bool:
        """Check if streamer exists."""
        result = await self.get_streamer(twitch_id)
        return result is not None and "detail" not in result

    async def get_guild_settings(self) -> Optional[Dict]:
        """Get guild settings."""
        data = await self._request("GET", "/guild")
        if not isinstance(data, dict):
            return None
        data["notification_templates"] = json.loads(
            data.get("notification_templates", "{}")
        )
        return data

    async def update_guild_settings(self, **kwargs) -> Optional[Dict]:
        """Update guild settings."""
        return await self._request("PATCH", "/guild/settings", data=kwargs)

    async def update_guild_templates(self, templates: Dict[str, str]) -> Optional[Dict]:
        """Update notification templates."""
        return await self._request("PATCH", "/guild/templates", data=templates)

    async def update_guild_rates(
        self,
        p0_rate: Optional[float] = None,
        p1_rate: Optional[float] = None,
        p2_rate: Optional[float] = None,
        p3_rate: Optional[float] = None,
        probation_rate: Optional[float] = None,
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
        if probation_rate is not None:
            data["probation_rate"] = probation_rate

        return await self._request("PATCH", "/guild/rates", data=data)

    async def claim_streamer(
        self, streamer_id: int, pr_id: int, is_probation: bool = False
    ) -> Optional[Dict]:
        """Claim a streamer (supports Probation via Slot Logic)."""
        return await self._request(
            "POST",
            "/spec/claim",
            data={
                "streamer_id": streamer_id,
                "pr_id": pr_id,
                "is_probation": is_probation,
            },
        )

    async def unclaim_streamer(
        self, streamer_id: int, pr_id: Optional[int] = None, reason: str = "manual"
    ) -> Optional[Dict]:
        """Unclaim a streamer."""
        data = {
            "streamer_id": streamer_id,
            "reason": reason,
        }
        if pr_id is not None:
            data["pr_id"] = pr_id

        return await self._request(
            "POST",
            "/spec/unclaim",
            data=data,
        )


    async def get_current_streamer_for_pr(self, pr_id: int) -> Optional[Dict]:
        """Get raw response for PR current streamer (includes 'assigned' flag)."""
        return await self._request("GET", f"/spec/by-pr/{pr_id}")

    async def get_pr_current_streamer(self, pr_id: int) -> Optional[Dict]:
        """Get the streamer currently assigned to a PR."""
        result = await self._request("GET", f"/spec/by-pr/{pr_id}")
        if result and result.get("assigned"):
            return result.get("streamer")
        return None

    async def get_claimable_streamers(self, user_id: int) -> Dict:
        """Get streamers available for claim by a specific user.

        Returns dict with:
        - streamers: list of {streamer_id, streamer_name, priority, main_free, probation_free}
        - can_spec_probation: bool
        """
        result = await self._request(
            "GET", "/spec/claimable", params={"user_id": user_id}
        )
        if result and "streamers" in result:
            return result
        return {"streamers": [], "can_spec_probation": False}

    async def get_assistants(self) -> List[Dict]:
        """Get all assistants."""
        result = await self._request("GET", "/assistants")
        # API returns list of assistants directly in data
        return result if isinstance(result, list) else []

    async def get_assistant(self, user_id: int) -> Optional[Dict]:
        """Get a specific assistant by ID."""
        return await self._request("GET", f"/assistants/{user_id}")

    async def get_assistant_capabilities(self, user_id: int) -> Dict[str, bool]:
        """Get assistant capabilities/permissions."""
        result = await self._request("GET", f"/assistants/{user_id}/capabilities")
        if result and isinstance(result, dict) and "detail" not in result:
            return result
        # Default capabilities if not found
        return {
            "can_spec_probation": False,
            "can_manage_events": False,
            "can_manage_streamers": False,
        }

    async def get_assistant_stats(self, user_id: int) -> Optional[Dict]:
        """Get assistant stats (uses assistant details endpoint)."""
        return await self._request("GET", f"/assistants/{user_id}")

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

    async def refresh_monitoring(self, force: bool = False) -> Optional[Dict]:
        """Request monitoring refresh."""
        return await self._request("POST", "/monitoring/refresh", data={"force": force})

    async def get_dashboard_stats(self) -> Optional[Dict]:
        """Get dashboard stats."""
        result = await self._request("GET", "/stats/dashboard")
        return result if isinstance(result, dict) else None

    async def get_dashboard_status(self) -> Optional[Dict]:
        """Backward-compatible alias for dashboard stats."""
        return await self.get_dashboard_stats()

    async def get_monitoring_status(self) -> Optional[Dict]:
        """Get monitoring view model for Discord display."""
        return await self._request("GET", "/monitoring/status")

    async def render_notification(
        self, event_type: str, streamer_id: int
    ) -> Optional[Dict]:
        """
        Get pre-rendered notification from API.
        Returns message text and component spec for Discord.
        """
        return await self._request(
            "GET",
            f"/notifications/render/{event_type}",
            params={"streamer_id": streamer_id},
        )

    async def get_leaderboard(self, limit: int = 10) -> Optional[Dict]:
        """Get PR leaderboard derived from assistants list."""
        assistants = await self.get_assistants()
        if not assistants:
            return {"items": []}

        sorted_items = sorted(
            assistants,
            key=lambda item: item.get("total_spec_seconds", 0),
            reverse=True,
        )
        return {"items": sorted_items[:limit]}

    async def create_event(
        self,
        name: str,
        description: str,
        required_pr_count: int,
        created_by: int,
        start_time: Optional[str] = None,
        pr_slots: Optional[int] = None,
        priority: int = 0,
    ) -> Optional[Dict]:
        """Create a new event."""
        data = {
            "name": name,
            "description": description,
            "required_pr_count": required_pr_count,
            "pr_slots": pr_slots if pr_slots is not None else required_pr_count,
            "priority": priority,
            "created_by": created_by,
        }
        if start_time:
            data["start_time"] = start_time

        return await self._request("POST", "/events", data=data)

    async def get_active_events(self) -> List[Dict]:
        """Get active events."""
        result = await self._request("GET", "/events/active")
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

    async def start_event(self, event_id: int) -> Optional[Dict]:
        """Start an event and migrate its reserved participants to active sessions."""
        return await self._request("POST", f"/events/{event_id}/start")

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

    async def get_event(self, event_id: int) -> Optional[Dict]:
        """Get a specific event by ID."""
        return await self._request("GET", f"/events/{event_id}")

    async def get_event_participants(self, event_id: int) -> List[Dict]:
        """Get event participants."""
        result = await self._request("GET", f"/events/{event_id}/participants")
        return result if isinstance(result, list) else []

    async def update_streamer_priority(self, streamer_id: int, priority: int) -> bool:
        """Update streamer priority."""
        result = await self._request(
            "PATCH", f"/streamers/{streamer_id}", data={"priority": priority}
        )
        return result is not None and "detail" not in result

    async def get_streamer_assigned_pr(self, streamer_id: int) -> Optional[int]:
        """Get the PR ID assigned to a streamer."""
        streamer = await self.get_streamer(streamer_id)
        if streamer:
            return streamer.get("assigned_pr_id")
        return None

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
        date: str,
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
                "date": date,
                "p0_seconds": p0,
                "p1_seconds": p1,
                "p2_seconds": p2,
                "p3_seconds": p3,
                "total_points": total_points,
            },
        )
        return result is not None and "detail" not in result

    async def create_manual_session(
        self,
        pr_id: int,
        target_type: str,
        target_id: Optional[int],
        target_name: Optional[str],
        started_at: str,
        ended_at: str,
        is_probation: bool = False,
        priority: int = 0,
        session_admin_comment: Optional[str] = None,
    ) -> bool:
        """Create a manual spec session."""
        result = await self._request(
            "POST",
            f"/assistants/{pr_id}/session",
            data={
                "target_type": target_type,
                "target_id": target_id,
                "target_name": target_name,
                "started_at": started_at,
                "ended_at": ended_at,
                "is_probation": is_probation,
                "priority": priority,
                "session_admin_comment": session_admin_comment,
            },
        )
        return result is not None and "detail" not in result

    async def get_pr_actions_channel(self) -> Optional[int]:
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

    async def set_notification_channel(self, channel_id: int) -> bool:
        """Set notification channel."""
        result = await self.update_guild_settings(notification_channel_id=channel_id)
        return result is not None

    async def set_monitoring_channel(self, channel_id: int) -> bool:
        """Set monitoring channel."""
        result = await self.update_guild_settings(monitoring_channel_id=channel_id)
        return result is not None

    async def set_pr_actions_channel(self, channel_id: int) -> bool:
        """Set PR actions channel."""
        result = await self.update_guild_settings(pr_actions_channel_id=channel_id)
        return result is not None
