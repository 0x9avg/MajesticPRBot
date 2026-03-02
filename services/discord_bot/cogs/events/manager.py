"""Events Manager - Event Creation and Scheduling.
EventCreateModal, scheduled events loop, event end logic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api_client import APIClient
    from discord_bot import DiscordBot

from datetime import datetime, timedelta, timezone

# Moscow timezone (UTC+3)
MSK = timezone(timedelta(hours=3))

import disnake
from disnake import MessageInteraction
from disnake.ext import commands, tasks
from utils import parse_to_unix

# =============================================================================
# Events Embed
# =============================================================================


async def get_events_embed(api) -> disnake.Embed:
    """Create embed showing active events."""
    try:
        events = await api.get_active_events()
    except Exception:
        events = []

    embed = disnake.Embed(
        title="🎉 Управление Событиями",
        color=0xFFC107,
    )

    if not events:
        embed.description = "Нет активных событий.\nСоздайте новое!"
    else:
        for event in events:
            ts = parse_to_unix(event.get("start_time"))
            time_str = f"<t:{ts}:R>" if ts else "?"

            embed.add_field(
                name=f"📅 {event['name']}",
                value=(
                    f"👥 Участников: **{event.get('current_participants', 0)}** "
                    f"(Слотов: {event.get('pr_slots', event.get('required_pr_count', '?'))})\n"
                    f"🕒 Начало: {time_str}"
                ),
                inline=False,
            )

    return embed





# =============================================================================
# Event Create Modal
# =============================================================================

class EventCreateModal(disnake.ui.Modal):
    """Modal for creating a new event with optional scheduling."""

    bot: "DiscordBot"

    def __init__(self, bot: "DiscordBot"):
        self.bot = bot

        components = [
            disnake.ui.TextInput(
                label="Название события",
                placeholder="Спек для Ютубера...",
                custom_id="name",
                style=disnake.TextInputStyle.short,
                max_length=100,
            ),
            disnake.ui.TextInput(
                label="Описание",
                placeholder="Подробности мероприятия...",
                custom_id="description",
                style=disnake.TextInputStyle.paragraph,
                max_length=1000,
            ),
            disnake.ui.TextInput(
                label="Слоты PR",
                placeholder="5",
                custom_id="pr_slots",
                style=disnake.TextInputStyle.short,
                max_length=3,
            ),
            disnake.ui.TextInput(
                label="Приоритет (0-3)",
                placeholder="0",
                custom_id="priority",
                style=disnake.TextInputStyle.short,
                max_length=1,
                required=False,
            ),
            disnake.ui.TextInput(
                label="Время начала (МСК) [ДД.ММ ЧЧ:ММ]",
                placeholder="18:00 или 25.01 18:00 (Необязательно)",
                custom_id="start_time",
                style=disnake.TextInputStyle.short,
                max_length=20,
                required=False,
            ),
        ]
        super().__init__(title="Создание события", components=components)

    async def callback(self, interaction: disnake.ModalInteraction):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        try:
            name = interaction.text_values["name"]
            description = interaction.text_values["description"]

            try:
                pr_slots = int(interaction.text_values["pr_slots"])
            except ValueError:
                await interaction.edit_original_message(
                    content="❌ Количество слотов должно быть числом"
                )
                return

            priority_str = interaction.text_values.get("priority", "0").strip()
            try:
                priority = int(priority_str) if priority_str else 0
                priority = max(0, min(3, priority))
            except ValueError:
                priority = 0

            # Parse start time (Local -> UTC)
            start_time_str = interaction.text_values.get("start_time", "").strip()
            start_dt = None

            if start_time_str:
                from datetime import datetime, timedelta, timezone
                try:
                    parts = start_time_str.split()
                    now_local = datetime.now(MSK)

                    if len(parts) == 2:
                        # DD.MM HH:MM format
                        date_str, time_str = parts
                        day, month = map(int, date_str.split("."))
                        hour, minute = map(int, time_str.split(":"))
                        target_dt_local = datetime(
                            now_local.year, month, day, hour, minute, tzinfo=now_local.tzinfo
                        )
                        if target_dt_local < now_local:
                            target_dt_local = target_dt_local.replace(year=now_local.year + 1)
                    elif len(parts) == 1:
                        # HH:MM format (today or tomorrow)
                        hour, minute = map(int, start_time_str.split(":"))
                        target_dt_local = datetime.combine(
                            now_local.date(),
                            datetime.strptime(start_time_str, "%H:%M").time(),
                        ).replace(tzinfo=now_local.tzinfo)
                        if target_dt_local < now_local:
                            target_dt_local += timedelta(days=1)
                    else:
                        raise ValueError("Invalid format")

                    # target_dt_local already has MSK timezone set above
                    start_dt = target_dt_local
                except Exception:
                    await interaction.edit_original_message(
                        content="❌ Неверный формат. Используйте `ЧЧ:ММ` или `ДД.ММ ЧЧ:ММ` (МСК)"
                    )
                    return

            # Create event via API
            result = await self.bot.api_client.create_event(
                name=name,
                description=description,
                required_pr_count=pr_slots,
                created_by=interaction.user.id,
                start_time=start_dt.isoformat() if start_dt else None,
                pr_slots=pr_slots,
                priority=priority,
            )

            if not result:
                await interaction.edit_original_message(content="❌ Ошибка API")
                return

            event_id = result["id"]

            await interaction.edit_original_message(content="✅ Событие создано!")

            # Tag role and notify
            settings = await self.bot.api_client.get_guild_settings()
            if settings:
                notification_channel_id = settings.get("notification_channel_id")
                if notification_channel_id:
                    channel = self.bot.get_channel(int(notification_channel_id))
                    if channel:
                        time_info = "уже началось!" if start_dt is None else "запланировано!"
                        try:
                            await channel.send(
                                f"Новое событие **{name}** {time_info}",
                                delete_after=600,
                            )
                        except Exception as e:
                            self.bot.logger.error(f"Event announce error: {e}")

            # Refresh the persistent Control Panel Message
            try:
                guild_settings = await self.bot.api_client.get_guild_settings()
                if guild_settings:
                    cp_channel_id = guild_settings.get("control_panel_channel_id")
                    cp_message_id = guild_settings.get("control_panel_message_id")

                    if cp_channel_id and cp_message_id:
                        channel = self.bot.get_channel(int(cp_channel_id))
                        if channel:
                            try:
                                msg = await channel.fetch_message(int(cp_message_id))
                                embed = await get_events_embed(self.bot.api_client)
                                await msg.edit(embed=embed, view=EventsView(self.bot))
                                self.bot.logger.info(
                                    f"✓ Updated control panel message in {channel.name}"
                                )
                            except disnake.NotFound:
                                self.bot.logger.warning(
                                    "Control Panel message not found (deleted?)"
                                )
                            except Exception as e:
                                self.bot.logger.error(
                                    f"Failed to edit control panel: {e}"
                                )
            except Exception as e:
                self.bot.logger.error(f"Control panel refresh error: {e}")

            # Refresh monitoring
            await self.bot.api_client.refresh_monitoring()

        except Exception as e:
            self.bot.logger.error(f"Event creation error: {e}", exc_info=True)
            await interaction.edit_original_message(content="❌ Ошибка")

# =============================================================================
# Event Select for Ending
# =============================================================================


class EventEndSelect(disnake.ui.StringSelect):
    """Select for choosing event to end."""

    def __init__(self, events: list):
        options = []
        for e in events[:25]:
            ts = parse_to_unix(e.get("start_time"))
            if ts:
                from datetime import datetime
                time_str = datetime.fromtimestamp(ts, tz=MSK).strftime(
                    "%d.%m %H:%M"
                )
            else:
                time_str = "?"
            options.append(
                disnake.SelectOption(
                    label=f"{e['name']} ({time_str})",
                    value=str(e["id"]),
                )
            )
        super().__init__(
            custom_id="admin_events_end_select",
            placeholder="Выберите событие для завершения",
            options=options,
        )

    async def callback(self, interaction: MessageInteraction):
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        event_id = int(self.values[0])

        try:
            # End event via API
            result = await interaction.bot.api_client.end_event(event_id)

            # Try to update the event message
            if result and result.get("channel_id") and result.get("message_id"):
                channel = interaction.bot.get_channel(int(result["channel_id"]))
                if channel:
                    try:
                        msg = await channel.fetch_message(int(result["message_id"]))
                        embed = msg.embeds[0] if msg.embeds else None
                        if embed:
                            embed.title = f"🏁 [ЗАВЕРШЕНО] {embed.title.replace('🎉 Событие: ', '')}"
                            embed.color = disnake.Color.dark_grey()
                            await msg.edit(embed=embed, components=[])
                    except Exception:
                        pass

            await interaction.edit_original_response(content="✅ Событие завершено!")

            # Refresh the persistent Control Panel Message
            try:
                guild_settings = await interaction.bot.api_client.get_guild_settings()
                if guild_settings:
                    cp_channel_id = guild_settings.get("control_panel_channel_id")
                    cp_message_id = guild_settings.get("control_panel_message_id")

                    if cp_channel_id and cp_message_id:
                        channel = interaction.bot.get_channel(int(cp_channel_id))
                        if channel:
                            try:
                                msg = await channel.fetch_message(int(cp_message_id))

                                embed = await get_events_embed(
                                    interaction.bot.api_client
                                )
                                await msg.edit(
                                    embed=embed, view=EventsView(interaction.bot)
                                )
                                interaction.bot.logger.info(
                                    f"✓ Updated control panel message in {channel.name}"
                                )
                            except disnake.NotFound:
                                interaction.bot.logger.warning(
                                    "Control Panel message not found (deleted?)"
                                )
            except Exception as e:
                interaction.bot.logger.error(f"Failed to refresh persistent panel: {e}")

            # Refresh monitoring
            await interaction.bot.api_client.refresh_monitoring()

        except Exception as e:
            interaction.bot.logger.error(f"End event error: {e}")
            await interaction.edit_original_response(content="❌ Ошибка")


# =============================================================================
# Events View
# =============================================================================


class EventsView(disnake.ui.View):
    """View for event management."""

    bot: "DiscordBot"

    def __init__(self, bot: "DiscordBot"):
        super().__init__(timeout=None)
        self.bot = bot

    @disnake.ui.button(
        label="Создать",
        custom_id="admin_events_create",
        style=disnake.ButtonStyle.success,
        emoji="➕",
        row=0,
    )
    async def create_button(
        self, button: disnake.ui.Button, interaction: MessageInteraction
    ):
        """Show event creation modal."""
        await interaction.response.send_modal(EventCreateModal(self.bot))

    @disnake.ui.button(
        label="Завершить",
        custom_id="admin_events_end",
        style=disnake.ButtonStyle.danger,
        emoji="🏁",
        row=0,
    )
    async def end_button(
        self, button: disnake.ui.Button, interaction: MessageInteraction
    ):
        """Show event select for ending."""
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        events = await self.bot.api_client.get_active_events()
        if not events:
            await interaction.followup.send("Нет активных событий", ephemeral=True)
            return

        view = disnake.ui.View(timeout=None)
        view.add_item(EventEndSelect(events))
        await interaction.followup.send(
            "Выберите событие для завершения:", view=view, ephemeral=True
        )

    @disnake.ui.button(
        label="Назад",
        custom_id="admin_events_back",
        style=disnake.ButtonStyle.secondary,
        emoji="🔙",
        row=1,
    )
    async def back_button(
        self, button: disnake.ui.Button, interaction: MessageInteraction
    ):
        from cogs.admin.core import AdminMainView, get_main_embed

        if not interaction.response.is_done():
            await interaction.response.defer()

        await interaction.edit_original_response(
            embed=get_main_embed(), view=AdminMainView(self.bot)
        )


# =============================================================================
# Events Manager Cog
# =============================================================================


class EventsManager(commands.Cog):
    """Event creation, scheduling, and management."""

    bot: "DiscordBot"
    api: "APIClient"

    def __init__(self, bot: "DiscordBot") -> None:
        self.bot = bot
        self.api = bot.api_client

    @commands.Cog.listener("on_button_click")
    async def on_events_button(self, interaction: MessageInteraction):
        """Handle admin_events navigation."""
        if interaction.component.custom_id != "admin_events":
            return

        if not interaction.response.is_done():
            await interaction.response.defer()
        embed = await get_events_embed(self.api)
        await interaction.edit_original_response(embed=embed, view=EventsView(self.bot))




def setup(bot: commands.Bot) -> None:
    bot.add_cog(EventsManager(bot))
