"""
Twitch Bot - полностью независимый микросервис.
Обрабатывает EventSub события и общается через API и RabbitMQ.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# Импортируем для аннотации типов в IDE
if TYPE_CHECKING:
    import logging

    from .api_client import APIClient

import asyncio
import logging
from typing import Optional

import twitchio
from config import Config
from twitchio import AutoClient, eventsub


class TwitchBot(AutoClient):
    """
    Twitch Bot микросервис.

    НЕ имеет прямых ссылок на:
    - database
    - discord_bot

    Использует только:
    - api_client для HTTP запросов к API
    """

    api: "APIClient"
    logger: "logging.Logger"

    def __init__(self, api_client: "APIClient", logger: "logging.Logger | None" = None):
        self.api = api_client
        self.logger = logger or Config.setup_logging("TwitchBot")
        self.subs: list[eventsub.SubscriptionPayload] = []

        # Enable twitchio logging
        twitchio.utils.setup_logging(level=logging.INFO)

        super().__init__(
            client_id=Config.twitch_client_id,
            client_secret=Config.twitch_client_secret,
            bot_id=Config.twitch_bot_id,
            subscriptions=self.subs,
            force_subscribe=True,
        )

    async def get_streamer_id(self, username: str) -> Optional[int]:
        """Get Twitch user ID by username."""
        try:
            user = await self.fetch_user(login=username)
            return user.id if user else None
        except Exception as e:
            self.logger.error(f"Error fetching user ID for {username}: {e}")
            return None

    async def get_stream_info(self, streamer_id: int) -> dict:
        """Get current stream info."""
        try:
            streams = await self.fetch_streams(user_ids=[streamer_id])
            is_online = len(streams) > 0

            if is_online:
                s = streams[0]
                return {
                    "is_online": True,
                    "title": s.title,
                    "started_at": s.started_at,
                    "game_id": s.game_id,
                    "game_name": s.game_name,
                    "thumbnail_url": s.thumbnail.url if s.thumbnail else None,
                }

            return {
                "is_online": False,
                "title": None,
                "started_at": None,
                "game_id": None,
                "game_name": None,
                "thumbnail_url": None,
            }
        except Exception as e:
            self.logger.error(f"Error fetching stream info: {e}")
            return {
                "is_online": False,
                "title": None,
                "started_at": None,
                "game_id": None,
                "game_name": None,
                "thumbnail_url": None,
            }

    async def sync_streamers(self):
        """Sync streamers from API and subscribe to EventSub."""
        try:
            await self.delete_all_eventsub_subscriptions()

            self.logger.info("Syncing streamers from API...")
            streamers = await self.api.list_all_streamers()
            self.logger.info(f"Found {len(streamers)} streamers")

            streamer_ids = [
                s["streamer_id"]
                for s in streamers
                if s["streamer_id"] != Config.twitch_bot_id
            ]

            # Batch fetch online status
            online_streams = {}
            for i in range(0, len(streamer_ids), 100):
                chunk = streamer_ids[i : i + 100]
                streams = await self.fetch_streams(user_ids=chunk)
                for stream in streams:
                    online_streams[str(stream.user.id)] = stream
                await asyncio.sleep(0)

            self.logger.info(f"Found {len(online_streams)} streamers online")

            # Batch fetch user profiles (for profile_image_url)
            user_profiles = {}
            for i in range(0, len(streamer_ids), 100):
                chunk = streamer_ids[i : i + 100]
                users = await self.fetch_users(ids=chunk)
                for user in users:
                    user_profiles[str(user.id)] = user
                await asyncio.sleep(0)

            self.logger.info(f"Fetched {len(user_profiles)} user profiles")

            new_subs = []

            # Update each streamer and prepare subscriptions
            for streamer in streamers:
                streamer_id = streamer["streamer_id"]

                if streamer_id == Config.twitch_bot_id:
                    continue

                # Add to subscription list
                new_subs.extend(
                    [
                        eventsub.StreamOnlineSubscription(
                            broadcaster_user_id=str(streamer_id)
                        ),
                        eventsub.StreamOfflineSubscription(
                            broadcaster_user_id=str(streamer_id)
                        ),
                        eventsub.ChannelUpdateSubscription(
                            broadcaster_user_id=str(streamer_id)
                        ),
                    ]
                )

            # Prepare bulk status updates
            status_updates = []
            for streamer in streamers:
                streamer_id = streamer["streamer_id"]
                if streamer_id == Config.twitch_bot_id:
                    continue

                stream = online_streams.get(str(streamer_id))
                user = user_profiles.get(str(streamer_id))
                is_online = stream is not None

                status_updates.append(
                    {
                        "streamer_id": streamer_id,
                        "is_online": is_online,
                        "started_at": (
                            str(stream.started_at)
                            if is_online and stream.started_at
                            else None
                        ),
                        "game_id": stream.game_id if is_online else None,
                        "game_name": stream.game_name if is_online else None,
                        "stream_title": stream.title if is_online else None,
                        "stream_thumbnail_url": (
                            stream.thumbnail.url
                            if is_online and stream.thumbnail
                            else None
                        ),
                        "profile_image_url": (
                            str(user.profile_image) if user and user.profile_image else None
                        ),
                    }
                )

            # Bulk update all statuses (API handles batching internally if needed)
            if status_updates:
                updated_count = await self.api.sync_streamers_status_bulk(
                    status_updates
                )
                self.logger.info(f"✓ Bulk updated {updated_count} streamer statuses")

            # Perform subscriptions in batches
            if new_subs:
                self.logger.info(f"Subscribing to {len(new_subs)} events...")

                # Batch size for EventSub subscriptions (safe limit)
                batch_size = 100
                for i in range(0, len(new_subs), batch_size):
                    batch = new_subs[i : i + batch_size]
                    try:
                        resp = await self.multi_subscribe(batch)
                        if resp and resp.errors:
                            self.logger.warning(
                                f"Subscription errors in batch {i//batch_size}: {resp.errors}"
                            )
                    except Exception as ex:
                        self.logger.error(
                            f"Subscription batch {i//batch_size} failed: {ex}"
                        )

                    # Small delay between batches
                    await asyncio.sleep(0.1)

            self.logger.info(f"✓ Synced {len(streamers)} streamers")

        except Exception as e:
            self.logger.error(f"Error syncing streamers: {e}", exc_info=True)
            raise

    async def event_ready(self) -> None:
        """Called when bot is ready."""
        self.logger.info(f"✓ Twitch bot ready as {self.user}")

        await self.sync_streamers()

    async def event_stream_online(self, payload: twitchio.StreamOnline) -> None:
        """Handle stream online event."""
        self.logger.info(f"🔴 Stream ONLINE: {payload.broadcaster.name}")

        try:
            stream = await self.get_stream_info(payload.broadcaster.id)

            # Update via API (API will publish the event)
            await self.api.update_streamer_status(
                payload.broadcaster.id,
                True,
                started_at=str(stream["started_at"]) if stream["started_at"] else None,
                game_id=stream["game_id"],
                game_name=stream["game_name"],
                stream_title=stream["title"],
                stream_thumbnail_url=stream["thumbnail_url"],
            )

            self.logger.debug(f"✓ Stream online processed: {payload.broadcaster.name}")

        except Exception as e:
            self.logger.error(f"Error handling stream online: {e}", exc_info=True)

    async def event_stream_offline(self, payload: twitchio.StreamOffline) -> None:
        """Handle stream offline event."""
        self.logger.info(f"⚫ Stream OFFLINE: {payload.broadcaster.name}")

        try:
            # Check if claimed and auto-unclaim via API (API will emit spec.unclaimed)
            streamer = await self.api.get_streamer(payload.broadcaster.id)

            if streamer and streamer.get("assigned_pr_id"):
                await self.api.unclaim_streamer(payload.broadcaster.id, "stream_end")

            # Update status via API (API will publish the offline event)
            await self.api.update_streamer_status(
                payload.broadcaster.id,
                False,
                started_at=None,
                game_id=None,
                game_name=None,
                stream_title=None,
                stream_thumbnail_url=None,
            )

            self.logger.debug(f"✓ Stream offline processed: {payload.broadcaster.name}")

        except Exception as e:
            self.logger.error(f"Error handling stream offline: {e}", exc_info=True)

    async def event_channel_update(self, payload: twitchio.ChannelUpdate) -> None:
        """Handle channel update (category change)."""
        try:
            self.logger.debug(f"Channel update: {payload.broadcaster.name}")

            # 1. Get current data from DB
            streamer_db = await self.api.get_streamer(payload.broadcaster.id)
            if not streamer_db:
                return  # Not tracking this streamer

            # 2. Verify Online Status via Twitch API & Get Metadata (Thumbnail, StartedAt)
            stream_info = await self.get_stream_info(payload.broadcaster.id)

            # If Twitch API returns offline but we received a ChannelUpdate event,
            # it's likely a transient API issue. Trust the DB state and payload.
            if not stream_info or not stream_info.get("is_online"):
                # Check DB: if streamer was online according to our records, proceed with update
                if streamer_db.get("is_online"):
                    self.logger.warning(
                        f"Twitch API returned offline for {payload.broadcaster.name} during ChannelUpdate, "
                        f"but DB says online. Proceeding with cached/payload data."
                    )
                    # Use existing DB data for fields not in payload
                    stream_info = {
                        "is_online": True,
                        "started_at": streamer_db.get("started_at"),
                        "thumbnail_url": streamer_db.get("stream_thumbnail_url"),
                    }
                else:
                    # Stream is genuinely offline
                    return

            old_game_id = (
                str(streamer_db.get("game_id")) if streamer_db.get("game_id") else None
            )
            new_game_id = str(payload.category_id) if payload.category_id else None

            # Skip if no actual change (prevents duplicate events)
            if old_game_id == new_game_id:
                return

            # Check for GTA category changes BEFORE updating
            switched_from_gta = (
                old_game_id == Config.gta5_game_id
                and new_game_id != Config.gta5_game_id
            )

            # Auto-unclaim on leaving GTA (API will emit spec.unclaimed)
            if switched_from_gta and streamer_db.get("assigned_pr_id"):
                await self.api.unclaim_streamer(
                    payload.broadcaster.id, "category_change"
                )

            # Update via API (API will publish the category change event)
            # Use Payload for Game/Title (Event Source) and StreamInfo for Thumbnail/Time (Live Source)
            # Safely convert category_id to int
            game_id_int = None
            if payload.category_id and str(payload.category_id).isdigit():
                game_id_int = int(payload.category_id)

            await self.api.update_streamer_status(
                payload.broadcaster.id,
                True,
                started_at=(
                    str(stream_info["started_at"])
                    if stream_info.get("started_at")
                    else None
                ),
                game_id=game_id_int,
                game_name=payload.category_name,
                stream_title=payload.title,
                stream_thumbnail_url=stream_info.get("thumbnail_url"),
            )

            switched_to_gta = new_game_id == Config.gta5_game_id and (
                old_game_id is None or old_game_id != Config.gta5_game_id
            )
            if switched_to_gta or switched_from_gta:
                self.logger.info(
                    f"🎮 Category change: {payload.broadcaster.name} {'→' if switched_to_gta else '←'} GTA 5"
                )

        except Exception as e:
            self.logger.error(f"Error handling channel update: {e}", exc_info=True)

    async def add_notification(self, streamer_id: int) -> None:
        """Add EventSub subscriptions for a streamer."""
        if streamer_id == Config.twitch_bot_id:
            return

        try:
            subs = [
                eventsub.StreamOnlineSubscription(broadcaster_user_id=str(streamer_id)),
                eventsub.StreamOfflineSubscription(
                    broadcaster_user_id=str(streamer_id)
                ),
                eventsub.ChannelUpdateSubscription(
                    broadcaster_user_id=str(streamer_id)
                ),
            ]

            resp = await self.multi_subscribe(subs)
            if resp.errors:
                self.logger.warning(
                    f"Failed to subscribe for {streamer_id}: {resp.errors}"
                )
            else:
                self.logger.debug(f"✓ Subscribed to events for {streamer_id}")
        except Exception as e:
            self.logger.error(f"Error subscribing: {e}")

    async def remove_subscription(self, streamer_id: int) -> None:
        """Remove EventSub subscriptions for a streamer."""
        try:
            subs_response = await self.fetch_eventsub_subscriptions(
                user_id=str(streamer_id)
            )
            async for sub in subs_response.subscriptions:
                await self.delete_eventsub_subscription(sub.id)
                self.logger.debug(f"Deleted subscription {sub.id}")
        except Exception as e:
            self.logger.error(f"Error removing subscription: {e}")
