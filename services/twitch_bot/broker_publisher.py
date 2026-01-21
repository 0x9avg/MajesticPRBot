"""
RabbitMQ Broker Publisher for Twitch Bot.
Publishes events when stream state changes.
"""

import asyncio
import json
from typing import Optional, Dict, Any
import logging

import aio_pika
from aio_pika import ExchangeType


class BrokerPublisher:
    """RabbitMQ message publisher for Twitch bot."""
    
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
        return f"amqp://{self.user}:{self.password}@{self.host}:{self.port}/{self.vhost}"
    
    async def connect(self) -> None:
        """Connect to RabbitMQ."""
        try:
            self.connection = await aio_pika.connect_robust(self.url)
            self.channel = await self.connection.channel()
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
        """Disconnect from RabbitMQ."""
        try:
            if self.connection:
                await self.connection.close()
                self.logger.info("✓ Disconnected from RabbitMQ")
        except Exception as e:
            self.logger.error(f"Error disconnecting: {e}")
    
    async def publish(self, routing_key: str, data: Dict[str, Any]) -> bool:
        """Publish a message."""
        if not self.exchange:
            self.logger.warning("Not connected to RabbitMQ")
            return False
        
        try:
            message = aio_pika.Message(
                body=json.dumps(data).encode(),
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            )
            await self.exchange.publish(message, routing_key=routing_key)
            self.logger.debug(f"Published: {routing_key}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to publish {routing_key}: {e}")
            return False
    
    # =========================================================================
    # Stream Events
    # =========================================================================
    
    async def emit_stream_online(
        self,
        streamer_id: int,
        streamer_name: str,
        game_id: str = None,
        game_name: str = None,
        stream_title: str = None,
        thumbnail_url: str = None,
        guild_id: int = None,
    ) -> bool:
        """Emit stream online event."""
        return await self.publish("stream.state.online", {
            "event": "online",
            "streamer_id": streamer_id,
            "streamer_name": streamer_name,
            "is_online": True,
            "game_id": game_id,
            "game_name": game_name,
            "stream_title": stream_title,
            "thumbnail_url": thumbnail_url,
            "guild_id": guild_id,
        })
    
    async def emit_stream_offline(
        self,
        streamer_id: int,
        streamer_name: str,
        guild_id: int = None,
    ) -> bool:
        """Emit stream offline event."""
        return await self.publish("stream.state.offline", {
            "event": "offline",
            "streamer_id": streamer_id,
            "streamer_name": streamer_name,
            "is_online": False,
            "guild_id": guild_id,
        })
    
    async def emit_category_change(
        self,
        streamer_id: int,
        streamer_name: str,
        old_game_id: str,
        new_game_id: str,
        new_game_name: str,
        stream_title: str = None,
        thumbnail_url: str = None,
        guild_id: int = None,
    ) -> bool:
        """Emit category change event."""
        return await self.publish("stream.state.category", {
            "event": "category_change",
            "streamer_id": streamer_id,
            "streamer_name": streamer_name,
            "old_game_id": old_game_id,
            "new_game_id": new_game_id,
            "new_game_name": new_game_name,
            "stream_title": stream_title,
            "thumbnail_url": thumbnail_url,
            "guild_id": guild_id,
        })
    
    async def emit_spec_unclaimed(
        self,
        streamer_id: int,
        streamer_name: str,
        pr_id: int,
        duration_seconds: int,
        reason: str,
        guild_id: int = None,
    ) -> bool:
        """Emit spec unclaimed event."""
        return await self.publish("spec.unclaimed", {
            "event": "unclaimed",
            "streamer_id": streamer_id,
            "streamer_name": streamer_name,
            "pr_id": pr_id,
            "duration_seconds": duration_seconds,
            "reason": reason,
            "guild_id": guild_id,
        })
    
    async def emit_monitoring_refresh(self, guild_id: int = None) -> bool:
        """Request monitoring refresh."""
        return await self.publish("monitoring.refresh", {
            "event": "refresh",
            "guild_id": guild_id,
        })
