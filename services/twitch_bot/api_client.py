"""
API Client for Twitch Bot.
HTTP client for communicating with the central API service.
"""

import aiohttp
from typing import Optional, List, Dict, Any
import logging


class APIClient:
    """HTTP client for API communication."""
    
    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        timeout: int = 30,
        logger: Optional[logging.Logger] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.logger = logger or logging.getLogger(__name__)
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=self.timeout,
                headers={"Content-Type": "application/json"},
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
    ) -> Optional[Dict]:
        session = await self._get_session()
        url = f"{self.base_url}/api{endpoint}"
        
        try:
            async with session.request(method, url, json=data, params=params) as resp:
                if resp.status == 204:
                    return {"status": "success"}
                result = await resp.json()
                if resp.status >= 400:
                    self.logger.error(f"API error {resp.status}: {result}")
                    return None
                return result
        except aiohttp.ClientError as e:
            self.logger.error(f"API request failed: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error: {e}")
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
    
    async def create_streamer_full(
        self,
        streamer_id: int,
        streamer_name: str,
        is_online: bool = False,
        started_at: str = None,
        priority: int = 0,
        is_paid: bool = False,
        added_by_id: int = 0,
        game_id: int = None,
        game_name: str = None,
        stream_title: str = None,
        stream_thumbnail_url: str = None,
    ) -> Optional[Dict]:
        """Create streamer with full data (for Twitch bot use)."""
        params = {
            "streamer_id": str(streamer_id),
            "streamer_name": streamer_name,
            "is_online": str(is_online).lower(),
            "priority": str(priority),
            "is_paid": str(is_paid).lower(),
            "added_by_id": str(added_by_id),
        }
        if started_at:
            params["started_at"] = str(started_at)
        if game_id:
            params["game_id"] = str(game_id)
        if game_name:
            params["game_name"] = game_name
        if stream_title:
            params["stream_title"] = stream_title
        if stream_thumbnail_url:
            params["stream_thumbnail_url"] = stream_thumbnail_url
        
        return await self._request("POST", "/streamers/full", params=params)
    
    async def update_streamer_status(
        self,
        twitch_id: int,
        is_online: bool,
        started_at: str = None,
        game_id: int = None,
        game_name: str = None,
        stream_title: str = None,
        stream_thumbnail_url: str = None,
    ) -> bool:
        """Update streamer online status."""
        # Convert boolean to string for aiohttp params
        params = {"is_online": str(is_online).lower()}
        if started_at:
            params["started_at"] = str(started_at)
        if game_id is not None:
            params["game_id"] = str(game_id)
        if game_name is not None:
            params["game_name"] = game_name
        if stream_title is not None:
            params["stream_title"] = stream_title
        if stream_thumbnail_url is not None:
            params["stream_thumbnail_url"] = stream_thumbnail_url
        
        result = await self._request("PATCH", f"/streamers/{twitch_id}/status", params=params)
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
    
    async def unclaim_streamer(self, streamer_id: int, reason: str = "stream_end") -> Optional[Dict]:
        """Unclaim a streamer (auto-unclaim on stream end)."""
        return await self._request("POST", "/spec/unclaim", data={
            "streamer_id": streamer_id,
            "reason": reason,
        })
    
    async def get_available_gta_streamers(self) -> List[Dict]:
        """Get available GTA streamers for claiming."""
        result = await self._request("GET", "/streamers/available-gta")
        return result if isinstance(result, list) else []
