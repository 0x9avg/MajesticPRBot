"""Twitch bot module for PRMajesticBot.
Handles Twitch EventSub subscriptions and stream events.
"""

import twitchio
from twitchio import eventsub, AutoClient
import logging

from config import Config


class TwitchBot(AutoClient):
    def __init__(self, client_id, client_secret, bot_id, logger, database) -> None:
        self.subs: list[eventsub.SubscriptionPayload] = []
        self.LOGGER = logger
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
            self.LOGGER.debug(f"Fetching user ID for: {username}")
            user = await self.fetch_user(login=username)
            if user:
                self.LOGGER.debug(f"Found user {username} with ID: {user.id}")
            else:
                self.LOGGER.warning(f"User not found: {username}")
            return user.id if user else None
        except Exception as e:
            self.LOGGER.error(f"Error fetching user ID for {username}: {e}", exc_info=True)
            return None

    async def sync_streamers(self):
        """Sync all streamers from database and subscribe to their events."""
        try:
            self.LOGGER.debug("Syncing streamers from database...")
            streamers = await self.database.list_all_streamers()
            self.LOGGER.debug(f"Found {len(streamers)} streamers in database")
            
            for streamer in streamers:
                if streamer["streamer_id"] == self.BOT_ID:
                    self.LOGGER.debug(f"Skipping bot account (ID: {self.BOT_ID})")
                    continue

                self.LOGGER.debug(f"Adding subscriptions for {streamer['streamer_name']} (ID: {streamer['streamer_id']})")
                self.subs.extend(
                    [
                        eventsub.StreamOnlineSubscription(
                            broadcaster_user_id=streamer["streamer_id"]
                        ),
                        eventsub.StreamOfflineSubscription(
                            broadcaster_user_id=streamer["streamer_id"]
                        ),
                        eventsub.ChannelUpdateSubscription(
                            broadcaster_user_id=streamer["streamer_id"]
                        ),
                    ]
                )

                # Update stream status
                data = await self.get_stream_info(streamer["streamer_id"])
                await self.database.update_streamer_status(
                    streamer["streamer_id"],
                    data["is_online"] if data["is_online"] else False,
                    data["started_at"] if data["is_online"] else None,
                    data["game_id"] if data["is_online"] else None,
                    data["game_name"] if data["is_online"] else None,
                    data["title"] if data["is_online"] else None,
                )
            
            self.LOGGER.debug(f"✓ Synced {len(streamers)} streamers with {len(self.subs)} subscriptions")
        except Exception as e:
            self.LOGGER.error(f"Error syncing streamers: {e}", exc_info=True)
            raise

    async def get_stream_info(self, streamer_id: int):
        """Get current stream information for a streamer."""
        try:
            self.LOGGER.debug(f"Fetching stream info for streamer ID: {streamer_id}")
            streams = await self.fetch_streams(user_ids=[streamer_id])
            is_online = len(streams) > 0
            
            if is_online:
                self.LOGGER.debug(f"Streamer {streamer_id} is online: '{streams[0].title}'")
            else:
                self.LOGGER.debug(f"Streamer {streamer_id} is offline")

            return {
                "id": streamer_id,
                "is_online": is_online,
                "user": streams[0].user if is_online else None,
                "title": streams[0].title if is_online else None,
                "started_at": streams[0].started_at if is_online else None,
                "game_id": streams[0].game_id if is_online else None,
                "game_name": streams[0].game_name if is_online else None,
                "viewer_count": streams[0].viewer_count if is_online else None,
            }
        except Exception as e:
            self.LOGGER.error(f"Error fetching stream info for {streamer_id}: {e}", exc_info=True)
            return {
                "id": streamer_id,
                "is_online": False,
                "user": None,
                "title": None,
                "started_at": None,
                "game_id": None,
                "game_name": None,
                "viewer_count": None,
            }

    async def event_ready(self) -> None:
        self.LOGGER.info("Successfully logged in as: %s", self.user)

        await self.sync_streamers()

        self._is_ready_ = True

    async def event_stream_online(self, payload: twitchio.StreamOnline) -> None:
        """Handle stream online event."""
        self.LOGGER.info(f"🔴 Stream ONLINE: {payload.broadcaster.name} (ID: {payload.broadcaster.id})")

        try:
            guilds_ids = await self.database.list_streamer_guilds(
                payload.broadcaster.id
            )
            self.LOGGER.debug(f"Notifying {len(guilds_ids)} guilds about stream start")

            for guild_id in guilds_ids:
                guild_settings = await self.database.get_guild(guild_id)
                notification_channel_id = guild_settings["notification_channel_id"] if guild_settings else None
                if notification_channel_id is None:
                    self.LOGGER.warning(f"No notification channel set for guild {guild_id}")
                    continue

                channel = self.discord_bot.get_channel(notification_channel_id)
                if channel is None:
                    self.LOGGER.warning(f"Channel {notification_channel_id} not found for guild {guild_id}")
                    continue

                await channel.send(f"{payload.broadcaster.name} is now ONLINE!")
                self.LOGGER.debug(f"Sent notification to guild {guild_id}")

            # Update database
            stream = await self.get_stream_info(payload.broadcaster.id)
            await self.database.update_streamer_status(
                payload.broadcaster.id,
                True,
                started_at=stream["started_at"],
                game_id=stream["game_id"] if stream["game_id"] else None,
                game_name=stream["game_name"] if stream["game_name"] else None,
                stream_title=stream["title"],
            )
            self.logger.debug(f"✓ Stream online event processed for {payload.broadcaster.name}")
        except Exception as e:
            self.LOGGER.error(f"Error handling stream online event for {payload.broadcaster.name}: {e}", exc_info=True)

    async def event_stream_offline(self, payload: twitchio.StreamOffline) -> None:
        self.LOGGER.info("[%s] ended a stream!", payload.broadcaster)
        guilds_ids = await self.database.list_streamer_guilds(
            payload.broadcaster.id
        )

        for guild_id in guilds_ids:
            guild_settings = await self.database.get_guild(guild_id)
            notification_channel_id = guild_settings["notification_channel_id"] if guild_settings else None
            if notification_channel_id is None:
                continue

            channel = self.discord_bot.get_channel(notification_channel_id)
            if channel is None:
                continue

            await channel.send(f"{payload.broadcaster.name} is now OFFLINE!")

        await self.database.update_streamer_status(
            payload.broadcaster.id,
            False,
            started_at=None,
            game_id=None,
            game_name=None,
            stream_title=None,
        )

    async def event_channel_update(self, payload: twitchio.ChannelUpdate) -> None:
        """Handle channel update events (title/category changes)."""
        try:
            self.LOGGER.debug("Handling channel update for [%s]", payload.broadcaster.name)

            # CRITICAL FIX: Use payload data directly instead of querying Helix
            # Helix API may have stale data when EventSub arrives first
            streamer_data_db = await self.database.get_streamer(payload.broadcaster.id)

            # Get game info from payload (fresh data from EventSub)
            new_game_id = payload.category_id  # From payload - always fresh!
            new_game_name = payload.category_name
            new_title = payload.title
            
            old_game_id = streamer_data_db.get("game_id")

            new_game_str = str(new_game_id) if new_game_id is not None else None
            old_game_str = str(old_game_id) if old_game_id is not None else None

            # Use Config constant instead of hardcoded value
            if new_game_str == Config.GTA5_GAME_ID and old_game_str != Config.GTA5_GAME_ID:
                self.LOGGER.info(
                    f"🎮 Category changed to GTA 5: {payload.broadcaster.name}"
                )

                await self.database.update_streamer_status(
                    payload.broadcaster.id,
                    streamer_data_db["is_online"],  # Keep existing online status
                    started_at=streamer_data_db.get("started_at"),  # Keep existing start time
                    game_id=new_game_id,  # Fresh from payload
                    game_name=new_game_name,  # Fresh from payload
                    stream_title=new_title,  # Fresh from payload
                )

                guilds_ids = await self.database.list_streamer_guilds(
                    payload.broadcaster.id
                )

                for guild_id in guilds_ids:
                    guild_settings = await self.database.get_guild(guild_id)
                    notification_channel_id = guild_settings["notification_channel_id"] if guild_settings else None
                    if notification_channel_id is None:
                        continue

                    channel = self.discord_bot.get_channel(notification_channel_id)
                    if channel is None:
                        continue

                    await channel.send(
                        f"[{payload.broadcaster.name}] changed category to GTA 5!"
                    )

            elif old_game_str == Config.GTA5_GAME_ID and new_game_str != Config.GTA5_GAME_ID:
                self.LOGGER.info(
                    f"🎮 Category changed from GTA 5: {payload.broadcaster.name}"
                )

                await self.database.update_streamer_status(
                    payload.broadcaster.id,
                    streamer_data_db["is_online"],  # Keep existing online status
                    started_at=streamer_data_db.get("started_at"),  # Keep existing start time
                    game_id=new_game_id,  # Fresh from payload
                    game_name=new_game_name,  # Fresh from payload
                    stream_title=new_title,  # Fresh from payload
                )

                guilds_ids = await self.database.list_streamer_guilds(
                    payload.broadcaster.id
                )

                for guild_id in guilds_ids:
                    guild_settings = await self.database.get_guild(guild_id)
                    notification_channel_id = guild_settings["notification_channel_id"] if guild_settings else None
                    if notification_channel_id is None:
                        continue

                    channel = self.discord_bot.get_channel(notification_channel_id)
                    if channel is None:
                        continue

                    await channel.send(
                        f"[{payload.broadcaster.name}] changed category from GTA 5!"
                    )
        except Exception as e:
            self.LOGGER.error(f"Error handling channel update for {payload.broadcaster.name}: {e}", exc_info=True)


    async def add_notification(self, streamer_id: int) -> None:
        if streamer_id == self.BOT_ID:
            return

        subs: list[eventsub.SubscriptionPayload] = [
            eventsub.StreamOnlineSubscription(broadcaster_user_id=streamer_id),
            eventsub.StreamOfflineSubscription(broadcaster_user_id=streamer_id),
            eventsub.ChannelUpdateSubscription(broadcaster_user_id=streamer_id),
        ]

        resp: twitchio.MultiSubscribePayload = await self.multi_subscribe(subs)
        if resp.errors:
            self.LOGGER.warning(
                "Failed to subscribe to: %r, for user: %s", resp.errors, streamer_id
            )

    # TODO : Not to delete all the subscriptions every time instead only the necessary ones
    async def sync_subscriptions(self) -> None:
        self.subs.clear()
        await self.delete_all_eventsub_subscriptions()

        streamers = await self.database.list_all_streamers()
        for user in streamers:
            if user["streamer_id"] == self.BOT_ID:
                continue

            self.subs.extend(
                [
                    eventsub.StreamOnlineSubscription(
                        broadcaster_user_id=user["streamer_id"]
                    ),
                    eventsub.StreamOfflineSubscription(
                        broadcaster_user_id=user["streamer_id"]
                    ),
                    eventsub.ChannelUpdateSubscription(
                        broadcaster_user_id=user["streamer_id"]
                    ),
                ]
            )
        await self.multi_subscribe(self.subs)
