"""Admin Notifications - Template Management.
Edit notification templates for stream events.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...api_client import APIClient
    from ...discord_bot import DiscordBot

import disnake
from disnake import MessageInteraction
from disnake.ext import commands


# =============================================================================
# Constants
# =============================================================================

EVENT_TYPES = {
    "stream_online": "🟢 Стрим начался",
    "stream_offline": "🔴 Стрим закончился",
    "category_to_gta": "🎮 Смена на GTA 5",
    "category_from_gta": "🚫 Уход с GTA 5",
}

# Default templates used when no custom template is set
DEFAULT_TEMPLATES = {
    "stream_online": "🟢 **{streamer_name}** начал стрим!",
    "stream_offline": "🔴 **{streamer_name}** закончил стрим.",
    "category_to_gta": "🎮 **{streamer_name}** сменил категорию на **GTA 5**!",
    "category_from_gta": "🚫 **{streamer_name}** ушёл с GTA 5.",
}


# =============================================================================
# Notifications Embed
# =============================================================================


def get_notifications_embed() -> disnake.Embed:
    """Create embed for notifications settings."""
    embed = disnake.Embed(
        title="🔔 Настройка Уведомлений",
        description=(
            "Выберите шаблон для редактирования.\n\n"
            "**Доступные переменные:**\n"
            "`{streamer_name}` — имя стримера\n"
            "`{stream_title}` — название стрима\n"
            "`{game_name}` — название игры\n"
            "`{streamer_link}` — ссылка на канал"
        ),
        color=0xE91E63,
    )
    return embed


# =============================================================================
# Template Edit Modal
# =============================================================================


class TemplateEditModal(disnake.ui.Modal):
    """Modal for editing notification template."""

    def __init__(self, bot, event_type: str, current_template: str):
        self.bot = bot
        self.event_type = event_type

        label = EVENT_TYPES.get(event_type, event_type)
        title = f"Редактировать: {label}"
        if len(title) > 45:
            title = title[:42] + "..."

        components = [
            disnake.ui.TextInput(
                label="Шаблон уведомления",
                placeholder="Введите текст уведомления",
                custom_id="template_input",
                style=disnake.TextInputStyle.paragraph,
                value=current_template,
                required=True,
                max_length=500,
            ),
        ]
        super().__init__(title=title, components=components)

    async def callback(self, interaction: disnake.ModalInteraction):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        try:
            new_template = interaction.text_values["template_input"]
            await self.bot.api_client.update_guild_templates(
                {self.event_type: new_template}
            )
            label = EVENT_TYPES.get(self.event_type, self.event_type)
            await interaction.edit_original_message(
                content=f"✅ Шаблон для **{label}** обновлён!"
            )
        except Exception as e:
            self.bot.logger.error(f"Template update error: {e}")
            await interaction.edit_original_message(content="❌ Ошибка")


# =============================================================================
# Template Select
# =============================================================================


class TemplateSelect(disnake.ui.StringSelect):
    """Select for choosing template to edit."""

    def __init__(self):
        options = [
            disnake.SelectOption(
                label=label.split(" ", 1)[1] if " " in label else label,
                value=event_type,
                emoji=label.split()[0] if " " in label else "📝",
            )
            for event_type, label in EVENT_TYPES.items()
        ]
        super().__init__(
            custom_id="admin_notif_template_select",
            placeholder="Выберите шаблон...",
            options=options,
        )


# =============================================================================
# Notifications View
# =============================================================================


class NotificationsView(disnake.ui.View):
    """View for notification template management."""

    bot: "DiscordBot"

    def __init__(self, bot: "DiscordBot"):
        super().__init__(timeout=None)
        self.bot = bot
        self.add_item(TemplateSelect())

        # Buttons
        self.add_item(
            disnake.ui.Button(
                label="Тест 🟢",
                custom_id="admin_notif_test_on",
                style=disnake.ButtonStyle.secondary,
                row=1,
            )
        )

        self.add_item(
            disnake.ui.Button(
                label="Тест 🔴",
                custom_id="admin_notif_test_off",
                style=disnake.ButtonStyle.secondary,
                row=1,
            )
        )

        self.add_item(
            disnake.ui.Button(
                label="Назад",
                custom_id="admin_notif_back",
                style=disnake.ButtonStyle.secondary,
                emoji="🔙",
                row=2,
            )
        )


# =============================================================================
# Admin Notifications Cog
# =============================================================================


class AdminNotifications(commands.Cog):
    """Notification template management."""

    bot: "DiscordBot"
    api: "APIClient"

    def __init__(self, bot: "DiscordBot") -> None:
        self.bot = bot
        self.api = bot.api_client

    @commands.Cog.listener("on_button_click")
    async def on_notifications_button(self, interaction: MessageInteraction):
        """Handle admin_notifications and sub-buttons."""
        custom_id = interaction.component.custom_id or ""

        # 1. STRICT FILTER
        if not custom_id.startswith("admin_notifications") and not custom_id.startswith(
            "admin_notif_"
        ):
            return

        # 2. SAFE DEFER
        # All buttons currently defer (tests, back, entry). None open modal directly (dropdown does).
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except Exception as e:
            self.bot.logger.warning(f"Failed to defer {custom_id}: {e}")

        # 3. EXECUTE
        try:
            if custom_id == "admin_notifications":
                await interaction.edit_original_response(
                    embed=get_notifications_embed(),
                    view=NotificationsView(self.bot),
                )

            elif custom_id == "admin_notif_back":
                from .core import AdminMainView, get_main_embed

                await interaction.edit_original_response(
                    embed=get_main_embed(), view=AdminMainView(self.bot)
                )

            elif custom_id in ["admin_notif_test_on", "admin_notif_test_off"]:
                # Get settings checks logic
                settings = await self.bot.api_client.get_guild_settings()
                channel_id = (
                    settings.get("notification_channel_id") if settings else None
                )

                if not channel_id:
                    await interaction.followup.send(
                        "❌ Канал уведомлений не настроен", ephemeral=True
                    )
                    return

                channel = self.bot.get_channel(int(channel_id))
                if not channel:
                    await interaction.followup.send(
                        "❌ Канал не найден", ephemeral=True
                    )
                    return

                templates = settings.get("notification_templates", "{}")

                if custom_id == "admin_notif_test_on":
                    template = templates.get(
                        "stream_online", "🟢 **{streamer_name}** начал стрим!"
                    )
                else:
                    template = templates.get(
                        "stream_offline", "🔴 **{streamer_name}** закончил стрим"
                    )

                test_msg = template.format(
                    streamer_name="TestStreamer",
                    stream_title="Тестовый стрим",
                    game_name="Grand Theft Auto V",
                    streamer_link="https://twitch.tv/teststreamer",
                )

                await channel.send(f"[ТЕСТ] {test_msg}", delete_after=30)
                await interaction.followup.send(
                    "✅ Тестовое уведомление отправлено!", ephemeral=True
                )

        except Exception as e:
            self.bot.logger.error(
                f"Error handling notification button {custom_id}: {e}", exc_info=True
            )
            try:
                await interaction.followup.send(
                    "❌ Произошла ошибка обработки.", ephemeral=True
                )
            except:
                pass

    @commands.Cog.listener("on_dropdown")
    async def on_notifications_dropdown(self, interaction: MessageInteraction):
        """Handle notification template select."""
        custom_id = interaction.component.custom_id or ""

        if custom_id != "admin_notif_template_select":
            return

        # Select opens MODAL -> NO DEFER

        try:
            event_type = interaction.values[0]

            # Get current template (fallback to default if empty)
            try:
                settings = await self.bot.api_client.get_guild_settings()
                templates = (
                    settings.get("notification_templates", {}) if settings else {}
                )
                current = templates.get(event_type) or DEFAULT_TEMPLATES.get(
                    event_type, ""
                )
            except Exception:
                current = DEFAULT_TEMPLATES.get(event_type, "")

            # Open Modal
            await interaction.response.send_modal(
                TemplateEditModal(self.bot, event_type, current)
            )
        except Exception as e:
            self.bot.logger.error(
                f"Error handling notification dropdown: {e}", exc_info=True
            )
            # Cannot reply if modal fail? Or try ephemeral msg
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ Ошибка.", ephemeral=True
                    )
            except:
                pass


def setup(bot: commands.Bot) -> None:
    bot.add_cog(AdminNotifications(bot))
