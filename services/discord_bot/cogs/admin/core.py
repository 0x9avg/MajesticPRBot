"""Admin Core - Main Dashboard View.
Entry point for the admin panel with navigation to sub-menus.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api_client import APIClient
    from discord_bot import DiscordBot

import disnake
from disnake import MessageInteraction
from disnake.ext import commands
from utils import safe_defer


class AdminMainView(disnake.ui.View):
    """Persistent main menu for Admin Dashboard."""

    bot: "DiscordBot"

    def __init__(self, bot: "DiscordBot"):
        super().__init__(timeout=None)
        self.bot = bot

        # Row 0 - Main categories
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

        # Row 1 - Secondary categories
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
        self.add_item(
            disnake.ui.Button(
                label="Сервер",
                custom_id="admin_guild",
                emoji="⚙️",
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
            "🔔 **Уведомления** — шаблоны сообщений\n"
            "🎥 **Стримеры** — добавление, редактирование\n"
            "👥 **Ассистенты** — статистика, управление\n"
            "🎉 **События** — создание и управление\n"
            "🛠️ **Сервис** — техническое обслуживание\n"
            "⚙️ **Сервер** — каналы, роли, баллы"
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
        await self._ensure_control_panel()

    async def _ensure_control_panel(self):
        """Ensure control panel message exists and is up-to-date."""
        try:
            settings = await self.api.get_guild_settings()
            if not settings:
                self.bot.logger.warning("No guild settings found, skipping control panel")
                return

            cp_channel_id = settings.get("control_panel_channel_id")
            if not cp_channel_id:
                self.bot.logger.debug("No control panel channel configured")
                return

            channel = self.bot.get_channel(int(cp_channel_id))
            if not channel:
                self.bot.logger.warning(f"Control panel channel {cp_channel_id} not found")
                return

            old_msg_id = settings.get("control_panel_message_id")
            old_msg = None


            if old_msg_id:
                try:
                    old_msg = await channel.fetch_message(int(old_msg_id))
                except (disnake.NotFound, disnake.Forbidden):
                    self.bot.logger.info("Old control panel message not found, will create new")
                    old_msg = None
                except Exception as e:
                    self.bot.logger.warning(f"Error fetching control panel message: {e}")
                    old_msg = None

            if old_msg:

                try:
                    embed = get_main_embed()
                    await old_msg.edit(embed=embed, view=AdminMainView(self.bot))
                    self.bot.logger.info(f"✓ Updated control panel message in #{channel.name}")
                except Exception as e:
                    self.bot.logger.error(f"Failed to edit control panel: {e}")
            else:

                embed = get_main_embed()
                msg = await channel.send(embed=embed, view=AdminMainView(self.bot))

                # Update message ID in API
                await self.api.update_guild_settings(control_panel_message_id=msg.id)
                self.bot.logger.info(f"✓ Control panel created in #{channel.name}")

        except Exception as e:
            self.bot.logger.error(f"Failed to ensure control panel: {e}", exc_info=True)

    @commands.Cog.listener("on_button_click")
    async def on_admin_home_button(self, interaction: MessageInteraction):
        """Handle 'Back to Home' navigation button."""
        custom_id = interaction.component.custom_id
        if custom_id != "admin_home":
            return

        # Back to main menu
        await safe_defer(interaction, ephemeral=False)
        await interaction.edit_original_response(
            embed=get_main_embed(), view=AdminMainView(self.bot)
        )


def setup(bot: commands.Bot) -> None:
    bot.add_cog(AdminCore(bot))
