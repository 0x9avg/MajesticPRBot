"""Events Handlers - Event Join/Leave Buttons."""

import disnake
from disnake import MessageInteraction
from disnake.ext import commands
from utils import format_spec_duration, send_pr_action_log

EVENT_JOIN_PERMS = ["events.participation.self.join"]
EVENT_LEAVE_PERMS = ["events.participation.self.leave"]


class EventsHandlers(commands.Cog):
    """Event button handlers for join/leave."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.api = bot.api_client

    @staticmethod
    def _extract_api_error(result) -> str | None:
        """Extract readable error text from API response."""
        if result is None:
            return "API недоступно"

        if not isinstance(result, dict):
            return "Некорректный ответ API"

        status = result.get("status")
        if status and status != "success":
            return str(result.get("message") or result.get("detail") or "Ошибка API")

        if result.get("error"):
            return str(result["error"])

        if "detail" in result and "event_id" not in result:
            return str(result["detail"])

        return None

    async def _update_event_message(self, event_id: int):
        """Legacy no-op: event message linkage is no longer part of event payload."""
        return None

    async def _send_pr_action(self, message: str):
        """Send message to PR actions log channel."""
        await send_pr_action_log(self.bot, message)

    @commands.Cog.listener("on_button_click")
    async def on_event_button(self, interaction: MessageInteraction):
        """Handle event join/leave buttons."""
        custom_id = interaction.component.custom_id or ""


        if not custom_id.startswith(("event_join_", "event_leave_")):
            return


        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except Exception as e:
            self.bot.logger.warning(f"Failed to defer {custom_id}: {e}")


        try:
            if custom_id.startswith("event_join_"):
                event_id = int(custom_id.replace("event_join_", ""))
                await self._handle_event_join(interaction, event_id)
            elif custom_id.startswith("event_leave_"):
                event_id = int(custom_id.replace("event_leave_", ""))
                await self._handle_event_leave(interaction, event_id)
        except Exception as e:
            self.bot.logger.error(
                f"Error handling event button {custom_id}: {e}", exc_info=True
            )
            try:
                await interaction.followup.send(
                    f"❌ Произошла ошибка обработки: {e}", ephemeral=True
                )
            except Exception as e:
                self.bot.logger.debug(f"Failed to send error response: {e}")

    async def _handle_event_join(self, interaction: MessageInteraction, event_id: int):
        """Handle user joining an event."""
        if not await self.bot.ensure_user_permissions(
            interaction,
            require_any=EVENT_JOIN_PERMS,
            error_message="❌ Нет прав на присоединение к событиям.",
        ):
            return

        user_id = interaction.user.id

        try:
            # Check if already joined
            result = await self.api.join_event(event_id, user_id)
            error_message = self._extract_api_error(result)
            if error_message:
                await interaction.followup.send(f"❌ {error_message}", ephemeral=True)
                return

            if isinstance(result, dict) and result.get("already_joined"):
                # Already in event - offer to leave
                leave_btn = disnake.ui.Button(
                    label="Покинуть событие",
                    custom_id=f"event_leave_{event_id}",
                    style=disnake.ButtonStyle.danger,
                    emoji="🚪",
                )
                view = disnake.ui.View(timeout=None)
                view.add_item(leave_btn)
                await interaction.followup.send(
                    "ℹ️ Вы уже участвуете в этом событии.", view=view, ephemeral=True
                )
                return

            if not isinstance(result, dict):
                await interaction.followup.send(
                    "❌ Некорректный ответ API при входе в событие", ephemeral=True
                )
                return

            if str(result.get("event_id")) != str(event_id) or str(
                result.get("pr_id")
            ) != str(user_id):
                await interaction.followup.send(
                    "❌ API вернул неполный ответ при входе в событие",
                    ephemeral=True,
                )
                return

            await interaction.followup.send(
                "✅ Вы присоединились к событию!", ephemeral=True
            )

            # Update event message
            await self._update_event_message(event_id)

            # Log to PR actions
            event = await self.api.get_event(event_id)
            if event:
                await self._send_pr_action(
                    f"📥 **Присоединение к событию**\n"
                    f"📅 Событие: **{event.get('name')}**\n"
                    f"🎯 PR: <@{user_id}>",
                )

        except Exception as e:
            self.bot.logger.error(f"Event join error: {e}")
            await interaction.followup.send(f"❌ Ошибка: {e}", ephemeral=True)

    async def _handle_event_leave(self, interaction: MessageInteraction, event_id: int):
        """Handle user leaving an event."""
        if not await self.bot.ensure_user_permissions(
            interaction,
            require_any=EVENT_LEAVE_PERMS,
            error_message="❌ Нет прав на выход из событий.",
        ):
            return

        user_id = interaction.user.id

        try:
            result = await self.api.leave_event(event_id, user_id)
            error_message = self._extract_api_error(result)
            if error_message:
                await interaction.followup.send(f"❌ {error_message}", ephemeral=True)
                return

            if not isinstance(result, dict):
                await interaction.followup.send(
                    "❌ Некорректный ответ API при выходе из события", ephemeral=True
                )
                return

            if str(result.get("event_id")) != str(event_id) or str(
                result.get("pr_id")
            ) != str(user_id):
                await interaction.followup.send(
                    "❌ API вернул неполный ответ при выходе из события",
                    ephemeral=True,
                )
                return

            duration = result.get("duration", 0)
            duration_str = format_spec_duration(duration) if duration else "0м"

            await interaction.followup.send(
                f"✅ Вы покинули событие. Время: **{duration_str}**", ephemeral=True
            )

            # Update event message
            await self._update_event_message(event_id)

            # Log to PR actions
            event = await self.api.get_event(event_id)
            if event:
                await self._send_pr_action(
                    f"📤 **Выход из события**\n"
                    f"📅 Событие: **{event.get('name')}**\n"
                    f"🎯 PR: <@{user_id}>\n"
                    f"⏱️ Время: **{duration_str}**",
                )

        except Exception as e:
            self.bot.logger.error(f"Event leave error: {e}")
            await interaction.followup.send(f"❌ Ошибка: {e}", ephemeral=True)


def setup(bot: commands.Bot) -> None:
    bot.add_cog(EventsHandlers(bot))
