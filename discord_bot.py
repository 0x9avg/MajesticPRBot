import discord
from discord.ext import commands
import os


class DiscordBot(commands.Bot):
    def __init__(self, DiscordToken, database, logger):
        self.token = DiscordToken
        self.channel_id = None
        self.database = database
        self.channel = None
        self._is_ready_ = False
        self.logger = logger
        self.synced = False

        intents = discord.Intents.all()

        super().__init__(
            command_prefix="!",
            intents=intents,
        )

    def start(self):
        return super().start(self.token)

    async def on_ready(self):
        await self.wait_until_ready()

        if not self.synced:
            for filename in os.listdir("./cogs"):
                if filename.endswith(".py"):
                    await self.load_extension(f"cogs.{filename[:-3]}")
                    self.logger.info(f"Cog {filename[:-3]} loaded")
            synced = await self.tree.sync()
            print(f"Synced {len(synced)} commands")

            self.synced = True
        await self.change_presence(
            status=discord.Status.idle, activity=discord.Game("TEST BUILD")
        )
        self.logger.info(f"Bot has logged in as {self.user}.")

        self._is_ready_ = True

        # TODO: Replace it with multi-server support
        self.channel = self.get_channel(self.channel_id)
