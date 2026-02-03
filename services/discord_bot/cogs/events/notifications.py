"""
Notifications Cog.
Handles sending stream status notifications to configured Discord channels.
Uses API render_notification for server-driven UI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api_client import APIClient
    from discord_bot import DiscordBot
    from logging import Logger


import logging

import disnake
from config import Config
from disnake.ext import commands


class Notifications(commands.Cog):
    """Event notifications system."""

    bot: DiscordBot
    api: APIClient

    def __init__(self, bot: DiscordBot):
        self.bot: DiscordBot = bot
        self.api: APIClient = bot.api_client
        self.logger: Logger = bot.logger

    async def handle_stream_event(self, event_type: str, data: dict):
        """
        Handle stream state events using API-rendered notifications.
        """
        try:
            streamer_name = data.get("streamer_name", "Unknown")
            streamer_id = data.get("streamer_id")

            if not streamer_id:
                self.logger.warning(f"Notification skipped: No streamer_id in data")
                return

            # Map broker event types to notification types
            event_map = {
                "online": "stream_online",
                "offline": "stream_offline",
                "category_to_gta": "category_to_gta",
                "category_from_gta": "category_from_gta",
                "stream_online": "stream_online",
                "stream_offline": "stream_offline",
            }
            
            notification_type = event_map.get(event_type)
            if not notification_type:
                self.logger.debug(f"No notification mapping for event type: {event_type}")
                return

            self.logger.info(
                f"Notification: Processing {notification_type} for {streamer_name}"
            )

            # Get pre-rendered notification from API
            rendered = await self.api.render_notification(notification_type, streamer_id)
            
            if not rendered:
                self.logger.warning(f"Failed to render notification for {notification_type}")
                # Fallback to legacy behavior
                await self._legacy_notification(event_type, data)
                return

            notification_channel_id = rendered.get("notification_channel_id")
            if not notification_channel_id:
                self.logger.warning("Notification skipped: No channel configured")
                return

            channel = self.bot.get_channel(int(notification_channel_id))
            if not channel:
                self.logger.error(f"Channel {notification_channel_id} not found")
                return

            # Build Discord components from API spec
            from utils import create_notification_component

            # Determine if we should include the embed (container)
            # User request: No embed for stream end and category change
            # But "change category" is ambiguous. "to_gta" is usually treated as "online" for us.
            # Assuming "category_from_gta" and "stream_offline" should NOT have embeds.
            # "category_to_gta" usually HAS embed because it allows claiming.
            # However, if user wants NO embed on category change... maybe even to_gta?
            # Let's assume ONLY stream_online gets the full embed.
            # Wait, category_to_gta IS the "start" event for GTA streamers. It needs the claiming button.
            # The button is separate from the container in our new valid utils logic.
            # So we can show button WITHOUT container? Yes.
            
            # Strict interpretation:
            # stream_online -> Embed = True
            # stream_offline -> Embed = False
            # category_to/from -> Embed = False (User said "change category")
            
            include_embed = notification_type == "stream_online" or notification_type == "category_to_gta"

            spec = rendered.get("component_spec", {})
            components = create_notification_component(
                rendered.get("message", ""),
                spec.get("streamer_name", streamer_name),
                spec.get("stream_title", ""),
                spec.get("game_name", ""),
                spec.get("thumbnail_url", ""),
                streamer_id=spec.get("streamer_id", streamer_id),
                show_claim_button=spec.get("show_claim_button", False),
                assigned_pr_id=spec.get("assigned_pr_id"),
                include_embed=include_embed,
            )

            await channel.send(components=components)
            self.logger.info(f"Notification sent: {notification_type} for {streamer_name}")

        except Exception as e:
            self.logger.error(f"Error handling notification: {e}", exc_info=True)

    async def _legacy_notification(self, event_type: str, data: dict):
        """Fallback legacy notification logic."""
        try:
            from utils import create_notification_component, format_notification_template

            streamer_name = data.get("streamer_name", "Unknown")
            streamer_id = data.get("streamer_id")
            stream_title = data.get("stream_title") or ""
            game_name = data.get("game_name") or ""
            thumbnail_url = data.get("thumbnail_url") or ""

            settings = await self.api.get_guild_settings()
            if not settings:
                return

            notification_channel_id = settings.get("notification_channel_id")
            if not notification_channel_id:
                return

            channel = self.bot.get_channel(int(notification_channel_id))
            if not channel:
                return

            defaults = {
                "stream_online": "**{streamer_name}** начал стрим! Играет в **{game_name}**\n{streamer_link}",
                "stream_offline": "**{streamer_name}** закончил стрим.",
                "category_to_gta": "🎮 **{streamer_name}** переключился на GTA 5!",
                "category_from_gta": "📴 **{streamer_name}** вышел из GTA 5.",
            }

            template = settings.get(f"template_{event_type}") or defaults.get(event_type, "")
            if not template:
                return

            message = format_notification_template(template, streamer_name, stream_title, game_name)

            is_gta = str(data.get("new_game_id") or data.get("game_id")) == Config.gta5_game_id
            show_claim = is_gta and event_type in ["stream_online", "category_to_gta"]

            components = create_notification_component(
                message, streamer_name, stream_title, game_name, thumbnail_url,
                streamer_id=streamer_id, show_claim_button=show_claim
            )

            await channel.send(components=components)
            self.logger.info(f"Legacy notification sent: {event_type} for {streamer_name}")

        except Exception as e:
            self.logger.error(f"Legacy notification error: {e}", exc_info=True)


def setup(bot: commands.Bot) -> None:
    bot.add_cog(Notifications(bot))
