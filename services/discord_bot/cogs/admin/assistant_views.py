"""
Assistant Management Views for Dashboard.
New modular system for PR assistant management.
"""

import disnake
from disnake.ext import commands
from disnake import MessageInteraction
from typing import Optional, Dict, List
from datetime import datetime, timezone, timedelta


def format_duration(seconds: int) -> str:
    """Format seconds to human-readable duration."""
    if seconds <= 0:
        return "0ч 0м"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours}ч {minutes}м"


def format_points(points: float) -> str:
    """Format points with precision."""
    return f"{points:.2f}"


class AssistantManagementView(disnake.ui.View):
    """Main entry point for assistant management."""

    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot
        self.api = bot.api_client
        self.selected_user_id: Optional[int] = None

        self._build_main_menu()

    def _build_main_menu(self):
        """Build the main menu with user selection."""
        self.clear_items()

        # User Select
        self.add_item(
            disnake.ui.UserSelect(
                custom_id="assistant_select_user",
                placeholder="🔍 Выберите ассистента",
                min_values=1,
                max_values=1,
                row=0,
            )
        )

        # Bulk Operations Button
        self.add_item(
            disnake.ui.Button(
                label="📦 Массовые операции",
                custom_id="assistant_bulk_ops",
                style=disnake.ButtonStyle.secondary,
                row=1,
            )
        )

        # Top Assistants Button
        self.add_item(
            disnake.ui.Button(
                label="🏆 Топ ассистентов",
                custom_id="assistant_top",
                style=disnake.ButtonStyle.secondary,
                row=1,
            )
        )

        # Back Button
        self.add_item(
            disnake.ui.Button(
                label="🔙 Назад",
                custom_id="admin_home",
                style=disnake.ButtonStyle.secondary,
                row=2,
            )
        )

    def get_main_embed(self) -> disnake.Embed:
        """Create main menu embed."""
        embed = disnake.Embed(
            title="👤 Управление ассистентами",
            description="Выберите ассистента для просмотра статистики и управления.\n\n"
            "**Доступные действия:**\n"
            "• 🔍 Выбор ассистента → Обзор, статистика, редактирование\n"
            "• 📦 Массовые операции → Добавить время, сброс\n"
            "• 🏆 Топ ассистентов → Лидерборд",
            color=0x2B2D31,
        )
        return embed


class AssistantOverviewView(disnake.ui.View):
    """Overview view for selected assistant."""

    def __init__(self, bot: commands.Bot, user_id: int, user_name: str):
        super().__init__(timeout=None)
        self.bot = bot
        self.api = bot.api_client
        self.user_id = user_id
        self.user_name = user_name

        self._build_overview_buttons()

    def _build_overview_buttons(self):
        """Build action buttons."""
        self.clear_items()

        # Navigation Row
        self.add_item(
            disnake.ui.Button(
                label="📊 Статистика",
                custom_id=f"assistant_stats_{self.user_id}",
                style=disnake.ButtonStyle.primary,
                row=0,
            )
        )
        self.add_item(
            disnake.ui.Button(
                label="✏️ Редактировать",
                custom_id=f"assistant_edit_{self.user_id}",
                style=disnake.ButtonStyle.secondary,
                row=0,
            )
        )
        self.add_item(
            disnake.ui.Button(
                label="🕓 История",
                custom_id=f"assistant_history_{self.user_id}",
                style=disnake.ButtonStyle.secondary,
                row=0,
            )
        )

        # Actions Row
        self.add_item(
            disnake.ui.Button(
                label="⚙️ Действия",
                custom_id=f"assistant_actions_{self.user_id}",
                style=disnake.ButtonStyle.secondary,
                row=1,
            )
        )

        # Back
        self.add_item(
            disnake.ui.Button(
                label="🔙 Назад",
                custom_id="btn_back_to_menu",
                style=disnake.ButtonStyle.secondary,
                row=2,
            )
        )

    async def get_overview_embed(self) -> disnake.Embed:
        """Get overview embed with assistant data."""
        try:
            # Fetch assistant data via API
            data = await self.api.get_assistant_stats(self.user_id)

            if not data:
                return disnake.Embed(
                    title=f"👤 {self.user_name}",
                    description="❌ Данные не найдены. Возможно, ассистент еще не начинал работу.",
                    color=disnake.Color.red(),
                )

            # Basic stats
            total_seconds = data.get("total_spec_seconds", 0)
            session_count = data.get("session_count", 0)

            # Calculate today's stats from daily_stats
            today_seconds = 0
            today_points = 0.0
            month_seconds = 0
            month_points = 0.0

            daily_stats = data.get("daily_stats", [])
            today = datetime.now(timezone.utc).date()

            for day in daily_stats:
                day_date = day.get("date")
                if isinstance(day_date, str):
                    day_date = datetime.fromisoformat(day_date).date()

                day_total = (
                    day.get("p0_seconds", 0)
                    + day.get("p1_seconds", 0)
                    + day.get("p2_seconds", 0)
                    + day.get("p3_seconds", 0)
                )
                day_points = day.get("total_points", 0)

                if day_date == today:
                    today_seconds = day_total
                    today_points = day_points

                # Check if in current month
                if day_date.year == today.year and day_date.month == today.month:
                    month_seconds += day_total
                    month_points += day_points

            # Check if currently specing
            current = await self.api.get_current_streamer_for_pr(self.user_id)
            is_specing = current and current.get("assigned")
            status_icon = "🟢" if is_specing else "⚫"
            status_text = (
                f"Спекает: **{current['streamer']['streamer_name']}**"
                if is_specing
                else "Не спекает"
            )

            embed = disnake.Embed(
                title=f"👤 {self.user_name}",
                description=f"{status_icon} {status_text}",
                color=disnake.Color.green() if is_specing else disnake.Color.greyple(),
            )

            # Stats fields
            embed.add_field(
                name="📅 Сегодня",
                value=f"⏱️ {format_duration(today_seconds)}\n⭐ {format_points(today_points)} баллов",
                inline=True,
            )
            embed.add_field(
                name="📆 Этот месяц",
                value=f"⏱️ {format_duration(month_seconds)}\n⭐ {format_points(month_points)} баллов",
                inline=True,
            )
            embed.add_field(
                name="📊 Всего",
                value=f"⏱️ {format_duration(total_seconds)}\n🔢 {session_count} сессий",
                inline=True,
            )

            embed.set_footer(text=f"ID: {self.user_id}")

            return embed

        except Exception as e:
            self.bot.logger.error(
                f"Error getting assistant overview: {e}", exc_info=True
            )
            return disnake.Embed(
                title="❌ Ошибка",
                description="Не удалось загрузить данные.",
                color=disnake.Color.red(),
            )


class AssistantStatsView(disnake.ui.View):
    """Detailed statistics view with date filtering."""

    def __init__(self, bot: commands.Bot, user_id: int, user_name: str):
        super().__init__(timeout=None)
        self.bot = bot
        self.api = bot.api_client
        self.user_id = user_id
        self.user_name = user_name
        self.filter_mode = "today"  # today, yesterday, week, month

        self._build_components()

    def _build_components(self):
        """Build filter dropdown and navigation."""
        self.clear_items()

        # Date Filter Select
        options = [
            disnake.SelectOption(
                label="Сегодня",
                value="today",
                emoji="📅",
                default=(self.filter_mode == "today"),
            ),
            disnake.SelectOption(
                label="Вчера",
                value="yesterday",
                emoji="📆",
                default=(self.filter_mode == "yesterday"),
            ),
            disnake.SelectOption(
                label="Неделя",
                value="week",
                emoji="📊",
                default=(self.filter_mode == "week"),
            ),
            disnake.SelectOption(
                label="Месяц",
                value="month",
                emoji="📈",
                default=(self.filter_mode == "month"),
            ),
        ]
        self.add_item(
            disnake.ui.StringSelect(
                custom_id="assistant_stats_filter",
                placeholder="📅 Период",
                options=options,
                row=0,
            )
        )

        # Refresh
        self.add_item(
            disnake.ui.Button(
                label="🔄 Обновить",
                custom_id="assistant_stats_refresh",
                style=disnake.ButtonStyle.secondary,
                row=1,
            )
        )

        # Edit Daily Stats (opens modal) - Needs user_id in custom_id
        self.add_item(
            disnake.ui.Button(
                label="✏️ Редактировать",
                custom_id=f"assistant_edit_stats_{self.user_id}",
                style=disnake.ButtonStyle.primary,
                row=1,
            )
        )

        # Back
        self.add_item(
            disnake.ui.Button(
                label="🔙 К обзору",
                custom_id=f"assistant_overview_{self.user_id}",
                style=disnake.ButtonStyle.secondary,
                row=2,
            )
        )

    async def get_stats_embed(self) -> disnake.Embed:
        """Get detailed stats embed."""
        try:
            data = await self.api.get_assistant_stats(self.user_id)

            if not data:
                return disnake.Embed(
                    title=f"📊 Статистика: {self.user_name}",
                    description="Нет данных.",
                    color=disnake.Color.greyple(),
                )

            daily_stats = data.get("daily_stats", [])
            today = datetime.now(timezone.utc).date()

            # Filter by mode
            if self.filter_mode == "today":
                target_date = today
                period_name = "Сегодня"
            elif self.filter_mode == "yesterday":
                target_date = today - timedelta(days=1)
                period_name = "Вчера"
            elif self.filter_mode == "week":
                target_date = None
                period_name = "За неделю"
            else:
                target_date = None
                period_name = "За месяц"

            # Aggregate data
            p0_total = p1_total = p2_total = p3_total = 0
            points_total = 0.0
            days_count = 0

            for day in daily_stats:
                day_date = day.get("date")
                if isinstance(day_date, str):
                    day_date = datetime.fromisoformat(day_date).date()

                include = False
                if target_date:
                    include = day_date == target_date
                elif self.filter_mode == "week":
                    include = (today - day_date).days <= 7
                elif self.filter_mode == "month":
                    include = (
                        day_date.year == today.year and day_date.month == today.month
                    )

                if include:
                    p0_total += day.get("p0_seconds", 0)
                    p1_total += day.get("p1_seconds", 0)
                    p2_total += day.get("p2_seconds", 0)
                    p3_total += day.get("p3_seconds", 0)
                    points_total += day.get("total_points", 0)
                    days_count += 1

            grand_total = p0_total + p1_total + p2_total + p3_total

            embed = disnake.Embed(
                title=f"📊 Статистика: {self.user_name}",
                description=f"**{period_name}**",
                color=0x2B2D31,
            )

            # Time by Priority
            time_text = (
                f"**P0:** {format_duration(p0_total)}\n"
                f"**P1:** {format_duration(p1_total)}\n"
                f"**P2:** {format_duration(p2_total)}\n"
                f"**P3:** {format_duration(p3_total)}\n"
                f"───────────\n"
                f"**Итого:** {format_duration(grand_total)}"
            )
            embed.add_field(name="⏱️ Время по приоритетам", value=time_text, inline=True)

            # Points
            points_text = f"**Баллов:** {format_points(points_total)}"
            if days_count > 1:
                avg = points_total / days_count if days_count else 0
                points_text += f"\n**В среднем/день:** {format_points(avg)}"
            embed.add_field(name="⭐ Баллы", value=points_text, inline=True)

            embed.set_footer(text=f"ID: {self.user_id} | Дней: {days_count}")

            return embed

        except Exception as e:
            self.bot.logger.error(f"Error getting stats: {e}", exc_info=True)
            return disnake.Embed(title="❌ Ошибка", color=disnake.Color.red())


class AssistantEditModal(disnake.ui.Modal):
    """Modal for editing assistant time."""

    def __init__(self, bot: commands.Bot, user_id: int, user_name: str):
        self.bot = bot
        self.api = bot.api_client
        self.user_id = user_id

        components = [
            disnake.ui.TextInput(
                label="Добавить/вычесть время (минуты)",
                placeholder="+30 или -15",
                custom_id="time_delta",
                style=disnake.TextInputStyle.short,
                max_length=10,
            ),
            disnake.ui.TextInput(
                label="Приоритет (0-3)",
                placeholder="0",
                custom_id="priority",
                style=disnake.TextInputStyle.short,
                max_length=1,
                value="0",
            ),
            disnake.ui.TextInput(
                label="Причина (необязательно)",
                placeholder="Коррекция за пропущенный стрим",
                custom_id="reason",
                style=disnake.TextInputStyle.paragraph,
                required=False,
                max_length=200,
            ),
        ]
        super().__init__(
            title=f"Редактировать: {user_name[:20]}", components=components
        )

    async def callback(self, interaction: disnake.ModalInteraction):
        await interaction.response.defer(ephemeral=True)

        try:
            time_str = interaction.text_values["time_delta"].strip()
            priority_str = interaction.text_values["priority"].strip()
            reason = interaction.text_values.get("reason", "").strip()

            # Parse time delta
            if time_str.startswith("+"):
                seconds = int(time_str[1:]) * 60
                action = "add"
            elif time_str.startswith("-"):
                seconds = int(time_str[1:]) * 60
                action = "subtract"
            else:
                seconds = int(time_str) * 60
                action = "add" if seconds >= 0 else "subtract"
                seconds = abs(seconds)

            # Parse priority
            priority = int(priority_str)
            if priority < 0 or priority > 3:
                await interaction.edit_original_message(
                    content="❌ Приоритет должен быть 0-3."
                )
                return

            # API call
            if action == "add":
                await self.api.add_assistant_time(self.user_id, seconds)
            else:
                await self.api.subtract_assistant_time(self.user_id, seconds)

            minutes = seconds // 60
            sign = "+" if action == "add" else "-"
            msg = f"✅ Время изменено: **{sign}{minutes} мин** (P{priority})"
            if reason:
                msg += f"\n📝 Причина: {reason}"

            await interaction.edit_original_message(content=msg)

        except ValueError:
            await interaction.edit_original_message(
                content="❌ Неверный формат. Используйте +30 или -15."
            )
        except Exception as e:
            self.bot.logger.error(f"Edit time error: {e}")
            await interaction.edit_original_message(content="❌ Ошибка.")


class AssistantActionsView(disnake.ui.View):
    """Actions view with reset options."""

    def __init__(self, bot: commands.Bot, user_id: int, user_name: str):
        super().__init__(timeout=None)
        self.bot = bot
        self.api = bot.api_client
        self.user_id = user_id
        self.user_name = user_name

        self._build_actions()

    def _build_actions(self):
        self.clear_items()

        self.add_item(
            disnake.ui.Button(
                label="🔄 Полный сброс",
                custom_id=f"assistant_reset_full_{self.user_id}",
                style=disnake.ButtonStyle.danger,
                row=0,
            )
        )

        self.add_item(
            disnake.ui.Button(
                label="🔙 К обзору",
                custom_id=f"assistant_overview_{self.user_id}",
                style=disnake.ButtonStyle.secondary,
                row=1,
            )
        )

    async def get_actions_embed(self) -> disnake.Embed:
        return disnake.Embed(
            title=f"⚙️ Действия: {self.user_name}",
            description="Выберите действие для выполнения.\n\n"
            "⚠️ **Полный сброс** удалит ВСЮ статистику ассистента!",
            color=disnake.Color.orange(),
        )


class TopAssistantsView(disnake.ui.View):
    """Leaderboard view."""

    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot
        self.api = bot.api_client

        self.add_item(
            disnake.ui.Button(
                label="🔄 Обновить",
                custom_id="assistant_top_refresh",
                style=disnake.ButtonStyle.secondary,
            )
        )
        self.add_item(
            disnake.ui.Button(
                label="🔙 Назад",
                custom_id="assistant_back_to_select",
                style=disnake.ButtonStyle.secondary,
            )
        )

    async def get_top_embed(self) -> disnake.Embed:
        try:
            top = await self.api.get_top_assistants(limit=15)

            embed = disnake.Embed(
                title="🏆 Топ ассистентов", color=disnake.Color.gold()
            )

            if not top:
                embed.description = "Нет данных."
                return embed

            lines = []
            for i, a in enumerate(top, 1):
                medal = (
                    "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
                )
                pr_id = a.get("pr_id")
                total = a.get("total_spec_seconds", 0)
                lines.append(f"{medal} <@{pr_id}> — **{format_duration(total)}**")

            embed.description = "\n".join(lines)

            return embed
        except Exception as e:
            self.bot.logger.error(f"Error getting top: {e}")
            return disnake.Embed(title="❌ Ошибка", color=disnake.Color.red())


def setup(bot: commands.Bot) -> None:
    pass
