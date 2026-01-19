"""Ког для Панели Управления (Дашборда)."""

import disnake
from disnake import ApplicationCommandInteraction, MessageInteraction
from disnake.ext import commands, tasks
from typing import Optional
from datetime import datetime, timedelta, timezone
import calendar

from config import Config

from utils import create_streamers_component, format_spec_duration

class DashboardView(disnake.ui.View):
    """Постоянное view для Панели Управления."""
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot
        
        # Row 0
        self.add_item(disnake.ui.Button(label="Настройка каналов", custom_id="nav_tab_channels", emoji="📺", row=0, style=disnake.ButtonStyle.secondary))
        self.add_item(disnake.ui.Button(label="Шаблоны уведомлений", custom_id="nav_tab_templates", emoji="📝", row=0, style=disnake.ButtonStyle.secondary))
        self.add_item(disnake.ui.Button(label="Управление стримерами", custom_id="nav_tab_streamers", emoji="🎥", row=0, style=disnake.ButtonStyle.secondary))
        
        # Row 1
        self.add_item(disnake.ui.Button(label="Управление ассистентами", custom_id="nav_tab_assistants", emoji="👥", row=1, style=disnake.ButtonStyle.secondary))
        self.add_item(disnake.ui.Button(label="Технические настройки", custom_id="nav_tab_tech", emoji="🛠️", row=1, style=disnake.ButtonStyle.secondary))
        self.add_item(disnake.ui.Button(label="События", custom_id="nav_tab_events", emoji="🎉", row=1, style=disnake.ButtonStyle.secondary))

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
                value="0"
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

            streamer_id = await self.bot.twitch_bot.get_streamer_id(username)
            if streamer_id is None:
                await interaction.edit_original_message(content=f"❌ Стример {username} не найден на Twitch.")
                return

            await self.bot.twitch_bot.add_notification(streamer_id)
            stream_data = await self.bot.twitch_bot.get_stream_info(streamer_id)

            if not await self.bot.database.streamer_exists(streamer_id):
                await self.bot.database.create_streamer(
                    streamer_name=username,
                    streamer_id=streamer_id,
                    is_online=stream_data["is_online"],
                    started_at=stream_data["started_at"],
                    game_id=stream_data["game_id"],
                    game_name=stream_data["game_name"],
                    stream_title=stream_data["title"],
                    stream_thumbnail_url=stream_data["thumbnail_url"],
                    priority=priority,
                    added_by_id=interaction.user.id,
                    is_paid=False, 
                )

            await self.bot.twitch_bot.update_monitoring_messages()
            await interaction.edit_original_message(content=f"✅ Стример **{username}** добавлен!")
            
        except Exception as e:
            self.bot.logger.error(f"Error adding streamer: {e}", exc_info=True)
            self.bot.logger.error(f"Error adding streamer: {e}", exc_info=True)
            await interaction.edit_original_message(content="❌ Произошла ошибка при добавлении.")

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
                max_length=1
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
                await interaction.edit_original_message(content="❌ Приоритет должен быть числом от 0 до 3.")
                return

            # Update DB
            success = await self.bot.database.update_streamer_priority(self.streamer_id, priority)
            
            if success:
                await interaction.edit_original_message(content=f"✅ Приоритет стримера обновлен на **{priority}**.")
            else:
                await interaction.edit_original_message(content="❌ Ошибка при обновлении базы данных.")
                
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
                value=str(current_rates.get(0, 0.25)),
                custom_id="p0",
                style=disnake.TextInputStyle.short
            ),
            disnake.ui.TextInput(
                label="Приоритет 1 (Балл/Час)",
                value=str(current_rates.get(1, 0.4)),
                custom_id="p1",
                style=disnake.TextInputStyle.short
            ),
            disnake.ui.TextInput(
                label="Приоритет 2 (Балл/Час)",
                value=str(current_rates.get(2, 0.5)),
                custom_id="p2",
                style=disnake.TextInputStyle.short
            ),
            disnake.ui.TextInput(
                label="Приоритет 3 (Балл/Час)",
                value=str(current_rates.get(3, 0.6)),
                custom_id="p3",
                style=disnake.TextInputStyle.short
            ),
        ]
        super().__init__(title="Настройка баллов", components=components)

    async def callback(self, interaction: disnake.ModalInteraction):
        await interaction.response.defer(ephemeral=True)
        try:
            rates = {}
            for i in range(4):
                val_str = interaction.text_values[f"p{i}"]
                rates[i] = float(val_str.replace(",", "."))
            
            await self.bot.database.set_points_config(self.guild_id, rates)
            await interaction.edit_original_message(content="✅ Настройки баллов сохранены!")
            
        except ValueError:
            await interaction.edit_original_message(content="❌ Значения должны быть числами (можно дробные).")
        except Exception as e:
            self.bot.logger.error(f"Points config error: {e}")
            await interaction.edit_original_message(content="❌ Ошибка сохранения.")

class ResetStatsModal(disnake.ui.Modal):
    def __init__(self, bot, dashboard_interaction):
        self.bot = bot
        self.dashboard_interaction = dashboard_interaction
        components = [
            disnake.ui.TextInput(
                label="ID пользователя (Discord ID)",
                placeholder="123456789012345678",
                custom_id="user_id",
                style=disnake.TextInputStyle.short,
                min_length=17,
                max_length=20,
            ),
        ]
        super().__init__(title="Сброс статистики", components=components)

    async def callback(self, interaction: disnake.ModalInteraction):
        await interaction.response.defer(ephemeral=True)
        try:
            user_id = int(interaction.text_values["user_id"])
            success = await self.bot.database.reset_assistant_stats(user_id)
            if success:
                await interaction.edit_original_message(content=f"✅ Статистика пользователя <@{user_id}> сброшена.")
            else:
                await interaction.edit_original_message(content=f"❌ Пользователь <@{user_id}> не найден или не имеет статистики.")
                
            # Update Dashboard? Hard to update original interaction from modal if not stored or expired.
            # User can refresh by clicking tab again.
            
        except ValueError:
            await interaction.edit_original_message(content="❌ Некорректный ID.")
        except Exception as e:
            await interaction.edit_original_message(content="❌ Ошибка.")

class EditDailyStatsModal(disnake.ui.Modal):
    def __init__(self, bot, pr_id, date_obj, p0, p1, p2, p3, total_points):
        self.bot = bot
        self.pr_id = pr_id
        self.date_obj = date_obj
        
        components = [
            disnake.ui.TextInput(label="P0 Секунды", value=str(p0), custom_id="p0", style=disnake.TextInputStyle.short),
            disnake.ui.TextInput(label="P1 Секунды", value=str(p1), custom_id="p1", style=disnake.TextInputStyle.short),
            disnake.ui.TextInput(label="P2 Секунды", value=str(p2), custom_id="p2", style=disnake.TextInputStyle.short),
            disnake.ui.TextInput(label="P3 Секунды", value=str(p3), custom_id="p3", style=disnake.TextInputStyle.short),
            disnake.ui.TextInput(label="Итого Баллов (Override)", value=str(total_points), custom_id="total_points", style=disnake.TextInputStyle.short),
        ]
        super().__init__(title=f"Edit Stats: {date_obj.strftime('%d.%m')}", components=components)

    async def callback(self, interaction: disnake.ModalInteraction):
        await interaction.response.defer(ephemeral=True)
        try:
            p0 = int(interaction.text_values["p0"])
            p1 = int(interaction.text_values["p1"])
            p2 = int(interaction.text_values["p2"])
            p3 = int(interaction.text_values["p3"])
            points = float(interaction.text_values["total_points"].replace(",", "."))
            
            await self.bot.database.update_daily_stats_manual(self.pr_id, self.date_obj, p0, p1, p2, p3, points)
            await interaction.edit_original_message(content="✅ Статистика обновлена.")
        except Exception as e:
            await interaction.edit_original_message(content=f"❌ Ошибка: {e}")

class AssistantStatsView(disnake.ui.View):
    def __init__(self, bot, user, db):
        super().__init__(timeout=600)
        self.bot = bot
        self.user = user # The user viewing (admin check?)
        self.db = db
        self.filter_mode = "today" # today, yesterday, all_time
        self.target_pr_id = None
        
        self.date_obj = datetime.now(timezone.utc).date()
        self.page = 0
        
        # Initialize components
        self.update_components()

    def update_components(self):
        self.clear_items()
        
        # Filter Select
        options = [
            disnake.SelectOption(label="Сегодня", value="today", default=(self.filter_mode=="today")),
            disnake.SelectOption(label="Вчера", value="yesterday", default=(self.filter_mode=="yesterday")),
            disnake.SelectOption(label="Все время (Топ)", value="all_time", default=(self.filter_mode=="all_time")),
        # Custom date picker is hard with just buttons/selects without modal interaction loop.
        ]
        self.add_item(disnake.ui.StringSelect(custom_id="filter_date", placeholder="Фильтр даты", options=options, max_values=1))
        
        # Refresh Button
        self.add_item(disnake.ui.Button(label="Обновить", custom_id="refresh", style=disnake.ButtonStyle.secondary, emoji="🔄"))
        
        if self.filter_mode in ["today", "yesterday"]:
             self.add_item(disnake.ui.Button(label="Редактировать (Admin)", custom_id="admin_edit_select", style=disnake.ButtonStyle.danger, emoji="✏️"))

    async def get_embed(self):
        # Fetch Data
        if self.filter_mode == "today":
            d = datetime.now(timezone.utc).date()
            stats = await self.db.get_daily_stats(date_obj=d)
            title = f"Статистика за Сегодня ({d.strftime('%d.%m')})"
        elif self.filter_mode == "yesterday":
            d = datetime.now(timezone.utc).date() - timedelta(days=1)
            stats = await self.db.get_daily_stats(date_obj=d)
            title = f"Статистика за Вчера ({d.strftime('%d.%m')})"
        else:
            stats = await self.db.get_top_assistants(limit=20)
            title = "Топ Ассистентов (Все время)"

        embed = disnake.Embed(title=title, color=disnake.Color.blue())
        
        if not stats:
            embed.description = "Нет данных."
            return embed
            
        lines = []
        for i, s in enumerate(stats, 1):
            if self.filter_mode == "all_time":
                # s is dict from assistants table: pr_id, total_spec_seconds, session_count
                t = format_spec_duration(s['total_spec_seconds'])
                lines.append(f"{i}. <@{s['pr_id']}>: **{t}** ({s['session_count']} сес.)")
            else:
                # s is daily_stats: pr_id, total_points, p0..p3 seconds
                total_sec = s['p0_seconds'] + s['p1_seconds'] + s['p2_seconds'] + s['p3_seconds']
                t = format_spec_duration(total_sec)
                pts = round(s['total_points'], 2)
                lines.append(f"{i}. <@{s['pr_id']}>: **{pts}** баллов | {t}")
                
        embed.description = "\n".join(lines)
        return embed
    
    async def interaction_check(self, interaction: disnake.MessageInteraction) -> bool:
        if interaction.data.custom_id == "filter_date":
            self.filter_mode = interaction.values[0]
            self.update_components()
            await interaction.response.edit_message(embed=await self.get_embed(), view=self)
        
        elif interaction.data.custom_id == "refresh":
             await interaction.response.edit_message(embed=await self.get_embed(), view=self)
             
        elif interaction.data.custom_id == "admin_edit_select":
            # Show user select
            await interaction.response.defer(ephemeral=True)
            
            # Use Custom View to handle selection
            v = UserSelectView(self.bot, self.filter_mode)
            await interaction.followup.send("Выберите ассистента для редактирования:", view=v, ephemeral=True)
            
        elif interaction.data.custom_id == "admin_edit_user_sel":
            # This will be handled by the ephemeral view created above? 
            # No, that view is generic.
            # Interaction on that view will fail if not handled.
            pass
            
        return True

# Handlers for "admin_edit_user_sel" need to be in a persistent listener or the view that holds it.
# If I send a NEW view for user selection, I must define it.
class UserSelectView(disnake.ui.View):
    def __init__(self, bot, date_mode):
        super().__init__(timeout=60)
        self.bot = bot
        self.date_mode = date_mode
        self.add_item(disnake.ui.UserSelect(custom_id="s_user", placeholder="User"))
        
    async def interaction_check(self, interaction):
        user_id = int(interaction.values[0])
        # Open Modal
        # Determine Date
        d = datetime.now(timezone.utc).date()
        if self.date_mode == "yesterday":
            d -= timedelta(days=1)
            
        # Fetch current stats
        stats = await self.bot.database.get_daily_stats(pr_id=user_id, date_obj=d)
        if stats:
             s = stats[0]
             p0, p1, p2, p3 = s['p0_seconds'], s['p1_seconds'], s['p2_seconds'], s['p3_seconds']
             tp = s['total_points']
        else:
             p0, p1, p2, p3, tp = 0, 0, 0, 0, 0
             
        # MODAL
        await interaction.response.send_modal(EditDailyStatsModal(self.bot, user_id, d, p0, p1, p2, p3, tp))
        return True

class EventCreateModal(disnake.ui.Modal):
    def __init__(self, bot, guild_id, channel_id, dashboard_interaction):
        self.bot = bot
        self.database = bot.database
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.dashboard_interaction = dashboard_interaction  # To try editing back

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

            # Start Time Parsing
            start_time_str = interaction.text_values["start_time"].strip()
            start_dt = None
            
            if start_time_str:
                try:
                    # Check if DD.MM HH:MM format
                    parts = start_time_str.split()
                    if len(parts) == 2:
                        # Date and Time
                        date_str, time_str = parts
                        day, month = map(int, date_str.split("."))
                        hour, minute = map(int, time_str.split(":"))
                        
                        now_msk = datetime.now(timezone(timedelta(hours=3)))
                        target_dt_msk = datetime(now_msk.year, month, day, hour, minute, tzinfo=timezone(timedelta(hours=3)))
                        
                        # Handle year rollover
                        if target_dt_msk < now_msk:
                            target_dt_msk = target_dt_msk.replace(year=now_msk.year + 1)
                        
                    elif len(parts) == 1:
                        # Time only (today/tomorrow logic)
                        target_time = datetime.strptime(start_time_str, "%H:%M").time()
                        msk_tz = timezone(timedelta(hours=3))
                        now_msk = datetime.now(msk_tz)
                        target_dt_msk = datetime.combine(now_msk.date(), target_time).replace(tzinfo=msk_tz)
                        if target_dt_msk < now_msk:
                            target_dt_msk += timedelta(days=1)
                    else:
                        raise ValueError

                    # Convert to UTC
                    start_dt = target_dt_msk.astimezone(timezone.utc)
                    
                except ValueError:
                    await interaction.edit_original_message(content="❌ Неверный формат. Используйте `ЧЧ:ММ` или `ДД.ММ ЧЧ:ММ` (МСК).")
                    return
            
            # Send event message to the selected channel
            channel = self.bot.get_channel(self.channel_id)
            if not channel:
                await interaction.edit_original_message(content="❌ Канал не найден.")
                return

            # Create event embed
            embed = disnake.Embed(
                title=f"🎉 Событие: {name}",
                description=f"{description}\n\n**Требуется PR:** {required_count}\n**Участников:** 0",
                color=disnake.Color.gold()
            )
            embed.set_footer(text=f"Создал: {interaction.user.display_name}")
            
            if start_dt:
                ts = int(start_dt.timestamp())
                embed.add_field(name="🕒 Начало", value=f"<t:{ts}:t> (<t:{ts}:R>)", inline=False)
            
            # Button for joining
            # Insert with dummy message_id
            event_id = await self.database.create_event(
                guild_id=self.guild_id,
                name=name,
                description=description,
                channel_id=self.channel_id,
                message_id=0, # Placeholder
                created_by=interaction.user.id,
                required_pr_count=required_count,
                start_time=start_dt,
                notification_sent=(start_dt is None) # True if immediate start
            )
            
            if not event_id:
                await interaction.edit_original_message(content="❌ Ошибка базы данных.")
                return

            # Send message with Join Button
            join_btn = disnake.ui.Button(
                label="Присоединиться", 
                custom_id=f"event_join_{event_id}", 
                style=disnake.ButtonStyle.success,
                emoji="✋"
            )
            
            msg = await channel.send(embed=embed, components=[join_btn])
            
            # Update DB with real message_id
            # Update DB with real message_id
            async with self.database.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                     await cursor.execute("UPDATE events SET message_id = %s WHERE id = %s", (msg.id, event_id))
                     await conn.commit()
            
            # If immediate start, send notification immediately
            # If immediate start, send notification immediately
            # We tag role here regardless of start time because it's "Creation".
            
            settings = await self.database.get_guild(self.guild_id)
            role_mention = ""
            if settings and settings.get("assistant_role_id"):
                    role_mention = f"<@&{settings['assistant_role_id']}>"
            
            if role_mention:
                time_info = "уже началось!" if start_dt is None else "запланировано!"
                await channel.send(f"{role_mention} Новое событие **{name}** {time_info}", delete_after=600)

            # Update Dashboard to return to Events tab
            try:
                # 1. Defer the modal interaction (ephemeral) so it doesn't fail
                # await interaction.response.defer(ephemeral=True) # Already deferred at start of callback
                
                # 2. Get the PERSISTENT Dashboard Message from DB
                guild_settings = await self.database.get_guild(self.guild_id)
                if not guild_settings:
                    return

                cp_channel_id = guild_settings.get("control_panel_channel_id")
                cp_message_id = guild_settings.get("control_panel_message_id")

                if not cp_channel_id or not cp_message_id:
                    self.bot.logger.warning("Control Panel location not found in DB.")
                    return

                # 3. Fetch the message
                cp_channel = self.bot.get_channel(cp_channel_id)
                if not cp_channel:
                    # Try fetch?
                    try:
                        cp_channel = await self.bot.fetch_channel(cp_channel_id)
                    except:
                        return
                
                try:
                    cp_message = await cp_channel.fetch_message(cp_message_id)
                except:
                    return

                # 4. Rebuild the events tab view
                embed = disnake.Embed(title="🎉 Активные события", color=disnake.Color.gold())
                events = await self.database.get_active_events(self.guild_id)
                
                if not events:
                    embed.description = "Нет активных событий. Создайте новое!"
                else:
                    for event in events:
                        embed.add_field(
                            name=f"📅 {event['name']}",
                            value=f"👥 Участников: **{event.get('current_participants', 0)}** (Требуется: {event['required_pr_count']})\n"
                                  f"🔗 [Перейти к сообщению](https://discord.com/channels/{self.guild_id}/{event['channel_id']}/{event['message_id']})\n"
                                  f"🕒 Начало: <t:{int(calendar.timegm(event['start_time'].timetuple()))}:R>",
                            inline=False
                        )

                view = disnake.ui.View()
                # Back button
                view.add_item(disnake.ui.Button(label="Назад", custom_id="btn_back_to_menu", style=disnake.ButtonStyle.secondary, emoji="🔙", row=2))
                # Create button
                view.add_item(disnake.ui.Button(label="Создать событие", custom_id="btn_create_event", style=disnake.ButtonStyle.success, emoji="➕", row=0))
                # End button if events exist
                if events:
                    view.add_item(disnake.ui.Button(label="Завершить событие", custom_id="btn_end_event_select", style=disnake.ButtonStyle.danger, emoji="🏁", row=0))
                
                # 5. Edit the PERSISTENT message
                await cp_message.edit(embed=embed, view=view)
                
                try:
                    await interaction.edit_original_response(content="✅", view=None)
                except:
                    pass

            except Exception as e:
                self.bot.logger.error(f"Failed to refresh persistent dashboard UI: {e}")
            
            # Update Monitoring
            await self.bot.twitch_bot.update_monitoring_messages()
            
        except Exception as e:
            self.bot.logger.error(f"Event creation error: {e}", exc_info=True)
            await interaction.edit_original_message(content="❌ Произошла ошибка.")

class NotificationTemplateModal(disnake.ui.Modal):
    def __init__(self, event_type: str, current_template: str, database, dashboard_interaction):
        self.event_type = event_type
        self.database = database
        self.dashboard_interaction = dashboard_interaction
        label = Config.EVENT_TYPE_LABELS.get(event_type, event_type)

        title = f"Редактировать: {label}"
        if len(title) > 45:
            title = title[:42] + "..."

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
        new_template = interaction.text_values["template_input"]

        await self.database.update_notification_template(
            interaction.guild_id,
            self.event_type,
            new_template,
        )

        await interaction.response.send_message(
            f"✅ Шаблон для **{Config.EVENT_TYPE_LABELS.get(self.event_type)}** обновлён!",
            ephemeral=True,
        )
        # Restore Dashboard? It's a modal, so original interaction is background.
        # Ideally we might want to refresh the view to ensure consistency, but it's not strictly necessary for templates.

class Dashboard(commands.Cog):
    """Система Панели Управления."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.database = bot.database
        self.twitch_bot = bot.twitch_bot
        self.check_event_starts.start()

    def cog_unload(self):
        self.check_event_starts.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        """Регистрация постоянного view при запуске."""
        self.bot.add_view(DashboardView(self.bot))

    @tasks.loop(seconds=60)
    async def check_event_starts(self):
        """Проверка запланированных событий, которые начались."""
        try:
             async with self.database.pool.acquire() as conn:
                 async with conn.cursor() as cursor:
                     # Get events that need starting
                     await cursor.execute(
                         """
                         SELECT id, guild_id, name, channel_id 
                         FROM events 
                         WHERE is_active = TRUE 
                           AND start_time <= UTC_TIMESTAMP() 
                           AND (notification_sent IS FALSE OR notification_sent IS NULL)
                         """
                     )
                     events_to_start = await cursor.fetchall()

                     for event in events_to_start:
                         event_id = event["id"]
                         guild_id = event["guild_id"]
                         name = event["name"]
                         channel_id = event["channel_id"]
                         
                         channel = self.bot.get_channel(channel_id)
                         if channel:
                             participants = await self.database.get_event_participants(event_id)
                             
                             if participants:
                                 mentions = [f"<@{p['user_id']}>" for p in participants]
                                 mention_str = ", ".join(mentions)
                                 try:
                                     await channel.send(f"{mention_str} Событие **{name}** началось! Пора присоединяться!", delete_after=300)
                                 except Exception as e:
                                     self.bot.logger.error(f"Failed to send start notification for event {event_id}: {e}")
                             else:
                                 pass

                         # Mark as sent
                         await self.database.mark_event_notification_sent(event_id)
                         
        except Exception as e:
            self.bot.logger.error(f"Error in check_event_starts loop: {e}", exc_info=True)
    
    @check_event_starts.before_loop
    async def before_check_event_starts(self):
        await self.bot.wait_until_ready()


    @commands.Cog.listener("on_button_click")
    async def on_dashboard_button(self, interaction: MessageInteraction):
        """Обработка кликов по кнопкам дашборда."""
        custom_id = interaction.component.custom_id
        if not custom_id:
            return
        
        if custom_id == "btn_back_to_menu":
            await interaction.response.defer()
            # Restore Main Menu
            embed = disnake.Embed(
                title="🎛️ Панель Управления",
                description="Добро пожаловать в панель управления PRMajesticBot.\nВыберите раздел в меню ниже.",
                color=0x2B2D31
            )
            embed.set_footer(text="Используйте кнопки для навигации")
            await interaction.edit_original_response(embed=embed, view=DashboardView(self.bot))
            return

        if custom_id.startswith("nav_"):
            await interaction.response.defer()
            target_tab = custom_id.replace("nav_", "")
            await self.render_tab(interaction, target_tab)
            return

        if custom_id == "btn_add_streamer":
            await interaction.response.send_modal(AddStreamerModal(self.bot, interaction.guild_id))
            return
            
        if custom_id == "btn_list_streamers":
            await interaction.response.defer(ephemeral=True)
            streamers = await self.database.list_all_streamers()
            if not streamers:
                await interaction.followup.send("Список пуст.", ephemeral=True)
                return
            
            lines = []
            for s in streamers:
                lines.append(f"• **{s['streamer_name']}** (ID: {s['streamer_id']}) - Priority: {s['priority']}")
            
            chunk_size = 1000
            content = "\n".join(lines)
            if len(content) > 2000:
                content = content[:1900] + "... (truncated)"
                
            await interaction.followup.send(f"Список стримеров:\n{content}", ephemeral=True)
            return

        if custom_id == "btn_remove_streamer":
            await interaction.response.defer(ephemeral=True)
            streamers = await self.database.list_all_streamers()
            if not streamers:
                await interaction.followup.send("Некого удалять.", ephemeral=True)
                return
                
            options = []
            for s in streamers[:25]:
                 options.append(disnake.SelectOption(label=s['streamer_name'], value=str(s['streamer_id'])))
                 
            select = disnake.ui.StringSelect(custom_id="select_remove_streamer", placeholder="Выберите стримера для удаления", options=options)
            await interaction.followup.send("Выберите стримера для удаления:", view=disnake.ui.View().add_item(select), ephemeral=True)
            select = disnake.ui.StringSelect(custom_id="select_remove_streamer", placeholder="Выберите стримера для удаления", options=options)
            await interaction.followup.send("Выберите стримера для удаления:", view=disnake.ui.View().add_item(select), ephemeral=True)
            return

        if custom_id == "btn_edit_streamer":
            await interaction.response.defer(ephemeral=True)
            streamers = await self.database.list_all_streamers()
            if not streamers:
                await interaction.followup.send("Список стримеров пуст.", ephemeral=True)
                return
                
            options = []
            for s in streamers[:25]: # Limit 25
                 options.append(disnake.SelectOption(label=f"{s['streamer_name']} (P{s['priority']})", value=str(s['streamer_id'])))
                 
            select = disnake.ui.StringSelect(custom_id="select_edit_streamer", placeholder="Выберите стримера для редактирования", options=options)
            await interaction.followup.send("Выберите стримера:", view=disnake.ui.View().add_item(select), ephemeral=True)
            return

        if custom_id == "btn_config_points":
             rates = await self.database.get_points_config(interaction.guild_id)
             await interaction.response.send_modal(PointsConfigModal(self.bot, interaction.guild_id, rates))
             return
            
        if custom_id == "btn_end_event_select":
             await interaction.response.defer(ephemeral=True)
             events = await self.database.get_active_events(interaction.guild_id)
             if not events:
                 await interaction.followup.send("Нет активных событий.", ephemeral=True)
                 return
             
             options = []
             for e in events:
                 start_dt = e['start_time'].strftime("%d.%m %H:%M")
                 options.append(disnake.SelectOption(label=f"{e['name']} ({start_dt})", value=str(e['id'])))
             
             select = disnake.ui.StringSelect(custom_id="select_end_event", placeholder="Выберите событие для завершения", options=options)
             await interaction.followup.send("Выберите событие для завершения:", view=disnake.ui.View().add_item(select), ephemeral=True)
             return

        if custom_id == "btn_reset_stats":
            await interaction.response.send_modal(ResetStatsModal(self.bot, interaction))
            return

        if custom_id == "btn_detailed_stats":
            # Send the View
            v = AssistantStatsView(self.bot, interaction.user, self.database)
            await interaction.response.send_message(embed=await v.get_embed(), view=v, ephemeral=True)
            return

        if custom_id == "btn_force_sync":
            # UX: Send separate message instead of editing original
            await interaction.response.send_message("✅ Синхронизация стримеров запущена.", ephemeral=True)
            try:
                # Run sync in background so we don't block
                self.bot.loop.create_task(self.twitch_bot.sync_streamers())
            except Exception as e:
                 # Should hardly happen if backgrounded, but good practice
                 self.bot.logger.error(f"Sync error: {e}")
            return

        if custom_id == "btn_create_event":
            # Show channel select for event
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

        if custom_id.startswith("btn_set_"):
            # ... existing channel logic ...
            channel_type = custom_id.replace("btn_set_", "")
            
            # Create channel select menu
            if channel_type == "notif":
                placeholder = "Выберите канал уведомлений"
                cid = "select_channel_notif"
            elif channel_type == "monitor":
                placeholder = "Выберите канал мониторинга"
                cid = "select_channel_monitor"
            elif channel_type == "actions":
                placeholder = "Выберите канал действий PR"
                cid = "select_channel_actions"
            else:
                return

            select = disnake.ui.ChannelSelect(
                custom_id=cid,
                placeholder=placeholder,
                channel_types=[disnake.ChannelType.text],
                min_values=1,
                max_values=1
            )
            
            # Back/Cancel button
            cancel_btn = disnake.ui.Button(label="Отмена", custom_id="btn_cancel_select", style=disnake.ButtonStyle.danger)
            
            view = disnake.ui.View()
            view.add_item(select)
            view.add_item(cancel_btn)
            
            await interaction.response.edit_message(
                embed=disnake.Embed(title=placeholder, description="Выберите канал из списка ниже.", color=disnake.Color.blurple()),
                view=view
            )

        elif custom_id == "btn_cancel_event_create":
            # Return specifically to Events tab
            await interaction.response.defer()
            await self.render_tab(interaction, "tab_events")

        elif custom_id == "btn_cancel_select":
            # Return to Channels tab (Default)
            await interaction.response.defer()
            await self.render_tab(interaction, "tab_channels")



    @commands.Cog.listener("on_dropdown")
    async def on_dashboard_dropdown(self, interaction: MessageInteraction):
        """Обработка выпадающих списков дашборда."""
        custom_id = interaction.component.custom_id
        
        if custom_id == "dashboard_select":
             pass
        elif custom_id == "select_edit_streamer":
             try:
                 streamer_id = int(interaction.values[0])
                 streamer = await self.database.get_streamer(streamer_id)
                 if streamer:
                     await interaction.response.send_modal(EditStreamerModal(self.bot, streamer_id, streamer["streamer_name"], streamer.get("priority", 0)))
                 else:
                     await interaction.response.send_message("Стример не найден.", ephemeral=True)
             except Exception as e:
                 self.bot.logger.error(f"Edit select error: {e}")
                 await interaction.response.send_message("Ошибка.", ephemeral=True)
             return

        elif custom_id == "select_event_channel":
            channel_id = int(interaction.values[0])
            # Open Modal
            await interaction.response.send_modal(
                EventCreateModal(self.bot, interaction.guild_id, channel_id, interaction)
            )
            # Message remains in "Select Channel" state. User will get an ephemeral "Created" message.

        elif custom_id == "select_notification_template":
             event_type = interaction.values[0]
             current_template = await self.database.get_notification_template(
                 interaction.guild_id, event_type
             )
             await interaction.response.send_modal(
                 NotificationTemplateModal(event_type, current_template, self.database, interaction)
             )
             return

        elif custom_id.startswith("select_channel_"):
            await interaction.response.defer()
            target = custom_id.replace("select_channel_", "")
            channel_id = int(interaction.values[0])
            
            if target == "notif":
                await self.database.set_notification_channel(interaction.guild_id, channel_id)
            elif target == "monitor":
                await self.database.set_monitoring_channel(interaction.guild_id, channel_id)
            elif target == "actions":
                await self.database.set_pr_actions_channel(interaction.guild_id, channel_id)
            
            # Return to Channels tab
            await self.render_tab(interaction, "tab_channels")

        elif custom_id == "select_remove_streamer":
            await interaction.response.defer(ephemeral=True)
            streamer_id = int(interaction.values[0])
            
            await self.database.delete_streamer(streamer_id)
            await self.twitch_bot.remove_subscription(streamer_id)

            await self.bot.twitch_bot.update_monitoring_messages()
            await interaction.edit_original_response(content="✅ Стример удален!", view=None)
            return

        elif custom_id == "select_end_event":
            await interaction.response.defer(ephemeral=True)
            event_id = int(interaction.values[0])
            
            # Fetch event name before ending (for log)
            event_name = "Событие"
            try:
                evt = await self.database.get_event(event_id)
                if evt: event_name = evt['name']
            except: pass

            participants_data = await self.database.end_event(event_id)
            
            # Log individual unclaims to PR Actions
            if participants_data:
                for p in participants_data:
                    dur_str = format_spec_duration(p['duration'])
                    msg = (
                        f"📤 **Открепление (Конец события)**\n"
                        f"📅 Событие: **{event_name}**\n"
                        f"🎯 PR: <@{p['user_id']}>\n"
                        f"⏱️ Спек: **{dur_str}**"
                    )
                    await self._send_pr_action(interaction.guild_id, msg)
            else:
                 # Log event end even if empty
                 await self._send_pr_action(interaction.guild_id, f"🏁 **Событие завершено: {event_name}** (Нет участников)")

            try:
                event = await self.database.get_event(event_id)
                if event:
                    channel = self.bot.get_channel(event['channel_id'])
                    if channel:
                        msg = await channel.fetch_message(event['message_id'])
                        embed = msg.embeds[0]
                        embed.title = f"🏁 [ЗАВЕРШЕНО] {embed.title.replace('🎉 Событие: ', '')}"
                        embed.color = disnake.Color.dark_grey()
                        await msg.edit(embed=embed, components=[]) 
            except Exception as e:
                pass
                
            await self.bot.twitch_bot.update_monitoring_messages()
            # UX: Return to Events tab (Persistent Message)
            try:
                guild_settings = await self.database.get_guild(interaction.guild_id)
                if guild_settings:
                    cp_channel_id = guild_settings.get("control_panel_channel_id")
                    cp_message_id = guild_settings.get("control_panel_message_id")
                    
                    if cp_channel_id and cp_message_id:
                         cp_channel = self.bot.get_channel(cp_channel_id) or await self.bot.fetch_channel(cp_channel_id)
                         if cp_channel:
                             cp_message = await cp_channel.fetch_message(cp_message_id)
                             
                             # Rebuild Events Tab
                             embed = await self._get_events_embed(interaction.guild_id)
                             view = disnake.ui.View()
                             view.add_item(disnake.ui.Button(label="Назад", custom_id="btn_back_to_menu", style=disnake.ButtonStyle.secondary, emoji="🔙", row=2))
                             view.add_item(disnake.ui.Button(label="Создать событие", custom_id="btn_create_event", style=disnake.ButtonStyle.success, emoji="➕", row=0))
                             # Check if any events remain
                             if await self.database.get_active_events(interaction.guild_id):
                                 view.add_item(disnake.ui.Button(label="Завершить событие", custom_id="btn_end_event_select", style=disnake.ButtonStyle.danger, emoji="🏁", row=0))
                             
                             await cp_message.edit(embed=embed, view=view)

            except Exception as e:
                self.bot.logger.error(f"Failed to refresh dashboard on end event: {e}")

            await interaction.edit_original_response(content="✅ Событие завершено!", view=None)
            return

    async def render_tab(self, interaction: MessageInteraction, tab_id: str):
        """Рендер содержимого выбранной вкладки."""
        
        # Create a fresh view for the tab
        view = disnake.ui.View()
        # Add Back Button first (row 2 to appear at bottom usually, but we want it consistent)
        # Let's put Main Action buttons on row 0/1 and Back on row 2
        
        # Common Back Button
        back_btn = disnake.ui.Button(label="Назад", custom_id="btn_back_to_menu", style=disnake.ButtonStyle.secondary, emoji="🔙", row=2)

        if tab_id == "tab_channels":
            embed = await self._get_channels_embed(interaction.guild_id)
            view.add_item(disnake.ui.Button(label="Изменить канал уведомлений", custom_id="btn_set_notif", style=disnake.ButtonStyle.primary, emoji="🔔", row=0))
            view.add_item(disnake.ui.Button(label="Изменить канал мониторинга", custom_id="btn_set_monitor", style=disnake.ButtonStyle.primary, emoji="📊", row=0))
            view.add_item(disnake.ui.Button(label="Изменить канал действий", custom_id="btn_set_actions", style=disnake.ButtonStyle.primary, emoji="📢", row=1))
            
        elif tab_id == "tab_templates":
            embed = disnake.Embed(
                title="📝 Шаблоны уведомлений", 
                description="Выберите тип события для редактирования шаблона.", 
                color=disnake.Color.blue()
            )
            embed.add_field(
                name="📌 Доступные переменные",
                value=(
                    "`{streamer_name}` — имя стримера\n"
                    "`{stream_title}` — название стрима\n"
                    "`{game_name}` — название игры\n"
                    "`{streamer_link}` — ссылка на канал"
                ),
                inline=False,
            )
            
            # Dropdown for templates
            options = [
                disnake.SelectOption(label=label, value=event_type, emoji=label.split()[0] if " " in label else "📝")
                for event_type, label in Config.EVENT_TYPE_LABELS.items()
            ]
            
            select = disnake.ui.StringSelect(
                custom_id="select_notification_template",
                placeholder="Выберите событие...",
                options=options,
                min_values=1,
                max_values=1
            )
            view.add_item(select)
            
        elif tab_id == "tab_streamers":
            streamers = await self.database.list_all_streamers()
            count = len(streamers)
            embed = disnake.Embed(title="🎥 Управление стримерами", description=f"Подписано стримеров: **{count}**", color=disnake.Color.purple())
            
            view.add_item(disnake.ui.Button(label="Добавить", custom_id="btn_add_streamer", style=disnake.ButtonStyle.success, emoji="➕", row=0))
            view.add_item(disnake.ui.Button(label="Редактировать", custom_id="btn_edit_streamer", style=disnake.ButtonStyle.secondary, emoji="✏️", row=0))
            view.add_item(disnake.ui.Button(label="Удалить", custom_id="btn_remove_streamer", style=disnake.ButtonStyle.danger, emoji="➖", row=0))
            view.add_item(disnake.ui.Button(label="Список стримеров", custom_id="btn_list_streamers", style=disnake.ButtonStyle.primary, emoji="📜", row=1))
            
        elif tab_id == "tab_assistants":
            assistants = await self.database.get_top_assistants(limit=10)
            
            embed = disnake.Embed(title="👥 Управление ассистентами", color=disnake.Color.green())
            
            if not assistants:
                embed.description = "Нет данных об ассистентах."
            else:
                desc = "**Топ ассистентов по времени:**\n"
                for idx, a in enumerate(assistants, 1):
                    time_str = format_spec_duration(a['total_spec_seconds'])
                    desc += f"{idx}. <@{a['pr_id']}> — **{time_str}** ({a['session_count']} сессий)\n"
                embed.description = desc
                
            view.add_item(disnake.ui.Button(label="Подробная статистика", custom_id="btn_detailed_stats", style=disnake.ButtonStyle.primary, emoji="📊", row=0))
            view.add_item(disnake.ui.Button(label="Сбросить (ID)", custom_id="btn_reset_stats", style=disnake.ButtonStyle.secondary, emoji="🗑️", row=0))
            
        elif tab_id == "tab_tech":
            ping = round(self.bot.latency * 1000)
            embed = disnake.Embed(title="🛠️ Технические настройки", color=disnake.Color.greyple())
            
            embed.add_field(name="📶 Задержка (Ping)", value=f"{ping} ms", inline=True)
            embed.add_field(name="🤖 Статус", value="✅ Работает", inline=True)
            
            view.add_item(disnake.ui.Button(label="Принудительная синхронизация", custom_id="btn_force_sync", style=disnake.ButtonStyle.primary, emoji="🔄", row=0))
            view.add_item(disnake.ui.Button(label="⚙️ Баллы", custom_id="btn_config_points", style=disnake.ButtonStyle.secondary, emoji="💰", row=1))
            
        elif tab_id == "tab_events":
            embed = await self._get_events_embed(interaction.guild_id)
            view.add_item(disnake.ui.Button(label="Создать событие", custom_id="btn_create_event", style=disnake.ButtonStyle.success, emoji="➕", row=0))
            
            if await self.database.get_active_events(interaction.guild_id):
                view.add_item(disnake.ui.Button(label="Завершить событие", custom_id="btn_end_event_select", style=disnake.ButtonStyle.danger, emoji="🏁", row=0))
        
        else:
            embed = disnake.Embed(title="Ошибка", description="Неизвестная вкладка", color=disnake.Color.red())

        view.add_item(back_btn)
        
        # Check if we are responding to a deferred interaction or need to edit
        if interaction.response.is_done():
            # If deferred or already responded, use edit_original_message
            await interaction.edit_original_message(embed=embed, view=view)
        else:
            # If called freshly (e.g. from nav button)
            await interaction.response.edit_message(embed=embed, view=view)

    async def _get_channels_embed(self, guild_id: int) -> disnake.Embed:
        data = await self.database.get_guild(guild_id)
        if not data:
             data = {} # Handle empty
             
        embed = disnake.Embed(title="📺 Настройка каналов", color=0xC9A6F6)
        
        def format_channel(cid):
            if not cid:
                return "❌ Не настроен"
            ch = self.bot.get_channel(cid)
            if ch:
                return ch.mention
            return f"⚠️ Удален/Недоступен (ID: {cid})"
        
        notif = format_channel(data.get('notification_channel_id'))
        monit = format_channel(data.get('monitoring_channel_id'))
        action = format_channel(data.get('pr_actions_channel_id'))
        
        embed.add_field(name="🔔 Канал уведомлений", value=notif, inline=False)
        embed.add_field(name="📊 Канал мониторинга", value=monit, inline=False)
        embed.add_field(name="📢 Канал действий PR", value=action, inline=False)
        
        return embed

    async def _get_events_embed(self, guild_id: int) -> disnake.Embed:
        events = await self.database.get_active_events(guild_id)
        
        embed = disnake.Embed(title="🎉 Активные события", color=disnake.Color.gold())
        
        if not events:
            embed.description = "Нет активных событий. Создайте новое!"
        else:
            for event in events:
                embed.add_field(
                    name=f"📅 {event['name']}",
                    value=f"👥 Участников: **{event.get('current_participants', 0)}** (Требуется: {event['required_pr_count']})\n"
                          f"🔗 [Перейти к сообщению](https://discord.com/channels/{guild_id}/{event['channel_id']}/{event['message_id']})\n"
                          f"🕒 Начало: <t:{int(calendar.timegm(event['start_time'].timetuple()))}:R>",
                    inline=False
                )
        return embed

    async def _send_pr_action(self, guild_id: int, message: str):
        """Отправка сообщения в канал действий PR."""
        try:
            channel_id = await self.database.get_pr_actions_channel(guild_id)
            if not channel_id:
                return

            channel = self.bot.get_channel(channel_id)
            if channel:
                await channel.send(message)
        except Exception as e:
            self.bot.logger.error(f"Error sending PR action: {e}")

def setup(bot: commands.Bot) -> None:
    bot.add_cog(Dashboard(bot))
