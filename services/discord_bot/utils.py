"""Utility functions for Discord Bot (Ported from Legacy)."""

import disnake
from disnake.ext import commands
import calendar
import datetime
import logging
import time
from typing import List, Dict, Any

from config import Config

# Module logger
logger = logging.getLogger(__name__)


def format_spec_duration(seconds: int) -> str:
    """Format duration in seconds to human readable string."""
    if seconds < 60:
        return f"{seconds}с"
    
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    
    if hours > 0:
        return f"{hours}ч {minutes}м" if minutes > 0 else f"{hours}ч"
    return f"{minutes}м"

async def send_pr_action_log(bot: commands.Bot, message: str) -> bool:
    """
    Send message to the PR actions log channel.
    
    Args:
        bot: The Discord bot instance (must have api_client)
        message: The formatted message to send
        
    Returns:
        True if message was sent successfully, False otherwise
    """
    try:
        settings = await bot.api_client.get_guild_settings()
        if not settings or not isinstance(settings, dict):
            return False
        
        channel_id = settings.get("pr_actions_channel_id")
        if not channel_id:
            return False
        
        channel = bot.get_channel(int(channel_id))
        if not channel:
            return False
        
        await channel.send(message)
        return True
        
    except Exception as e:
        bot.logger.error(f"Failed to send PR action log: {e}")
        return False


def create_streamers_embed(
    online_streamers: List[Dict[str, Any]],
    subscribed_count: int,
    gta_count: int,
) -> disnake.Embed:
    """Create embed with online streamers list."""
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
        
        # Handle various date formats (str or datetime)
        started_at_unix = 0
        if started_at:
            if isinstance(started_at, str):
                try:
                    # ISO format parsing
                    dt = datetime.datetime.fromisoformat(started_at.replace('Z', '+00:00'))
                    started_at_unix = int(dt.timestamp())
                except:
                    started_at_unix = 0
            elif isinstance(started_at, (datetime.datetime, datetime.date)):
                 started_at_unix = int(started_at.timestamp())

        stream_title = streamer.get("stream_title") or "Без названия"
        game_name = streamer.get("game_name") or "Не в игре"
        priority = streamer.get("priority", 0)
        game_id = str(streamer.get("game_id", ""))
        game_emoji = "🟢" if game_id == Config.gta5_game_id else "🟠"

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
    """Create UI component with streamers and events (for Monitoring)."""
    if events is None:
        events = []

    now_unix = int(time.time())

    # Handle empty states
    if subscribed_count == 0 and not events:
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
        started_at_unix = 0
        if started_at:
            if isinstance(started_at, str):
                try:
                   dt = datetime.datetime.fromisoformat(started_at.replace('Z', '+00:00'))
                   started_at_unix = int(dt.timestamp())
                except: pass
            elif isinstance(started_at, (datetime.datetime, datetime.date)):
                 started_at_unix = int(started_at.timestamp())
        
        stream_title = streamer.get("stream_title") or "Без названия"
        game_name = streamer.get("game_name") or "Не в игре"
        priority = streamer.get("priority", 0)
        game_id = str(streamer.get("game_id", ""))
        game_emoji = "🟢" if game_id == Config.gta5_game_id else "🟠"
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
            # Parse start_time
            start_time = event.get("start_time")
            start_unix = 0
            if start_time:
                 if isinstance(start_time, str):
                     try:
                        dt = datetime.datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                        start_unix = int(dt.timestamp())
                     except: pass
                 elif isinstance(start_time, (datetime.datetime, datetime.date)):
                     start_unix = int(start_time.timestamp())

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
                    content=f"{event.get('description', '')[:100]}{'...' if len(event.get('description', ''))>100 else ''}"
                )
            )
            components.append(
                disnake.ui.TextDisplay(
                    content=f"👥 **Участников:** {participant_count} / {required}\n🕒 **Начало:** <t:{start_unix}:R>"
                )
            )


    # Add last updated timestamp at the bottom
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
    """Create notification components (Embed + ActionRow)."""
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

    result = []
    
    # Only include TextDisplay if message is not empty
    if message and message.strip():
        text_display = disnake.ui.TextDisplay(content=message)
        result.append(text_display)
    
    result.append(container)

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
    """Create dropdown for monitoring message."""
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
    """Format notification template string."""
    streamer_link = f"https://twitch.tv/{streamer_name}"

    try:
        return template.format(
            streamer_name=streamer_name,
            stream_title=stream_title or "Без названия",
            game_name=game_name or "Не указана",
            streamer_link=streamer_link,
        )
    except Exception:
        # Return fallback
        return f"{template} (Error formatting) - {streamer_name}"
