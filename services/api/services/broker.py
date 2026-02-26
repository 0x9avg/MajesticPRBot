"""
RabbitMQ Broker Service for publishing events.
All events include trace_id for distributed tracing.
"""

import asyncio
import json
import logging
from typing import Optional

import aio_pika
from aio_pika import ExchangeType, Message


class BrokerService:
    """RabbitMQ message broker for publishing events."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5672,
        user: str = "guest",
        password: str = "guest",
        vhost: str = "/",
        exchange_name: str = "prmajesticbot",
        logger: Optional[logging.Logger] = None,
    ):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.vhost = vhost
        self.exchange_name = exchange_name
        self.logger = logger or logging.getLogger(__name__)

        self.connection: Optional[aio_pika.RobustConnection] = None
        self.channel: Optional[aio_pika.Channel] = None
        self.exchange: Optional[aio_pika.Exchange] = None

    @property
    def url(self) -> str:
        """Get the AMQP connection URL."""
        return (
            f"amqp://{self.user}:{self.password}@{self.host}:{self.port}/{self.vhost}"
        )

    async def connect(self) -> None:
        """Establish connection to RabbitMQ."""
        try:
            self.connection = await aio_pika.connect_robust(self.url)
            self.channel = await self.connection.channel()

            # Declare a topic exchange
            self.exchange = await self.channel.declare_exchange(
                self.exchange_name,
                ExchangeType.TOPIC,
                durable=True,
            )

            self.logger.info(f"✓ Connected to RabbitMQ at {self.host}:{self.port}")
        except Exception as e:
            self.logger.error(f"Failed to connect to RabbitMQ: {e}")
            raise

    async def disconnect(self) -> None:
        """Close connection to RabbitMQ."""
        try:
            if self.connection:
                await self.connection.close()
                self.logger.info("✓ Disconnected from RabbitMQ")
        except Exception as e:
            self.logger.error(f"Error disconnecting from RabbitMQ: {e}")

    async def publish(self, routing_key: str, data: dict) -> bool:
        """
        Publish a message to the exchange.

        Args:
            routing_key: Topic routing key (e.g., "streamer.added", "spec.claimed")
            data: Dictionary to serialize as JSON

        Returns:
            True if published successfully, False otherwise
        """
        if not self.exchange:
            self.logger.warning("Cannot publish: not connected to RabbitMQ")
            return False

        try:
            message = Message(
                body=json.dumps(data, default=str).encode(),
                content_type="application/json",
            )

            await self.exchange.publish(message, routing_key=routing_key)
            self.logger.debug(f"Published event: {routing_key}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to publish event {routing_key}: {e}")
            return False

    # =========================================================================
    # Convenience methods for specific events (all include trace_id)
    # =========================================================================

    async def emit_streamer_added(
        self,
        streamer_id: int,
        streamer_name: str,
        data: dict = None,
        trace_id: str = None,
    ) -> bool:
        """Emit streamer.added event."""
        return await self.publish(
            "streamer.added",
            {
                "event": "streamer.added",
                "streamer_id": streamer_id,
                "streamer_name": streamer_name,
                "data": data or {},
                "trace_id": trace_id,
            },
        )

    async def emit_streamer_removed(
        self,
        streamer_id: int,
        streamer_name: str,
        trace_id: str = None,
    ) -> bool:
        """Emit streamer.removed event."""
        return await self.publish(
            "streamer.removed",
            {
                "event": "streamer.removed",
                "streamer_id": streamer_id,
                "streamer_name": streamer_name,
                "trace_id": trace_id,
            },
        )

    async def emit_streamer_updated(
        self,
        streamer_id: int,
        streamer_name: str,
        data: dict = None,
        trace_id: str = None,
    ) -> bool:
        """Emit streamer.updated event."""
        return await self.publish(
            "streamer.updated",
            {
                "event": "streamer.updated",
                "streamer_id": streamer_id,
                "streamer_name": streamer_name,
                "data": data or {},
                "trace_id": trace_id,
            },
        )

    async def emit_stream_state_changed(
        self,
        streamer_id: int,
        streamer_name: str,
        is_online: bool,
        data: dict = None,
        trace_id: str = None,
    ) -> bool:
        """Emit stream.state.changed event."""
        return await self.publish(
            "stream.state.changed",
            {
                "event": "stream.state.changed",
                "streamer_id": streamer_id,
                "streamer_name": streamer_name,
                "is_online": is_online,
                "data": data or {},
                "trace_id": trace_id,
            },
        )

    async def emit_spec_claimed(
        self,
        streamer_id: int,
        streamer_name: str,
        pr_id: int,
        data: dict = None,
        trace_id: str = None,
    ) -> bool:
        """Emit spec.claimed event."""
        return await self.publish(
            "spec.claimed",
            {
                "event": "spec.claimed",
                "streamer_id": streamer_id,
                "streamer_name": streamer_name,
                "pr_id": pr_id,
                "data": data or {},
                "trace_id": trace_id,
            },
        )

    async def emit_spec_unclaimed(
        self,
        streamer_id: int,
        streamer_name: str,
        pr_id: int,
        duration_seconds: int,
        reason: str,
        trace_id: str = None,
    ) -> bool:
        """Emit spec.unclaimed event."""
        return await self.publish(
            "spec.unclaimed",
            {
                "event": "spec.unclaimed",
                "streamer_id": streamer_id,
                "streamer_name": streamer_name,
                "pr_id": pr_id,
                "duration_seconds": duration_seconds,
                "reason": reason,
                "trace_id": trace_id,
            },
        )

    async def emit_guild_settings_updated(
        self,
        data: dict = None,
        trace_id: str = None,
    ) -> bool:
        """Emit guild.settings.updated event."""
        return await self.publish(
            "guild.settings.updated",
            {
                "event": "guild.settings.updated",
                "data": data or {},
                "trace_id": trace_id,
            },
        )

    async def emit_guild_templates_updated(
        self,
        data: dict = None,
        trace_id: str = None,
    ) -> bool:
        """Emit guild.templates.updated event."""
        return await self.publish(
            "guild.templates.updated",
            {
                "event": "guild.templates.updated",
                "data": data or {},
                "trace_id": trace_id,
            },
        )

    async def emit_guild_rates_updated(
        self,
        data: dict = None,
        trace_id: str = None,
    ) -> bool:
        """Emit guild.rates.updated event."""
        return await self.publish(
            "guild.rates.updated",
            {
                "event": "guild.rates.updated",
                "data": data or {},
                "trace_id": trace_id,
            },
        )

    async def emit_streamer_verify(
        self,
        username: str,
        added_by_data: dict = None,
        trace_id: str = None,
    ) -> bool:
        """Emit streamer.verify event for async ID resolution."""
        return await self.publish(
            "streamer.verify",
            {
                "event": "streamer.verify",
                "username": username,
                "added_by": added_by_data or {},
                "trace_id": trace_id,
            },
        )

    # =========================================================================
    # Stream State Events (called from update_streamer_status)
    # =========================================================================

    async def emit_stream_online(
        self,
        streamer_id: int,
        streamer_name: str,
        game_id: int = None,
        game_name: str = None,
        stream_title: str = None,
        thumbnail_url: str = None,
        trace_id: str = None,
    ) -> bool:
        """Emit stream.state.online event."""
        return await self.publish(
            "stream.state.online",
            {
                "event": "online",
                "streamer_id": streamer_id,
                "streamer_name": streamer_name,
                "is_online": True,
                "game_id": game_id,
                "game_name": game_name,
                "stream_title": stream_title,
                "thumbnail_url": thumbnail_url,
                "trace_id": trace_id,
            },
        )

    async def emit_stream_offline(
        self,
        streamer_id: int,
        streamer_name: str,
        trace_id: str = None,
    ) -> bool:
        """Emit stream.state.offline event."""
        return await self.publish(
            "stream.state.offline",
            {
                "event": "offline",
                "streamer_id": streamer_id,
                "streamer_name": streamer_name,
                "is_online": False,
                "trace_id": trace_id,
            },
        )

    async def emit_category_change(
        self,
        streamer_id: int,
        streamer_name: str,
        old_game_id: str,
        new_game_id: str,
        new_game_name: str,
        stream_title: str = None,
        thumbnail_url: str = None,
        trace_id: str = None,
    ) -> bool:
        """Emit stream.state.category event."""
        return await self.publish(
            "stream.state.category",
            {
                "event": "category_change",
                "streamer_id": streamer_id,
                "streamer_name": streamer_name,
                "old_game_id": old_game_id,
                "new_game_id": new_game_id,
                "new_game_name": new_game_name,
                "stream_title": stream_title,
                "thumbnail_url": thumbnail_url,
                "trace_id": trace_id,
            },
        )

    async def emit_event_joined(
        self,
        event_id: int,
        event_name: str,
        pr_id: int,
        trace_id: str = None,
    ) -> bool:
        """Emit event.joined event."""
        return await self.publish(
            "event.joined",
            {
                "event": "event.joined",
                "event_id": event_id,
                "event_name": event_name,
                "pr_id": pr_id,
                "trace_id": trace_id,
            },
        )

    async def emit_event_left(
        self,
        event_id: int,
        event_name: str,
        pr_id: int,
        duration_seconds: int = 0,
        trace_id: str = None,
    ) -> bool:
        """Emit event.left event."""
        return await self.publish(
            "event.left",
            {
                "event": "event.left",
                "event_id": event_id,
                "event_name": event_name,
                "pr_id": pr_id,
                "duration_seconds": duration_seconds,
                "trace_id": trace_id,
            },
        )

    async def emit_monitoring_refresh(self, trace_id: str = None) -> bool:
        """Request monitoring refresh."""
        return await self.publish(
            "monitoring.refresh",
            {
                "event": "refresh",
                "trace_id": trace_id,
            },
        )
