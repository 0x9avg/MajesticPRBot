"""Utility functions for PRMajesticBot."""

import disnake
import calendar
import datetime
import logging
import time
from typing import List, Dict, Any

from config import Config

# Module logger
logger = logging.getLogger(__name__)


def format_spec_duration(seconds: int) -> str:
    """
    Форматирование длительности в читаемый вид.

    Args:
        seconds: Длительность в секундах

    Returns:
        Строка вида "1ч 30м" или "45м"
    """
    if seconds < 60:
        return f"{seconds}с"
    
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    
    if hours > 0:
        return f"{hours}ч {minutes}м" if minutes > 0 else f"{hours}ч"
    return f"{minutes}м"

def split_time_by_day(start_dt, end_dt) -> List[tuple]:
    """
    Разделение временного интервала по дням.
    
    Args:
        start_dt: Начало (aware datetime)
        end_dt: Конец (aware datetime)
        
    Returns:
        Список кортежей (date, duration_seconds)
    """
    chunks = []
    current = start_dt
    
    while current < end_dt:
        # Calculate next midnight
        next_day = (current + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Determine strict end for this chunk
        chunk_end = min(end_dt, next_day)
        
        duration = int((chunk_end - current).total_seconds())
        if duration > 0:
            chunks.append((current.date(), duration))
            
        current = chunk_end
        
    return chunks
def create_streamers_embed(
    online_streamers: List[Dict[str, Any]],
    subscribed_count: int,
    gta_count: int,
) -> disnake.Embed:
    """
    Создание эмбеда со списком онлайн стримеров.

    Args:
        online_streamers: Список данных стримеров
        subscribed_count: Общее количество подписок
        gta_count: Количество стримеров в GTA 5

    Returns:
        Объект disnake.Embed
    """
    # Handle empty states
    if subscribed_count == 0:
        return disnake.Embed(
            title="📭 Нет подписок",
            description="Этот сервер не подписан ни на одного стримера.\n"
            "Используйте `/add_streamer` чтобы добавить стримера.",
            color=disnake.Color.orange(),
        )

    if not online_streamers:
        return disnake.Embed(
            title="😴 Все офлайн",
            description=f"Из **{subscribed_count}** подписанных стримеров сейчас никто не в эфире.",
            color=disnake.Color.greyple(),
        )

    # Build embed with online streamers
    embed = disnake.Embed(
        title="🎥 Стримеры онлайн — Majestic",
        description=f"**🟢 в GTA** · **🟠 не в GTA**\n\n"
        f"**Онлайн:** {len(online_streamers)} · **В GTA:** {gta_count} · "
        f"**Всего подписок:** {subscribed_count}",
        color=disnake.Color.green(),
    )

    # Sort by priority
    online_streamers_sorted = sorted(
        online_streamers, key=lambda s: s.get("priority", 0), reverse=True
    )

    for streamer in online_streamers_sorted:
        streamer_name = streamer["streamer_name"]
        started_at = streamer.get("started_at")
        # Convert naive datetime (UTC from DB) to unix timestamp properly
        if started_at:
            started_at_unix = int(calendar.timegm(started_at.timetuple()))
        else:
            started_at_unix = 0
        stream_title = streamer.get("stream_title") or "Без названия"
        game_name = streamer.get("game_name") or "Не в игре"
        priority = streamer.get("priority", 0)
        game_id = str(streamer.get("game_id", ""))
        game_emoji = "🟢" if game_id == Config.GTA5_GAME_ID else "🟠"

        embed.add_field(
            name=f"{game_emoji} {streamer_name}",
            value=f"**{stream_title[:50]}{'...' if len(stream_title) > 50 else ''}**\n"
            f"🏷 Приоритет: **{priority}**  🎮 **{game_name}**\n"
            f"🕒 Стримит: <t:{started_at_unix}:R>\n"
            f"🔗 https://twitch.tv/{streamer_name}",
            inline=False,
        )

    return embed


def create_streamers_component(
    online_streamers: List[Dict[str, Any]],
    subscribed_count: int,
    gta_count: int,
    events: List[Dict[str, Any]] = None,
) -> disnake.ui.Container:
    """
    Создание компонента со стримерами и событиями.
    
    Args:
        online_streamers: Список стримеров
        subscribed_count: Всего подписок
        gta_count: Стримеров в GTA
        events: Список активных событий
    
    Returns:
        Объект disnake.ui.Container
    """
    if events is None:
        events = []

    # Handle empty states
    if subscribed_count == 0 and not events:
        now_unix = int(time.time())
        return disnake.ui.Container(
            disnake.ui.TextDisplay(content="### 📭 Нет подписок"),
            disnake.ui.TextDisplay(
                content="Этот сервер не подписан ни на одного стримера."
            ),
            disnake.ui.TextDisplay(
                content="Используйте `/add_streamer` чтобы добавить стримера."
            ),
            disnake.ui.Separator(divider=True, spacing=disnake.SeparatorSpacing.small),
            disnake.ui.TextDisplay(content=f"-# 🔄 Обновлено: <t:{now_unix}:R>"),
        )

    if not online_streamers and not events:
        now_unix = int(time.time())
        return disnake.ui.Container(
            disnake.ui.TextDisplay(content="### 😴 Все офлайн"),
            disnake.ui.TextDisplay(
                content=f"Из **{subscribed_count}** подписанных стримеров сейчас никто не в эфире."
            ),
            disnake.ui.Separator(divider=True, spacing=disnake.SeparatorSpacing.small),
            disnake.ui.TextDisplay(content=f"-# 🔄 Обновлено: <t:{now_unix}:R>"),
        )

    # Sort streamers by priority
    online_streamers_sorted = sorted(
        online_streamers, key=lambda s: s.get("priority", 0), reverse=True
    )

    # Build all components for the container
    components = [
        disnake.ui.TextDisplay(content="### 🎥 Стримеры онлайн — Majestic"),
        disnake.ui.TextDisplay(
            content=f"**Онлайн**: {len(online_streamers)} · **В GTA:** {gta_count} · **Всего:** {subscribed_count}"
        ),
    ]

    for streamer in online_streamers_sorted:
        streamer_name = streamer["streamer_name"]
        started_at = streamer.get("started_at")
        if started_at:
            started_at_unix = int(calendar.timegm(started_at.timetuple()))
        else:
            started_at_unix = 0
        stream_title = streamer.get("stream_title") or "Без названия"
        game_name = streamer.get("game_name") or "Не в игре"
        priority = streamer.get("priority", 0)
        game_id = str(streamer.get("game_id", ""))
        game_emoji = "🟢" if game_id == Config.GTA5_GAME_ID else "🟠"
        thumbnail_url = (
            streamer.get("stream_thumbnail_url")
            or "https://static-cdn.jtvnw.net/previews-ttv/live_user_placeholder-320x180.jpg"
        )
        assigned_pr_id = streamer.get("assigned_pr_id")
        
        pr_line = f"👤 PR: <@{assigned_pr_id}>" if assigned_pr_id else "👤 PR: *свободен*"

        components.append(
            disnake.ui.Separator(divider=True, spacing=disnake.SeparatorSpacing.small)
        )
        components.append(
            disnake.ui.TextDisplay(content=f"### {game_emoji} {streamer_name}")
        )
        components.append(
            disnake.ui.TextDisplay(
                content=f"**{stream_title[:50]}{'...' if len(stream_title) > 50 else ''}**"
            )
        )
        components.append(
            disnake.ui.Section(
                disnake.ui.TextDisplay(
                    content=f"🏷 Приоритет: **{priority}**\n🎮 **{game_name}**\n🕒 Стримит: <t:{started_at_unix}:R>\n{pr_line}\n🔗 https://twitch.tv/{streamer_name}"
                ),
                accessory=disnake.ui.Thumbnail(media=thumbnail_url),
            )
        )

    # Add Events Section
    if events:
        components.append(
            disnake.ui.Separator(divider=True, spacing=disnake.SeparatorSpacing.large)
        )
        components.append(
            disnake.ui.TextDisplay(content="### 🎉 Активные события")
        )
        
        for event in events:
            # event keys: id, name, description, ... current_participants
            # event keys: id, name, description, ... current_participants
            start_unix = int(calendar.timegm(event["start_time"].timetuple()))
            participant_count = event.get("current_participants", 0)
            participant_count = event.get("current_participants", 0)
            required = event.get("required_pr_count", 0)
            
            components.append(
                disnake.ui.Separator(divider=True, spacing=disnake.SeparatorSpacing.small)
            )
            components.append(
                disnake.ui.TextDisplay(
                    content=f"### {event['name']}"
                )
            )
            components.append(
                disnake.ui.TextDisplay(
                    content=f"{event['description'][:100]}{'...' if len(event['description'])>100 else ''}"
                )
            )
            components.append(
                disnake.ui.TextDisplay(
                    content=f"👥 **Участников:** {participant_count} / {required}\n🕒 **Начало:** <t:{start_unix}:R>"
                )
            )


    # Add last updated timestamp at the bottom
    now_unix = int(time.time())
    components.append(
        disnake.ui.Separator(divider=True, spacing=disnake.SeparatorSpacing.small)
    )
    components.append(
        disnake.ui.TextDisplay(content=f"-# 🔄 Обновлено: <t:{now_unix}:R>")
    )

    return disnake.ui.Container(*components, accent_colour=disnake.Colour(65358))


def create_notification_component(
    message: str,
    streamer_name: str,
    stream_title: str,
    game_name: str,
    thumbnail_url: str,
    streamer_id: int = None,
    show_claim_button: bool = False,
    assigned_pr_id: int = None,
    assigned_pr_name: str = None,
) -> list:
    """
    Создание компонентов для уведомления о стриме.

    Args:
        message: Текст сообщения
        streamer_name: Имя стримера
        stream_title: Название стрима
        game_name: Название игры
        thumbnail_url: URL превью
        streamer_id: ID стримера (для кнопки взятия)
        show_claim_button: Показывать ли кнопку "Взять"
        assigned_pr_id: ID назначенного PR (если занят)
        assigned_pr_name: Имя назначенного PR

    Returns:
        Список компонентов для отправки
    """
    streamer_link = f"https://twitch.tv/{streamer_name}"

    # Use default placeholder if no thumbnail
    if not thumbnail_url:
        thumbnail_url = "https://static-cdn.jtvnw.net/previews-ttv/live_user_placeholder-320x180.jpg"

    container = disnake.ui.Container(
        disnake.ui.TextDisplay(content=f"### {streamer_name}"),
        disnake.ui.TextDisplay(
            content=f"### [**{stream_title[:80] if stream_title else 'Без названия'}**]({streamer_link})"
        ),
        disnake.ui.TextDisplay(content=f"**Игра:**\n{game_name or 'Не указана'}"),
        disnake.ui.TextDisplay(content=f"**Ссылка:**\n{streamer_link}"),
        disnake.ui.MediaGallery(disnake.MediaGalleryItem(media=thumbnail_url)),
        accent_colour=disnake.Colour.purple(),
    )

    # Only include TextDisplay if message is not empty
    if message:
        text_display = disnake.ui.TextDisplay(content=message)
        result = [text_display, container]
    else:
        result = [container]

    # Add claim button if requested and we have streamer_id
    if show_claim_button and streamer_id:
        if assigned_pr_id:
            # Already claimed - show who claimed it
            claim_label = f"✅ Взял: {assigned_pr_name}" if assigned_pr_name else "✅ Взят"
            result.append(
                disnake.ui.ActionRow(
                    disnake.ui.Button(
                        label=claim_label,
                        custom_id=f"spec_claimed_{streamer_id}",
                        style=disnake.ButtonStyle.secondary,
                        disabled=True,
                    )
                )
            )
        else:
            # Not claimed - show claim button
            result.append(
                disnake.ui.ActionRow(
                    disnake.ui.Button(
                        label="🎯 Взять медиа",
                        custom_id=f"spec_claim_{streamer_id}",
                        style=disnake.ButtonStyle.success,
                    )
                )
            )

    return result


def create_monitoring_select(available_streamers: list, events: list = None) -> disnake.ui.ActionRow:
    """Создание выпадающего списка для сообщения мониторинга."""
    options = []
    
    # Add Streamers
    for s in available_streamers:
        options.append(
            disnake.SelectOption(
                label=s["streamer_name"],
                value=str(s["streamer_id"]),
                description="Взять медиа (GTA 5)",
                emoji="🎯"
            )
        )
        
    # Add Events
    if events:
        for e in events:
            # Prefix event IDs to distinguish from streamer IDs
            # Although streamer IDs are big ints and event IDs small ints, let's use prefix "event_"
            options.append(
                disnake.SelectOption(
                    label=e["name"][:100],
                    value=f"event_{e['id']}",
                    description=f"Событие (PR: {e.get('current_participants')}/{e.get('required_pr_count')})",
                    emoji="🎉"
                )
            )

    if not options:
        options.append(
            disnake.SelectOption(
                label="Нет доступных медиа/событий",
                value="none",
                description="Все занято или пусто",
                default=True
            )
        )

    select = disnake.ui.StringSelect(
        placeholder="🎯 Взять медиа / 🎉 Событие",
        min_values=1,
        max_values=1,
        options=options[:25],  # Max 25 options
        custom_id="spec_claim_select",
        disabled=not options or (len(options) == 1 and options[0].value == "none")
    )
    
    return disnake.ui.ActionRow(select)


def format_notification_template(
    template: str,
    streamer_name: str,
    stream_title: str = "",
    game_name: str = "",
) -> str:
    """
    Форматирование шаблона уведомления.

    Args:
        template: Строка шаблона
        streamer_name: Имя стримера
        stream_title: Название стрима
        game_name: Игра

    Returns:
        Отформатированное сообщение
    """
    streamer_link = f"https://twitch.tv/{streamer_name}"

    try:
        return template.format(
            streamer_name=streamer_name,
            stream_title=stream_title or "Без названия",
            game_name=game_name or "Не указана",
            streamer_link=streamer_link,
        )
    except KeyError as e:
        logger.warning(
            f"Invalid template placeholder {e} in template: {template[:100]}..."
        )
        # Return template with basic substitution as fallback
        return template.replace("{streamer_name}", streamer_name)

