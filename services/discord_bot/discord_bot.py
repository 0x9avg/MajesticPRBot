"""
Discord Bot - полностью независимый микросервис.
Общается с внешним миром только через API и RabbitMQ.
"""

import disnake
from disnake.ext import commands
from typing import Optional

from config import Config


class DiscordBot(commands.Bot):
    """
    Discord Bot микросервис.

    НЕ имеет прямых ссылок на:
    - database
    - twitch_bot
    - другие сервисы

    Использует только:
    - api_client для HTTP запросов к API
    - broker для получения событий через RabbitMQ
    """

    def __init__(self, api_client, broker_consumer=None, logger=None):
        self.api_client = api_client
        self.broker = broker_consumer
        self.logger = logger or Config.setup_logging("DiscordBot")

        intents = disnake.Intents.all()

        self.logger.debug("Initializing Discord bot")
        super().__init__(command_prefix="!", intents=intents)

    @property
    def api(self):
        """Shortcut for API client."""
        return self.api_client

    def setup_cogs(self):
        """Load all cogs."""
        self.logger.debug("Loading cogs...")
        try:
            self.load_extensions("cogs/admin")
            self.load_extensions("cogs/events")
            self.load_extensions("cogs/spec")
            self.load_extensions("cogs/temp")  # Will be deleted in the future
            self.logger.info("✓ All cogs loaded")
        except Exception as e:
            self.logger.error(f"Error loading cogs: {e}", exc_info=True)
            raise


    async def start_bot(self):
        """Start the bot with token from config."""
        await self.start(Config.discord_token)

    async def on_ready(self):
        """Called when bot is ready."""
        self.logger.info(f"✓ Discord bot ready as {self.user}")
        self.logger.info(f"Bot ID: {self.user.id}, Guilds: {len(self.guilds)}")

        # Check target guild
        guild = self.get_guild(int(Config.guild_id))
        if guild:
            self.logger.info(f"✓ Connected to target guild: {guild.name}")
        else:
            self.logger.error(f"⚠ Bot is NOT in target guild {Config.guild_id}!")

        # Start broker consumer if available
        if self.broker:
            try:
                await self.broker.connect()
                await self.broker.consume_in_background()
                self.logger.info("✓ Broker consumer started")
            except Exception as e:
                self.logger.warning(f"Broker unavailable: {e}")

    async def on_slash_command_error(
        self, interaction: disnake.ApplicationCommandInteraction, error: Exception
    ):
        """Global error handler for slash commands."""
        if isinstance(error, commands.CommandOnCooldown):
            # Format time remaining
            seconds = int(error.retry_after)
            if seconds >= 60:
                time_str = f"{seconds // 60} мин {seconds % 60} сек"
            else:
                time_str = f"{seconds} сек"

            embed = disnake.Embed(
                title="⏳ Подождите",
                description=f"Вы сможете использовать эту команду через **{time_str}**.",
                color=disnake.Color.orange(),
            )

            try:
                if interaction.response.is_done():
                    await interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    await interaction.response.send_message(embed=embed, ephemeral=True)
            except:
                pass
            return

        # Log other errors
        self.logger.error(f"Slash command error: {error}", exc_info=True)

        # Try to send error message
        try:
            msg = "❌ Произошла ошибка при выполнении команды."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except:
            pass

    async def close(self):
        """Cleanup on shutdown."""
        if self.api_client:
            await self.api_client.close()
            self.logger.debug("✓ API client closed")

        if self.broker:
            await self.broker.disconnect()
            self.logger.debug("✓ Broker disconnected")

        await super().close()
