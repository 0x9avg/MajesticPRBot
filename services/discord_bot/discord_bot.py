"""Discord Bot - полностью независимый микросервис."""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

# Импортируем для аннотации типов в IDE
if TYPE_CHECKING:
    import logging

    from .api_client import APIClient
    from .broker_consumer import BrokerConsumer


import disnake
from config import Config
from disnake.ext import commands
from utils import UserAuthCache, UserPermissionsCache


class DiscordBot(commands.Bot):
    """
    Discord Bot микросервис.
    """

    api_client: "APIClient"
    broker: "BrokerConsumer | None"
    logger: "logging.Logger"

    def __init__(
        self,
        api_client: "APIClient",
        broker_consumer: "BrokerConsumer | None" = None,
        logger: "logging.Logger | None" = None,
    ):
        self.api_client = api_client
        self.broker = broker_consumer
        self.logger = logger or Config.setup_logging("DiscordBot")
        self.auth_cache = UserAuthCache(ttl_seconds=300)
        self.permissions_cache = UserPermissionsCache(ttl_seconds=120)

        intents = disnake.Intents.all()

        self.logger.debug("Initializing Discord bot")
        reload = Config.env == "development"
        super().__init__(command_prefix="!", intents=intents, reload=reload)

        # Add global checks for single-server enforcement AND user authorization
        self.add_check(self._check_guild_text_command)
        self.add_app_command_check(
            self._check_guild_and_auth_interaction,
            slash_commands=True,
            user_commands=True,
            message_commands=True,
        )

    def _check_guild_text_command(self, ctx: commands.Context) -> bool:
        """Global check for text commands - only allow from target guild."""
        if not ctx.guild:
            return False
        return str(ctx.guild.id) == Config.guild_id

    def _check_guild_interaction(
        self, inter: disnake.ApplicationCommandInteraction
    ) -> bool:
        """Global check for slash commands - only allow from target guild."""
        if not inter.guild_id:
            return False
        return str(inter.guild_id) == Config.guild_id

    async def _check_guild_and_auth_interaction(
        self, inter: disnake.ApplicationCommandInteraction
    ) -> bool:
        """
        Global check for slash commands:
        1. Must be from target guild.
        2. User must exist in database (assistants table).
        """
        # Guild check first
        if not inter.guild_id or str(inter.guild_id) != Config.guild_id:
            return False

        user_id = inter.user.id

        # Check cache first
        cached = self.auth_cache.get(user_id)
        if cached is not None:
            return cached

        # API lookup
        try:
            assistant = await self.api_client.get_assistant(user_id)
            is_authorized = assistant is not None and "pr_id" in assistant
            self.auth_cache.set(user_id, is_authorized)

            if not is_authorized:
                self.logger.debug(f"Auth denied for user {user_id}: not in database")

            return is_authorized
        except Exception as e:
            self.logger.error(f"Auth check failed for {user_id}: {e}")
            # On error, deny access (fail-safe)
            return False

    async def get_user_permissions(
        self,
        user_id: int,
        *,
        refresh: bool = False,
    ) -> dict[str, bool]:
        """Fetch and cache user RBAC permissions."""
        if not refresh:
            cached = self.permissions_cache.get(user_id)
            if cached is not None:
                return cached

        try:
            permissions = await self.api_client.get_assistant_capabilities(user_id)
        except Exception as e:
            self.logger.error(f"Permission lookup failed for {user_id}: {e}")
            permissions = {}

        normalized = {str(k): bool(v) for k, v in (permissions or {}).items()}
        self.permissions_cache.set(user_id, normalized)
        return normalized

    async def has_permission(self, user_id: int, permission: str) -> bool:
        permissions = await self.get_user_permissions(user_id)
        return bool(permissions.get(permission, False))

    async def has_any_permission(
        self,
        user_id: int,
        permissions: Iterable[str],
    ) -> bool:
        perms = await self.get_user_permissions(user_id)
        return any(bool(perms.get(key, False)) for key in permissions)

    async def ensure_user_permissions(
        self,
        interaction: disnake.Interaction,
        *,
        require_any: Iterable[str] | None = None,
        require_all: Iterable[str] | None = None,
        error_message: str = "❌ Недостаточно прав для этого действия.",
    ) -> bool:
        """Check acting user permissions and send denial message if needed."""
        user_id = int(interaction.user.id)
        perms = await self.get_user_permissions(user_id)

        any_list = list(require_any or [])
        all_list = list(require_all or [])

        allowed_any = (
            True if not any_list else any(bool(perms.get(k, False)) for k in any_list)
        )
        allowed_all = (
            True if not all_list else all(bool(perms.get(k, False)) for k in all_list)
        )
        if allowed_any and allowed_all:
            return True

        try:
            if interaction.response.is_done():
                await interaction.followup.send(error_message, ephemeral=True)
            else:
                await interaction.response.send_message(error_message, ephemeral=True)
        except Exception:
            pass
        return False

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

        # Check target guild (fixed: pass guild_id as int)
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

    async def on_guild_join(self, guild: disnake.Guild):
        """Auto-leave guilds that are not the target guild."""
        if str(guild.id) != Config.guild_id:
            self.logger.warning(
                f"Joined unauthorized guild {guild.name} ({guild.id}). Leaving..."
            )
            await guild.leave()

    async def on_slash_command_error(
        self, interaction: disnake.ApplicationCommandInteraction, error: Exception
    ):
        """Global error handler for slash commands."""
        # Handle authorization / check failures
        if isinstance(error, commands.CheckFailure):
            try:
                msg = "❌ **Доступ запрещен**\nВы не зарегистрированы в системе."
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
            except Exception as e:
                self.logger.debug(f"Failed to send forbidden message: {e}")
            return

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
            except Exception as e:
                self.logger.debug(f"Failed to send cooldown message: {e}")
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
        except Exception as e:
            self.logger.debug(f"Failed to send error message: {e}")

    async def close(self):
        """Cleanup on shutdown."""
        if self.api_client:
            await self.api_client.close()
            self.logger.debug("✓ API client closed")

        if self.broker:
            await self.broker.disconnect()
            self.logger.debug("✓ Broker disconnected")

        await super().close()
