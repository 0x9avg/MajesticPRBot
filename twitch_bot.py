"""Twitch bot module for PRMajesticBot.
Handles Twitch EventSub subscriptions and stream events.
"""

import twitchio
from twitchio import eventsub, AutoClient
import logging
import asyncio

from config import Config

from utils import (
    create_streamers_component,
    create_notification_component,
    format_notification_template,
)


class TwitchBot(AutoClient):
    def __init__(self, client_id, client_secret, bot_id, logger, database) -> None:
        self.subs: list[eventsub.SubscriptionPayload] = []
        self.logger = logger
        self.CLIENT_ID = client_id
        self.CLIENT_SECRET = client_secret
        self.BOT_ID = bot_id
        self.database = database
        self._is_ready_ = False

        twitchio.utils.setup_logging(level=logging.INFO)

        super().__init__(
            client_id=self.CLIENT_ID,
            client_secret=self.CLIENT_SECRET,
            bot_id=self.BOT_ID,
            subscriptions=self.subs,
            force_subscribe=True,
        )

    async def get_streamer_id(self, username: str) -> int:
        """Get Twitch user ID by username."""
        try:
            self.logger.debug(f"Fetching user ID for: {username}")
            user = await self.fetch_user(login=username)
            if user:
                self.logger.debug(f"Found user {username} with ID: {user.id}")
            else:
                self.logger.warning(f"User not found: {username}")
            return user.id if user else None
        except Exception as e:
            self.logger.error(
                f"Error fetching user ID for {username}: {e}", exc_info=True
            )
            return None

    async def sync_streamers(self):
        """Sync all streamers from database and subscribe to their events."""
        try:
            self.logger.debug("Syncing streamers from database...")
            streamers = await self.database.list_all_streamers()
            self.logger.debug(f"Found {len(streamers)} streamers in database")

            # Collect all streamer IDs (excluding bot account)
            streamer_ids = [
                s["streamer_id"] for s in streamers if s["streamer_id"] != self.BOT_ID
            ]

            # Batch fetch all streams (API supports up to 100 IDs per request)
            self.logger.debug(
                f"Batch fetching stream status for {len(streamer_ids)} streamers..."
            )

            # Split into chunks of 100 (Twitch API limit)
            online_streams = {}
            for i in range(0, len(streamer_ids), 100):
                chunk = streamer_ids[i : i + 100]
                streams = await self.fetch_streams(user_ids=chunk)
                for stream in streams:
                    online_streams[str(stream.user.id)] = stream
                # Yield control between chunks
                if i + 100 < len(streamer_ids):
                    await asyncio.sleep(0)

            self.logger.debug(f"Found {len(online_streams)} streamers currently online")

            for streamer in streamers:
                streamer_id = streamer["streamer_id"]

                if streamer_id == self.BOT_ID:
                    self.logger.debug(f"Skipping bot account (ID: {self.BOT_ID})")
                    continue

                self.logger.debug(
                    f"Adding subscriptions for {streamer['streamer_name']} (ID: {streamer_id})"
                )
                self.subs.extend(
                    [
                        eventsub.StreamOnlineSubscription(
                            broadcaster_user_id=streamer_id
                        ),
                        eventsub.StreamOfflineSubscription(
                            broadcaster_user_id=streamer_id
                        ),
                        eventsub.ChannelUpdateSubscription(
                            broadcaster_user_id=streamer_id
                        ),
                    ]
                )

                # Get stream data from batch result
                stream = online_streams.get(str(streamer_id))
                is_online = stream is not None

                if is_online:
                    self.logger.debug(
                        f"Streamer {streamer_id} is online: '{stream.title}'"
                    )
                else:
                    self.logger.debug(f"Streamer {streamer_id} is offline")

                await self.database.update_streamer_status(
                    streamer_id,
                    is_online,
                    started_at=stream.started_at if is_online else None,
                    game_id=stream.game_id if is_online else None,
                    game_name=stream.game_name if is_online else None,
                    stream_title=stream.title if is_online else None,
                    stream_thumbnail_url=(
                        stream.thumbnail.url if is_online and stream.thumbnail else None
                    ),
                )

                # Yield control to event loop to prevent blocking Discord commands
                await asyncio.sleep(0)

            self.logger.debug(
                f"✓ Synced {len(streamers)} streamers with {len(self.subs)} subscriptions"
            )
        except Exception as e:
            self.logger.error(f"Error syncing streamers: {e}", exc_info=True)
            raise

    async def update_monitoring_messages(self, guild_id: int = None) -> None:
        """Update monitoring message(s) with current online streamers.

        Args:
            guild_id: If specified, update only for this guild.
                      If None, update for all guilds with monitoring configured.
        """

        try:
            if guild_id:
                # Update for specific guild
                guild_settings = await self.database.get_guild(guild_id)
                if not guild_settings:
                    return
                guilds_to_update = [guild_settings]
            else:
                # Update for all guilds with monitoring
                guilds_to_update = await self.database.list_guilds_with_monitoring()

            for guild_settings in guilds_to_update:
                try:
                    monitoring_channel_id = guild_settings.get("monitoring_channel_id")
                    monitoring_message_id = guild_settings.get("monitoring_message_id")
                    current_guild_id = guild_settings.get("guild_id")

                    # Skip if no monitoring channel configured
                    if not monitoring_channel_id:
                        continue

                    # Get channel
                    channel = self.discord_bot.get_channel(monitoring_channel_id)
                    if not channel:
                        self.logger.warning(
                            f"Monitoring channel {monitoring_channel_id} not found for guild {current_guild_id}"
                        )
                        continue

                    # Get streamer data for this guild (needed for both update and create)
                    streamers = await self.database.list_guild_streamers(
                        current_guild_id
                    )
                    online_streamers = []
                    gta_count = 0

                    for streamer in streamers:
                        if streamer.get("is_online"):
                            online_streamers.append(streamer)
                            if str(streamer.get("game_id")) == Config.GTA5_GAME_ID:
                                gta_count += 1

                    # Create container
                    container = create_streamers_component(
                        online_streamers, len(streamers), gta_count
                    )

                    # Try to get existing message or create new one
                    message = None
                    if monitoring_message_id:
                        try:
                            message = await channel.fetch_message(monitoring_message_id)
                        except Exception as e:
                            self.logger.warning(
                                f"Monitoring message {monitoring_message_id} not found for guild {current_guild_id}: {e}. "
                                "Will create a new one."
                            )
                            message = None

                    if message:
                        # Update existing message
                        await message.edit(components=container)
                        self.logger.debug(
                            f"✓ Updated monitoring message for guild {current_guild_id}"
                        )
                    else:
                        # Create new monitoring message
                        new_message = await channel.send(components=container)
                        
                        # Save new message ID to database
                        await self.database.create_or_update_guild(
                            guild_id=current_guild_id,
                            monitoring_message_id=new_message.id
                        )
                        self.logger.info(
                            f"✓ Created new monitoring message {new_message.id} for guild {current_guild_id}"
                        )

                except Exception as e:
                    self.logger.error(
                        f"Error updating monitoring for guild {guild_settings.get('guild_id')}: {e}",
                        exc_info=True,
                    )

        except Exception as e:
            self.logger.error(
                f"Error in update_monitoring_messages: {e}", exc_info=True
            )

    async def get_stream_info(self, streamer_id: int):
        """Get current stream information for a streamer."""
        try:
            self.logger.debug(f"Fetching stream info for streamer ID: {streamer_id}")
            streams = await self.fetch_streams(user_ids=[streamer_id])
            is_online = len(streams) > 0

            if is_online:
                self.logger.debug(
                    f"Streamer {streamer_id} is online: '{streams[0].title}'"
                )
            else:
                self.logger.debug(f"Streamer {streamer_id} is offline")

            return {
                "id": streamer_id,
                "is_online": is_online,
                "user": streams[0].user if is_online else None,
                "title": streams[0].title if is_online else None,
                "started_at": streams[0].started_at if is_online else None,
                "game_id": streams[0].game_id if is_online else None,
                "game_name": streams[0].game_name if is_online else None,
                "viewer_count": streams[0].viewer_count if is_online else None,
                "thumbnail_url": (
                    streams[0].thumbnail.url
                    if is_online and streams[0].thumbnail
                    else None
                ),
            }
        except Exception as e:
            self.logger.error(
                f"Error fetching stream info for {streamer_id}: {e}", exc_info=True
            )
            return {
                "id": streamer_id,
                "is_online": False,
                "user": None,
                "title": None,
                "started_at": None,
                "game_id": None,
                "game_name": None,
                "viewer_count": None,
                "thumbnail_url": None,
            }

    async def event_ready(self) -> None:
        self.logger.info("Successfully logged in as: %s", self.user)

        await self.sync_streamers()

        # Update monitoring messages after syncing all streamers
        await self.update_monitoring_messages()

        self._is_ready_ = True

    async def event_stream_online(self, payload: twitchio.StreamOnline) -> None:
        """Handle stream online event."""
        self.logger.info(
            f"🔴 Stream ONLINE: {payload.broadcaster.name} (ID: {payload.broadcaster.id})"
        )

        try:
            # Get stream info first
            stream = await self.get_stream_info(payload.broadcaster.id)

            # Update database first
            await self.database.update_streamer_status(
                payload.broadcaster.id,
                True,
                started_at=stream["started_at"],
                game_id=stream["game_id"] if stream["game_id"] else None,
                game_name=stream["game_name"] if stream["game_name"] else None,
                stream_title=stream["title"],
                stream_thumbnail_url=stream["thumbnail_url"],
            )

            guilds_ids = await self.database.list_streamer_guilds(
                payload.broadcaster.id
            )
            self.logger.debug(f"Notifying {len(guilds_ids)} guilds about stream start")

            for guild_id in guilds_ids:
                guild_settings = await self.database.get_guild(guild_id)
                notification_channel_id = (
                    guild_settings["notification_channel_id"]
                    if guild_settings
                    else None
                )
                if notification_channel_id is None:
                    self.logger.warning(
                        f"No notification channel set for guild {guild_id}"
                    )
                    continue

                channel = self.discord_bot.get_channel(notification_channel_id)
                if channel is None:
                    self.logger.warning(
                        f"Channel {notification_channel_id} not found for guild {guild_id}"
                    )
                    continue

                # Get template and format message
                template = await self.database.get_notification_template(
                    guild_id, "stream_online"
                )
                message = format_notification_template(
                    template,
                    streamer_name=payload.broadcaster.name,
                    stream_title=stream["title"] or "",
                    game_name=stream["game_name"] or "",
                )

                # Create notification components (TextDisplay + Container)
                components = create_notification_component(
                    message=message,
                    streamer_name=payload.broadcaster.name,
                    stream_title=stream["title"] or "",
                    game_name=stream["game_name"] or "",
                    thumbnail_url=stream["thumbnail_url"] or "",
                )

                await channel.send(components=components)
                self.logger.debug(f"Sent notification to guild {guild_id}")

            self.logger.debug(
                f"✓ Stream online event processed for {payload.broadcaster.name}"
            )

            # Update monitoring messages for affected guilds
            await self.update_monitoring_messages()
        except Exception as e:
            self.logger.error(
                f"Error handling stream online event for {payload.broadcaster.name}: {e}",
                exc_info=True,
            )

    async def event_stream_offline(self, payload: twitchio.StreamOffline) -> None:
        """Handle stream offline event."""
        try:
            self.logger.info("[%s] ended a stream!", payload.broadcaster)

            guilds_ids = await self.database.list_streamer_guilds(
                payload.broadcaster.id
            )

            for guild_id in guilds_ids:
                guild_settings = await self.database.get_guild(guild_id)
                notification_channel_id = (
                    guild_settings["notification_channel_id"]
                    if guild_settings
                    else None
                )
                if notification_channel_id is None:
                    continue

                channel = self.discord_bot.get_channel(notification_channel_id)
                if channel is None:
                    continue

                # Get template and format message
                template = await self.database.get_notification_template(
                    guild_id, "stream_offline"
                )
                message = format_notification_template(
                    template,
                    streamer_name=payload.broadcaster.name,
                )

                await channel.send(content=message)

            await self.database.update_streamer_status(
                payload.broadcaster.id,
                False,
                started_at=None,
                game_id=None,
                game_name=None,
                stream_title=None,
                stream_thumbnail_url=None,
            )

            # Update monitoring messages for affected guilds
            await self.update_monitoring_messages()
        except Exception as e:
            self.logger.error(
                f"Error handling stream offline event for {payload.broadcaster.name}: {e}",
                exc_info=True,
            )

    async def _send_category_notification(self, streamer_id: int, message: str) -> None:
        """Send notification to all guilds subscribed to a streamer.

        Args:
            streamer_id: Twitch user ID
            message: Message to send to notification channels
        """
        guilds_ids = await self.database.list_streamer_guilds(streamer_id)

        for guild_id in guilds_ids:
            guild_settings = await self.database.get_guild(guild_id)
            notification_channel_id = (
                guild_settings["notification_channel_id"] if guild_settings else None
            )
            if notification_channel_id is None:
                continue

            channel = self.discord_bot.get_channel(notification_channel_id)
            if channel is None:
                continue

            await channel.send(message)

    async def event_channel_update(self, payload: twitchio.ChannelUpdate) -> None:
        """Handle channel update events (title/category changes)."""
        try:
            self.logger.debug(
                "Handling channel update for [%s]", payload.broadcaster.name
            )

            # Get streamer data from database
            streamer_data_db = await self.database.get_streamer(payload.broadcaster.id)

            # Skip if streamer is offline - no need to update
            if not streamer_data_db or not streamer_data_db.get("is_online"):
                self.logger.debug(
                    f"Skipping channel update for {payload.broadcaster.name} - streamer is offline"
                )
                return

            # Get game info from payload (fresh data from EventSub)
            # Convert empty strings to None for MySQL compatibility
            new_game_id = payload.category_id if payload.category_id else None
            new_game_name = payload.category_name if payload.category_name else None
            new_title = payload.title

            old_game_id = streamer_data_db.get("game_id")

            new_game_str = str(new_game_id) if new_game_id else None
            old_game_str = str(old_game_id) if old_game_id else None

            # Always update database with fresh data
            await self.database.update_streamer_status(
                payload.broadcaster.id,
                streamer_data_db["is_online"],  # Keep existing online status
                started_at=streamer_data_db.get(
                    "started_at"
                ),  # Keep existing start time
                game_id=new_game_id,  # Fresh from payload
                game_name=new_game_name,  # Fresh from payload
                stream_title=new_title,  # Fresh from payload
                stream_thumbnail_url=streamer_data_db.get(
                    "stream_thumbnail_url"
                ),  # Keep existing thumbnail
            )

            # Check for GTA 5 category changes - send notifications only for these
            switched_to_gta = (
                new_game_str == Config.GTA5_GAME_ID
                and old_game_str != Config.GTA5_GAME_ID
            )
            switched_from_gta = (
                old_game_str == Config.GTA5_GAME_ID
                and new_game_str != Config.GTA5_GAME_ID
            )

            if switched_to_gta or switched_from_gta:
                direction = "to" if switched_to_gta else "from"
                event_type = (
                    "category_to_gta" if switched_to_gta else "category_from_gta"
                )
                self.logger.info(
                    f"🎮 Category changed {direction} GTA 5: {payload.broadcaster.name}"
                )

                # Send notification to all subscribed guilds
                guilds_ids = await self.database.list_streamer_guilds(
                    payload.broadcaster.id
                )
                for guild_id in guilds_ids:
                    guild_settings = await self.database.get_guild(guild_id)
                    notification_channel_id = (
                        guild_settings["notification_channel_id"]
                        if guild_settings
                        else None
                    )
                    if notification_channel_id is None:
                        continue

                    channel = self.discord_bot.get_channel(notification_channel_id)
                    if channel is None:
                        continue

                    # Get template and format message
                    template = await self.database.get_notification_template(
                        guild_id, event_type
                    )
                    message = format_notification_template(
                        template,
                        streamer_name=payload.broadcaster.name,
                        stream_title=new_title or "",
                        game_name=new_game_name or "",
                    )

                    # Create component for to_gta only (they started playing GTA)
                    if switched_to_gta:
                        components = create_notification_component(
                            message=message,
                            streamer_name=payload.broadcaster.name,
                            stream_title=new_title or "",
                            game_name=new_game_name or "",
                            thumbnail_url=streamer_data_db.get("stream_thumbnail_url")
                            or "",
                        )
                        await channel.send(components=components)
                    else:
                        await channel.send(content=message)

            # Always update monitoring messages
            await self.update_monitoring_messages()
        except Exception as e:
            self.logger.error(
                f"Error handling channel update for {payload.broadcaster.name}: {e}",
                exc_info=True,
            )

    async def remove_subscription(self, streamer_id: str) -> None:
        """Remove EventSub subscriptions for a streamer.

        Args:
            streamer_id: Twitch user ID
        """
        try:
            subscriptions_response = await self.fetch_eventsub_subscriptions(
                user_id=streamer_id
            )
            async for subscription in subscriptions_response.subscriptions:
                await self.delete_eventsub_subscription(subscription.id)
                self.logger.debug(
                    f"Deleted EventSub subscription {subscription.id} for streamer ID: {streamer_id}"
                )
        except Exception as e:
            self.logger.error(
                f"Error removing subscriptions for streamer {streamer_id}: {e}",
                exc_info=True,
            )

    async def add_notification(self, streamer_id: int) -> None:
        """Add EventSub subscriptions for a streamer.

        Args:
            streamer_id: Twitch user ID
        """
        if streamer_id == self.BOT_ID:
            return

        try:
            subs: list[eventsub.SubscriptionPayload] = [
                eventsub.StreamOnlineSubscription(broadcaster_user_id=streamer_id),
                eventsub.StreamOfflineSubscription(broadcaster_user_id=streamer_id),
                eventsub.ChannelUpdateSubscription(broadcaster_user_id=streamer_id),
            ]

            resp: twitchio.MultiSubscribePayload = await self.multi_subscribe(subs)
            if resp.errors:
                self.logger.warning(
                    "Failed to subscribe to: %r, for user: %s", resp.errors, streamer_id
                )
            else:
                self.logger.debug(
                    f"✓ Successfully subscribed to events for streamer ID: {streamer_id}"
                )
        except Exception as e:
            self.logger.error(
                f"Error adding notification subscriptions for streamer {streamer_id}: {e}",
                exc_info=True,
            )
