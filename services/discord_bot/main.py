"""
Discord Bot Entry Point.
Запуск полностью независимого микросервиса.
"""

import asyncio
import sys

from config import Config
from api_client import APIClient
from broker_consumer import BrokerConsumer
from discord_bot import DiscordBot


async def main():
    """Main entry point."""
    logger = Config.setup_logging("Main")

    # Validate config
    missing = Config.validate_env_vars()
    if missing:
        logger.error(f"Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)

    logger.info("✓ Environment variables validated")

    logger.info("Starting Discord Bot microservice...")

    # Initialize API client
    api_client = APIClient(
        base_url=Config.API_BASE_URL,
        timeout=Config.API_TIMEOUT,
        logger=Config.setup_logging("APIClient"),
    )
    logger.info(f"✓ API client configured: {Config.API_BASE_URL}")

    # Initialize broker consumer (optional)
    broker = None
    try:
        broker = BrokerConsumer(
            host=Config.RABBITMQ_HOST,
            port=Config.RABBITMQ_PORT,
            user=Config.RABBITMQ_USER,
            password=Config.RABBITMQ_PASSWORD,
            vhost=Config.RABBITMQ_VHOST,
            exchange_name=Config.RABBITMQ_EXCHANGE,
            queue_name=Config.RABBITMQ_QUEUE,
            logger=Config.setup_logging("Broker"),
        )
        logger.info(
            f"✓ Broker configured: {Config.RABBITMQ_HOST}:{Config.RABBITMQ_PORT}"
        )
    except Exception as e:
        logger.warning(f"Broker configuration failed, running without: {e}")

    # Create and start bot
    bot = DiscordBot(
        api_client=api_client,
        broker_consumer=broker,
        logger=Config.setup_logging("DiscordBot"),
    )

    # Load cogs
    bot.setup_cogs()

    # Run
    try:
        await bot.start_bot()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await bot.close()
        logger.info("✓ Discord Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
