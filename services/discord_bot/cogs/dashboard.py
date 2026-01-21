"""Ког для Панели Управления (Дашборда).
Ported from Legacy to Microservices (API-based).
"""

import disnake
from disnake import ApplicationCommandInteraction, MessageInteraction
from disnake.ext import commands, tasks
from typing import Optional
from datetime import datetime, timedelta, timezone
import calendar
import logging

from config import Config
from utils import (
    create_streamers_component,
    format_spec_duration,
    create_monitoring_select,
)
from cogs.assistant_views import (
    AssistantManagementView,
    AssistantOverviewView,
    AssistantStatsView as NewAssistantStatsView,
    AssistantEditModal,
    AssistantActionsView,
    TopAssistantsView,
)


class DashboardView(disnake.ui.View):
    """Постоянное view для Панели Управления."""

    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

        # Row 0
        self.add_item(
            disnake.ui.Button(
                label="Настройка каналов",
                custom_id="nav_tab_channels",
                emoji="📺",
                row=0,
                style=disnake.ButtonStyle.secondary,
            )
        )
        self.add_item(
            disnake.ui.Button(
                label="Шаблоны уведомлений",
                custom_id="nav_tab_templates",
                emoji="📝",
                row=0,
                style=disnake.ButtonStyle.secondary,
            )
        )
        self.add_item(
            disnake.ui.Button(
                label="Управление стримерами",
                custom_id="nav_tab_streamers",
                emoji="🎥",
                row=0,
                style=disnake.ButtonStyle.secondary,
            )
        )

        # Row 1
        self.add_item(
            disnake.ui.Button(
                label="Управление ассистентами",
                custom_id="nav_tab_assistants",
                emoji="👥",
                row=1,
                style=disnake.ButtonStyle.secondary,
            )
        )
        self.add_item(
            disnake.ui.Button(
                label="Технические настройки",
                custom_id="nav_tab_tech",
                emoji="🛠️",
                row=1,
                style=disnake.ButtonStyle.secondary,
            )
        )
        self.add_item(
            disnake.ui.Button(
                label="События",
                custom_id="nav_tab_events",
                emoji="🎉",
                row=1,
                style=disnake.ButtonStyle.secondary,
            )
        )


class AddStreamerModal(disnake.ui.Modal):
    def __init__(self, bot, guild_id):
        self.bot = bot
        self.guild_id = guild_id
        components = [
            disnake.ui.TextInput(
                label="Ссылка на Twitch или Никнейм",
                placeholder="https://twitch.tv/username",
                custom_id="url",
                style=disnake.TextInputStyle.short,
            ),
            disnake.ui.TextInput(
                label="Приоритет (по умолчанию 0)",
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
            try:
                priority = int(interaction.text_values["priority"])
            except ValueError:
                priority = 0

            if url.startswith("https://www.twitch.tv/"):
                username = url.replace("https://www.twitch.tv/", "").rstrip("/").strip()
            else:
                username = url.rstrip("/").strip()

            # API Call to add streamer
            # Note: Verification happens on API side or Async via Broker
            result = await self.bot.api.add_streamer(
                twitch_url=username, priority=priority
            )

            # Since API might be async in validation, we assume success if 201 created
            await interaction.edit_original_message(
                content=f"✅ Запрос на добавление стримера **{username}** отправлен!"
            )

        except Exception as e:
            self.bot.logger.error(f"Error adding streamer: {e}", exc_info=True)
            await interaction.edit_original_message(content=f"❌ Ошибка: {str(e)}")


class EditStreamerModal(disnake.ui.Modal):
    def __init__(self, bot, streamer_id: int, streamer_name: str, priority: int):
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
            try:
                priority = int(interaction.text_values["priority"])
                if priority < 0 or priority > 3:
                    raise ValueError
            except ValueError:
                await interaction.edit_original_message(
                    content="❌ Приоритет должен быть числом от 0 до 3."
                )
                return

            # Update via API
            await self.bot.api.update_streamer(self.streamer_id, priority=priority)

            await interaction.edit_original_message(
                content=f"✅ Приоритет обновлен на **{priority}**."
            )

        except Exception as e:
            self.bot.logger.error(f"Edit streamer error: {e}")
            await interaction.edit_original_message(content="❌ Произошла ошибка.")


class PointsConfigModal(disnake.ui.Modal):
    def __init__(self, bot, guild_id, current_rates: dict):
        self.bot = bot
        self.guild_id = guild_id

        components = [
            disnake.ui.TextInput(
                label="Приоритет 0 (Балл/Час)",
                value=str(
                    current_rates.get("0", 0.25)
                ),  # API returns keys as strings in JSON?
                custom_id="p0",
                style=disnake.TextInputStyle.short,
            ),
            disnake.ui.TextInput(
                label="Приоритет 1 (Балл/Час)",
                value=str(current_rates.get("1", 0.4)),
                custom_id="p1",
                style=disnake.TextInputStyle.short,
            ),
            disnake.ui.TextInput(
                label="Приоритет 2 (Балл/Час)",
                value=str(current_rates.get("2", 0.5)),
                custom_id="p2",
                style=disnake.TextInputStyle.short,
            ),
            disnake.ui.TextInput(
                label="Приоритет 3 (Балл/Час)",
                value=str(current_rates.get("3", 0.6)),
                custom_id="p3",
                style=disnake.TextInputStyle.short,
            ),
        ]
        super().__init__(title="Настройка баллов", components=components)

    async def callback(self, interaction: disnake.ModalInteraction):
        await interaction.response.defer(ephemeral=True)
        try:
            rates = {}
            for i in range(4):
                val_str = interaction.text_values[f"p{i}"]
                rates[str(i)] = float(val_str.replace(",", "."))

            await self.bot.api.update_guild_rates(
                p0_rate=rates.get("0"),
                p1_rate=rates.get("1"),
                p2_rate=rates.get("2"),
                p3_rate=rates.get("3")
            )
            await interaction.edit_original_message(
                content="✅ Настройки баллов сохранены!"
            )

        except ValueError:
            await interaction.edit_original_message(
                content="❌ Значения должны быть числами."
            )
        except Exception as e:
            self.bot.logger.error(f"Points config error: {e}")
            await interaction.edit_original_message(content="❌ Ошибка сохранения.")


class AssistantStatsView(disnake.ui.View):
    def __init__(self, bot, user, api_client):
        super().__init__(timeout=600)
        self.bot = bot
        self.user = user
        self.api = api_client
        self.filter_mode = "today"  # today, yesterday, all_time

        self.update_components()

    def update_components(self):
        self.clear_items()

        options = [
            disnake.SelectOption(
                label="Сегодня", value="today", default=(self.filter_mode == "today")
            ),
            disnake.SelectOption(
                label="Вчера",
                value="yesterday",
                default=(self.filter_mode == "yesterday"),
            ),
            disnake.SelectOption(
                label="Все время (Топ)",
                value="all_time",
                default=(self.filter_mode == "all_time"),
            ),
        ]
        self.add_item(
            disnake.ui.StringSelect(
                custom_id="filter_date",
                placeholder="Фильтр даты",
                options=options,
                max_values=1,
            )
        )
        self.add_item(
            disnake.ui.Button(
                label="Обновить",
                custom_id="refresh",
                style=disnake.ButtonStyle.secondary,
                emoji="🔄",
            )
        )

    async def get_embed(self):
        # Fetch Data from API
        # We need a unified stats endpoint or reuse existing ones
        # Use simple logic: if all_time -> /assistants (sorted)
        # if today/yesterday -> /stats/daily (new endpoint needed? OR filter /assistants/{id}/stats)
        # Actually existing /stats/leaderboard is all_time/monthly.

        # Fallback: using /stats/leaderboard for all_time, and maybe nothing generic for today/yesterday yet?
        # User wants restored logic.
        # Let's assume /stats/daily exists or I can use /assistants and filter? No inefficient.
        # I will use /stats/leaderboard for all of them but with a param 'period' if available.
        # Currently only LIMIT is available on leaderboard.

        # Simulating logic for now or using available endpoints.
        # TODO: Add date filtering to API stats.

        title = "Статистика"

        if self.filter_mode == "all_time":
            data = await self.api.get_leaderboard(
                limit=20
            )  # This is monthly/all_time usually
            title = "Топ Ассистентов"
            stats = data.get("leaderboard", [])
        else:
            # Placeholder: API doesn't support daily global stats yet in the ported code
            # We can use /stats/daily endpoint if I added it...
            # I see I added /stats/daily in Dashboard cog for 'stats' command!
            # It takes 'days'.
            # So for 'today' we check day 0?
            # But that endpoint returns aggregated stats per day, not per user.

            # Critical Missing: API endpoint for "Top Assistants by Day".
            # I will just show "Not implemented yet" for daily filters to avoid crashing,
            # or revert to all_time.
            stats = []
            title = f"Статистика ({self.filter_mode} - WIP)"

        embed = disnake.Embed(title=title, color=disnake.Color.blue())

        if not stats:
            embed.description = "Нет данных."
        else:
            lines = []
            for i, s in enumerate(stats, 1):
                # s: rank, pr_id, total_formatted, session_count
                lines.append(
                    f"{i}. <@{s['pr_id']}>: **{s['total_formatted']}** ({s['session_count']} сес.)"
                )
            embed.description = "\n".join(lines)

        return embed

    async def interaction_check(self, interaction: disnake.MessageInteraction) -> bool:
        if interaction.data.custom_id == "filter_date":
            self.filter_mode = interaction.values[0]
            self.update_components()
            await interaction.response.edit_message(
                embed=await self.get_embed(), view=self
            )

        elif interaction.data.custom_id == "refresh":
            await interaction.response.edit_message(
                embed=await self.get_embed(), view=self
            )

        return True


class NotificationTemplateModal(disnake.ui.Modal):
    def __init__(self, event_type: str, current_template: str, bot):
        self.bot = bot
        self.event_type = event_type

        labels = {
            "stream_online": "Стрим Начался",
            "stream_offline": "Стрим Закончился",
            "category_to_gta": "Сменил на GTA 5",
            "category_from_gta": "Ушел с GTA 5",
        }
        label = labels.get(event_type, event_type)
        title = f"Редактировать: {label}"

        super().__init__(
            title=title,
            custom_id=f"edit_template_{event_type}",
            components=[
                disnake.ui.TextInput(
                    label="Шаблон уведомления",
                    placeholder="Введите текст уведомления",
                    custom_id="template_input",
                    style=disnake.TextInputStyle.paragraph,
                    value=current_template,
                    required=True,
                    max_length=500,
                ),
            ],
        )

    async def callback(self, interaction: disnake.ModalInteraction):
        await interaction.response.defer(ephemeral=True)
        try:
            new_template = interaction.text_values["template_input"]
            await self.bot.api.update_guild_templates({self.event_type: new_template})
            await interaction.edit_original_message(content=f"✅ Шаблон обновлён!")
        except Exception as e:
            self.bot.logger.error(f"Template update error: {e}")
            await interaction.edit_original_message(content="❌ Ошибка.")


class ResetStatsModal(disnake.ui.Modal):
    """Modal for resetting assistant statistics."""
    def __init__(self, bot):
        self.bot = bot
        components = [
            disnake.ui.TextInput(
                label="ID пользователя Discord",
                placeholder="123456789012345678",
                custom_id="user_id",
                style=disnake.TextInputStyle.short,
                max_length=20,
            ),
        ]
        super().__init__(title="Сбросить статистику", components=components)

    async def callback(self, interaction: disnake.ModalInteraction):
        await interaction.response.defer(ephemeral=True)
        try:
            user_id = int(interaction.text_values["user_id"])
            result = await self.bot.api.reset_assistant_stats(user_id)
            if result:
                await interaction.edit_original_message(
                    content=f"✅ Статистика пользователя <@{user_id}> сброшена!"
                )
            else:
                await interaction.edit_original_message(
                    content="❌ Пользователь не найден или ошибка."
                )
        except ValueError:
            await interaction.edit_original_message(
                content="❌ ID должен быть числом."
            )
        except Exception as e:
            self.bot.logger.error(f"Reset stats error: {e}")
            await interaction.edit_original_message(content="❌ Ошибка.")


class EventCreateModal(disnake.ui.Modal):
    def __init__(self, bot, guild_id, channel_id, dashboard_interaction):
        self.bot = bot
        self.api = bot.api_client
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.dashboard_interaction = dashboard_interaction

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
                placeholder="18:00 или 25.10 18:00 (Необязательно)",
                custom_id="start_time",
                style=disnake.TextInputStyle.short,
                max_length=20,
                required=False
            ),
        ]
        super().__init__(title="Создание события", components=components)

    async def callback(self, interaction: disnake.ModalInteraction):
        await interaction.response.defer(ephemeral=True)
        try:
            name = interaction.text_values["name"]
            description = interaction.text_values["description"]
            try:
                required_count = int(interaction.text_values["required_count"])
            except ValueError:
                await interaction.edit_original_message(content="❌ Количество должно быть числом.")
                return

            # Start Time Parsing (Ported from legacy)
            start_time_str = interaction.text_values["start_time"].strip()
            start_dt = None
            
            if start_time_str:
                try:
                    parts = start_time_str.split()
                    now_msk = datetime.now(timezone(timedelta(hours=3)))
                    
                    if len(parts) == 2:
                        date_str, time_str = parts
                        day, month = map(int, date_str.split("."))
                        hour, minute = map(int, time_str.split(":"))
                        target_dt_msk = datetime(now_msk.year, month, day, hour, minute, tzinfo=timezone(timedelta(hours=3)))
                        if target_dt_msk < now_msk:
                            target_dt_msk = target_dt_msk.replace(year=now_msk.year + 1)
                    elif len(parts) == 1:
                        target_time = datetime.strptime(start_time_str, "%H:%M").time()
                        target_dt_msk = datetime.combine(now_msk.date(), target_time).replace(tzinfo=timezone(timedelta(hours=3)))
                        if target_dt_msk < now_msk:
                            target_dt_msk += timedelta(days=1)
                    else:
                        raise ValueError

                    start_dt = target_dt_msk.astimezone(timezone.utc)
                except ValueError:
                    await interaction.edit_original_message(content="❌ Неверный формат. Используйте `ЧЧ:ММ` или `ДД.ММ ЧЧ:ММ` (МСК).")
                    return
            
            # Send event message to channel
            channel = self.bot.get_channel(self.channel_id)
            if not channel:
                await interaction.edit_original_message(content="❌ Канал не найден.")
                return

            embed = disnake.Embed(
                title=f"🎉 Событие: {name}",
                description=f"{description}\n\n**Требуется PR:** {required_count}\n**Участников:** 0",
                color=disnake.Color.gold()
            )
            embed.set_footer(text=f"Создал: {interaction.user.display_name}")
            
            if start_dt:
                ts = int(start_dt.timestamp())
                embed.add_field(name="🕒 Начало", value=f"<t:{ts}:t> (<t:{ts}:R>)", inline=False)
            
            # Create Event via API
            result = await self.api.create_event(
                name=name,
                description=description,
                required_pr_count=required_count,
                channel_id=self.channel_id,
                created_by=interaction.user.id,
                guild_id=self.guild_id,
                start_time=start_dt.isoformat() if start_dt else None
            )
            
            if not result:
                await interaction.edit_original_message(content="❌ Ошибка API при создании события.")
                return
                
            event_id = result["id"]

            # Send message with Join Button
            join_btn = disnake.ui.Button(
                label="Присоединиться", 
                custom_id=f"event_join_{event_id}", 
                style=disnake.ButtonStyle.success,
                emoji="✋"
            )
            
            msg = await channel.send(embed=embed, components=[join_btn])
            
            # Update API with real message_id
            await self.api.update_event_message(event_id, msg.id)
            
            # Tag role if needed (Logic requires helper to get settings, we can do generic)
            settings = await self.api.get_guild_settings()
            role_mention = ""
            if settings and settings.get("assistant_role_id"):
                 role_mention = f"<@&{settings['assistant_role_id']}>"
            
            if role_mention:
                time_info = "уже началось!" if start_dt is None else "запланировано!"
                await channel.send(f"{role_mention} Новое событие **{name}** {time_info}", delete_after=600)

            # Refresh Dashboard UI
            await interaction.edit_original_message(content="✅ Событие создано!")
            
            # Trigger monitoring update
            await self.api.refresh_monitoring()

        except Exception as e:
            self.bot.logger.error(f"Event creation error: {e}", exc_info=True)
            await interaction.edit_original_message(content="❌ Ошибка.")


class Dashboard(commands.Cog):
    """Система Панели Управления (Ported)."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.api = bot.api_client
        self.check_event_starts.start()

    def cog_unload(self):
        self.check_event_starts.cancel()
        
    @tasks.loop(seconds=60)
    async def check_event_starts(self):
        """Check for scheduled events starting."""
        try:
            events = await self.api.get_scheduled_events()
            for event in events:
                channel_id = event["channel_id"]
                channel = self.bot.get_channel(channel_id)
                if channel:
                    participants = event.get("participants", [])
                    if participants:
                        mentions = [f"<@{p['user_id']}>" for p in participants]
                        mention_str = ", ".join(mentions)
                        try:
                            await channel.send(f"{mention_str} Событие **{event['name']}** началось! Пора присоединяться!", delete_after=300)
                        except Exception as e:
                            self.bot.logger.error(f"Failed to send start notification: {e}")
                
                await self.api.mark_event_notification_sent(event["id"])
                
        except Exception as e:
            self.bot.logger.error(f"Error in check_event_starts loop: {e}", exc_info=True)
    
    @check_event_starts.before_loop
    async def before_check_event_starts(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_ready(self):
        """Регистрация постоянного view при запуске."""
        self.bot.add_view(DashboardView(self.bot))

    @commands.Cog.listener("on_button_click")
    async def on_dashboard_button(self, interaction: MessageInteraction):
        """Обработка кликов по кнопкам дашборда."""
        custom_id = interaction.component.custom_id
        if not custom_id:
            return

        # Navigation
        if custom_id == "btn_back_to_menu":
            await interaction.response.defer()
            embed = disnake.Embed(
                title="🎛️ Панель Управления",
                description="Добро пожаловать в панель управления PRMajesticBot.\nВыберите раздел в меню ниже.",
                color=0x2B2D31,
            )
            embed.set_footer(text="Используйте кнопки для навигации")
            await interaction.edit_original_response(
                embed=embed, view=DashboardView(self.bot)
            )
            return

        elif custom_id == "btn_create_event":
            # Show channel select
            select = disnake.ui.ChannelSelect(
                custom_id="select_event_channel",
                placeholder="Выберите канал для события",
                channel_types=[disnake.ChannelType.text],
                min_values=1,
                max_values=1
            )
            cancel_btn = disnake.ui.Button(label="Отмена", custom_id="btn_cancel_event_create", style=disnake.ButtonStyle.danger)
            view = disnake.ui.View()
            view.add_item(select)
            view.add_item(cancel_btn)
            
            await interaction.response.edit_message(
                embed=disnake.Embed(title="Создание события", description="Выберите канал, куда будет отправлено сообщение о событии.", color=disnake.Color.gold()),
                view=view
            )
            return

        elif custom_id == "btn_cancel_event_create":
            await interaction.response.defer()
            await self.render_tab(interaction, "tab_events")
            return

        elif custom_id == "btn_end_event_select":
             await interaction.response.defer(ephemeral=True)
             events = await self.api.get_active_events(interaction.guild_id)
             if not events:
                 await interaction.followup.send("Нет активных событий.", ephemeral=True)
                 return
             
             options = []
             for e in events:
                 # Parse start_time string
                 try:
                     st = datetime.fromisoformat(e['start_time'].replace("Z", "+00:00"))
                     start_dt = st.strftime("%d.%m %H:%M")
                 except:
                     start_dt = "?"
                 options.append(disnake.SelectOption(label=f"{e['name']} ({start_dt})", value=str(e['id'])))
             
             select = disnake.ui.StringSelect(custom_id="select_end_event", placeholder="Выберите событие для завершения", options=options)
             await interaction.followup.send("Выберите событие для завершения:", view=disnake.ui.View().add_item(select), ephemeral=True)
             return
            
        elif custom_id == "btn_detailed_stats":
             v = AssistantStatsView(self.bot, interaction.user, self.api)
             await interaction.response.send_message(embed=await v.get_embed(), view=v, ephemeral=True)
             return

        elif custom_id == "btn_create_event":
            select = disnake.ui.ChannelSelect(
                custom_id="select_event_channel",
                placeholder="Выберите канал для события",
                channel_types=[disnake.ChannelType.text],
                min_values=1,
                max_values=1
            )
            cancel_btn = disnake.ui.Button(label="Отмена", custom_id="btn_cancel_event_create", style=disnake.ButtonStyle.danger)
            view = disnake.ui.View()
            view.add_item(select)
            view.add_item(cancel_btn)
            
            await interaction.response.edit_message(
                embed=disnake.Embed(title="Создание события", description="Выберите канал, куда будет отправлено сообщение о событии.", color=disnake.Color.gold()),
                view=view
            )
            return

        elif custom_id == "btn_cancel_event_create":
            await interaction.response.defer()
            await self.render_tab(interaction, "tab_events")
            return

        elif custom_id == "btn_end_event_select":
             await interaction.response.defer(ephemeral=True)
             events = await self.api.get_active_events(interaction.guild_id)
             if not events:
                 await interaction.followup.send("Нет активных событий.", ephemeral=True)
                 return
             
             options = []
             for e in events:
                 try:
                     st = datetime.fromisoformat(e['start_time'].replace("Z", "+00:00"))
                     start_dt = st.strftime("%d.%m %H:%M")
                 except:
                     start_dt = "?"
                 options.append(disnake.SelectOption(label=f"{e['name']} ({start_dt})", value=str(e['id'])))
             
             select = disnake.ui.StringSelect(custom_id="select_end_event", placeholder="Выберите событие для завершения", options=options)
             await interaction.followup.send("Выберите событие для завершения:", view=disnake.ui.View().add_item(select), ephemeral=True)
             return
            
        elif custom_id == "btn_detailed_stats":
             v = AssistantStatsView(self.bot, interaction.user, self.api)
             await interaction.response.send_message(embed=await v.get_embed(), view=v, ephemeral=True)
             return

        if custom_id.startswith("nav_"):
            await interaction.response.defer()
            target_tab = custom_id.replace("nav_tab_", "")
            await self.render_tab(interaction, target_tab)
            return

        # Streamer Actions
        if custom_id == "btn_add_streamer":
            await interaction.response.send_modal(
                AddStreamerModal(self.bot, interaction.guild_id)
            )
            return

        if custom_id == "btn_list_streamers":
            await interaction.response.defer(ephemeral=True)
            streamers = await self.api.list_all_streamers()
            if not streamers:
                await interaction.followup.send("Список пуст.", ephemeral=True)
                return

            lines = []
            for s in streamers:
                lines.append(
                    f"• **{s['streamer_name']}** (ID: {s['streamer_id']}) - Priority: {s['priority']}"
                )

            content = "\n".join(lines)[:1900]
            await interaction.followup.send(
                f"Список стримеров:\n{content}", ephemeral=True
            )
            return

        if custom_id == "btn_remove_streamer":
            await interaction.response.defer(ephemeral=True)
            streamers = await self.api.list_all_streamers()
            if not streamers:
                await interaction.followup.send("Некого удалять.", ephemeral=True)
                return

            options = []
            for s in streamers[:25]:
                options.append(
                    disnake.SelectOption(
                        label=s["streamer_name"], value=str(s["streamer_id"])
                    )
                )

            select = disnake.ui.StringSelect(
                custom_id="select_remove_streamer",
                placeholder="Выберите стримера для удаления",
                options=options,
            )
            await interaction.followup.send(
                "Выберите стримера для удаления:",
                view=disnake.ui.View().add_item(select),
                ephemeral=True,
            )
            return

        if custom_id == "btn_edit_streamer":
            await interaction.response.defer(ephemeral=True)
            streamers = await self.api.list_all_streamers()
            if not streamers:
                await interaction.followup.send(
                    "Список стримеров пуст.", ephemeral=True
                )
                return

            options = []
            for s in streamers[:25]:
                options.append(
                    disnake.SelectOption(
                        label=f"{s['streamer_name']} (P{s['priority']})",
                        value=str(s["streamer_id"]),
                    )
                )

            select = disnake.ui.StringSelect(
                custom_id="select_edit_streamer",
                placeholder="Выберите стримера для редактирования",
                options=options,
            )
            await interaction.followup.send(
                "Выберите стримера:",
                view=disnake.ui.View().add_item(select),
                ephemeral=True,
            )
            return

        if custom_id == "btn_config_points":
            # Need to fetch current rates
            settings = await self.api.get_guild_settings()
            
            # Map flat settings to rates dict expected by modal
            rates = {}
            if settings:
                p0 = settings.get("p0_rate")
                rates["0"] = p0 if p0 is not None else 0.0
                
                p1 = settings.get("p1_rate")
                rates["1"] = p1 if p1 is not None else 0.0
                
                p2 = settings.get("p2_rate")
                rates["2"] = p2 if p2 is not None else 0.0
                
                p3 = settings.get("p3_rate")
                rates["3"] = p3 if p3 is not None else 0.0
            
            await interaction.response.send_modal(
                PointsConfigModal(self.bot, interaction.guild_id, rates)
            )
            return

        if custom_id == "btn_reset_stats":
            await interaction.response.send_modal(ResetStatsModal(self.bot))
            return

        # Assistant Management Buttons
        if custom_id == "assistant_back_to_select":
            await interaction.response.defer()
            mgmt_view = AssistantManagementView(self.bot)
            await interaction.edit_original_response(
                embed=await mgmt_view.get_main_embed(),
                view=mgmt_view
            )
            return
        
        if custom_id == "assistant_top":
            await interaction.response.defer()
            top_view = TopAssistantsView(self.bot)
            await interaction.edit_original_response(
                embed=await top_view.get_top_embed(),
                view=top_view
            )
            return
        
        if custom_id == "assistant_top_refresh":
            await interaction.response.defer()
            top_view = TopAssistantsView(self.bot)
            await interaction.edit_original_response(
                embed=await top_view.get_top_embed(),
                view=top_view
            )
            return
        
        if custom_id == "assistant_stats_refresh":
            await interaction.response.defer()
            # Parse user_id from embed footer
            embed = interaction.message.embeds[0] if interaction.message.embeds else None
            if embed and embed.footer:
                try:
                    user_id = int(embed.footer.text.split("ID: ")[1].split(" ")[0])
                    user_name = embed.title.replace("📊 Статистика: ", "") if "Статистика" in embed.title else f"User {user_id}"
                    stats_view = NewAssistantStatsView(self.bot, user_id, user_name)
                    await interaction.edit_original_response(
                        embed=await stats_view.get_stats_embed(),
                        view=stats_view
                    )
                except:
                    pass
            return
        
        if custom_id.startswith("assistant_overview_"):
            await interaction.response.defer()
            user_id = int(custom_id.replace("assistant_overview_", ""))
            try:
                user = await self.bot.fetch_user(user_id)
                user_name = user.display_name
            except:
                user_name = f"User {user_id}"
            overview_view = AssistantOverviewView(self.bot, user_id, user_name)
            await interaction.edit_original_response(
                embed=await overview_view.get_overview_embed(),
                view=overview_view
            )
            return
        
        if custom_id.startswith("assistant_stats_"):
            user_id = int(custom_id.replace("assistant_stats_", ""))
            await interaction.response.defer()
            try:
                user = await self.bot.fetch_user(user_id)
                user_name = user.display_name
            except:
                user_name = f"User {user_id}"
            stats_view = NewAssistantStatsView(self.bot, user_id, user_name)
            await interaction.edit_original_response(
                embed=await stats_view.get_stats_embed(),
                view=stats_view
            )
            return
        
        if custom_id.startswith("assistant_edit_"):
            user_id = int(custom_id.replace("assistant_edit_", ""))
            try:
                user = await self.bot.fetch_user(user_id)
                user_name = user.display_name
            except:
                user_name = f"User {user_id}"
            await interaction.response.send_modal(
                AssistantEditModal(self.bot, user_id, user_name)
            )
            return
        
        if custom_id.startswith("assistant_actions_"):
            await interaction.response.defer()
            user_id = int(custom_id.replace("assistant_actions_", ""))
            try:
                user = await self.bot.fetch_user(user_id)
                user_name = user.display_name
            except:
                user_name = f"User {user_id}"
            actions_view = AssistantActionsView(self.bot, user_id, user_name)
            await interaction.edit_original_response(
                embed=await actions_view.get_actions_embed(),
                view=actions_view
            )
            return
        
        if custom_id.startswith("assistant_reset_full_"):
            await interaction.response.defer(ephemeral=True)
            user_id = int(custom_id.replace("assistant_reset_full_", ""))
            result = await self.api.reset_assistant_stats(user_id)
            if result:
                await interaction.followup.send(f"✅ Статистика <@{user_id}> полностью сброшена.", ephemeral=True)
            else:
                await interaction.followup.send("❌ Ошибка сброса.", ephemeral=True)
            return

        # Template buttons
        if custom_id.startswith("btn_tmpl_"):
            event_type = custom_id.replace("btn_tmpl_", "")
            settings = await self.api.get_guild_settings()
            templates = settings.get("templates", {})
            current = templates.get(event_type, "")
            await interaction.response.send_modal(
                NotificationTemplateModal(event_type, current, self.bot)
            )
            return

    @commands.Cog.listener("on_dropdown")
    async def on_dropdown(self, interaction: MessageInteraction):
        custom_id = interaction.component.custom_id

        # Assistant User Select
        if custom_id == "assistant_select_user":
            await interaction.response.defer()
            user_id = int(interaction.values[0])
            try:
                user = await self.bot.fetch_user(user_id)
                user_name = user.display_name
            except:
                user_name = f"User {user_id}"
            
            overview_view = AssistantOverviewView(self.bot, user_id, user_name)
            await interaction.edit_original_response(
                embed=await overview_view.get_overview_embed(),
                view=overview_view
            )
            return
        
        # Assistant Stats Filter
        if custom_id == "assistant_stats_filter":
            # Get user_id from view reference or embed footer
            # For simplicity, we'll parse from the message
            await interaction.response.defer()
            new_filter = interaction.values[0]
            
            # Try to get user_id from embed footer
            embed = interaction.message.embeds[0] if interaction.message.embeds else None
            if embed and embed.footer:
                try:
                    user_id = int(embed.footer.text.split("ID: ")[1].split(" ")[0])
                    user_name = embed.title.replace("📊 Статистика: ", "") if "Статистика" in embed.title else f"User {user_id}"
                    
                    stats_view = NewAssistantStatsView(self.bot, user_id, user_name)
                    stats_view.filter_mode = new_filter
                    stats_view._build_components()
                    
                    await interaction.edit_original_response(
                        embed=await stats_view.get_stats_embed(),
                        view=stats_view
                    )
                except:
                    pass
            return

        if custom_id == "select_remove_streamer":
            await interaction.response.defer(ephemeral=True)
            streamer_id = int(interaction.values[0])
            await self.api.delete_streamer(streamer_id)
            await interaction.edit_original_message(
                content="✅ Стример удален!", view=None
            )

        elif custom_id == "select_edit_streamer":
            streamer_id = int(interaction.values[0])
            # Fetch streamer details?
            streamer = await self.api.get_streamer(streamer_id)
            if streamer:
                await interaction.response.send_modal(
                    EditStreamerModal(
                        self.bot,
                        streamer_id,
                        streamer["streamer_name"],
                        streamer["priority"],
                    )
                )
            else:
                await interaction.response.send_message(
                    "Стример не найден", ephemeral=True
                )

        elif custom_id == "select_event_channel":
            channel_id = int(interaction.values[0])
            await interaction.response.send_modal(
                EventCreateModal(self.bot, interaction.guild_id, channel_id, interaction)
            )

        elif custom_id == "select_end_event":
            await interaction.response.defer(ephemeral=True)
            event_id = int(interaction.values[0])
            
            result = await self.api.end_event(event_id)
            if not result:
                await interaction.followup.send("❌ Ошибка завершения.", ephemeral=True)
                return

            participants = result.get("participants", [])
            
            # Log
            msg = f"🏁 **Событие завершено** (ID: {event_id})"
            if participants:
                msg += f"\nУчастников: {len(participants)}"
                for p in participants:
                     dur = format_spec_duration(p['duration'])
                     await self._send_pr_action(interaction.guild_id, f"📤 **Открепление (Конец)**\n🎯 <@{p['user_id']}>\n⏱️ {dur}")
            
            await self._send_pr_action(interaction.guild_id, msg)
            
            # Update Dashboard
            await self.api.refresh_monitoring()
            await interaction.edit_original_response(content="✅ Событие завершено!", view=None)

        elif custom_id == "select_notification_template":
             event_type = interaction.values[0]
             settings = await self.api.get_guild_settings()
             templates = settings.get("templates", {})
             current_template = templates.get(event_type, "")
             await interaction.response.send_modal(
                 NotificationTemplateModal(event_type, current_template, self.bot)
             )

    async def render_tab(self, interaction, tab_name):
        view = disnake.ui.View()
        view.add_item(
            disnake.ui.Button(
                label="Назад",
                custom_id="btn_back_to_menu",
                style=disnake.ButtonStyle.secondary,
                emoji="🔙",
                row=2,
            )
        )

        embed = disnake.Embed(color=0x2B2D31)

        if tab_name == "streamers":
            embed.title = "🎥 Управление стримерами"
            embed.description = "Добавляйте, удаляйте и настраивайте стримеров."

            view.add_item(
                disnake.ui.Button(
                    label="Добавить",
                    custom_id="btn_add_streamer",
                    style=disnake.ButtonStyle.success,
                    emoji="➕",
                    row=0,
                )
            )
            view.add_item(
                disnake.ui.Button(
                    label="Список",
                    custom_id="btn_list_streamers",
                    style=disnake.ButtonStyle.primary,
                    emoji="📋",
                    row=0,
                )
            )
            view.add_item(
                disnake.ui.Button(
                    label="Удалить",
                    custom_id="btn_remove_streamer",
                    style=disnake.ButtonStyle.danger,
                    emoji="🗑️",
                    row=0,
                )
            )
            view.add_item(
                disnake.ui.Button(
                    label="Редактировать",
                    custom_id="btn_edit_streamer",
                    style=disnake.ButtonStyle.secondary,
                    emoji="✏️",
                    row=0,
                )
            )

        elif tab_name == "assistants":
            # Use new modular assistant management
            mgmt_view = AssistantManagementView(self.bot)
            await interaction.edit_original_response(
                embed=await mgmt_view.get_main_embed(),
                view=mgmt_view,
            )
            return  # Special case

        elif tab_name == "channels":
            embed.title = "📺 Настройка каналов"
            embed.description = "Используйте команду `/setup` для настройки каналов."

        elif tab_name == "templates":
            embed.title = "📝 Шаблоны уведомлений"
            embed.description = "Настройте текст уведомлений."
            view.add_item(
                disnake.ui.Button(
                    label="Стрим Начался", custom_id="btn_tmpl_stream_online", row=0
                )
            )
            view.add_item(
                disnake.ui.Button(
                    label="Стрим Закончился", custom_id="btn_tmpl_stream_offline", row=0
                )
            )
            view.add_item(
                disnake.ui.Button(
                    label="В GTA 5", custom_id="btn_tmpl_category_to_gta", row=1
                )
            )
            view.add_item(
                disnake.ui.Button(
                    label="Из GTA 5", custom_id="btn_tmpl_category_from_gta", row=1
                )
            )

        elif tab_name == "tech":
            embed.title = "🛠️ Технические настройки"
            embed.description = "Настройка баллов и системы."
            view.add_item(
                disnake.ui.Button(
                    label="Настройка баллов",
                    custom_id="btn_config_points",
                    style=disnake.ButtonStyle.primary,
                )
            )

        elif tab_name == "events":
            embed.title = "🎉 События"
            events = await self.api.get_active_events(interaction.guild_id)
            if events:
                embed.description = f"Активных событий: **{len(events)}**"
                for e in events:
                    try:
                        st = datetime.fromisoformat(e.get('start_time', '').replace("Z", "+00:00"))
                        start_str = f"<t:{int(st.timestamp())}:R>"
                    except:
                        start_str = "?"
                    
                    e_name = e.get('name') or "Без названия"
                    e_req = e.get('required_pr_count', 0)
                    e_curr = e.get('current_participants', 0)
                    
                    embed.add_field(
                        name=f"📅 {e_name}", 
                        value=f"👥 Участников: {e_curr}/{e_req}\n🕒 {start_str}",
                        inline=False
                    )
            else:
                embed.description = "Нет активных событий."
                
            view.add_item(disnake.ui.Button(label="Создать событие", custom_id="btn_create_event", style=disnake.ButtonStyle.success, emoji="➕", row=0))
            if events:
                view.add_item(disnake.ui.Button(label="Завершить событие", custom_id="btn_end_event_select", style=disnake.ButtonStyle.danger, emoji="🏁", row=0))

        # Safeguard for empty description
        if not embed.description:
            embed.description = "..."
            self.bot.logger.warning(f"Empty description in render_tab for {tab_name}")
            
        await interaction.edit_original_response(embed=embed, view=view)

    async def _send_pr_action(self, guild_id, message):
        """Send message to PR actions channel."""
        try:
            settings = await self.api.get_guild_settings()
            if settings and settings.get("pr_actions_channel_id"):
                channel = self.bot.get_channel(settings["pr_actions_channel_id"])
                if channel:
                    await channel.send(message)
        except Exception as e:
            self.bot.logger.error(f"Error sending PR action: {e}")

    async def update_monitoring_message(self):
        """
        Update monitoring message with robust legacy logic (Ported).
        """
        try:
            # 1. Get Settings for target guild
            settings = await self.api.get_guild_settings()
            if not settings:
                # self.bot.logger.warning("Could not fetch guild settings via API")
                return

            guild_id = settings.get("guild_id") or Config.GUILD_ID
            monitoring_channel_id = settings.get("monitoring_channel_id")
            monitoring_message_id = settings.get("monitoring_message_id")

            if not monitoring_channel_id:
                return

            # 2. Get Channel
            channel = self.bot.get_channel(monitoring_channel_id)
            if not channel:
                # Try fetch
                try:
                    channel = await self.bot.fetch_channel(monitoring_channel_id)
                except Exception:
                    self.bot.logger.warning(
                        f"Monitoring channel {monitoring_channel_id} not found/accessible"
                    )
                    return

            # 3. Fetch Data
            # Streamers
            streamers = await self.api.list_all_streamers()

            # Filter Online Streamers
            online_streamers = []
            available_streamers = []  # For Select Menu (GTA 5 + No PR)
            gta_count = 0

            for s in streamers:
                if s.get("is_online"):
                    online_streamers.append(s)

                    is_gta = str(s.get("game_id")) == Config.GTA5_GAME_ID
                    if is_gta:
                        gta_count += 1
                        # If no PR assigned, it is available
                        if not s.get("assigned_pr_id"):
                            available_streamers.append(s)

            # Events (Placeholder for now, API needs GET /events/active)
            # active_events = await self.api.get_active_events()
            active_events = []

            # 4. Build Components
            # Main Container (Embed-like UI)
            container = create_streamers_component(
                online_streamers, len(streamers), gta_count, events=active_events
            )

            # Select Menu (For claiming)
            select_row = create_monitoring_select(available_streamers, active_events)

            final_components = [container, select_row]

            # 5. Edit or Create Message
            message = None
            if monitoring_message_id:
                try:
                    message = await channel.fetch_message(monitoring_message_id)
                except (disnake.NotFound, disnake.HTTPException):
                    self.bot.logger.warning(
                        f"Monitoring message {monitoring_message_id} not found. Creating new."
                    )
                    message = None

            if message:
                try:
                    await message.edit(components=final_components)
                    self.bot.logger.info(
                        f"Updated monitoring message for guild {guild_id}"
                    )
                except Exception as e:
                    self.bot.logger.error(f"Failed to edit monitoring message: {e}")
            else:
                try:
                    new_message = await channel.send(components=final_components)
                    # Update settings with new ID
                    await self.api.update_guild_settings(
                        monitoring_message_id=new_message.id
                    )
                    self.bot.logger.info(
                        f"Created monitoring message {new_message.id} for guild {guild_id}"
                    )
                except Exception as e:
                    self.bot.logger.error(f"Failed to send monitoring message: {e}")

        except Exception as e:
            self.bot.logger.error(f"Error updating monitoring: {e}", exc_info=True)


def setup(bot: commands.Bot) -> None:
    bot.add_cog(Dashboard(bot))
