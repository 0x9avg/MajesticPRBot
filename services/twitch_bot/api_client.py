"""
API Client for Twitch Bot.
HTTP client for communicating with the central API service.
"""

import logging
from typing import Dict, List, Optional, Any

import aiohttp


class APIError(Exception):
    """Custom exception for API errors."""
    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(f"API error {status}: {detail}")


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

    async def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        raise_on_error: bool = False,
    ) -> Optional[Dict]:
        session = await self._get_session()
        url = f"{self.base_url}/api{endpoint}"

        try:
            # Debug: check for non-serializable types
            if data:
                import json
                try:
                    json.dumps(data)
                except TypeError as e:
                    self.logger.error(f"Serialization Error: {e}")
                    for k, v in data.items():
                        self.logger.error(f"Field '{k}': type={type(v)}, value={str(v)[:100]}")
                    return None

            async with session.request(method, url, json=data, params=params) as resp:
                if resp.status == 204:
                    return {"status": "success"}
                result = await resp.json()
                
                # Unwrap API Envelope
                if isinstance(result, dict) and "status" in result and "data" in result:
                    if result["status"] == "success" or resp.status < 400:
                        return result["data"]
                    else:
                         self.logger.warning(f"API Error ({resp.status}): {result.get('message')}")
                         if raise_on_error:
                             raise APIError(resp.status, result.get("message", "Unknown error"))
                         return result # Return full envelope on error

                if resp.status >= 400:
                    detail = result.get("detail", str(result)) if isinstance(result, dict) else str(result)
                    self.logger.error(f"API error {resp.status}: {detail}")
                    if raise_on_error:
                        raise APIError(resp.status, detail)
                    return None
                return result
        except aiohttp.ClientError as e:
            self.logger.error(f"API request failed: {e}")
            if raise_on_error:
                raise
            return None
        except APIError:
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error: {e}")
            if raise_on_error:
                raise
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

    async def sync_streamers(self) -> Dict[str, Any]:
        """Trigger streamers sync (via refreshing monitoring for now)."""
        return await self.refresh_monitoring(force=True)

    async def refresh_monitoring(self, force: bool = False) -> Optional[Dict]:
        """Request monitoring refresh."""
        return await self._request("POST", "/monitoring/refresh", data={"force": force})

    async def create_streamer(
        self,
        streamer_id: int,
        streamer_name: str,
        is_online: bool = False,
        started_at: str = None,
        priority: int = 0,
        game_id: int = None,
        game_name: str = None,
        stream_title: str = None,
        stream_thumbnail_url: str = None,
        profile_image_url: str = None,
    ) -> Optional[Dict]:
        """Create streamer with full data (for Twitch bot use).

        Uses unified POST /streamers endpoint with full data mode.
        """
        data = {
            "streamer_id": streamer_id,
            "streamer_name": streamer_name,
            "is_online": is_online,
            "priority": priority,
        }
        if started_at:
            data["started_at"] = started_at
        if game_id is not None:
            data["game_id"] = game_id
        if game_name is not None:
            data["game_name"] = game_name
        if stream_title is not None:
            data["stream_title"] = stream_title
        if stream_thumbnail_url is not None:
            data["stream_thumbnail_url"] = stream_thumbnail_url
        if profile_image_url is not None:
            data["profile_image_url"] = profile_image_url

        return await self._request("POST", "/streamers", data=data)

    async def update_streamer_status(
        self,
        twitch_id: int,
        is_online: bool,
        started_at: str = None,
        game_id: int = None,
        game_name: str = None,
        stream_title: str = None,
        stream_thumbnail_url: str = None,
        profile_image_url: str = None,
    ) -> bool:
        """Update streamer online status using JSON body."""
        data = {"is_online": is_online}
        if started_at:
            data["started_at"] = started_at
        if game_id is not None:
            data["game_id"] = game_id
        if game_name is not None:
            data["game_name"] = game_name
        if stream_title is not None:
            data["stream_title"] = stream_title
        if stream_thumbnail_url is not None:
            data["stream_thumbnail_url"] = stream_thumbnail_url
        if profile_image_url is not None:
            data["profile_image_url"] = profile_image_url

        result = await self._request(
            "PATCH", f"/streamers/{twitch_id}/status", data=data
        )
        return result is not None

    # =========================================================================
    # Guild Settings API
    # =========================================================================

    async def get_guild_settings(self) -> Optional[Dict]:
        """Get guild settings."""
        return await self._request("GET", "/guild")

    async def get_notification_template(self, event_type: str) -> str:
        """Get notification template."""
        result = await self._request("GET", f"/guild/templates/{event_type}")
        return result.get("template", "") if result else ""

    # =========================================================================
    # Spec System API
    # =========================================================================

    async def unclaim_streamer(
        self, streamer_id: int, reason: str = "stream_end"
    ) -> Optional[Dict]:
        """Unclaim a streamer (auto-unclaim on stream end)."""
        return await self._request(
            "POST",
            "/spec/unclaim",
            data={
                "streamer_id": streamer_id,
                "reason": reason,
            },
        )




    async def sync_streamers_status_bulk(self, updates: List[Dict]) -> int:
        """
        Bulk update streamer statuses.

        Args:
            updates: List of dicts with streamer status info

        Returns:
            Number of streamers updated
        """
        if not updates:
            return 0

        result = await self._request("POST", "/streamers/sync_status", data=updates)
        if result:
            return result.get("updated_count", 0)
        return 0
