"""Admin Guild - Points Configuration.
Handles points rate configuration (including probation rate).
Channel/role setup is handled by setup.py cog via /setup command.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api_client import APIClient
    from discord_bot import DiscordBot

import disnake
from disnake import MessageInteraction
from disnake.ext import commands

from .core import AdminMainView, get_main_embed


# =============================================================================
# Settings Embed
# =============================================================================


def create_guild_settings_embed(data: dict | None) -> disnake.Embed:
    """Create embed showing current points configuration."""
    embed = disnake.Embed(
        title="⚙️ Настройки Сервера",
        colour=0xC9A6F6,
    )

    if data is None:
        data = {}

    embed.description = (
        "Настройка баллов за спек по приоритетам.\n"
        "Для настройки каналов используйте команду `/setup`."
    )

    # Points rates
    embed.add_field(
        name="💰 Ставки баллов",
        value=(
            f"• P0: **{data.get('p0_rate', 0.25)}** б/ч\n"
            f"• P1: **{data.get('p1_rate', 0.4)}** б/ч\n"
            f"• P2: **{data.get('p2_rate', 0.5)}** б/ч\n"
            f"• P3: **{data.get('p3_rate', 0.6)}** б/ч\n"
            f"• Испытательный: **{data.get('probation_rate', 0.2)}** б/ч"
        ),
        inline=False,
    )

    # Quick info about configured channels
    channels_status = []
    if data.get("notification_channel_id"):
        channels_status.append("✅ Уведомления")
    else:
        channels_status.append("❌ Уведомления")

    if data.get("monitoring_channel_id"):
        channels_status.append("✅ Мониторинг")
    else:
        channels_status.append("❌ Мониторинг")

    if data.get("control_panel_channel_id"):
        channels_status.append("✅ Панель")
    else:
        channels_status.append("❌ Панель")

    embed.add_field(
        name="📡 Каналы (настройка через /setup)",
        value=" | ".join(channels_status),
        inline=False,
    )

    # GTA Filter status
    gta_filter_on = data.get("monitoring_filter_gta", False)
    embed.add_field(
        name="🎮 Фильтр мониторинга",
        value="✅ Только GTA" if gta_filter_on else "❌ Все стримеры",
        inline=False,
    )

    return embed


# =============================================================================
# Component IDs
# =============================================================================
ID_SETUP_POINTS = "guild_setup_points"
ID_TOGGLE_GTA_FILTER = "guild_toggle_gta_filter"
ID_BTN_HOME = "admin_home"


# =============================================================================
# Views
# =============================================================================


class GuildSettingsView(disnake.ui.View):
    """View for guild settings - points configuration."""

    def __init__(self, user_id: int, gta_filter_on: bool = False):
        super().__init__(timeout=None)
        self.user_id = user_id

        # Points config button
        self.add_item(
            disnake.ui.Button(
                label="💰 Настроить баллы",
                custom_id=ID_SETUP_POINTS,
                style=disnake.ButtonStyle.success,
                row=0,
            )
        )
        
        # GTA filter toggle button
        self.add_item(
            disnake.ui.Button(
                label="🎮 Только GTA" if gta_filter_on else "🎮 Все стримеры",
                custom_id=ID_TOGGLE_GTA_FILTER,
                style=disnake.ButtonStyle.primary if gta_filter_on else disnake.ButtonStyle.secondary,
                row=0,
            )
        )

        # Back to main
        self.add_item(
            disnake.ui.Button(
                label="🏠 Главная",
                custom_id=ID_BTN_HOME,
                style=disnake.ButtonStyle.secondary,
                row=1,
            )
        )


# =============================================================================
# Points Config Modal (with Probation Rate)
# =============================================================================


class PointsConfigModal(disnake.ui.Modal):
    """Modal for configuring point rates per priority level, including probation."""

    def __init__(self, bot: "DiscordBot", current_rates: dict):
        self.bot = bot
        self.api = bot.api_client

        components = [
            disnake.ui.TextInput(
                label="Приоритет 0 (Балл/Час)",
                value=str(current_rates.get("p0_rate", 0.25)),
                custom_id="p0",
                style=disnake.TextInputStyle.short,
            ),
            disnake.ui.TextInput(
                label="Приоритет 1 (Балл/Час)",
                value=str(current_rates.get("p1_rate", 0.4)),
                custom_id="p1",
                style=disnake.TextInputStyle.short,
            ),
            disnake.ui.TextInput(
                label="Приоритет 2 (Балл/Час)",
                value=str(current_rates.get("p2_rate", 0.5)),
                custom_id="p2",
                style=disnake.TextInputStyle.short,
            ),
            disnake.ui.TextInput(
                label="Приоритет 3 (Балл/Час)",
                value=str(current_rates.get("p3_rate", 0.6)),
                custom_id="p3",
                style=disnake.TextInputStyle.short,
            ),
            disnake.ui.TextInput(
                label="Испытательный срок (Балл/Час)",
                value=str(current_rates.get("probation_rate", 0.2)),
                custom_id="probation",
                style=disnake.TextInputStyle.short,
            ),
        ]
        super().__init__(title="💰 Настройка баллов", components=components)

    async def callback(self, interaction: disnake.ModalInteraction):
        await interaction.response.defer(ephemeral=True)
        try:
            # Parse values
            p0 = float(interaction.text_values["p0"].replace(",", "."))
            p1 = float(interaction.text_values["p1"].replace(",", "."))
            p2 = float(interaction.text_values["p2"].replace(",", "."))
            p3 = float(interaction.text_values["p3"].replace(",", "."))
            probation = float(interaction.text_values["probation"].replace(",", "."))

            # Save via API
            await self.api.update_guild_rates(
                p0_rate=p0,
                p1_rate=p1,
                p2_rate=p2,
                p3_rate=p3,
                probation_rate=probation,
            )

            await interaction.edit_original_message(
                content=(
                    "✅ **Настройки баллов сохранены!**\n"
                    f"• P0: {p0} б/ч\n"
                    f"• P1: {p1} б/ч\n"
                    f"• P2: {p2} б/ч\n"
                    f"• P3: {p3} б/ч\n"
                    f"• Испытательный: {probation} б/ч"
                )
            )

        except ValueError:
            await interaction.edit_original_message(
                content="❌ Значения должны быть числами (можно дробные, например 0.5)."
            )
        except Exception as e:
            self.bot.logger.error(f"Points config error: {e}", exc_info=True)
            await interaction.edit_original_message(content="❌ Ошибка сохранения.")


# =============================================================================
# Admin Guild Cog
# =============================================================================


class AdminGuild(commands.Cog):
    """Guild points configuration (part of admin panel)."""

    bot: "DiscordBot"
    api: "APIClient"

    def __init__(self, bot: "DiscordBot") -> None:
        self.bot = bot
        self.api = bot.api_client

    @commands.Cog.listener("on_button_click")
    async def on_guild_button_interaction(self, interaction: MessageInteraction):
        """Handle guild settings buttons."""
        custom_id = interaction.component.custom_id or ""

        # Strict Filter - only handle guild_ and admin_guild
        if not custom_id.startswith(("guild_setup_", "guild_toggle_", "admin_guild")):
            return

        # Safe Defer (except for modal)
        if custom_id != ID_SETUP_POINTS:
            try:
                if not interaction.response.is_done():
                    await interaction.response.defer(ephemeral=True)
            except Exception as e:
                self.bot.logger.warning(f"Defer failed: {e}")

        try:
            user_id = interaction.user.id

            # Navigation from main menu
            if custom_id == "admin_guild":
                data = await self.api.get_guild_settings()
                gta_filter_on = data.get("monitoring_filter_gta", False) if data else False
                await interaction.edit_original_response(
                    embed=create_guild_settings_embed(data),
                    view=GuildSettingsView(user_id, gta_filter_on),
                )

            elif custom_id == ID_TOGGLE_GTA_FILTER:
                # Toggle GTA filter
                data = await self.api.get_guild_settings()
                current_value = data.get("monitoring_filter_gta", False) if data else False
                new_value = not current_value
                
                await self.api.update_guild_settings(monitoring_filter_gta=new_value)
                
                # Refresh monitoring messages
                await self.api.refresh_monitoring()
                
                # Refresh embed and view
                data = await self.api.get_guild_settings()
                gta_filter_on = data.get("monitoring_filter_gta", False) if data else False
                await interaction.edit_original_response(
                    embed=create_guild_settings_embed(data),
                    view=GuildSettingsView(user_id, gta_filter_on),
                )
                
                status_text = "включён" if new_value else "выключен"
                await interaction.followup.send(
                    f"✅ Фильтр GTA {status_text}!", ephemeral=True
                )

            elif custom_id == ID_SETUP_POINTS:
                # Open points config modal
                data = await self.api.get_guild_settings()
                modal = PointsConfigModal(self.bot, data or {})
                await interaction.response.send_modal(modal)

        except disnake.errors.InteractionResponded:
            # Modal was sent, interaction already responded
            pass
        except Exception as e:
            self.bot.logger.error(f"Guild button error {custom_id}: {e}", exc_info=True)
            try:
                await interaction.followup.send("❌ Ошибка.", ephemeral=True)
            except:  # noqa: E722
                pass


def setup(bot: commands.Bot) -> None:
    bot.add_cog(AdminGuild(bot))
