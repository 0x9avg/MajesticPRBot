"""
Script to unsubscribe from ALL EventSub subscriptions for the application.
"""

import asyncio
import logging
import os
import sys

# Add parent directory to path to import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from twitchio import Client

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Unsubscriber")


class UnsubscribeBot(Client):
    def __init__(self):
        super().__init__(
            client_id=Config.twitch_client_id,
            client_secret=Config.twitch_client_secret,
        )

    async def event_ready(self):
        logger.info("Authenticated successfully (Client).")

        try:
            await self.delete_all_eventsub_subscriptions()
            subs = await self.fetch_eventsub_subscriptions()
            print(subs)

            logger.info("Finished! Deleted all subscriptions.")

        except Exception as e:
            logger.error(f"An error occurred during cleanup: {e}")
        finally:
            logger.info("Closing client...")
            await self.close()


async def main():
    logger.info("Initializing Twitch Client...")
    Config.validate_twitch_credentials()
    bot = UnsubscribeBot()
    try:
        await bot.start()
    except KeyboardInterrupt:
        await bot.close()


if __name__ == "__main__":
    asyncio.run(main())
