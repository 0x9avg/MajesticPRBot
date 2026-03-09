"""
RabbitMQ Broker Consumer for Discord Bot.
Полностью независимый - не импортирует из других сервисов.
"""

import asyncio
import json
import logging
from contextlib import suppress
from typing import Callable, Dict, Optional
from urllib.parse import quote

import aio_pika
from aio_pika import ExchangeType, IncomingMessage


class BrokerConsumer:
    """RabbitMQ message consumer for Discord bot."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5672,
        user: str = "guest",
        password: str = "guest",
        vhost: str = "/",
        exchange_name: str = "prmajesticbot",
        queue_name: str = "discord_bot",
        logger: Optional[logging.Logger] = None,
    ):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.vhost = vhost
        self.exchange_name = exchange_name
        self.queue_name = queue_name
        self.logger = logger or logging.getLogger(__name__)

        self.connection: Optional[aio_pika.RobustConnection] = None
        self.channel: Optional[aio_pika.Channel] = None
        self.queue: Optional[aio_pika.Queue] = None

        # Event handlers
        self._handlers: Dict[str, Callable] = {}
        self._running = False
        self._closing = False
        self._consumer_task: Optional[asyncio.Task] = None

    @property
    def url(self) -> str:
        """Get the AMQP connection URL."""
        user = quote(self.user, safe="")
        password = quote(self.password, safe="")
        vhost = quote(self.vhost, safe="")
        return (
            f"amqp://{user}:{password}@{self.host}:{self.port}/{vhost}"
        )

    def on(self, event_pattern: str):
        """Decorator to register event handler.

        Usage:
            @broker.on("streamer.added")
            async def handle_streamer_added(data):
                ...
        """

        def decorator(func: Callable):
            self._handlers[event_pattern] = func
            return func

        return decorator

    def register_handler(self, event_pattern: str, handler: Callable) -> None:
        """Register an event handler."""
        self._handlers[event_pattern] = handler
        self.logger.debug(f"Registered handler for: {event_pattern}")

    async def connect(self) -> None:
        """Establish connection to RabbitMQ with retry loop."""
        while not self._closing:
            if (
                self.connection
                and not self.connection.is_closed
                and self.channel
                and not self.channel.is_closed
                and self.queue
            ):
                return

            try:
                self.logger.info(f"Connecting to RabbitMQ at {self.host}...")
                self.connection = await aio_pika.connect_robust(self.url)
                self.channel = await self.connection.channel()
                await self.channel.set_qos(prefetch_count=10)

                # Declare exchange
                exchange = await self.channel.declare_exchange(
                    self.exchange_name,
                    ExchangeType.TOPIC,
                    durable=True,
                )

                # Declare queue
                self.queue = await self.channel.declare_queue(
                    self.queue_name,
                    durable=True,
                )

                # Bind to all relevant routing keys
                bindings = [
                    "streamer.*",
                    "stream.state.*",
                    "spec.*",
                    "event.*",
                    "guild.*",
                    "monitoring.*",
                ]

                for binding in bindings:
                    await self.queue.bind(exchange, routing_key=binding)

                self.logger.info(f"✓ Connected to RabbitMQ at {self.host}:{self.port}")
                return
            except Exception as e:
                self.logger.error(f"Failed to connect to RabbitMQ: {e}")
                if self._closing:
                    return
                self.logger.info("Retrying broker consumer connection in 5 seconds...")
                await asyncio.sleep(5)

    async def disconnect(self) -> None:
        """Close connection to RabbitMQ."""
        self._closing = True
        self._running = False
        if self._consumer_task and not self._consumer_task.done():
            self._consumer_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._consumer_task
        self._consumer_task = None
        try:
            if self.connection:
                await self.connection.close()
                self.logger.info("✓ Disconnected from RabbitMQ")
        except Exception as e:
            self.logger.error(f"Error disconnecting: {e}")

    def _match_pattern(self, pattern: str, routing_key: str) -> bool:
        """Check if routing key matches pattern."""
        pattern_parts = pattern.split(".")
        key_parts = routing_key.split(".")

        for i, part in enumerate(pattern_parts):
            if part == "*":
                if i >= len(key_parts):
                    return False
                continue
            if part == "#":
                return True
            if i >= len(key_parts) or part != key_parts[i]:
                return False

        return len(pattern_parts) == len(key_parts)

    async def _process_message(self, message: IncomingMessage) -> None:
        """Process incoming message."""
        async with message.process():
            try:
                routing_key = message.routing_key
                body = json.loads(message.body.decode())

                self.logger.info(f"Received Broker Event: {routing_key}")

                # Find matching handler
                for pattern, handler in self._handlers.items():
                    if self._match_pattern(pattern, routing_key):
                        try:
                            await handler(body)
                        except Exception as e:
                            self.logger.error(f"Handler error: {e}")
                        break

            except json.JSONDecodeError as e:
                self.logger.error(f"Invalid JSON: {e}")
            except Exception as e:
                self.logger.error(f"Processing error: {e}")

    async def start_consuming(self) -> None:
        """Start consuming messages."""
        if not self.queue:
            raise RuntimeError("Not connected. Call connect() first.")
        if self._running:
            self.logger.debug("Broker consumer is already running")
            return

        self._running = True
        self.logger.info("Started consuming messages...")

        await self.queue.consume(self._process_message)

        while self._running:
            await asyncio.sleep(1)

    async def consume_in_background(self) -> asyncio.Task:
        """Start consuming in background."""
        if self._consumer_task and not self._consumer_task.done():
            self.logger.debug("Background consumer already running")
            return self._consumer_task

        if not self.queue:
            await self.connect()

        task = asyncio.create_task(self.start_consuming())
        self._consumer_task = task
        self.logger.info("Started background consumer")
        return task
