"""Discord bot module for PRMajesticBot.
Handles Discord interactions and slash commands via cogs.
"""

import disnake
from disnake.ext import commands
from config import Config


class DiscordBot(commands.Bot):
    def __init__(self, DiscordToken, database, logger):
        self.token = DiscordToken
        self.database = database
        self.logger = logger
        self.twitch_bot = None  # Will be set by main.py before setup_cogs()

        intents = disnake.Intents.all()

        self.logger.debug("Initializing Discord bot with all intents")
        super().__init__(command_prefix="!", intents=intents)

    def setup_cogs(self):
        """Load cogs. Call this AFTER setting twitch_bot reference."""
        self.logger.debug("Loading cogs from 'cogs' directory...")
        try:
            self.load_extensions("cogs")
            self.logger.debug("✓ All cogs loaded successfully")
        except Exception as e:
            self.logger.error(f"Error loading cogs: {e}", exc_info=True)
            raise

    def start(self):
        """Start the Discord bot."""
        self.logger.debug("Starting Discord bot...")
        return super().start(self.token)

    async def on_ready(self):
        """Called when the bot is ready and connected."""
        self.logger.info(f"✓ Discord bot ready as {self.user}")
        self.logger.debug(f"Bot ID: {self.user.id}, Guilds: {len(self.guilds)}")

        # Check if bot is in target guild
        guild = self.get_guild(Config.GUILD_ID)
        if guild:
            self.logger.info(f"✓ Connected to target guild: {guild.name}")
        else:
            self.logger.error(f"⚠ Bot is NOT in target guild {Config.GUILD_ID}!")

    async def on_guild_remove(self, guild: disnake.Guild):
        """Called when the bot is removed from a guild."""
        if guild.id == Config.GUILD_ID:
            self.logger.error(f"⚠ Bot was removed from target guild!")
        else:
            self.logger.debug(f"Bot removed from guild: {guild.name}")

    async def on_guild_join(self, guild: disnake.Guild):
        """Called when the bot joins a new guild."""
        self.logger.debug(f"Bot joined guild: {guild.name} (ID: {guild.id})")
