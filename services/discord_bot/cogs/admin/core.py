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

    def __init__(
        self,
        bot: "DiscordBot",
        permissions: dict[str, bool] | None = None,
        owner_id: int | None = None,
    ):
        super().__init__(timeout=None)
        self.bot = bot
        self.owner_id = owner_id
        permissions_map = permissions or {}

        def has_any(required: list[str]) -> bool:
            return any(bool(permissions_map.get(key, False)) for key in required)

        def has_all(required: list[str]) -> bool:
            return all(bool(permissions_map.get(key, False)) for key in required)

        if has_any(["guild.templates.view", "guild.templates.update"]):
            self.add_item(
                disnake.ui.Button(
                    label="Уведомления",
                    custom_id="admin_notifications",
                    emoji="🔔",
                    row=0,
                    style=disnake.ButtonStyle.secondary,
                )
            )

        if has_any(["streamers.create", "streamers.update", "streamers.delete"]):
            self.add_item(
                disnake.ui.Button(
                    label="Стримеры",
                    custom_id="admin_streamers",
                    emoji="🎥",
                    row=0,
                    style=disnake.ButtonStyle.secondary,
                )
            )

        if has_any(["events.create", "events.manage"]):
            self.add_item(
                disnake.ui.Button(
                    label="События",
                    custom_id="admin_events",
                    emoji="🎉",
                    row=1,
                    style=disnake.ButtonStyle.secondary,
                )
            )

        if has_all(["guild.view"]) and has_any(
            ["guild.settings.update", "guild.templates.update", "guild.rates.update"]
        ):
            self.add_item(
                disnake.ui.Button(
                    label="Сервер",
                    custom_id="admin_guild",
                    emoji="⚙️",
                    row=1,
                    style=disnake.ButtonStyle.secondary,
                )
            )

        if has_any(["monitoring.view", "streamers.status.update", "guild.settings.update"]):
            self.add_item(
                disnake.ui.Button(
                    label="Сервис",
                    custom_id="admin_service",
                    emoji="🛠️",
                    row=1,
                    style=disnake.ButtonStyle.secondary,
                )
            )

        if not self.children:
            self.add_item(
                disnake.ui.Button(
                    label="Нет доступных разделов",
                    custom_id="admin_no_access",
                    style=disnake.ButtonStyle.secondary,
                    disabled=True,
                    row=0,
                )
            )

    async def interaction_check(self, interaction: MessageInteraction) -> bool:
        """Allow interactions only for the owner when owner_id is set."""
        if self.owner_id is None or interaction.user.id == self.owner_id:
            return True
        try:
            if interaction.response.is_done():
                await interaction.followup.send(
                    "❌ Эта панель открыта для другого пользователя.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "❌ Эта панель открыта для другого пользователя.",
                    ephemeral=True,
                )
        except Exception:
            pass
        return False


class AdminControlPanelView(disnake.ui.View):
    """Persistent launcher view for opening per-user admin menu."""

    bot: "DiscordBot"

    def __init__(self, bot: "DiscordBot"):
        super().__init__(timeout=None)
        self.bot = bot
        self.add_item(
            disnake.ui.Button(
                label="Открыть панель",
                custom_id="admin_open",
                emoji="🔧",
                style=disnake.ButtonStyle.primary,
                row=0,
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
        self.bot.add_view(AdminControlPanelView(self.bot))
        self.bot.logger.info("✓ AdminControlPanelView registered")

        # Recreate control panel message
        await self._ensure_control_panel()

    async def _ensure_control_panel(self):
        """Ensure control panel message exists and is up-to-date."""
        try:
            settings = await self.api.get_guild_settings()
            if not settings:
                self.bot.logger.warning(
                    "No guild settings found, skipping control panel"
                )
                return

            cp_channel_id = settings.get("control_panel_channel_id")
            if not cp_channel_id:
                self.bot.logger.debug("No control panel channel configured")
                return

            channel = self.bot.get_channel(int(cp_channel_id))
            if not channel:
                self.bot.logger.warning(
                    f"Control panel channel {cp_channel_id} not found"
                )
                return

            old_msg_id = settings.get("control_panel_message_id")
            old_msg = None

            if old_msg_id:
                try:
                    old_msg = await channel.fetch_message(int(old_msg_id))
                except (disnake.NotFound, disnake.Forbidden):
                    self.bot.logger.info(
                        "Old control panel message not found, will create new"
                    )
                    old_msg = None
                except Exception as e:
                    self.bot.logger.warning(
                        f"Error fetching control panel message: {e}"
                    )
                    old_msg = None

            if old_msg:

                try:
                    embed = get_main_embed()
                    await old_msg.edit(embed=embed, view=AdminControlPanelView(self.bot))
                    self.bot.logger.info(
                        f"✓ Updated control panel message in #{channel.name}"
                    )
                except Exception as e:
                    self.bot.logger.error(f"Failed to edit control panel: {e}")
            else:

                embed = get_main_embed()
                msg = await channel.send(embed=embed, view=AdminControlPanelView(self.bot))

                # Update message ID in API
                await self.api.update_guild_settings(control_panel_message_id=msg.id)
                self.bot.logger.info(f"✓ Control panel created in #{channel.name}")

        except Exception as e:
            self.bot.logger.error(f"Failed to ensure control panel: {e}", exc_info=True)

    @commands.Cog.listener("on_button_click")
    async def on_admin_home_button(self, interaction: MessageInteraction):
        """Handle 'Back to Home' navigation button."""
        custom_id = interaction.component.custom_id
        if custom_id not in {"admin_home", "admin_open"}:
            return

        permissions = await self.bot.get_user_permissions(interaction.user.id)

        # Open admin panel from public control panel:
        # send a dedicated ephemeral message instead of editing source message.
        if custom_id == "admin_open":
            embed = get_main_embed()
            view = AdminMainView(self.bot, permissions, owner_id=interaction.user.id)
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        embed=embed,
                        view=view,
                        ephemeral=True,
                    )
                else:
                    await interaction.response.send_message(
                        embed=embed,
                        view=view,
                        ephemeral=True,
                    )
            except Exception as e:
                self.bot.logger.error(f"Failed to open admin panel ephemerally: {e}")
            return

        # Back to main menu inside ephemeral admin flow.
        if not await safe_defer(interaction, ephemeral=True):
            return
        await interaction.edit_original_response(
            embed=get_main_embed(),
            view=AdminMainView(self.bot, permissions, owner_id=interaction.user.id),
        )


def setup(bot: commands.Bot) -> None:
    bot.add_cog(AdminCore(bot))
