"""Admin Setup - Initial Server Configuration.
Handles /setup command for channel configuration.
Separate from guild settings which handles ongoing configuration (points, etc.)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api_client import APIClient
    from discord_bot import DiscordBot

import disnake
from disnake import MessageInteraction
from disnake.ext import commands
from utils import create_monitoring_select, create_streamers_component

from .core import AdminMainView, get_main_embed

# =============================================================================
# Setup Embed
# =============================================================================


def create_setup_embed(data: dict | None) -> disnake.Embed:
    """Create embed showing current channel configuration."""
    embed = disnake.Embed(
        title="🛠️ Первоначальная Настройка",
        colour=0x5865F2,
    )

    if data is None:
        data = {}

    embed.description = (
        "Настройте каналы и роли для работы бота.\n"
        "После настройки панель управления появится в выбранном канале."
    )

    embed.add_field(
        name="🔔 Канал для уведомлений",
        value=(
            f"<#{data['notification_channel_id']}>"
            if data.get("notification_channel_id")
            else "❌ Не настроен"
        ),
        inline=True,
    )

    embed.add_field(
        name="📊 Канал для мониторинга",
        value=(
            f"<#{data['monitoring_channel_id']}>"
            if data.get("monitoring_channel_id")
            else "❌ Не настроен"
        ),
        inline=True,
    )

    embed.add_field(
        name="📢 Канал логов PR",
        value=(
            f"<#{data['pr_actions_channel_id']}>"
            if data.get("pr_actions_channel_id")
            else "❌ Не настроен"
        ),
        inline=True,
    )

    embed.add_field(
        name="🎛️ Канал Панели",
        value=(
            f"<#{data.get('control_panel_channel_id')}>"
            if data.get("control_panel_channel_id")
            else "❌ Не настроен"
        ),
        inline=True,
    )

    return embed


# =============================================================================
# Component IDs
# =============================================================================
ID_SETUP_NOTIFICATION = "setup_channel_notification"
ID_SETUP_MON = "setup_channel_mon"
ID_SETUP_LOGS = "setup_channel_logs"
ID_SETUP_PANEL = "setup_channel_panel"

ID_SELECT_NOTIFICATION = "setup_sel_notification"
ID_SELECT_MON = "setup_sel_mon"
ID_SELECT_LOGS = "setup_sel_logs"
ID_SELECT_PANEL = "setup_sel_panel"

ID_BTN_BACK = "setup_btn_back"


# =============================================================================
# Views
# =============================================================================


class SetupMainView(disnake.ui.View):
    """Main view for /setup command - channel configuration."""

    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id

        # Row 0 - Channels
        self.add_item(
            disnake.ui.Button(
                label="🔔 Уведомления",
                custom_id=ID_SETUP_NOTIFICATION,
                style=disnake.ButtonStyle.primary,
                row=0,
            )
        )
        self.add_item(
            disnake.ui.Button(
                label="📊 Мониторинг",
                custom_id=ID_SETUP_MON,
                style=disnake.ButtonStyle.primary,
                row=0,
            )
        )
        self.add_item(
            disnake.ui.Button(
                label="📢 Логи PR",
                custom_id=ID_SETUP_LOGS,
                style=disnake.ButtonStyle.primary,
                row=0,
            )
        )

        # Row 1 - Panel
        self.add_item(
            disnake.ui.Button(
                label="🎛️ Панель",
                custom_id=ID_SETUP_PANEL,
                style=disnake.ButtonStyle.primary,
                row=1,
            )
        )


class SetupChannelSelectView(disnake.ui.View):
    """Generic channel select view for setup."""

    def __init__(self, user_id: int, select_custom_id: str):
        super().__init__(timeout=None)
        self.add_item(
            disnake.ui.ChannelSelect(
                custom_id=select_custom_id,
                channel_types=[disnake.ChannelType.text],
                placeholder="Выберите канал...",
                min_values=1,
                max_values=1,
            )
        )
        self.add_item(
            disnake.ui.Button(
                label="🔙 Назад",
                custom_id=ID_BTN_BACK,
                style=disnake.ButtonStyle.secondary,
                row=1,
            )
        )


# =============================================================================
# Admin Setup Cog
# =============================================================================


class AdminSetup(commands.Cog):
    """Initial server setup - channels configuration."""

    bot: "DiscordBot"
    api: "APIClient"

    def __init__(self, bot: "DiscordBot") -> None:
        self.bot = bot
        self.api = bot.api_client

    @commands.slash_command(
        name="setup", description="🛠️ Первоначальная настройка каналов и ролей"
    )
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def setup_command(
        self, interaction: disnake.ApplicationCommandInteraction
    ) -> None:
        """Initial setup - channels (only slash command allowed)."""
        if not interaction.author.guild_permissions.administrator:
            await interaction.response.send_message(
                "🚫 У вас нет прав администратора.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        data = await self.api.get_guild_settings()
        embed = create_setup_embed(data)
        await interaction.followup.send(
            embed=embed, view=SetupMainView(interaction.user.id), ephemeral=True
        )

    @commands.Cog.listener("on_button_click")
    async def on_setup_button_interaction(self, interaction: MessageInteraction):
        """Handle all setup buttons."""
        custom_id = interaction.component.custom_id or ""

        # Strict Filter - only handle setup_ prefixed buttons
        if not custom_id.startswith(("setup_channel_", "setup_btn_")):
            return

        # Safe Defer
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except Exception as e:
            self.bot.logger.warning(f"Defer failed: {e}")

        try:
            user_id = interaction.user.id

            # Back to setup main
            if custom_id == ID_BTN_BACK:
                data = await self.api.get_guild_settings()
                await interaction.edit_original_response(
                    embed=create_setup_embed(data),
                    view=SetupMainView(user_id),
                    content=None,
                )

            # Channel setup buttons
            elif custom_id == ID_SETUP_NOTIFICATION:
                await interaction.edit_original_response(
                    content="Выберите канал для уведомлений:",
                    embed=None,
                    view=SetupChannelSelectView(user_id, ID_SELECT_NOTIFICATION),
                )

            elif custom_id == ID_SETUP_MON:
                await interaction.edit_original_response(
                    content="Выберите канал для мониторинга:",
                    embed=None,
                    view=SetupChannelSelectView(user_id, ID_SELECT_MON),
                )

            elif custom_id == ID_SETUP_LOGS:
                await interaction.edit_original_response(
                    content="Выберите канал для логов PR:",
                    embed=None,
                    view=SetupChannelSelectView(user_id, ID_SELECT_LOGS),
                )

            elif custom_id == ID_SETUP_PANEL:
                await interaction.edit_original_response(
                    content="Выберите канал для Панели Управления:",
                    embed=None,
                    view=SetupChannelSelectView(user_id, ID_SELECT_PANEL),
                )

        except Exception as e:
            self.bot.logger.error(f"Setup button error {custom_id}: {e}", exc_info=True)
            try:
                await interaction.followup.send(f"❌ Ошибка: {e}", ephemeral=True)
            except:  # noqa: E722
                pass

    @commands.Cog.listener("on_dropdown")
    async def on_setup_dropdown_interaction(self, interaction: MessageInteraction):
        """Handle setup dropdowns."""
        custom_id = interaction.component.custom_id or ""

        if not custom_id.startswith("setup_sel_"):
            return

        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except:  # noqa: E722
            pass

        try:
            user_id = interaction.user.id
            val = interaction.values[0]

            async def back_to_main():
                data = await self.api.get_guild_settings()
                await interaction.edit_original_response(
                    embed=create_setup_embed(data),
                    view=SetupMainView(user_id),
                    content=None,
                )

            if custom_id == ID_SELECT_NOTIFICATION:
                await self.api.update_guild_settings(notification_channel_id=int(val))
                await back_to_main()
                await interaction.followup.send(
                    f"✅ Канал уведомлений: <#{val}>", ephemeral=True
                )

            elif custom_id == ID_SELECT_LOGS:
                await self.api.update_guild_settings(pr_actions_channel_id=int(val))
                await back_to_main()
                await interaction.followup.send(
                    f"✅ Канал логов: <#{val}>", ephemeral=True
                )

            elif custom_id == ID_SELECT_PANEL:
                channel_id = int(val)
                channel = self.bot.get_channel(channel_id)
                if channel:
                    try:
                        msg = await channel.send(
                            embed=get_main_embed(), view=AdminMainView(self.bot)
                        )
                        await self.api.update_guild_settings(
                            control_panel_channel_id=channel_id,
                            control_panel_message_id=msg.id,
                        )
                        await back_to_main()
                        await interaction.followup.send(
                            f"✅ Панель создана: <#{val}>", ephemeral=True
                        )
                    except Exception as e:
                        await interaction.followup.send(
                            f"❌ Ошибка создания панели: {e}", ephemeral=True
                        )
                else:
                    await interaction.followup.send(
                        "❌ Канал не найден.", ephemeral=True
                    )

            elif custom_id == ID_SELECT_MON:
                channel_id = int(val)
                channel = self.bot.get_channel(channel_id)
                if channel:
                    # Get monitoring status from API (includes available_for_claim)
                    status = await self.api.get_monitoring_status()
                    if not status:
                        await interaction.followup.send(
                            "❌ Не удалось получить данные.", ephemeral=True
                        )
                        return

                    online = status.get("online_streamers", [])
                    total_count = status.get("total_streamers", 0)
                    gta_count = status.get("gta_count", 0)
                    online_count = status.get("online_count", len(online))
                    available = status.get("available_for_claim", [])

                    pages = create_streamers_component(
                        online, total_count, gta_count, online_count=online_count
                    )
                    select_row = create_monitoring_select(available, [])

                    # Send all pages and collect message IDs
                    message_ids = []
                    for i, page in enumerate(pages):
                        if i == len(pages) - 1:
                            # Last page: include select row
                            msg = await channel.send(components=[page, select_row])
                        else:
                            msg = await channel.send(components=[page])
                        message_ids.append(msg.id)

                    await self.api.update_guild_settings(
                        monitoring_channel_id=channel_id,
                        monitoring_message_ids=message_ids,
                    )
                    await back_to_main()
                    await interaction.followup.send(
                        f"✅ Мониторинг настроен: <#{val}>", ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "❌ Канал не найден.", ephemeral=True
                    )

        except Exception as e:
            self.bot.logger.error(
                f"Setup dropdown error {custom_id}: {e}", exc_info=True
            )
            try:
                await interaction.followup.send(f"❌ Ошибка: {e}", ephemeral=True)
            except:  # noqa: E722
                pass


def setup(bot: commands.Bot) -> None:
    bot.add_cog(AdminSetup(bot))
