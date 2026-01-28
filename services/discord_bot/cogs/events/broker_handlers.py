"""Broker Event Handlers - RabbitMQ message processing.
Handles all broker events (stream state, spec, monitoring).
"""

from disnake.ext import commands

from config import Config
from utils import format_spec_duration, send_pr_action_log


class BrokerHandlers(commands.Cog):
    """RabbitMQ broker event handlers."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.logger = bot.logger
        self._handlers_registered = False

    @commands.Cog.listener()
    async def on_ready(self):
        """Register handlers when bot is ready and broker is connected."""
        if self._handlers_registered or not self.bot.broker:
            return
        
        self._register_handlers()
        self._handlers_registered = True

    def _register_handlers(self):
        """Register all broker event handlers."""
        broker = self.bot.broker

        @broker.on("streamer.added")
        async def on_streamer_added(data):
            self.logger.info(f"Event: streamer.added - {data.get('streamer_name')}")
            await self._refresh_monitoring()

        @broker.on("streamer.removed")
        async def on_streamer_removed(data):
            self.logger.info(f"Event: streamer.removed - {data.get('streamer_name')}")
            await self._refresh_monitoring()

        @broker.on("stream.state.online")
        async def on_stream_online(data):
            self.logger.info(f"Event: stream online - {data.get('streamer_name')}")
            await self._refresh_monitoring()
            await self._handle_notification("stream_online", data)

        @broker.on("stream.state.offline")
        async def on_stream_offline(data):
            self.logger.info(f"Event: stream offline - {data.get('streamer_name')}")
            await self._refresh_monitoring()
            await self._handle_notification("stream_offline", data)

        @broker.on("stream.state.category")
        async def on_category_change(data):
            old_id = data.get("old_game_id")
            new_id = data.get("new_game_id")
            
            self.logger.info(
                f"DEBUG Handler: {data.get('streamer_name')} | Old: {old_id} | New: {new_id} | GTA: {Config.GTA5_GAME_ID} | NewName: {data.get('new_game_name')}"
            )
            
            await self._refresh_monitoring()

            if str(new_id) == Config.GTA5_GAME_ID and str(old_id) != Config.GTA5_GAME_ID:
                self.logger.info("-> Sending category_to_gta")
                await self._handle_notification("category_to_gta", data)
            elif str(old_id) == Config.GTA5_GAME_ID and str(new_id) != Config.GTA5_GAME_ID:
                self.logger.info("-> Sending category_from_gta")
                await self._handle_notification("category_from_gta", data)

        @broker.on("spec.*")
        async def on_spec_event(data):
            event = data.get("event", "")
            self.logger.info(f"Event: spec - {event}")
            await self._refresh_monitoring()

            if event == "spec.claimed":
                await self._log_pr_claim(data)
            elif event == "spec.unclaimed":
                await self._log_pr_unclaim(data)
            elif event == "spec.transferred":
                await self._log_pr_transfer(data)

        @broker.on("monitoring.refresh")
        async def on_monitoring_refresh(data):
            self.logger.info("Event: monitoring.refresh")
            await self._refresh_monitoring()

        self.logger.debug("✓ Broker handlers registered")

    async def _refresh_monitoring(self):
        """Refresh monitoring message via Spec cog."""
        try:
            spec_cog = self.bot.get_cog("Spec")
            if spec_cog:
                await spec_cog.update_monitoring()
            else:
                self.logger.warning("Spec cog not loaded, skipping monitoring refresh")
        except Exception as e:
            self.logger.error(f"Failed to refresh monitoring: {e}")

    async def _handle_notification(self, event_type: str, data: dict):
        """Delegate notification handling to Notifications cog."""
        notifications = self.bot.get_cog("Notifications")
        if notifications:
            await notifications.handle_stream_event(event_type, data)

    async def _log_pr_claim(self, data: dict):
        """Log PR claim action to PR actions channel."""
        try:
            streamer_name = data.get("streamer_name", "Unknown")
            pr_id = data.get("pr_id")
            
            message = (
                f"📥 **Закрепление**\n"
                f"👤 Стример: **{streamer_name}**\n"
                f"🎯 PR: <@{pr_id}>"
            )
            
            await send_pr_action_log(self.bot, message)
            self.logger.debug(f"PR claim logged: {streamer_name} -> {pr_id}")
            
        except Exception as e:
            self.logger.error(f"Failed to log PR claim: {e}")

    async def _log_pr_unclaim(self, data: dict):
        """Log PR unclaim action to PR actions channel."""
        try:
            streamer_name = data.get("streamer_name", "Unknown")
            pr_id = data.get("pr_id")
            duration_seconds = data.get("duration_seconds", 0)
            reason = data.get("reason", "unknown")
            
            duration_str = format_spec_duration(duration_seconds)
            
            if reason == "stream_end":
                emoji = "⚫"
                title = "Стрим завершен"
            elif reason == "category_change":
                emoji = "🔄"
                title = "Смена категории (выход из GTA)"
            else:
                emoji = "📤"
                title = "Откреплен"
            
            message = (
                f"{emoji} **{title}**\n"
                f"👤 Стример: **{streamer_name}**\n"
                f"🎯 PR: <@{pr_id}>\n"
                f"⏱️ Спек: **{duration_str}**"
            )
            
            await send_pr_action_log(self.bot, message)
            self.logger.debug(f"PR unclaim logged: {title} - {streamer_name}")
            
        except Exception as e:
            self.logger.error(f"Failed to log PR unclaim: {e}")

    async def _log_pr_transfer(self, data: dict):
        """Log PR transfer action to PR actions channel."""
        try:
            streamer_name = data.get("streamer_name", "Unknown")
            from_pr_id = data.get("from_pr_id")
            to_pr_id = data.get("to_pr_id")
            duration_seconds = data.get("duration_seconds", 0)
            
            duration_str = format_spec_duration(duration_seconds)
            
            # Unclaim message
            await send_pr_action_log(
                self.bot,
                f"📤 **Открепление (передача)**\n"
                f"👤 Стример: **{streamer_name}**\n"
                f"🎯 PR: <@{from_pr_id}>\n"
                f"⏱️ Спек: **{duration_str}**"
            )
            
            # Claim message
            await send_pr_action_log(
                self.bot,
                f"📥 **Закрепление (передача)**\n"
                f"👤 Стример: **{streamer_name}**\n"
                f"🎯 PR: <@{to_pr_id}>"
            )
            
            self.logger.debug(f"PR transfer logged: {streamer_name} {from_pr_id} -> {to_pr_id}")
            
        except Exception as e:
            self.logger.error(f"Failed to log PR transfer: {e}")


def setup(bot: commands.Bot) -> None:
    bot.add_cog(BrokerHandlers(bot))
