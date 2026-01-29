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
        base_url=Config.api_base_url,
        timeout=Config.api_timeout,
        logger=Config.setup_logging("APIClient"),
    )
    logger.info(f"✓ API client configured: {Config.api_base_url}")

    # Initialize broker consumer (optional)
    broker = None
    try:
        broker = BrokerConsumer(
            host=Config.rabbitmq_host,
            port=Config.rabbitmq_port,
            user=Config.rabbitmq_user,
            password=Config.rabbitmq_password,
            vhost=Config.rabbitmq_vhost,
            exchange_name=Config.rabbitmq_exchange,
            queue_name=Config.rabbitmq_queue,
            logger=Config.setup_logging("Broker"),
        )
        logger.info(
            f"✓ Broker configured: {Config.rabbitmq_host}:{Config.rabbitmq_port}"
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
