"""Admin Core - Main Dashboard View.
Entry point for the admin panel with navigation to sub-menus.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...api_client import APIClient
    from ...discord_bot import DiscordBot

import disnake
from disnake import MessageInteraction
from disnake.ext import commands


class AdminMainView(disnake.ui.View):
    """Persistent main menu for Admin Dashboard."""

    bot: "DiscordBot"

    def __init__(self, bot: "DiscordBot"):
        super().__init__(timeout=None)
        self.bot = bot

        # Row 1 - Secondary categories
        self.add_item(
            disnake.ui.Button(
                label="Уведомления",
                custom_id="admin_notifications",
                emoji="🔔",
                row=0,
                style=disnake.ButtonStyle.secondary,
            )
        )

        self.add_item(
            disnake.ui.Button(
                label="Стримеры",
                custom_id="admin_streamers",
                emoji="🎥",
                row=0,
                style=disnake.ButtonStyle.secondary,
            )
        )
        self.add_item(
            disnake.ui.Button(
                label="Ассистенты",
                custom_id="admin_assistants",
                emoji="👥",
                row=0,
                style=disnake.ButtonStyle.secondary,
            )
        )

        self.add_item(
            disnake.ui.Button(
                label="События",
                custom_id="admin_events",
                emoji="🎉",
                row=1,
                style=disnake.ButtonStyle.secondary,
            )
        )
        self.add_item(
            disnake.ui.Button(
                label="Сервис",
                custom_id="admin_service",
                emoji="🛠️",
                row=1,
                style=disnake.ButtonStyle.secondary,
            )
        )


def get_main_embed() -> disnake.Embed:
    """Create main admin panel embed."""
    return disnake.Embed(
        title="🔧 Панель Управления",
        description=(
            "Добро пожаловать в панель управления ботом.\n"
            "Выберите категорию настроек ниже.\n\n"
            "**Доступные разделы:**\n"
            "⚙️ **Сервер** — каналы, роли, баллы\n"
            "🎥 **Стримеры** — добавление, редактирование\n"
            "👥 **Ассистенты** — статистика, управление\n"
            "🔔 **Уведомления** — шаблоны сообщений\n"
            "🎉 **События** — создание и управление\n"
            "🛠️ **Сервис** — техническое обслуживание"
        ),
        color=0x2B2D31,
    )


class AdminCore(commands.Cog):
    """Core Admin Dashboard - Main Menu and Navigation."""

    bot: "DiscordBot"
    api: "APIClient"

    def __init__(self, bot: "DiscordBot") -> None:
        self.bot = bot
        self.api = bot.api_client

    @commands.Cog.listener()
    async def on_ready(self):
        """Register persistent view and recreate control panel on bot start."""
        self.bot.add_view(AdminMainView(self.bot))
        self.bot.logger.info("✓ AdminMainView registered")

        # Recreate control panel message
        await self._recreate_control_panel()

    async def _recreate_control_panel(self):
        """Delete old control panel and create a new one."""
        try:
            settings = await self.api.get_guild_settings()
            if not settings:
                return

            cp_channel_id = settings.get("control_panel_channel_id")
            if not cp_channel_id:
                return

            channel = self.bot.get_channel(int(cp_channel_id))
            if not channel:
                self.bot.logger.warning("Control panel channel not found")
                return

            # Update old message
            old_msg_id = settings.get("control_panel_message_id")
            old_msg = await channel.fetch_message(int(old_msg_id))

            if old_msg:
                try:
                    embed = get_main_embed()
                    await old_msg.edit(embed=embed, view=AdminMainView(self.bot))
                    self.bot.logger.debug(
                        "✓ Updated old control panel message in #{channel.name}"
                    )
                except Exception:
                    pass

            else:
                # Create new panel
                embed = get_main_embed()
                msg = await channel.send(embed=embed, view=AdminMainView(self.bot))

                # Update message ID in DB
                await self.api.update_guild_settings(control_panel_message_id=msg.id)
                self.bot.logger.debug(f"✓ Control panel recreated in #{channel.name}")

        except Exception as e:
            self.bot.logger.error(f"Failed to recreate control panel: {e}")

    @commands.Cog.listener("on_button_click")
    async def on_admin_button(self, interaction: MessageInteraction):
        """Handle admin navigation buttons."""
        custom_id = interaction.component.custom_id
        if custom_id != "admin_home":
            return

        # Back to main menu
        if custom_id == "admin_home":
            if not interaction.response.is_done():
                await interaction.response.defer()
            await interaction.edit_original_response(
                embed=get_main_embed(), view=AdminMainView(self.bot)
            )
            return


def setup(bot: commands.Bot) -> None:
    bot.add_cog(AdminCore(bot))
