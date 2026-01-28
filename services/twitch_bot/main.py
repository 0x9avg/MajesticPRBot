"""
Twitch Bot Entry Point.
Запуск полностью независимого микросервиса.
"""

import asyncio
import sys

from config import Config
from api_client import APIClient
from twitch_bot import TwitchBot


async def main():
    """Main entry point."""
    logger = Config.setup_logging("Main")

    # Validate config
    missing = Config.validate_env_vars()
    if missing:
        logger.error(f"Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)

    logger.info("Starting Twitch Bot microservice...")

    # Initialize API client
    api_client = APIClient(
        base_url=Config.API_BASE_URL,
        timeout=Config.API_TIMEOUT,
        logger=Config.setup_logging("APIClient"),
    )
    logger.info(f"✓ API client: {Config.API_BASE_URL}")

    # Initialize broker consumer (for receiving events like streamer.added)
    consumer = None
    try:
        from broker_consumer import BrokerConsumer

        consumer = BrokerConsumer(
            host=Config.RABBITMQ_HOST,
            port=Config.RABBITMQ_PORT,
            user=Config.RABBITMQ_USER,
            password=Config.RABBITMQ_PASSWORD,
            vhost=Config.RABBITMQ_VHOST,
            exchange_name=Config.RABBITMQ_EXCHANGE,
            logger=Config.setup_logging("BrokerConsumer"),
        )

        logger.info(f"✓ Broker consumer configured: {Config.RABBITMQ_HOST}:{Config.RABBITMQ_PORT}")
    except Exception as e:
        logger.warning(f"Broker unavailable: {e}")
        consumer = None

    bot = TwitchBot(
        api_client=api_client,
        logger=Config.setup_logging("TwitchBot"),
    )

    # Start Consumer if available
    if consumer:
        consumer.bot = bot
        # Connect safely in background so it doesn't block startup if RabbitMQ limits/issues
        asyncio.create_task(consumer.connect())

    # Run
    try:
        await bot.start()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await api_client.close()
        if consumer:
            await consumer.disconnect()
        logger.info("✓ Twitch Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
