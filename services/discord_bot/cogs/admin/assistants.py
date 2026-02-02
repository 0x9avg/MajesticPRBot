"""Admin Assistants - Assistant Management Integration.
Integrates assistant_views.py with the new admin navigation system.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api_client import APIClient
    from discord_bot import DiscordBot

import disnake
from disnake import MessageInteraction
from disnake.ext import commands

from .assistant_views import (
    AssistantActionsView,
    AssistantEditModal,
    AssistantManagementView,
    AssistantOverviewView,
    AssistantStatsView,
    TopAssistantsView,
)
from .core import AdminMainView, get_main_embed


# =============================================================================
# EditDailyStatsModal
# =============================================================================


class EditDailyStatsModal(disnake.ui.Modal):
    """Modal for editing daily stats (P0-P3 + probation points) for a specific date."""

    bot: "DiscordBot"
    api: "APIClient"

    def __init__(
        self, bot: "DiscordBot", pr_id: int, date_str: str, current_stats: dict
    ):
        self.bot = bot
        self.pr_id = pr_id
        self.date_str = date_str

        components = [
            disnake.ui.TextInput(
                label=f"P0 секунды ({date_str})",
                value=str(current_stats.get("p0_seconds", 0)),
                custom_id="p0",
                style=disnake.TextInputStyle.short,
            ),
            disnake.ui.TextInput(
                label=f"P1 секунды ({date_str})",
                value=str(current_stats.get("p1_seconds", 0)),
                custom_id="p1",
                style=disnake.TextInputStyle.short,
            ),
            disnake.ui.TextInput(
                label=f"P2 секунды ({date_str})",
                value=str(current_stats.get("p2_seconds", 0)),
                custom_id="p2",
                style=disnake.TextInputStyle.short,
            ),
            disnake.ui.TextInput(
                label=f"P3 секунды ({date_str})",
                value=str(current_stats.get("p3_seconds", 0)),
                custom_id="p3",
                style=disnake.TextInputStyle.short,
            ),
            disnake.ui.TextInput(
                label=f"Испытательный секунды ({date_str})",
                value=str(current_stats.get("probation_seconds", 0)),
                custom_id="probation",
                style=disnake.TextInputStyle.short,
            ),
        ]
        super().__init__(title=f"Редактировать: {date_str}", components=components)

    async def callback(self, interaction: disnake.ModalInteraction):
        await interaction.response.defer(ephemeral=True)
        try:
            p0 = int(interaction.text_values.get("p0", "0"))
            p1 = int(interaction.text_values.get("p1", "0"))
            p2 = int(interaction.text_values.get("p2", "0"))
            p3 = int(interaction.text_values.get("p3", "0"))
            probation = int(interaction.text_values.get("probation", "0"))

            await self.bot.api_client.update_daily_stats(
                pr_id=self.pr_id,
                date=self.date_str,
                p0_seconds=p0,
                p1_seconds=p1,
                p2_seconds=p2,
                p3_seconds=p3,
                probation_seconds=probation,
            )
            await interaction.edit_original_message(
                content=f"✅ Статистика за {self.date_str} обновлена!"
            )
        except Exception as e:
            self.bot.logger.error(f"Edit daily stats error: {e}")
            await interaction.edit_original_message(content="❌ Ошибка")


# =============================================================================
# Admin Assistants Cog
# =============================================================================


class AdminAssistants(commands.Cog):
    """Assistant management integration with admin dashboard."""

    bot: "DiscordBot"
    api: "APIClient"

    def __init__(self, bot: "DiscordBot") -> None:
        self.bot = bot
        self.api = bot.api_client

    @commands.Cog.listener("on_button_click")
    async def on_assistants_button(self, interaction: MessageInteraction):
        """Handle admin_assistants and all sub-interactions."""
        custom_id = interaction.component.custom_id or ""

        # 1. STRICT FILTER
        if (
            not custom_id.startswith("admin_assistants")
            and not custom_id.startswith("assistant_")
            and custom_id != "btn_back_to_menu"
        ):
            return

        # 2. SAFE DEFER (Exception for Modals)
        should_defer = True
        if custom_id.startswith("assistant_edit_stats_") or custom_id.startswith(
            "assistant_edit_"
        ):
            should_defer = False

        if should_defer:
            try:
                if not interaction.response.is_done():
                    await interaction.response.defer(ephemeral=True)
            except Exception as e:
                self.bot.logger.warning(f"Failed to defer {custom_id}: {e}")

        # 3. EXECUTE
        try:
            if (
                custom_id == "admin_assistants"
                or custom_id == "assistant_back_to_select"
                or custom_id == "btn_back_to_menu"
            ):
                view = AssistantManagementView(self.bot)
                embed = view.get_main_embed()
                if interaction.response.is_done():
                    await interaction.edit_original_response(embed=embed, view=view)
                else:
                    await interaction.response.send_message(
                        embed=embed, view=view, ephemeral=True
                    )

            elif custom_id == "assistant_top":
                view = TopAssistantsView(self.bot)
                embed = await view.get_top_embed()
                await interaction.edit_original_response(embed=embed, view=view)

            elif custom_id == "assistant_top_refresh":
                view = TopAssistantsView(self.bot)
                embed = await view.get_top_embed()
                await interaction.edit_original_response(embed=embed, view=view)

            elif custom_id.startswith("assistant_overview_"):
                user_id = int(custom_id.replace("assistant_overview_", ""))
                try:
                    user = await self.bot.fetch_user(user_id)
                    name = user.display_name
                except:
                    name = "Unknown"
                view = AssistantOverviewView(self.bot, user_id, name)
                embed = await view.get_overview_embed()
                await interaction.edit_original_response(embed=embed, view=view)

            elif custom_id.startswith("assistant_stats_") and not custom_id.startswith(
                "assistant_stats_refresh"
            ):
                user_id = int(custom_id.replace("assistant_stats_", ""))
                try:
                    user = await self.bot.fetch_user(user_id)
                    name = user.display_name
                except:
                    name = "Unknown"
                view = AssistantStatsView(self.bot, user_id, name)
                embed = await view.get_stats_embed()
                await interaction.edit_original_response(embed=embed, view=view)

            elif custom_id.startswith("assistant_stats_refresh_"):
                user_id = int(custom_id.replace("assistant_stats_refresh_", ""))
                try:
                    user = await self.bot.fetch_user(user_id)
                    name = user.display_name
                except:
                    name = "Unknown"
                view = AssistantStatsView(self.bot, user_id, name)
                embed = await view.get_stats_embed()
                await interaction.edit_original_response(embed=embed, view=view)

            elif custom_id.startswith("assistant_actions_"):
                user_id = int(custom_id.replace("assistant_actions_", ""))
                try:
                    user = await self.bot.fetch_user(user_id)
                    name = user.display_name
                except:
                    name = "Unknown"
                view = AssistantActionsView(self.bot, user_id, name)
                embed = await view.get_actions_embed()
                await interaction.edit_original_response(embed=embed, view=view)

            elif custom_id.startswith("assistant_edit_stats_"):
                # OPEN EDIT DAILY STATS MODAL
                user_id = int(custom_id.replace("assistant_edit_stats_", ""))
                from datetime import datetime, timezone

                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                current_stats = {
                    "p0_seconds": 0,
                    "p1_seconds": 0,
                    "p2_seconds": 0,
                    "p3_seconds": 0,
                    "probation_seconds": 0,
                }
                await interaction.response.send_modal(
                    EditDailyStatsModal(self.bot, user_id, today, current_stats)
                )

            elif custom_id.startswith("assistant_edit_"):
                # OPEN TIME EDIT MODAL
                user_id = int(custom_id.replace("assistant_edit_", ""))
                try:
                    user = await self.bot.fetch_user(user_id)
                    name = user.display_name
                except:
                    name = "Unknown"
                await interaction.response.send_modal(
                    AssistantEditModal(self.bot, user_id, name)
                )

            elif custom_id.startswith("assistant_history_"):
                await interaction.followup.send(
                    "📝 История пока недоступна.", ephemeral=True
                )

            elif custom_id == "assistant_bulk_ops":
                await interaction.followup.send(
                    "📦 Массовые операции в разработке.", ephemeral=True
                )

            elif custom_id.startswith("assistant_reset_full_"):
                user_id = int(custom_id.replace("assistant_reset_full_", ""))
                await self.api.reset_assistant_stats(user_id)
                await interaction.followup.send(
                    f"✅ Статистика сброшена.", ephemeral=True
                )

        except Exception as e:
            self.bot.logger.error(
                f"Error handling assistant button {custom_id}: {e}", exc_info=True
            )
            try:
                await interaction.followup.send(
                    "❌ Произошла ошибка обработки.", ephemeral=True
                )
            except:
                pass

    @commands.Cog.listener("on_dropdown")
    async def on_assistant_select(self, interaction: MessageInteraction):
        """Handle assistant user select."""
        custom_id = interaction.component.custom_id

        if custom_id == "assistant_user_select":
            if not interaction.response.is_done():
                await interaction.response.defer()
            
            # Handle both UserSelect (returns User) and StringSelect (returns str)
            selected = interaction.values[0]
            if hasattr(selected, 'id'):
                # UserSelect returns User object
                user_id = selected.id
                user_name = selected.display_name
            else:
                # StringSelect returns string ID
                user_id = int(selected)
                member = interaction.guild.get_member(user_id)
                user_name = member.display_name if member else f"User {user_id}"

            # Check if user is registered as assistant in DB
            assistant = await self.api.get_assistant(user_id)
            if not assistant:
                await interaction.followup.send(
                    f"❌ **{user_name}** не зарегистрирован как ассистент в базе данных.",
                    ephemeral=True,
                )
                return

            view = AssistantOverviewView(self.bot, user_id, user_name)
            embed = await view.get_overview_embed()
            await interaction.edit_original_response(embed=embed, view=view)


def setup(bot: commands.Bot) -> None:
    bot.add_cog(AdminAssistants(bot))
