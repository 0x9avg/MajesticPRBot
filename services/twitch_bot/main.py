"""
Twitch Bot Entry Point.
Запуск полностью независимого микросервиса.
"""

import asyncio
import sys

from api_client import APIClient
from config import Config
from twitch_bot import TwitchBot


async def main():
    """Main entry point."""
    logger = Config.setup_logging("Main")

    try:
        Config.validate_startup_config()
    except ValueError as exc:
        logger.error(str(exc))
        sys.exit(1)

    logger.info("Starting Twitch Bot microservice...")
    # Initialize API client
    api_client = APIClient(
        base_url=Config.api_base_url,
        api_token=Config.service_token,
        timeout=Config.api_timeout,
        logger=Config.setup_logging("APIClient"),
    )
    logger.info(f"✓ API client: {Config.api_base_url}")

    # Initialize broker consumer (for receiving events like streamer.added)
    consumer = None
    try:
        from broker_consumer import BrokerConsumer

        consumer = BrokerConsumer(
            host=Config.rabbitmq_host,
            port=Config.rabbitmq_port,
            user=Config.rabbitmq_user,
            password=Config.rabbitmq_password,
            vhost=Config.rabbitmq_vhost,
            exchange_name=Config.rabbitmq_exchange,
            logger=Config.setup_logging("BrokerConsumer"),
        )

        logger.info(
            f"✓ Broker consumer configured: {Config.rabbitmq_host}:{Config.rabbitmq_port}"
        )
    except Exception as e:
        logger.warning(f"Broker unavailable: {e}")
        consumer = None

    bot = TwitchBot(
        api_client=api_client,
        logger=Config.setup_logging("TwitchBot"),
    )

    consumer_task = None

    # Start Consumer if available
    if consumer:
        consumer.bot = bot
        # Keep retrying in background until the broker becomes available.
        consumer_task = asyncio.create_task(consumer.connect())

    # Run
    try:
        await bot.start()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await bot.close()
        await api_client.close()
        if consumer:
            await consumer.disconnect()
        if consumer_task and not consumer_task.done():
            consumer_task.cancel()
            try:
                await consumer_task
            except asyncio.CancelledError:
                pass
        logger.info("✓ Twitch Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
