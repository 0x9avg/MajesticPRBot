"""
RabbitMQ Broker Consumer for Twitch Bot.
Listens for events like streamer.added to update subscriptions dynamically.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .twitch_bot import TwitchBot

import asyncio
import json
import logging
from typing import Any, Dict, Optional

import aio_pika
from aio_pika import ExchangeType
from config import Config


class BrokerConsumer:
    """RabbitMQ message consumer for Twitch bot."""

    bot: "TwitchBot | None"

    def __init__(
        self,
        bot: "TwitchBot | None" = None,
        host: str = Config.rabbitmq_host,
        port: int = Config.rabbitmq_port,
        user: str = Config.rabbitmq_user,
        password: str = Config.rabbitmq_password,
        vhost: str = Config.rabbitmq_vhost,
        exchange_name: str = Config.rabbitmq_exchange,
        logger: Optional[logging.Logger] = None,
    ):
        self.bot = bot
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.vhost = vhost
        self.exchange_name = exchange_name
        self.logger = logger or logging.getLogger("BrokerConsumer")
        self.queue_name = f"{self.exchange_name}.twitch_bot"

        self.connection: Optional[aio_pika.RobustConnection] = None
        self.channel: Optional[aio_pika.Channel] = None
        self.queue: Optional[aio_pika.Queue] = None
        self.exchange: Optional[aio_pika.Exchange] = None

    @property
    def url(self) -> str:
        return (
            f"amqp://{self.user}:{self.password}@{self.host}:{self.port}/{self.vhost}"
        )

    async def connect(self) -> None:
        """Connect to RabbitMQ and start consuming."""
        try:
            self.logger.info(f"Connecting to RabbitMQ at {self.host}...")
            self.connection = await aio_pika.connect_robust(self.url)
            self.channel = await self.connection.channel()

            # Set QoS to 1 to process one message at a time per consumer
            await self.channel.set_qos(prefetch_count=1)

            # Declare exchange (idempotent)
            self.exchange = await self.channel.declare_exchange(
                self.exchange_name, ExchangeType.TOPIC, durable=True
            )

            # Declare durable queue for this service
            self.queue = await self.channel.declare_queue(self.queue_name, durable=True)

            # Bind queue to relevant keys
            # We want to know when streamers are added/removed/updated
            await self.queue.bind(self.exchange, routing_key="streamer.added")
            await self.queue.bind(self.exchange, routing_key="streamer.removed")
            await self.queue.bind(self.exchange, routing_key="streamer.updated")
            await self.queue.bind(self.exchange, routing_key="streamer.verify")

            # Start consuming
            await self.queue.consume(self.process_message)
            self.logger.info("✓ Broker Consumer started")

        except Exception as e:
            self.logger.error(f"Failed to connect consumer: {e}")
            # Don't raise, just log. Retry logic via robust connection handles reconnects?
            # Ideally retry logic here too.
            await asyncio.sleep(5)
            # Recursion risky without limit, but RobustConnection handles network disconnects.
            # Initial connection failure needs handling.

    async def disconnect(self) -> None:
        """Close connection."""
        if self.connection:
            await self.connection.close()

    async def process_message(self, message: aio_pika.IncomingMessage):
        """Process incoming RabbitMQ message."""
        async with message.process():
            try:
                data = json.loads(message.body.decode())
                routing_key = message.routing_key
                self.logger.debug(f"Received event: {routing_key}")

                await self.handle_event(routing_key, data)

            except Exception as e:
                self.logger.error(f"Error processing message: {e}", exc_info=True)

    async def handle_event(self, key: str, data: Dict[str, Any]):
        """Route event to handler."""
        if not self.bot:
            self.logger.warning("Bot instance not set for consumer")
            return

        if key == "streamer.verify":
            username = data.get("username")
            added_by = data.get("added_by", {})
            self.logger.info(f"Verifying streamer: {username}")

            try:
                # Parse URL if needed (support twitch.tv/shroud, https://twitch.tv/shroud, etc.)
                if username:
                    username = username.strip()
                    # Remove protocol and domain
                    if "twitch.tv/" in username.lower():
                        username = username.split("twitch.tv/")[-1]
                    # Remove query params and trailing slashes
                    username = username.split("?")[0].split("/")[0].strip()

                if not username:
                    self.logger.warning("Empty username after parsing")
                    return

                self.logger.debug(f"Parsed username: {username}")

                # 1. Resolve Twitch ID
                twitch_id = await self.bot.get_streamer_id(username)

                if twitch_id:
                    self.logger.info(f"Resolved {username} -> ID {twitch_id}")

                    # 2. Get stream info for initial state
                    stream_info = await self.bot.get_stream_info(twitch_id)
                    is_online = stream_info.get("is_online", False)

                    # 2.5 Get user info for profile image
                    users = await self.bot.fetch_users(ids=[twitch_id])
                    profile_image_url = (
                        str(users[0].profile_image) if users and users[0].profile_image else None
                    )

                    # 3. Create full streamer in API (which inserts to DB)
                    result = await self.bot.api.create_streamer(
                        streamer_id=twitch_id,
                        streamer_name=username,
                        is_online=is_online,
                        started_at=(
                            str(stream_info.get("started_at"))
                            if stream_info.get("started_at")
                            else None
                        ),
                        priority=added_by.get("priority", 0),
                        added_by_id=added_by.get("added_by_id", 0),
                        game_id=stream_info.get("game_id"),
                        game_name=stream_info.get("game_name"),
                        stream_title=stream_info.get("title"),
                        stream_thumbnail_url=stream_info.get("thumbnail_url"),
                        profile_image_url=profile_image_url,
                    )

                    if result:
                        self.logger.info(
                            f"Created streamer {username} ({twitch_id}) via API"
                        )
                    else:
                        self.logger.error(
                            f"FAILED to create streamer {username} ({twitch_id}) - API returned None"
                        )

                    # 4. Do NOT subscribe here.
                    # The API will emit 'streamer.added', which we handle below.
                    # This avoids duplicate subscription attempts.
                    # await self.bot.add_notification(twitch_id)

                else:
                    self.logger.warning(
                        f"Could not resolve Twitch ID for user: {username}"
                    )
                    # Optional: Emit failure event to notify Discord User

            except Exception as e:
                self.logger.error(
                    f"Error verifying streamer {username}: {e}", exc_info=True
                )

        elif key == "streamer.added":
            streamer_id = data.get("streamer_id")
            if streamer_id:
                self.logger.info(
                    f"Processing streamer.added: {data.get('streamer_name')} ({streamer_id})"
                )
                await self.bot.add_notification(streamer_id)
                # Also force update status immediately
                # But fetch_streamer from API or just check online status?
                # bot.sync_streamers() is too heavy.
                # Just add sub is enough, event sub will trigger online/offline.

                # Check status once?
                try:
                    stream_info = await self.bot.get_stream_info(streamer_id)
                    is_online = stream_info.get("is_online", False)
                    await self.bot.api.update_streamer_status(
                        streamer_id,
                        is_online,
                        started_at=(
                            str(stream_info.get("started_at"))
                            if stream_info.get("started_at")
                            else None
                        ),
                        game_id=stream_info.get("game_id"),
                        game_name=stream_info.get("game_name"),
                        stream_title=stream_info.get("title"),
                        stream_thumbnail_url=stream_info.get("thumbnail_url"),
                    )
                except Exception as e:
                    self.logger.warning(f"Initial status check failed: {e}")

        elif key == "streamer.removed":
            streamer_id = data.get("streamer_id")
            if streamer_id:
                self.logger.info(
                    f"Processing streamer.removed: {data.get('streamer_name')} ({streamer_id})"
                )
                await self.bot.remove_subscription(streamer_id)
