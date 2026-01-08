import logging

import asyncio

from database import Database
from twitch_bot import TwitchBot
from discord_bot import DiscordBot

from dotenv import load_dotenv
import os

load_dotenv()


def main():
    LOGGER: logging.Logger = logging.getLogger(__name__)

    database = Database(
        db_host=os.getenv("DB_HOST"),
        db_user=os.getenv("DB_USER"),
        db_password=os.getenv("DB_PASSWORD"),
        db_name=os.getenv("DB_NAME"),
        logger=LOGGER,
    )

    twitch_bot = TwitchBot(
        client_id=os.getenv("CLIENT_ID"),
        client_secret=os.getenv("CLIENT_SECRET"),
        bot_id=os.getenv("BOT_ID"),
        logger=LOGGER,
        database=database,
    )

    discord_bot = DiscordBot(
        DiscordToken=os.getenv("DISCORD_TOKEN"),
        database=database,
        logger=LOGGER,
    )

    twitch_bot.discord_bot = discord_bot
    discord_bot.twitch_bot = twitch_bot

    loop = asyncio.get_event_loop()
    asyncio.set_event_loop(loop)
    task_database = loop.create_task(database.start())
    task_twitch = loop.create_task(twitch_bot.start())
    task_discord = loop.create_task(discord_bot.start())
    gathered = asyncio.gather(task_database, task_twitch, task_discord)

    try:
        loop.run_until_complete(gathered)
    except KeyboardInterrupt:
        LOGGER.warning("Shutting down due to KeyboardInterrupt.")


if __name__ == "__main__":
    main()
