"""Admin Streamers - Streamer Management.
Add, edit, delete, and list streamers.
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
                twitch_url=username, priority=priority
            )
            await interaction.edit_original_message(
                content=f"✅ Стример **{username}** добавлен!"
            )
        except Exception as e:
            self.bot.logger.error(f"Add streamer error: {e}")
            await interaction.edit_original_message(content=f"❌ Ошибка: {e}")


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
# Streamer Select Views
# =============================================================================


class EditStreamerSelect(disnake.ui.StringSelect):
    """Select for choosing streamer to edit."""

    def __init__(self, streamers: list):
        options = [
            disnake.SelectOption(
                label=f"{s['streamer_name']} (P{s.get('priority', 0)})",
                value=str(s["streamer_id"]),
            )
            for s in streamers[:25]
        ]
        super().__init__(
            custom_id="admin_str_edit_select",
            placeholder="Выберите стримера для редактирования",
            options=options,
        )

    async def callback(self, interaction: MessageInteraction):
        streamer_id = int(self.values[0])
        # Fetch streamer to get current priority
        streamers = await interaction.bot.api_client.list_all_streamers()
        streamer = next((s for s in streamers if s["streamer_id"] == streamer_id), None)

        if streamer:
            await interaction.response.send_modal(
                EditStreamerModal(
                    interaction.bot,
                    streamer_id,
                    streamer["streamer_name"],
                    streamer.get("priority", 0),
                )
            )
        else:
            await interaction.response.send_message(
                "❌ Стример не найден", ephemeral=True
            )


class DeleteStreamerSelect(disnake.ui.StringSelect):
    """Select for choosing streamer to delete."""

    def __init__(self, streamers: list):
        options = [
            disnake.SelectOption(
                label=s["streamer_name"],
                value=str(s["streamer_id"]),
            )
            for s in streamers[:25]
        ]
        super().__init__(
            custom_id="admin_str_del_select",
            placeholder="Выберите стримера для удаления",
            options=options,
        )

    async def callback(self, interaction: MessageInteraction):
        await interaction.response.defer(ephemeral=True)
        streamer_id = int(self.values[0])

        try:
            await interaction.bot.api_client.delete_streamer(streamer_id)
            await interaction.edit_original_response(content="✅ Стример удален!")
        except Exception as e:
            interaction.bot.logger.error(f"Delete streamer error: {e}")
            await interaction.edit_original_response(content="❌ Ошибка")


# =============================================================================
# Streamers View
# =============================================================================


class StreamersView(disnake.ui.View):
    """Main view for streamer management."""

    bot: "DiscordBot"

    def __init__(self, bot: "DiscordBot"):
        super().__init__(timeout=None)
        self.bot = bot

        # Add buttons manually to avoid internal callbacks
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
                label="Редактировать",
                custom_id="admin_str_edit",
                style=disnake.ButtonStyle.secondary,
                emoji="✏️",
                row=0,
            )
        )

        self.add_item(
            disnake.ui.Button(
                label="Удалить",
                custom_id="admin_str_del",
                style=disnake.ButtonStyle.danger,
                emoji="🗑️",
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
                custom_id="admin_str_back",
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
        # admin_str_add opens a Modal -> DO NOT DEFER
        if custom_id != "admin_str_add":
            try:
                # Some other buttons might result in modal? Check:
                # admin_str_edit -> Sends Select (Defer OK)
                # admin_str_del -> Sends Select (Defer OK)
                # admin_str_list -> Sends Embed (Defer OK)
                # admin_str_back -> Edit (Defer OK)
                if not interaction.response.is_done():
                    await interaction.response.defer(
                        ephemeral=True
                    )  # Most actions here are ephemeral
            except Exception as e:
                self.bot.logger.warning(f"Failed to defer {custom_id}: {e}")

        # 3. EXECUTE
        try:
            if custom_id == "admin_streamers":
                # Check for existing defer from previous step if it wasn't valid?
                # Actually admin_streamers comes from core view which might have diff ephemeral state?
                # Usually admin_streamers is "Show me the menu".
                # If we deferred above, we use edit_original_response.
                embed = await get_streamers_embed(self.api)

                # If interaction was deferred (likely), use edit_original_response
                if interaction.response.is_done():
                    await interaction.edit_original_response(
                        embed=embed, view=StreamersView(self.bot)
                    )
                else:
                    # Should have been deferred above unless it failed?
                    pass

            elif custom_id == "admin_str_add":
                # OPEN MODAL - DIRECT RESPONSE
                await interaction.response.send_modal(AddStreamerModal(self.bot))

            elif custom_id == "admin_str_edit":
                streamers = await self.api.list_all_streamers()
                if not streamers:
                    await interaction.followup.send("Список пуст", ephemeral=True)
                    return
                view = disnake.ui.View(timeout=None)
                view.add_item(EditStreamerSelect(streamers))
                await interaction.followup.send(
                    "Выберите стримера для редактирования:", view=view, ephemeral=True
                )

            elif custom_id == "admin_str_del":
                streamers = await self.api.list_all_streamers()
                if not streamers:
                    await interaction.followup.send("Список пуст", ephemeral=True)
                    return
                view = disnake.ui.View(timeout=None)
                view.add_item(DeleteStreamerSelect(streamers))
                await interaction.followup.send(
                    "Выберите стримера для удаления:", view=view, ephemeral=True
                )

            elif custom_id == "admin_str_list":
                streamers = await self.api.list_all_streamers()
                if not streamers:
                    await interaction.followup.send("Список пуст", ephemeral=True)
                    return
                lines = [
                    f"• **{s['streamer_name']}** (P{s.get('priority', 0)}) {'🟢' if s.get('is_online') else '⚫'}"
                    for s in streamers
                ]
                content = "\n".join(lines[:50])
                if len(lines) > 50:
                    content += f"\n... и еще {len(lines) - 50}"
                await interaction.followup.send(
                    f"**Стримеры ({len(streamers)}):**\n{content}", ephemeral=True
                )

            elif custom_id == "admin_str_back":
                from .core import AdminMainView, get_main_embed

                await interaction.edit_original_response(
                    embed=get_main_embed(), view=AdminMainView(self.bot)
                )

        except Exception as e:
            self.bot.logger.error(
                f"Error handling streamers button {custom_id}: {e}", exc_info=True
            )
            try:
                await interaction.followup.send(
                    "❌ Произошла ошибка обработки.", ephemeral=True
                )
            except:
                pass


def setup(bot: commands.Bot) -> None:
    bot.add_cog(AdminStreamers(bot))
