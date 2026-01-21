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
            self.load_extensions("cogs")
            self.logger.info("✓ All cogs loaded")
        except Exception as e:
            self.logger.error(f"Error loading cogs: {e}", exc_info=True)
            raise
    
    async def start_bot(self):
        """Start the bot with token from config."""
        await self.start(Config.DISCORD_TOKEN)
    
    async def on_ready(self):
        """Called when bot is ready."""
        self.logger.info(f"✓ Discord bot ready as {self.user}")
        self.logger.info(f"Bot ID: {self.user.id}, Guilds: {len(self.guilds)}")
        
        # Check target guild
        guild = self.get_guild(Config.GUILD_ID)
        if guild:
            self.logger.info(f"✓ Connected to target guild: {guild.name}")
        else:
            self.logger.error(f"⚠ Bot is NOT in target guild {Config.GUILD_ID}!")
        
        # Start broker consumer if available
        if self.broker:
            try:
                await self.broker.connect()
                self._register_broker_handlers()
                await self.broker.consume_in_background()
                self.logger.info("✓ Broker consumer started")
            except Exception as e:
                self.logger.warning(f"Broker unavailable: {e}")
    
    async def on_slash_command_error(self, interaction: disnake.ApplicationCommandInteraction, error: Exception):
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
                color=disnake.Color.orange()
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
    
    def _register_broker_handlers(self):
        """Register handlers for broker events."""
        if not self.broker:
            return
        
        @self.broker.on("streamer.added")
        async def on_streamer_added(data):
            self.logger.info(f"Event: streamer.added - {data.get('streamer_name')}")
            await self._refresh_monitoring()
        
        @self.broker.on("streamer.removed")
        async def on_streamer_removed(data):
            self.logger.info(f"Event: streamer.removed - {data.get('streamer_name')}")
            await self._refresh_monitoring()
        
        @self.broker.on("stream.state.online")
        async def on_stream_online(data):
            self.logger.info(f"Event: stream online - {data.get('streamer_name')}")
            await self._refresh_monitoring()
            
            notifications = self.get_cog("Notifications")
            if notifications:
                await notifications.handle_stream_event("stream_online", data)

        @self.broker.on("stream.state.offline")
        async def on_stream_offline(data):
            self.logger.info(f"Event: stream offline - {data.get('streamer_name')}")
            await self._refresh_monitoring()
            
            notifications = self.get_cog("Notifications")
            if notifications:
                await notifications.handle_stream_event("stream_offline", data)
        
        @self.broker.on("stream.state.category")
        async def on_category_change(data):
            # This routing key wasn't explicitly bound in broker_consumer.py bindings list?
            # broker_consumer had "stream.state.*" which covers it.
            # But the consumer logic iterates handlers. pattern "stream.state.*" matches "stream.state.category"?
            # Let's check regex/pattern match in broker_consumer.
            # "stream.state.*" matches "stream.state.category" IF "*" means one word.
            # Usually rabbitmq "*" is one word, "#" is zero or more.
            # "stream.state.category" has 3 parts. "stream.state.*" has 3 parts if * is category.
            # Yes.
            
            self.logger.info(f"Event: category - {data.get('streamer_name')} -> {data.get('new_game_name')}")
            await self._refresh_monitoring()
            
            notifications = self.get_cog("Notifications")
            if notifications:
                # Check for GTA transition events logic is inside Notifications? 
                # No, broker publisher emits specific event? 
                # TwitchBot broker publisher emits "stream.state.category" AND logs "Category change ... -> GTA 5".
                # But it passes "old_game_id" and "new_game_id".
                # So we need to determine event type here or in Cog.
                
                # Let's rely on data analysis in Cog? Or here?
                # Let's do it here or pass plain 'category_change' and let Cog decide?
                # Cog 'handle_stream_event' takes event_type string.
                
                # Determine subtype
                old_id = data.get("old_game_id")
                new_id = data.get("new_game_id")
                gta_id = Config.GTA5_GAME_ID # Need import? Config is available in this file.
                
                evt = "category_change"
                if str(new_id) == Config.GTA5_GAME_ID and str(old_id) != Config.GTA5_GAME_ID:
                    evt = "category_to_gta"
                elif str(old_id) == Config.GTA5_GAME_ID and str(new_id) != Config.GTA5_GAME_ID:
                    evt = "category_from_gta"
                
                await notifications.handle_stream_event(evt, data)
        
        @self.broker.on("spec.*")
        async def on_spec_event(data):
            self.logger.info(f"Event: spec - {data.get('event')}")
            await self._refresh_monitoring()
        
        @self.broker.on("monitoring.refresh")
        async def on_monitoring_refresh(data):
            self.logger.info("Event: monitoring.refresh")
            await self._refresh_monitoring()
    
    async def _refresh_monitoring(self):
        """Refresh monitoring message via Dashboard cog."""
        try:
            dashboard_cog = self.get_cog("Dashboard")
            if dashboard_cog:
                await dashboard_cog.update_monitoring_message()
            else:
                self.logger.warning("Dashboard cog not loaded, skipping monitoring refresh")
        except Exception as e:
            self.logger.error(f"Failed to refresh monitoring: {e}")
    
    async def close(self):
        """Cleanup on shutdown."""
        if self.api_client:
            await self.api_client.close()
            self.logger.debug("✓ API client closed")
        
        if self.broker:
            await self.broker.disconnect()
            self.logger.debug("✓ Broker disconnected")
        
        await super().close()
