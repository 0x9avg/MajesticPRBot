"""Admin Streamers - Streamer Management.
Add, edit, delete, and list streamers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api_client import APIClient
    from discord_bot import DiscordBot

import disnake
from disnake import MessageInteraction
from disnake.ext import commands
from utils import safe_defer, handle_interaction_error


# =============================================================================
# Streamers Embed
# =============================================================================


async def get_streamers_embed(api) -> disnake.Embed:
    """Create embed showing streamer stats."""
    try:
        streamers = await api.list_all_streamers()
        total = len(streamers)
        online = sum(1 for s in streamers if s.get("is_online"))
        gta = sum(
            1
            for s in streamers
            if s.get("is_online") and s.get("game_name") == "Grand Theft Auto V"
        )
    except Exception:
        total, online, gta = 0, 0, 0

    embed = disnake.Embed(
        title="🎥 Управление Стримерами",
        description=(
            f"**Всего:** {total} | **Онлайн:** {online} | **GTA 5:** {gta}\n\n"
            "Используйте кнопки ниже для управления."
        ),
        color=0x9B59B6,
    )
    return embed


# =============================================================================
# Add Streamer Modal
# =============================================================================


class AddStreamerModal(disnake.ui.Modal):
    """Modal for adding a new streamer."""

    bot: "DiscordBot"

    def __init__(self, bot: "DiscordBot"):
        self.bot = bot
        components = [
            disnake.ui.TextInput(
                label="Ссылка на Twitch или Никнейм",
                placeholder="https://twitch.tv/username",
                custom_id="url",
                style=disnake.TextInputStyle.short,
            ),
            disnake.ui.TextInput(
                label="Приоритет (0-3)",
                placeholder="0",
                custom_id="priority",
                style=disnake.TextInputStyle.short,
                required=False,
                value="0",
            ),
        ]
        super().__init__(title="Добавить стримера", components=components)

    async def callback(self, interaction: disnake.ModalInteraction):
        await interaction.response.defer(ephemeral=True)
        try:
            url = interaction.text_values["url"]
            priority = int(interaction.text_values.get("priority", "0") or "0")

            # Extract username
            if "twitch.tv/" in url:
                username = url.split("twitch.tv/")[-1].rstrip("/").strip()
            else:
                username = url.strip()

            await self.bot.api_client.add_streamer(
                twitch_url=username, priority=priority, added_by_id=interaction.user.id
            )
            await interaction.edit_original_message(
                content=f"✅ Стример **{username}** добавлен!"
            )
        except Exception as e:
            await handle_interaction_error(interaction, e, self.bot.logger)


# =============================================================================
# Edit Streamer Modal
# =============================================================================


class EditStreamerModal(disnake.ui.Modal):
    """Modal for editing streamer priority."""

    bot: "DiscordBot"

    def __init__(
        self, bot: "DiscordBot", streamer_id: int, streamer_name: str, priority: int
    ):
        self.bot = bot
        self.streamer_id = streamer_id
        components = [
            disnake.ui.TextInput(
                label="Приоритет (0-3)",
                value=str(priority),
                custom_id="priority",
                style=disnake.TextInputStyle.short,
                max_length=1,
            ),
        ]
        super().__init__(title=f"Редактировать: {streamer_name}", components=components)

    async def callback(self, interaction: disnake.ModalInteraction):
        await interaction.response.defer(ephemeral=True)
        try:
            priority = int(interaction.text_values["priority"])
            if not 0 <= priority <= 3:
                raise ValueError("Priority must be 0-3")

            await self.bot.api_client.update_streamer(
                self.streamer_id, priority=priority
            )
            await interaction.edit_original_message(
                content=f"✅ Приоритет обновлен на **{priority}**"
            )
        except ValueError as e:
            await interaction.edit_original_message(content=f"❌ {e}")
        except Exception as e:
            self.bot.logger.error(f"Edit streamer error: {e}")
            await interaction.edit_original_message(content="❌ Ошибка")


# =============================================================================
# Direct Input Modals (Edit / Delete by Nickname)
# =============================================================================



class EditStreamerByNameModal(disnake.ui.Modal):
    """Modal for editing streamer by entering nickname and new priority."""

    bot: "DiscordBot"

    def __init__(self, bot: "DiscordBot"):
        self.bot = bot
        components = [
            disnake.ui.TextInput(
                label="Никнейм стримера",
                placeholder="Введите точный никнейм Twitch",
                custom_id="streamer_name",
                style=disnake.TextInputStyle.short,
            ),
            disnake.ui.TextInput(
                label="Новый приоритет (0-3)",
                placeholder="0",
                custom_id="priority",
                style=disnake.TextInputStyle.short,
                max_length=1,
            ),
        ]
        super().__init__(title="Редактировать стримера", components=components)

    async def callback(self, interaction: disnake.ModalInteraction):
        await safe_defer(interaction, ephemeral=True)
        try:
            name = interaction.text_values["streamer_name"].strip().lower()
            priority_str = interaction.text_values["priority"].strip()
            
            if not priority_str.isdigit() or not (0 <= int(priority_str) <= 3):
                await interaction.edit_original_message(content="❌ Приоритет должен быть числом от 0 до 3.")
                return
                
            priority = int(priority_str)
            
            # Find streamer by name
            streamers = await self.bot.api_client.list_all_streamers()
            streamer = next(
                (s for s in streamers if s["streamer_name"].lower() == name), 
                None
            )
            
            if not streamer:
                await interaction.edit_original_message(
                    content=f"❌ Стример **{name}** не найден"
                )
                return
            
            # Update streamer
            await self.bot.api_client.update_streamer(
                streamer["streamer_id"], priority=priority
            )
            
            await interaction.edit_original_message(
                content=f"✅ Стример **{streamer['streamer_name']}** обновлен!\nНовый приоритет: **{priority}**"
            )

            await interaction.edit_original_message(
                content=f"✅ Стример **{streamer['streamer_name']}** обновлен!\nНовый приоритет: **{priority}**"
            )

        except Exception as e:
            await handle_interaction_error(interaction, e, self.bot.logger)


class DeleteStreamerByNameModal(disnake.ui.Modal):
    """Modal for deleting streamer by entering nickname."""

    bot: "DiscordBot"

    def __init__(self, bot: "DiscordBot"):
        self.bot = bot
        components = [
            disnake.ui.TextInput(
                label="Никнейм стримера",
                placeholder="Введите точный никнейм Twitch",
                custom_id="streamer_name",
                style=disnake.TextInputStyle.short,
            ),
        ]
        super().__init__(title="Удалить стримера", components=components)

    async def callback(self, interaction: disnake.ModalInteraction):
        await safe_defer(interaction, ephemeral=True)
        try:
            name = interaction.text_values["streamer_name"].strip().lower()
            
            # Find streamer by name
            streamers = await self.bot.api_client.list_all_streamers()
            streamer = next(
                (s for s in streamers if s["streamer_name"].lower() == name), 
                None
            )
            
            if not streamer:
                await interaction.edit_original_message(
                    content=f"❌ Стример **{name}** не найден"
                )
                return
            
            # Delete streamer
            await self.bot.api_client.delete_streamer(streamer["streamer_id"])
            await interaction.edit_original_message(
                content=f"✅ Стример **{streamer['streamer_name']}** удален!"
            )
        except Exception as e:
            await handle_interaction_error(interaction, e, self.bot.logger)


# =============================================================================
# Streamers View
# =============================================================================


class StreamersView(disnake.ui.View):
    """Main view for streamer management."""

    bot: "DiscordBot"

    def __init__(self, bot: "DiscordBot"):
        super().__init__(timeout=None)
        self.bot = bot

        # Add buttons
        self.add_item(
            disnake.ui.Button(
                label="Добавить",
                custom_id="admin_str_add",
                style=disnake.ButtonStyle.success,
                emoji="➕",
                row=0,
            )
        )

        self.add_item(
            disnake.ui.Button(
                label="Удалить",
                custom_id="admin_str_del",
                style=disnake.ButtonStyle.danger,
                emoji="🗑️",
                row=0,
            )
        )

        self.add_item(
            disnake.ui.Button(
                label="Редактировать",
                custom_id="admin_str_edit",
                style=disnake.ButtonStyle.secondary,
                emoji="✏️",
                row=1,
            )
        )


        self.add_item(
            disnake.ui.Button(
                label="Список",
                custom_id="admin_str_list",
                style=disnake.ButtonStyle.primary,
                emoji="📋",
                row=1,
            )
        )

        self.add_item(
            disnake.ui.Button(
                label="Назад",
                custom_id="admin_home",
                style=disnake.ButtonStyle.secondary,
                emoji="🔙",
                row=2,
            )
        )


# =============================================================================
# Admin Streamers Cog
# =============================================================================

class AdminStreamers(commands.Cog):
    """Streamer management."""

    bot: "DiscordBot"
    api: "APIClient"

    def __init__(self, bot: "DiscordBot") -> None:
        self.bot = bot
        self.api = bot.api_client

    @commands.Cog.listener("on_button_click")
    async def on_streamers_button(self, interaction: MessageInteraction):
        """Handle admin_streamers navigation and sub-buttons."""
        custom_id = interaction.component.custom_id or ""

        # 1. STRICT FILTER
        if not custom_id.startswith("admin_streamers") and not custom_id.startswith(
            "admin_str_"
        ):
            return

        # 2. SAFE DEFER (Exception for Modals)
        if custom_id not in ("admin_str_add", "admin_str_edit", "admin_str_del"):
            try:
                if not interaction.response.is_done():
                    await interaction.response.defer(ephemeral=True)
            except Exception as e:
                self.bot.logger.warning(f"Failed to defer {custom_id}: {e}")

        # 3. EXECUTE
        try:
            if custom_id == "admin_streamers":
                embed = await get_streamers_embed(self.api)
                if interaction.response.is_done():
                    await interaction.edit_original_response(
                        embed=embed, view=StreamersView(self.bot)
                    )

            elif custom_id == "admin_str_add":
                # OPEN MODAL - DIRECT RESPONSE
                await interaction.response.send_modal(AddStreamerModal(self.bot))

            elif custom_id == "admin_str_edit":
                # OPEN MODAL for nickname input
                await interaction.response.send_modal(EditStreamerByNameModal(self.bot))

            elif custom_id == "admin_str_del":
                # OPEN MODAL for nickname input
                await interaction.response.send_modal(DeleteStreamerByNameModal(self.bot))

            elif custom_id == "admin_str_list":
                # Show page 0 in new message
                await self._show_streamer_list(interaction, page=0, new_message=True)

            elif custom_id.startswith("admin_str_list_page_"):
                # Pagination buttons
                page = int(custom_id.split("_")[-1])
                await self._show_streamer_list(interaction, page=page)

        except Exception as e:
            await handle_interaction_error(interaction, e, self.bot.logger)

    async def _show_streamer_list(
        self, interaction: MessageInteraction, page: int, new_message: bool = False
    ):
        """Show paginated streamer list."""
        streamers = await self.api.list_all_streamers()
        if not streamers:
            await interaction.followup.send("Список пуст", ephemeral=True)
            return

        # Pagination
        per_page = 25
        total_pages = (len(streamers) + per_page - 1) // per_page
        page = max(0, min(page, total_pages - 1))
        start = page * per_page
        end = start + per_page
        page_streamers = streamers[start:end]

        lines = [
            f"• **{s['streamer_name']}** (P{s.get('priority', 0)}) {'🟢' if s.get('is_online') else '⚫'}"
            for s in page_streamers
        ]
        content = f"**Стримеры ({len(streamers)}) — Стр. {page + 1}/{total_pages}:**\n" + "\n".join(lines)

        # Build pagination buttons
        view = disnake.ui.View(timeout=None)
        if page > 0:
            view.add_item(
                disnake.ui.Button(
                    label="◀ Назад",
                    custom_id=f"admin_str_list_page_{page - 1}",
                    style=disnake.ButtonStyle.secondary,
                    row=0
                )
            )
        if page < total_pages - 1:
            view.add_item(
                disnake.ui.Button(
                    label="Вперед ▶",
                    custom_id=f"admin_str_list_page_{page + 1}",
                    style=disnake.ButtonStyle.secondary,
                    row=0
                )
            )

        if new_message:
            await interaction.followup.send(content=content, view=view, ephemeral=True)
        else:
            await interaction.edit_original_response(content=content, view=view)




def setup(bot: commands.Bot) -> None:
    bot.add_cog(AdminStreamers(bot))
