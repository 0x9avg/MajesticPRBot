"""Utility functions for PRMajesticBot."""

import disnake
import calendar
import logging
import time
from typing import List, Dict, Any

from config import Config

# Module logger
logger = logging.getLogger(__name__)


def create_streamers_embed(
    online_streamers: List[Dict[str, Any]],
    subscribed_count: int,
    gta_count: int,
) -> disnake.Embed:
    """Create embed showing online streamers.

    Args:
        online_streamers: List of online streamer data dicts
        subscribed_count: Total number of subscriptions for the guild
        gta_count: Number of streamers playing GTA 5

    Returns:
        Configured disnake.Embed
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
) -> disnake.ui.Container:
    """Create component showing online streamers.

    Args:
        online_streamers: List of online streamer data dicts
        subscribed_count: Total number of subscriptions for the guild
        gta_count: Number of streamers playing GTA 5

    Returns:
        Configured disnake.ui.Container (pass to components= parameter)
    """
    # Handle empty states
    if subscribed_count == 0:
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

    if not online_streamers:
        now_unix = int(time.time())
        return disnake.ui.Container(
            disnake.ui.TextDisplay(content="### 😴 Все офлайн"),
            disnake.ui.TextDisplay(
                content=f"Из **{subscribed_count}** подписанных стримеров сейчас никто не в эфире."
            ),
            disnake.ui.Separator(divider=True, spacing=disnake.SeparatorSpacing.small),
            disnake.ui.TextDisplay(content=f"-# 🔄 Обновлено: <t:{now_unix}:R>"),
        )

    # Sort by priority
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
        thumbnail_url = (
            streamer.get("stream_thumbnail_url")
            or "https://static-cdn.jtvnw.net/previews-ttv/live_user_placeholder-320x180.jpg"
        )

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
                    content=f"🏷 Приоритет: **{priority}**\n🎮 **{game_name}**\n🕒 Стримит: <t:{started_at_unix}:R>\n🔗 https://twitch.tv/{streamer_name}"
                ),
                accessory=disnake.ui.Thumbnail(media=thumbnail_url),
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

    # Return container directly - pass to components= parameter
    return disnake.ui.Container(*components, accent_colour=disnake.Colour(65358))


def create_notification_component(
    message: str,
    streamer_name: str,
    stream_title: str,
    game_name: str,
    thumbnail_url: str,
) -> list:
    """Create notification components for stream events.

    Args:
        message: Notification message (with @everyone if needed)
        streamer_name: Twitch username
        stream_title: Current stream title
        game_name: Current game name
        thumbnail_url: Stream thumbnail URL

    Returns:
        List of components [TextDisplay with message, Container with stream info]
    """
    streamer_link = f"https://twitch.tv/{streamer_name}"

    # Use default placeholder if no thumbnail
    if not thumbnail_url:
        thumbnail_url = "https://static-cdn.jtvnw.net/previews-ttv/live_user_placeholder-320x180.jpg"

    # TextDisplay with message goes OUTSIDE container for v2 components
    text_display = disnake.ui.TextDisplay(content=message)

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

    return [text_display, container]


def format_notification_template(
    template: str,
    streamer_name: str,
    stream_title: str = "",
    game_name: str = "",
) -> str:
    """Format notification template with streamer data.

    Args:
        template: Template string with placeholders
        streamer_name: Twitch username
        stream_title: Current stream title
        game_name: Current game name

    Returns:
        Formatted notification message
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

