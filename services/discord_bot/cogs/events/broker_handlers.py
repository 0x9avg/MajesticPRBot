"""Broker Event Handlers - RabbitMQ message processing.
Handles all broker events (stream state, spec, monitoring).
"""

import disnake
from config import Config
from disnake.ext import commands
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

        @broker.on("stream.state.online")
        async def on_stream_online(data):
            self.logger.info(f"Event: stream online - {data.get('streamer_name')}")
            # Determine notification type based on game category
            game_id = str(data.get("game_id", ""))
            if game_id == Config.gta5_game_id:
                await self._handle_notification("stream_online_gta", data)
            else:
                await self._handle_notification("stream_online_other", data)

        @broker.on("stream.state.offline")
        async def on_stream_offline(data):
            self.logger.info(f"Event: stream offline - {data.get('streamer_name')}")
            await self._handle_notification("stream_offline", data)

        @broker.on("stream.state.category")
        async def on_category_change(data):
            old_id = data.get("old_game_id")
            new_id = data.get("new_game_id")

            self.logger.info(
                f"DEBUG Handler: {data.get('streamer_name')} | Old: {old_id} | New: {new_id} | GTA: {Config.gta5_game_id} | NewName: {data.get('new_game_name')}"
            )



            if (
                str(new_id) == Config.gta5_game_id
                and str(old_id) != Config.gta5_game_id
            ):
                self.logger.info("-> Sending category_to_gta")
                await self._handle_notification("category_to_gta", data)
            elif (
                str(old_id) == Config.gta5_game_id
                and str(new_id) != Config.gta5_game_id
            ):
                self.logger.info("-> Sending category_from_gta")
                await self._handle_notification("category_from_gta", data)

        @broker.on("spec.*")
        async def on_spec_event(data):
            event = data.get("event", "")
            self.logger.info(f"Event: spec - {event}")

            if event == "spec.claimed":
                await self._log_pr_claim(data)
            elif event == "spec.unclaimed":
                await self._log_pr_unclaim(data)


        @broker.on("event.*")
        async def on_event_action(data):
            event = data.get("event", "")
            self.logger.info(f"Event: event action - {event}")

            if event == "event.joined":
                await self._log_event_join(data)
            elif event == "event.left":
                await self._log_event_leave(data)

        self.logger.debug("✓ Broker handlers registered")



    async def _handle_notification(self, event_type: str, data: dict):
        """Delegate notification handling to Notifications cog."""
        notifications = self.bot.get_cog("Notifications")
        if notifications:
            await notifications.handle_stream_event(event_type, data)

    async def _log_pr_claim(self, data: dict):
        """Log PR claim action to PR actions channel using UI Components."""
        try:
            streamer_name = data.get("streamer_name", "Unknown")
            pr_id = data.get("pr_id")
            
            # Retrieve the is_probation flag passed by the API backend
            is_probation = data.get("data", {}).get("is_probation", False)
            
            slot_type = "🟡 Стажерский" if is_probation else "🟢 Основной"
            color = disnake.Colour(3066993) if not is_probation else disnake.Colour(16763904) # Green / Yellow

            container = disnake.ui.Container(
                disnake.ui.TextDisplay(content="### 📥 Закрепление"),
                disnake.ui.TextDisplay(
                    content=f"👤 **Стример:** {streamer_name}\n"
                            f"🎯 **PR:** <@{pr_id}>\n"
                            f"🏷 **Слот:** {slot_type}"
                ),
                accent_colour=color
            )

            await send_pr_action_log(self.bot, components=[container])
            self.logger.debug(f"PR claim logged: {streamer_name} -> {pr_id} (Probation: {is_probation})")

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
                color = disnake.Colour(9807270) # Dark Gray
            elif reason == "category_change":
                emoji = "🔄"
                title = "Смена категории (выход из GTA)"
                color = disnake.Colour(15105570) # Orange
            else:
                emoji = "📤"
                title = "Откреплен"
                color = disnake.Colour(15158332) # Red

            container = disnake.ui.Container(
                disnake.ui.TextDisplay(content=f"### {emoji} {title}"),
                disnake.ui.TextDisplay(
                    content=f"👤 **Стример:** {streamer_name}\n"
                            f"🎯 **PR:** <@{pr_id}>\n"
                            f"⏱️ **Время спека:** {duration_str}"
                ),
                accent_colour=color
            )

            await send_pr_action_log(self.bot, components=[container])
            self.logger.debug(f"PR unclaim logged: {title} - {streamer_name}")

        except Exception as e:
            self.logger.error(f"Failed to log PR unclaim: {e}")



    async def _log_event_join(self, data: dict):
        """Log event join action to PR actions channel."""
        try:
            event_name = data.get("event_name", "Unknown")
            pr_id = data.get("pr_id")

            container = disnake.ui.Container(
                disnake.ui.TextDisplay(content="### 📥 Закрепление за событием"),
                disnake.ui.TextDisplay(
                    content=f"📅 **Событие:** {event_name}\n"
                            f"🎯 **PR:** <@{pr_id}>"
                ),
                accent_colour=disnake.Colour(10181046)  # Purple
            )

            await send_pr_action_log(self.bot, components=[container])
            self.logger.debug(f"Event join logged: {event_name} -> {pr_id}")

        except Exception as e:
            self.logger.error(f"Failed to log event join: {e}")

    async def _log_event_leave(self, data: dict):
        """Log event leave action to PR actions channel."""
        try:
            event_name = data.get("event_name", "Unknown")
            pr_id = data.get("pr_id")
            duration_seconds = data.get("duration_seconds", 0)

            duration_str = format_spec_duration(duration_seconds)

            container = disnake.ui.Container(
                disnake.ui.TextDisplay(content="### 📤 Открепление от события"),
                disnake.ui.TextDisplay(
                    content=f"📅 **Событие:** {event_name}\n"
                            f"🎯 **PR:** <@{pr_id}>\n"
                            f"⏱️ **Время:** {duration_str}"
                ),
                accent_colour=disnake.Colour(9807270)  # Dark Gray
            )

            await send_pr_action_log(self.bot, components=[container])
            self.logger.debug(f"Event leave logged: {event_name} <- {pr_id}")

        except Exception as e:
            self.logger.error(f"Failed to log event leave: {e}")


def setup(bot: commands.Bot) -> None:
    bot.add_cog(BrokerHandlers(bot))
