"""Utility functions for Discord Bot."""

import datetime
import logging
import time
from typing import Any, Dict, List, Optional, Tuple, Union

import disnake
from config import Config
from disnake.ext import commands

# Module logger
logger = logging.getLogger(__name__)


class UserAuthCache:
    """
    Simple TTL cache for user authorization status.
    Prevents API spam by caching user existence checks.
    """

    def __init__(self, ttl_seconds: int = 300):
        self._cache: Dict[int, Tuple[bool, float]] = {}
        self._ttl = ttl_seconds

    def get(self, user_id: int) -> Optional[bool]:
        """
        Get cached authorization status.
        Returns True (authorized), False (unauthorized), or None (not cached/expired).
        """
        if user_id not in self._cache:
            return None
        
        is_authorized, timestamp = self._cache[user_id]
        if time.time() - timestamp > self._ttl:
            # Expired
            del self._cache[user_id]
            return None
        
        return is_authorized

    def set(self, user_id: int, is_authorized: bool) -> None:
        """Cache authorization status for a user."""
        self._cache[user_id] = (is_authorized, time.time())

    def invalidate(self, user_id: int) -> None:
        """Remove a user from cache (e.g., after role change)."""
        self._cache.pop(user_id, None)

    def clear(self) -> None:
        """Clear entire cache."""
        self._cache.clear()


def parse_to_unix(value: Union[str, datetime.datetime, None]) -> int:
    """
    Convert API timestamp (ISO 8601) or datetime object to Unix timestamp.

    Args:
        value: ISO 8601 string (e.g., '2026-02-05T19:07:14' or '2026-02-05T19:07:14Z'),
               a datetime object, or None.

    Returns:
        Unix timestamp as an integer, or 0 if parsing fails or value is None.
    """
    if value is None:
        return 0

    try:
        if isinstance(value, str):
            # Handle ISO format with optional 'Z' suffix
            dt = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
            # If naive (no timezone), assume Local System Time and convert to UTC
            if dt.tzinfo is None:
                dt = dt.astimezone(datetime.timezone.utc)
            return int(dt.timestamp())
        elif isinstance(value, datetime.datetime):
            # If naive, assume Local System Time and convert to UTC
            if value.tzinfo is None:
                value = value.astimezone(datetime.timezone.utc)
            return int(value.timestamp())
        elif isinstance(value, datetime.date):
            # Convert date to datetime at midnight UTC
            dt = datetime.datetime.combine(value, datetime.time.min).replace(tzinfo=datetime.timezone.utc)
            return int(dt.timestamp())
    except Exception as e:
        logger.warning(f"Failed to parse timestamp '{value}': {e}")

    return 0


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
        started_at_unix = parse_to_unix(streamer.get("started_at"))

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
    online_count: int = None,
) -> List[disnake.ui.Container]:
    """Create UI components with streamers and events (for Monitoring).
    
    Returns a list of Containers, each representing one Discord message page.
    Pagination is used to stay within Discord's 40-component limit per message.
    """
    if events is None:
        events = []

    now_unix = int(time.time())
    
    # Constants for pagination
    STREAMERS_PER_PAGE = 5

    # Handle empty states - return single page
    if subscribed_count == 0 and not events:
        return [disnake.ui.Container(
            disnake.ui.TextDisplay(content="### 📭 Нет подписок"),
            disnake.ui.TextDisplay(
                content="Этот сервер не подписан ни на одного стримера."
            ),
            disnake.ui.TextDisplay(
                content="Добавьте стримеров для мониторинга."
            ),
            disnake.ui.Separator(divider=True, spacing=disnake.SeparatorSpacing.small),
            disnake.ui.TextDisplay(content=f"-# 🔄 Обновлено: <t:{now_unix}:R>"),
            accent_colour=disnake.Colour(65358),
        )]

    if not online_streamers and not events:
        return [disnake.ui.Container(
            disnake.ui.TextDisplay(content="### 😴 Все офлайн"),
            disnake.ui.TextDisplay(
                content=f"Из **{subscribed_count}** подписанных стримеров сейчас никто не в эфире."
            ),
            disnake.ui.Separator(divider=True, spacing=disnake.SeparatorSpacing.small),
            disnake.ui.TextDisplay(content=f"-# 🔄 Обновлено: <t:{now_unix}:R>"),
            accent_colour=disnake.Colour(65358),
        )]

    # Sort streamers by priority
    online_streamers_sorted = sorted(
        online_streamers, key=lambda s: s.get("priority", 0), reverse=True
    )
    
    def build_streamer_components(streamer: Dict[str, Any]) -> List:
        """Build 4 components for a single streamer."""
        streamer_name = streamer["streamer_name"]
        started_at_unix = parse_to_unix(streamer.get("started_at"))
        stream_title = streamer.get("stream_title") or "Без названия"
        game_name = streamer.get("game_name") or "Не в игре"
        priority = streamer.get("priority", 0)
        game_id = str(streamer.get("game_id", ""))
        game_emoji = "🟢" if game_id == Config.gta5_game_id else "🟠"
        thumbnail_url = (
            streamer.get("stream_thumbnail_url")
            or "https://static-cdn.jtvnw.net/previews-ttv/live_user_placeholder-320x180.jpg"
        )
        assignments = streamer.get("assignments", [])
        
        main_pr = None
        prob_pr = None
        if assignments:
            for a in assignments:
                if a.get("is_probation"):
                    prob_pr = a.get("pr_id")
                else:
                    main_pr = a.get("pr_id")

        lines = []
        if main_pr:
            lines.append(f"👤 PR: <@{main_pr}>")
        else:
            lines.append("👤 PR: *свободен*")
        if prob_pr:
            lines.append(f"👤 PR стажировка: <@{prob_pr}>")
        pr_line = "\n".join(lines)

        return [
            disnake.ui.Separator(divider=True, spacing=disnake.SeparatorSpacing.small),
            disnake.ui.TextDisplay(content=f"### {game_emoji} {streamer_name}"),
            disnake.ui.TextDisplay(
                content=f"**{stream_title[:50]}{'...' if len(stream_title) > 50 else ''}**"
            ),
            disnake.ui.Section(
                disnake.ui.TextDisplay(
                    content=f"🏷 Приоритет: **{priority}**\n🎮 **{game_name}**\n🕒 Стримит: <t:{started_at_unix}:R>\n{pr_line}\n🔗 https://twitch.tv/{streamer_name}"
                ),
                accessory=disnake.ui.Thumbnail(media=thumbnail_url),
            ),
        ]

    def build_event_components(event: Dict[str, Any]) -> List:
        """Build components for a single event."""
        start_unix = parse_to_unix(event.get("start_time"))
        participant_count = event.get("current_participants", 0)
        required = event.get("required_pr_count", 0)
        return [
            disnake.ui.Separator(divider=True, spacing=disnake.SeparatorSpacing.small),
            disnake.ui.TextDisplay(content=f"### {event['name']}"),
            disnake.ui.TextDisplay(
                content=f"{event.get('description', '')[:100]}{'...' if len(event.get('description', '')) > 100 else ''}"
            ),
            disnake.ui.TextDisplay(
                content=f"👥 **Участников:** {participant_count} / {required}\n🕒 **Начало:** <t:{start_unix}:R>"
            ),
        ]

    # Build all pages
    pages = []
    
    # Split streamers into chunks
    streamer_chunks = [
        online_streamers_sorted[i:i + STREAMERS_PER_PAGE]
        for i in range(0, len(online_streamers_sorted), STREAMERS_PER_PAGE)
    ]
    
    if not streamer_chunks:
        streamer_chunks = [[]]  # At least one empty chunk for events
    
    for page_idx, chunk in enumerate(streamer_chunks):
        components = []
        
        # First page: add header
        if page_idx == 0:
            # Use online_count if provided, else fallback to len of list
            display_online = online_count if online_count is not None else len(online_streamers)
            components.append(disnake.ui.TextDisplay(content="### 🎥 Стримеры онлайн — Majestic"))
            components.append(disnake.ui.TextDisplay(
                content=f"**Онлайн**: {display_online} · **В GTA:** {gta_count} · **Всего:** {subscribed_count}"
            ))
        
        # Add streamer components
        for streamer in chunk:
            components.extend(build_streamer_components(streamer))
        
        # Last page: add events and footer
        is_last_page = page_idx == len(streamer_chunks) - 1
        if is_last_page:
            if events:
                components.append(disnake.ui.Separator(divider=True, spacing=disnake.SeparatorSpacing.large))
                components.append(disnake.ui.TextDisplay(content="### 🎉 Активные события"))
                for event in events:
                    components.extend(build_event_components(event))
            
            # Footer timestamp
            components.append(disnake.ui.Separator(divider=True, spacing=disnake.SeparatorSpacing.small))
            components.append(disnake.ui.TextDisplay(content=f"-# 🔄 Обновлено: <t:{now_unix}:R>"))
        
        pages.append(disnake.ui.Container(*components, accent_colour=disnake.Colour(65358)))
    
    return pages


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
    is_probation: bool = False,
    include_embed: bool = True,
) -> list:
    """Create notification components (Embed + ActionRow)."""
    streamer_link = f"https://twitch.tv/{streamer_name}"

    result = []

    # Only include TextDisplay if message is not empty
    if message and message.strip():
        text_display = disnake.ui.TextDisplay(content=message)
        result.append(text_display)

    if include_embed:
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
        result.append(container)

    # Add claim button if requested and we have streamer_id
    if show_claim_button and streamer_id:
        if assigned_pr_id:
            # Already claimed - show who claimed it
            emoji = "🟡" if is_probation else "🔵"
            claim_label = (
                f"{emoji} Взял: {assigned_pr_name}" if assigned_pr_name else f"{emoji} Взят"
            )
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


def create_monitoring_select(
    available_streamers: list, events: list = None
) -> disnake.ui.ActionRow:
    """Create action row with Claim/Unclaim buttons for monitoring."""
    claim_btn = disnake.ui.Button(
        label="📥 Закрепиться",
        style=disnake.ButtonStyle.success,
        custom_id="monitoring_claim",
    )
    unclaim_btn = disnake.ui.Button(
        label="📤 Открепиться",
        style=disnake.ButtonStyle.danger,
        custom_id="monitoring_unclaim",
    )
    
    return disnake.ui.ActionRow(claim_btn, unclaim_btn)


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


async def safe_defer(interaction: disnake.Interaction, ephemeral: bool = True) -> bool:
    """
    Safely defer an interaction.
    Returns True if valid (deferred or already done), False if invalid/unknown.
    """
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=ephemeral)
        return True
    except (disnake.NotFound, disnake.HTTPException, disnake.InteractionResponded):
        return False
    except Exception as e:
        logger.warning(f"Unexpected error during defer: {e}")
        return False


async def handle_interaction_error(
    interaction: disnake.Interaction, 
    error: Exception, 
    logger_instance: logging.Logger = None
):
    """
    Handle errors during interaction processing.
    Logs the error and sends a user-friendly message.
    """
    if logger_instance:
        logger_instance.error(f"Interaction error: {error}", exc_info=True)
    else:
        logger.error(f"Interaction error: {error}", exc_info=True)

    msg = f"❌ Ошибка: {str(error)}"
    
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        pass
