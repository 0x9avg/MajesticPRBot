"""Events Manager - Event Creation and Scheduling.
EventCreateModal, scheduled events loop, event end logic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api_client import APIClient
    from discord_bot import DiscordBot

from datetime import datetime, timedelta, timezone

import disnake
from disnake import MessageInteraction
from disnake.ext import commands, tasks

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
            try:
                st = datetime.fromisoformat(event["start_time"].replace("Z", "+00:00"))
                ts = int(st.timestamp())
                time_str = f"<t:{ts}:R>"
            except Exception:
                time_str = "?"

            embed.add_field(
                name=f"📅 {event['name']}",
                value=(
                    f"👥 Участников: **{event.get('current_participants', 0)}** "
                    f"(Треб: {event.get('required_pr_count', '?')})\n"
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

    def __init__(self, bot: "DiscordBot", channel_id: int):
        self.bot = bot
        self.channel_id = channel_id

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
                label="Количество PR",
                placeholder="5",
                custom_id="required_count",
                style=disnake.TextInputStyle.short,
                max_length=3,
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
                required_count = int(interaction.text_values["required_count"])
            except ValueError:
                await interaction.edit_original_message(
                    content="❌ Количество должно быть числом"
                )
                return

            # Parse start time (MSK -> UTC)
            start_time_str = interaction.text_values.get("start_time", "").strip()
            start_dt = None

            if start_time_str:
                try:
                    parts = start_time_str.split()
                    msk_tz = timezone(timedelta(hours=3))
                    now_msk = datetime.now(msk_tz)

                    if len(parts) == 2:
                        # DD.MM HH:MM format
                        date_str, time_str = parts
                        day, month = map(int, date_str.split("."))
                        hour, minute = map(int, time_str.split(":"))
                        target_dt_msk = datetime(
                            now_msk.year, month, day, hour, minute, tzinfo=msk_tz
                        )
                        if target_dt_msk < now_msk:
                            target_dt_msk = target_dt_msk.replace(year=now_msk.year + 1)
                    elif len(parts) == 1:
                        # HH:MM format (today or tomorrow)
                        hour, minute = map(int, start_time_str.split(":"))
                        target_dt_msk = datetime.combine(
                            now_msk.date(),
                            datetime.strptime(start_time_str, "%H:%M").time(),
                        ).replace(tzinfo=msk_tz)
                        if target_dt_msk < now_msk:
                            target_dt_msk += timedelta(days=1)
                    else:
                        raise ValueError("Invalid format")

                    start_dt = target_dt_msk.astimezone(timezone.utc)
                except Exception:
                    await interaction.edit_original_message(
                        content="❌ Неверный формат. Используйте `ЧЧ:ММ` или `ДД.ММ ЧЧ:ММ` (МСК)"
                    )
                    return

            # Get channel
            channel = self.bot.get_channel(self.channel_id)
            if not channel:
                await interaction.edit_original_message(content="❌ Канал не найден")
                return

            # Create embed
            embed = disnake.Embed(
                title=f"🎉 Событие: {name}",
                description=f"{description}\n\n**Требуется PR:** {required_count}\n**Участников:** 0",
                color=disnake.Color.gold(),
            )
            embed.set_footer(text=f"Создал: {interaction.user.display_name}")

            if start_dt:
                ts = int(start_dt.timestamp())
                embed.add_field(
                    name="🕒 Начало", value=f"<t:{ts}:t> (<t:{ts}:R>)", inline=False
                )

            # Create event via API
            result = await self.bot.api_client.create_event(
                name=name,
                description=description,
                required_pr_count=required_count,
                channel_id=self.channel_id,
                created_by=interaction.user.id,
                start_time=start_dt.isoformat() if start_dt else None,
            )

            if not result:
                await interaction.edit_original_message(content="❌ Ошибка API")
                return

            event_id = result["id"]

            # Send message with Join button
            join_btn = disnake.ui.Button(
                label="Присоединиться",
                custom_id=f"event_join_{event_id}",
                style=disnake.ButtonStyle.success,
                emoji="✋",
            )
            msg = await channel.send(embed=embed, components=[join_btn])

            # Update API with message_id
            await self.bot.api_client.update_event_message(event_id, msg.id)

            # Tag role
            settings = await self.bot.api_client.get_guild_settings()
            if settings and settings.get("assistant_role_id"):
                role_mention = f"<@&{settings['assistant_role_id']}>"
                time_info = "уже началось!" if start_dt is None else "запланировано!"
                await channel.send(
                    f"{role_mention} Новое событие **{name}** {time_info}",
                    delete_after=600,
                )

            await interaction.edit_original_message(content="✅ Событие создано!")

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
                                from .manager import get_events_embed, EventsView
                                embed = await get_events_embed(self.bot.api_client)
                                await msg.edit(embed=embed, view=EventsView(self.bot))
                                self.bot.logger.info(f"✓ Updated control panel message in {channel.name}")
                            except disnake.NotFound:
                                self.bot.logger.warning("Control Panel message not found (deleted?)")
                            except Exception as e:
                                self.bot.logger.error(f"Failed to edit control panel: {e}")
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
            try:
                st = datetime.fromisoformat(e["start_time"].replace("Z", "+00:00"))
                time_str = st.strftime("%d.%m %H:%M")
            except Exception:
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
                                from .manager import get_events_embed, EventsView
                                embed = await get_events_embed(interaction.bot.api_client)
                                await msg.edit(embed=embed, view=EventsView(interaction.bot))
                                interaction.bot.logger.info(f"✓ Updated control panel message in {channel.name}")
                            except disnake.NotFound:
                                interaction.bot.logger.warning("Control Panel message not found (deleted?)")
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
        """Show channel select for event creation."""
        select = disnake.ui.ChannelSelect(
            custom_id="admin_events_channel_select",
            placeholder="Выберите канал для события",
            channel_types=[disnake.ChannelType.text],
            min_values=1,
            max_values=1,
        )
        view = disnake.ui.View(timeout=None)
        view.add_item(select)

        await interaction.response.send_message(
            "Выберите канал для события:", view=view, ephemeral=True
        )

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
        self.check_event_starts.start()

    def cog_unload(self):
        self.check_event_starts.cancel()

    @tasks.loop(seconds=60)
    async def check_event_starts(self):
        """Check for scheduled events that need to start."""
        try:
            events = await self.api.get_scheduled_events()
            for event in events:
                channel_id = event.get("channel_id")
                channel = self.bot.get_channel(int(channel_id)) if channel_id else None

                if channel:
                    participants = event.get("participants", [])
                    if participants:
                        mentions = [f"<@{p['user_id']}>" for p in participants]
                        mention_str = ", ".join(mentions)
                        try:
                            await channel.send(
                                f"{mention_str} Событие **{event['name']}** началось!",
                                delete_after=300,
                            )
                        except Exception as e:
                            self.bot.logger.error(
                                f"Event start notification error: {e}"
                            )

                # Mark as notified
                await self.api.mark_event_notification_sent(event["id"])

        except Exception as e:
            self.bot.logger.error(f"check_event_starts error: {e}", exc_info=True)

    @check_event_starts.before_loop
    async def before_check_event_starts(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener("on_button_click")
    async def on_events_button(self, interaction: MessageInteraction):
        """Handle admin_events navigation."""
        if interaction.component.custom_id != "admin_events":
            return

        if not interaction.response.is_done():
            await interaction.response.defer()
        embed = await get_events_embed(self.api)
        await interaction.edit_original_response(embed=embed, view=EventsView(self.bot))

    @commands.Cog.listener("on_dropdown")
    async def on_events_channel_select(self, interaction: MessageInteraction):
        """Handle channel select for event creation."""
        if interaction.component.custom_id != "admin_events_channel_select":
            return

        channel_id = int(interaction.values[0])
        await interaction.response.send_modal(EventCreateModal(self.bot, channel_id))


def setup(bot: commands.Bot) -> None:
    bot.add_cog(EventsManager(bot))
