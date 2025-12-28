import asyncio
import json
import logging

import twitchio
from twitchio import eventsub
from twitchio.ext import commands

from dotenv import load_dotenv
import os

load_dotenv()

LOGGER: logging.Logger = logging.getLogger(__name__)


CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
BOT_ID = os.getenv("BOT_ID")
OWNER_ID = os.getenv("OWNER_ID")


class Bot(commands.AutoBot):
    def __init__(self, subs: list[eventsub.SubscriptionPayload]) -> None:
        super().__init__(
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            bot_id=BOT_ID,
            owner_id=OWNER_ID,
            prefix="!",
            subscriptions=subs,
            force_subscribe=True,
        )

    async def event_ready(self) -> None:
        LOGGER.info("Successfully logged in as: %s", self.user)

    async def event_stream_online(self, payload: twitchio.StreamOnline) -> None:
        LOGGER.info("[%s] started a stream!", payload.broadcaster)

    async def event_stream_offline(self, payload: twitchio.StreamOffline) -> None:
        LOGGER.info("[%s] ended a stream!", payload.broadcaster)


def main() -> None:
    # Setup logging
    twitchio.utils.setup_logging(level=logging.INFO)

    # Define subscriptions
    subs: list[eventsub.SubscriptionPayload] = []

    streamers_ids = ["780806587"]  # yamat0pr

    for user_id in streamers_ids:
        if user_id == BOT_ID:
            continue

        subs.extend(
            [
                eventsub.StreamOnlineSubscription(broadcaster_user_id=user_id),
                eventsub.StreamOfflineSubscription(broadcaster_user_id=user_id),
            ]
        )

    async def runner() -> None:
        async with Bot(subs=subs) as bot:
            await bot.start()

    try:
        asyncio.run(runner())
    except KeyboardInterrupt:
        LOGGER.warning("Shutting down due to KeyboardInterrupt.")


if __name__ == "__main__":
    main()
