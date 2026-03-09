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
from datetime import datetime, timezone, timedelta
from typing import Optional

# Moscow timezone (UTC+3)
MSK = timezone(timedelta(hours=3))

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
        self._start_time = datetime.now(timezone.utc)
        self._heartbeat_task: asyncio.Task | None = None
        self._sync_lock = asyncio.Lock()
        self._last_sync_started_at: datetime | None = None
        self._last_sync_completed_at: datetime | None = None
        self._last_sync_status = "starting"
        self._last_sync_error: str | None = None
        self._last_sync_duration_seconds: float | None = None
        self._last_synced_streamers = 0
        self._last_online_streamers = 0
        self._last_subscription_targets = 0

        # Enable twitchio logging
        twitchio.utils.setup_logging(level=logging.INFO)

        super().__init__(
            client_id=Config.twitch_client_id,
            client_secret=Config.twitch_client_secret,
            bot_id=Config.twitch_bot_id,
            subscriptions=self.subs,
            force_subscribe=True,
        )

    async def load_tokens(self, path: str | None = None) -> None:
        """Persist TwitchIO tokens in a stable path suitable for containers."""
        await super().load_tokens(path or Config.twitch_tokens_file)

    async def save_tokens(self, path: str | None = None) -> None:
        """Persist TwitchIO tokens in a stable path suitable for containers."""
        await super().save_tokens(path or Config.twitch_tokens_file)

    @staticmethod
    def _convert_twitch_time_to_msk(time_val) -> Optional[str]:
        """Convert Twitch UTC time (string or datetime) to MSK string."""
        if not time_val:
            return None
        try:
            if isinstance(time_val, str):
                dt = datetime.fromisoformat(time_val.replace("Z", "+00:00"))
            else:
                dt = time_val
            
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            
            # Convert to MSK
            dt_msk = dt.astimezone(MSK)
            return dt_msk.isoformat()
        except Exception:
            return str(time_val)

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

    def _service_status_details(self) -> dict[str, object]:
        uptime_seconds = int(
            max(
                0,
                (datetime.now(timezone.utc) - self._start_time).total_seconds(),
            )
        )
        return {
            "ready": self.user is not None,
            "uptime_seconds": uptime_seconds,
            "last_sync_status": self._last_sync_status,
            "last_sync_started_at": self._convert_twitch_time_to_msk(self._last_sync_started_at)
            if self._last_sync_started_at
            else None,
            "last_sync_completed_at": self._convert_twitch_time_to_msk(
                self._last_sync_completed_at
            )
            if self._last_sync_completed_at
            else None,
            "last_sync_duration_seconds": self._last_sync_duration_seconds,
            "last_sync_error": self._last_sync_error,
            "tracked_streamers": self._last_synced_streamers,
            "online_streamers": self._last_online_streamers,
            "subscription_targets": self._last_subscription_targets,
            "sync_in_progress": self._sync_lock.locked(),
        }

    async def report_service_status(self, status: str) -> None:
        try:
            await self.api.report_service_status(
                status=status,
                details=self._service_status_details(),
            )
        except Exception as e:
            self.logger.debug(f"Service status report failed: {e}")

    async def _heartbeat_loop(self) -> None:
        while True:
            await self.report_service_status(
                "syncing" if self._sync_lock.locked() else "online"
            )
            await asyncio.sleep(30)

    async def sync_streamers(self, reason: str = "manual") -> dict[str, int]:
        """Sync streamers from API and subscribe to EventSub."""
        if self._sync_lock.locked():
            self.logger.info(
                "Full Twitch sync already in progress, skipping duplicate request"
            )
            return {
                "streamers": self._last_synced_streamers,
                "online": self._last_online_streamers,
            }

        async with self._sync_lock:
            sync_started_at = datetime.now(timezone.utc)
            self._last_sync_started_at = sync_started_at
            self._last_sync_status = "syncing"
            self._last_sync_error = None
            await self.report_service_status("syncing")

            try:
                self.logger.debug("Deleting old EventSub subscriptions...")
                await self.delete_all_eventsub_subscriptions()

                self.logger.info(f"Syncing streamers from API (reason={reason})...")
                streamers = await self.api.list_all_streamers(include_assignments=True)
                self.logger.info(f"Found {len(streamers)} streamers")

                streamer_ids = [
                    s["streamer_id"]
                    for s in streamers
                    if s["streamer_id"] != Config.twitch_bot_id
                ]

                online_streams = {}
                for i in range(0, len(streamer_ids), 100):
                    chunk = streamer_ids[i : i + 100]
                    streams = await self.fetch_streams(user_ids=chunk)
                    for stream in streams:
                        online_streams[str(stream.user.id)] = stream
                    await asyncio.sleep(0)

                self.logger.info(f"Found {len(online_streams)} streamers online")

                user_profiles = {}
                for i in range(0, len(streamer_ids), 100):
                    chunk = streamer_ids[i : i + 100]
                    users = await self.fetch_users(ids=chunk)
                    for user in users:
                        user_profiles[str(user.id)] = user
                    await asyncio.sleep(0)

                self.logger.info(f"Fetched {len(user_profiles)} user profiles")

                new_subs = []
                bulk_status_updates = []
                pipeline_updates = []
                stale_offline_to_unclaim = []
                stale_nongta_to_unclaim = []

                for streamer in streamers:
                    streamer_id = streamer["streamer_id"]

                    if streamer_id == Config.twitch_bot_id:
                        continue

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

                for streamer in streamers:
                    streamer_id = streamer["streamer_id"]
                    if streamer_id == Config.twitch_bot_id:
                        continue

                    stream = online_streams.get(str(streamer_id))
                    user = user_profiles.get(str(streamer_id))
                    is_online = stream is not None
                    old_is_online = bool(streamer.get("is_online"))
                    old_game_id = (
                        str(streamer.get("game_id"))
                        if streamer.get("game_id") is not None
                        else None
                    )
                    new_game_id = (
                        str(stream.game_id)
                        if is_online and getattr(stream, "game_id", None) is not None
                        else None
                    )
                    assignments = streamer.get("assignments", []) or []

                    update_payload = {
                        "streamer_id": streamer_id,
                        "is_online": is_online,
                        "started_at": (
                            self._convert_twitch_time_to_msk(stream.started_at)
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
                            str(user.profile_image)
                            if user and user.profile_image
                            else None
                        ),
                    }

                    state_changed = old_is_online != is_online
                    if is_online and old_game_id != new_game_id:
                        state_changed = True

                    if state_changed:
                        pipeline_updates.append(update_payload)
                    else:
                        bulk_status_updates.append(update_payload)

                        if assignments:
                            if not is_online:
                                stale_offline_to_unclaim.append(streamer_id)
                            elif new_game_id and new_game_id != Config.gta5_game_id:
                                stale_nongta_to_unclaim.append(streamer_id)

                if pipeline_updates:
                    self.logger.info(
                        f"Applying {len(pipeline_updates)} stateful streamer updates..."
                    )
                    for update in pipeline_updates:
                        try:
                            await self.api.update_streamer_status(
                                update["streamer_id"],
                                update["is_online"],
                                started_at=update.get("started_at"),
                                game_id=update.get("game_id"),
                                game_name=update.get("game_name"),
                                stream_title=update.get("stream_title"),
                                stream_thumbnail_url=update.get("stream_thumbnail_url"),
                                profile_image_url=update.get("profile_image_url"),
                            )
                        except Exception as ex:
                            self.logger.error(
                                f"Failed to apply stateful sync update for streamer {update['streamer_id']}: {ex}"
                            )

                if bulk_status_updates:
                    updated_count = await self.api.sync_streamers_status_bulk(
                        bulk_status_updates
                    )
                    self.logger.info(f"✓ Bulk updated {updated_count} streamer statuses")

                stale_unclaims = [
                    (streamer_id, "stream_end")
                    for streamer_id in stale_offline_to_unclaim
                ] + [
                    (streamer_id, "category_change")
                    for streamer_id in stale_nongta_to_unclaim
                ]

                if stale_unclaims:
                    self.logger.info(
                        f"Recovering {len(stale_unclaims)} stale streamer assignments..."
                    )
                    for streamer_id, reason in stale_unclaims:
                        try:
                            await self.api.unclaim_streamer(streamer_id, reason)
                            await asyncio.sleep(0.1)
                        except Exception as ex:
                            self.logger.error(
                                f"Failed to recover stale assignment for streamer {streamer_id}: {ex}"
                            )
                    self.logger.info("✓ Recovered stale streamer assignments")

                if new_subs:
                    self.logger.info(f"Subscribing to {len(new_subs)} events...")
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
                        await asyncio.sleep(0.1)

                self._last_synced_streamers = len(streamers)
                self._last_online_streamers = len(online_streams)
                self._last_subscription_targets = len(new_subs)
                self._last_sync_completed_at = datetime.now(timezone.utc)
                self._last_sync_duration_seconds = round(
                    (self._last_sync_completed_at - sync_started_at).total_seconds(), 2
                )
                self._last_sync_status = "online"

                self.logger.info(f"✓ Synced {len(streamers)} streamers")
                await self.report_service_status("online")
                return {
                    "streamers": len(streamers),
                    "online": len(online_streams),
                }
            except Exception as e:
                self._last_sync_completed_at = datetime.now(timezone.utc)
                self._last_sync_duration_seconds = round(
                    (self._last_sync_completed_at - sync_started_at).total_seconds(), 2
                )
                self._last_sync_status = "error"
                self._last_sync_error = str(e)
                await self.report_service_status("error")
                self.logger.error(f"Error syncing streamers: {e}", exc_info=True)
                raise

    async def event_ready(self) -> None:
        """Called when bot is ready."""
        await self.sync_streamers(reason="startup")

        self.logger.info(f"✓ Twitch bot ready as {self.user}")
        await self.report_service_status("online")
        if not self._heartbeat_task or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def close(self) -> None:
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        self._heartbeat_task = None
        await self.report_service_status("stopping")
        await super().close()

    async def event_stream_online(self, payload: twitchio.StreamOnline) -> None:
        """Handle stream online event."""
        self.logger.info(f"🔴 Stream ONLINE: {payload.broadcaster.name}")

        try:
            # Retry logic: Twitch API often lags behind EventSub by a few seconds
            stream = None
            max_retries = 5
            retry_delay = 1.0  # seconds

            for attempt in range(max_retries):
                stream = await self.get_stream_info(payload.broadcaster.id)

                if stream.get("is_online"):
                    if attempt > 0:
                        self.logger.debug(
                            f"Stream info retrieved on attempt {attempt + 1} for {payload.broadcaster.name}"
                        )
                    break

                if attempt < max_retries - 1:
                    self.logger.debug(
                        f"API returned offline for {payload.broadcaster.name}, "
                        f"retrying in {retry_delay}s (attempt {attempt + 1}/{max_retries})"
                    )
                    await asyncio.sleep(retry_delay)

            # If still no data after retries, log warning but proceed with what we have
            if not stream.get("is_online"):
                self.logger.warning(
                    f"API still returns offline for {payload.broadcaster.name} after {max_retries} retries. "
                    f"Proceeding with is_online=True but empty metadata."
                )

            self.logger.debug(
                f"EventStreamOnline for {payload.broadcaster.name}. "
                f"Sending to API. Thumbnail/Title available: {bool(stream.get('title'))}"
            )
            # Update via API (API will publish the event)
            await self.api.update_streamer_status(
                payload.broadcaster.id,
                True,
                started_at=(
                    self._convert_twitch_time_to_msk(stream.get("started_at")) if stream.get("started_at") else None
                ),
                game_id=stream.get("game_id"),
                game_name=stream.get("game_name"),
                stream_title=stream.get("title"),
                stream_thumbnail_url=stream.get("thumbnail_url"),
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

            self.logger.debug(
                f"EventStreamOffline for {payload.broadcaster.name}. "
                f"Streamer had assignment={bool(streamer and streamer.get('assigned_pr_id'))}. "
                f"Sending offline status to API."
            )
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

            self.logger.debug(
                f"ChannelUpdate for {payload.broadcaster.name}:\n"
                f"  BEFORE [DB]: GameID={old_game_id}, Title='{streamer_db.get('stream_title')}'\n"
                f"  AFTER [Event]: GameID={new_game_id}, Title='{payload.title}'\n"
                f"  Sending update to API."
            )
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
