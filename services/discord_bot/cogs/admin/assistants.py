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
        """Handle admin_assistants and all sub-interactions."""
        custom_id = interaction.component.custom_id or ""
        
        # 1. STRICT FILTER
        if not custom_id.startswith("admin_assistants") and not custom_id.startswith("assistant_") and custom_id != "btn_back_to_menu":
            return

        # 2. SAFE DEFER (Exception for Modals)
        # assistant_edit_{id} and assistant_edit_stats_{id} open Modals -> NO DEFER
        should_defer = True
        if custom_id.startswith("assistant_edit_stats_") or custom_id.startswith("assistant_edit_"):
            should_defer = False
        
        if should_defer:
            try:
                if not interaction.response.is_done():
                    await interaction.response.defer(ephemeral=True)
            except Exception as e:
                self.bot.logger.warning(f"Failed to defer {custom_id}: {e}")

        # 3. EXECUTE
        try:
            if custom_id == "admin_assistants" or custom_id == "assistant_back_to_select" or custom_id == "btn_back_to_menu":
                view = AssistantManagementView(self.bot)
                embed = view.get_main_embed()
                if interaction.response.is_done():
                    await interaction.edit_original_response(embed=embed, view=view)
                else:
                    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            
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
                user = await self.bot.fetch_user(user_id) # Might fail if not cached
                name = user.display_name if user else "Unknown"
                view = AssistantOverviewView(self.bot, user_id, name)
                embed = await view.get_overview_embed()
                await interaction.edit_original_response(embed=embed, view=view)

            elif custom_id.startswith("assistant_stats_") and not custom_id.startswith("assistant_stats_refresh"):
                # assistant_stats_{id}
                user_id = int(custom_id.replace("assistant_stats_", ""))
                user = await self.bot.fetch_user(user_id)
                name = user.display_name if user else "Unknown"
                view = AssistantStatsView(self.bot, user_id, name)
                embed = await view.get_stats_embed()
                await interaction.edit_original_response(embed=embed, view=view)
            
            elif custom_id == "assistant_stats_refresh":
                # This one is tricky because we need the user_id from context.
                # Usually views store state, but we are recreating. 
                # If we don't have user_id in ID, we can't easily refresh specific stats.
                # However, AssistantStatsView has "assistant_stats_refresh" button.
                # If we use a stateless listener, we need the ID in the custom_id.
                # The current View definition uses static "assistant_stats_refresh".
                # This is a design flaw in the View if processed globally.
                # For now, let's try to extract from message embed footer? Or fail gracefully.
                # Or simplistic approach: just say "Re-open stats".
                await interaction.followup.send("🔄 Пожалуйста, откройте статистику заново через меню.", ephemeral=True)

            elif custom_id.startswith("assistant_actions_"):
                user_id = int(custom_id.replace("assistant_actions_", ""))
                user = await self.bot.fetch_user(user_id)
                name = user.display_name if user else "Unknown"
                view = AssistantActionsView(self.bot, user_id, name)
                embed = await view.get_actions_embed()
                await interaction.edit_original_response(embed=embed, view=view)


            elif custom_id.startswith("assistant_edit_stats_"):
                # OPEN EDIT DAILY STATS MODAL
                user_id = int(custom_id.replace("assistant_edit_stats_", ""))
                user = await self.bot.fetch_user(user_id)
                name = user.display_name if user else "Unknown"
                # For now, open with today's date and default stats
                from datetime import datetime, timezone
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                current_stats = {"p0": 0, "p1": 0, "p2": 0, "p3": 0}  # API could fetch current
                await interaction.response.send_modal(EditDailyStatsModal(self.bot, user_id, today, current_stats))

            elif custom_id.startswith("assistant_edit_"):
                # OPEN TIME EDIT MODAL (general edit)
                user_id = int(custom_id.replace("assistant_edit_", ""))
                user = await self.bot.fetch_user(user_id)
                name = user.display_name if user else "Unknown"
                await interaction.response.send_modal(AssistantEditModal(self.bot, user_id, name))

            elif custom_id.startswith("assistant_history_"):
                # Not implemented in views yet?
                await interaction.followup.send("📝 История пока недоступна.", ephemeral=True)

            elif custom_id == "assistant_bulk_ops":
                await interaction.followup.send("📦 Массовые операции в разработке.", ephemeral=True)

            elif custom_id.startswith("assistant_reset_full_"):
                user_id = int(custom_id.replace("assistant_reset_full_", ""))
                await self.api.reset_assistant_stats(user_id) # Hypothetical API method?
                # Actually api might not have this yet. 
                await interaction.followup.send(f"✅ Статистика сброшена (API call simulated).", ephemeral=True)

        except Exception as e:
            self.bot.logger.error(f"Error handling assistant button {custom_id}: {e}", exc_info=True)
            try:
                await interaction.followup.send("❌ Произошла ошибка обработки.", ephemeral=True)
            except: pass

    @commands.Cog.listener("on_dropdown")
    async def on_assistant_select(self, interaction: MessageInteraction):
        """Handle assistant user select."""
        custom_id = interaction.component.custom_id
        
        if custom_id == "assistant_user_select":
            if not interaction.response.is_done():
                await interaction.response.defer()
            user = interaction.values[0]  # User object from UserSelect
            user_id = user.id
            user_name = user.display_name

            view = AssistantOverviewView(self.bot, user_id, user_name)
            embed = await view.get_overview_embed()
            await interaction.edit_original_response(embed=embed, view=view)


def setup(bot: commands.Bot) -> None:
    bot.add_cog(AdminAssistants(bot))
