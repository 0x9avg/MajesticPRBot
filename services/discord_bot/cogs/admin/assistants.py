"""Admin Assistants - Assistant Management Integration.
Integrates assistant_views.py with the new admin navigation system.
"""

import disnake
from disnake import MessageInteraction
from disnake.ext import commands

from .assistant_views import (
    AssistantManagementView,
    AssistantOverviewView,
    AssistantStatsView,
    AssistantEditModal,
    AssistantActionsView,
    TopAssistantsView,
)
from .core import AdminMainView, get_main_embed


# =============================================================================
# EditDailyStatsModal (from old_bot)
# =============================================================================


class EditDailyStatsModal(disnake.ui.Modal):
    """Modal for editing daily stats (P0-P3 points) for a specific date."""

    def __init__(self, bot, pr_id: int, date_str: str, current_stats: dict):
        self.bot = bot
        self.pr_id = pr_id
        self.date_str = date_str

        components = [
            disnake.ui.TextInput(
                label=f"P0 баллы ({date_str})",
                value=str(current_stats.get("p0", 0)),
                custom_id="p0",
                style=disnake.TextInputStyle.short,
            ),
            disnake.ui.TextInput(
                label=f"P1 баллы ({date_str})",
                value=str(current_stats.get("p1", 0)),
                custom_id="p1",
                style=disnake.TextInputStyle.short,
            ),
            disnake.ui.TextInput(
                label=f"P2 баллы ({date_str})",
                value=str(current_stats.get("p2", 0)),
                custom_id="p2",
                style=disnake.TextInputStyle.short,
            ),
            disnake.ui.TextInput(
                label=f"P3 баллы ({date_str})",
                value=str(current_stats.get("p3", 0)),
                custom_id="p3",
                style=disnake.TextInputStyle.short,
            ),
        ]
        super().__init__(title=f"Редактировать: {date_str}", components=components)

    async def callback(self, interaction: disnake.ModalInteraction):
        await interaction.response.defer(ephemeral=True)
        try:
            stats = {}
            for i in range(4):
                val = interaction.text_values.get(f"p{i}", "0")
                stats[f"p{i}"] = float(val.replace(",", "."))

            await self.bot.api_client.update_daily_stats(
                pr_id=self.pr_id,
                date_str=self.date_str,
                p0=stats["p0"],
                p1=stats["p1"],
                p2=stats["p2"],
                p3=stats["p3"],
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

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.api = bot.api_client

    @commands.Cog.listener("on_button_click")
    async def on_assistants_button(self, interaction: MessageInteraction):
        """Handle admin_assistants navigation."""
        custom_id = interaction.component.custom_id
        
        if custom_id == "admin_assistants":
            view = AssistantManagementView(self.bot)
            embed = view.get_main_embed()
            await interaction.response.edit_message(embed=embed, view=view)

        # Handle back to main menu from assistant views
        elif custom_id == "btn_back_to_menu":
            await interaction.response.edit_message(
                embed=get_main_embed(), view=AdminMainView(self.bot)
            )

    @commands.Cog.listener("on_dropdown")
    async def on_assistant_select(self, interaction: MessageInteraction):
        """Handle assistant user select."""
        custom_id = interaction.component.custom_id
        
        if custom_id == "assistant_user_select":
            user = interaction.values[0]  # User object from UserSelect
            user_id = user.id
            user_name = user.display_name

            view = AssistantOverviewView(self.bot, user_id, user_name)
            embed = await view.get_overview_embed()
            await interaction.response.edit_message(embed=embed, view=view)


def setup(bot: commands.Bot) -> None:
    bot.add_cog(AdminAssistants(bot))
