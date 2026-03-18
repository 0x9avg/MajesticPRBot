"""
Notifications Cog.
Handles sending stream status notifications to configured Discord channels.
Uses API render_notification for server-driven UI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from logging import Logger

    from api_client import APIClient
    from discord_bot import DiscordBot



from disnake.ext import commands, tasks

from utils import create_notification_component

class Notifications(commands.Cog):
    """Event notifications system."""

    bot: DiscordBot
    api: APIClient

    def __init__(self, bot: DiscordBot):
        self.bot: DiscordBot = bot
        self.api: APIClient = bot.api_client
        self.logger: Logger = bot.logger
        self.check_event_starts.start()

    def cog_unload(self):
        self.check_event_starts.cancel()

    @tasks.loop(seconds=60)
    async def check_event_starts(self):
        """Check for scheduled events that need to start."""
        try:
            events = await self.api.get_scheduled_events()
            if not events:
                return

            settings = await self.api.get_guild_settings()
            if not settings:
                return

            notification_channel_id = settings.get("notification_channel_id")
            if not notification_channel_id:
                self.logger.warning("Notification skipped: No channel configured")
                return

            channel = self.bot.get_channel(int(notification_channel_id))

            for event in events:
                if channel:
                    participants = event.get("participants", [])
                    if participants:
                        mentions = [f"<@{p['pr_id']}>" for p in participants]
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
                    else:
                        try:
                            await channel.send(
                                f"Событие **{event['name']}** началось!",
                                delete_after=300,
                            )
                        except Exception as e:
                            self.bot.logger.error(
                                f"Event start notification error: {e}"
                            )


                # Start event (migrate reserved participants to active, triggering PR logs)
                try:
                    await self.api.start_event(event["id"])
                except Exception as e:
                    self.bot.logger.error(f"Failed to start event {event['id']}: {e}")

                # Mark as notified
                await self.api.mark_event_notification_sent(event["id"])

        except Exception as e:
            self.bot.logger.error(f"check_event_starts error: {e}", exc_info=True)

    @check_event_starts.before_loop
    async def before_check_event_starts(self):
        await self.bot.wait_until_ready()

    async def handle_stream_event(self, event_type: str, data: dict):
        """
        Handle stream state events using API-rendered notifications.
        """
        try:
            streamer_name = data.get("streamer_name", "Unknown")
            streamer_id = data.get("streamer_id")

            if not streamer_id:
                self.logger.warning("Notification skipped: No streamer_id in data")
                return

            # Map broker event types to notification types
            event_map = {
                "stream_online_gta": "stream_online_gta",
                "stream_online_other": "stream_online_other",
                "offline": "stream_offline",
                "category_to_gta": "category_to_gta",
                "category_from_gta": "category_from_gta",
                "stream_offline": "stream_offline",
            }

            notification_type = event_map.get(event_type)
            if not notification_type:
                self.logger.debug(
                    f"No notification mapping for event type: {event_type}"
                )
                return

            self.logger.info(
                f"Notification: Processing {notification_type} for {streamer_name}"
            )

            # Get pre-rendered notification from API
            rendered = await self.api.render_notification(
                notification_type, streamer_id
            )

            if not rendered:
                self.logger.error(
                    f"Failed to render notification for {notification_type} — API unavailable"
                )
                return

            notification_channel_id = rendered.get("notification_channel_id")
            if not notification_channel_id:
                self.logger.warning("Notification skipped: No channel configured")
                return

            channel = self.bot.get_channel(int(notification_channel_id))
            if not channel:
                self.logger.error(f"Channel {notification_channel_id} not found")
                return

            include_embed = (
                notification_type == "stream_online_gta"
                or notification_type == "category_to_gta"
            )

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
            self.logger.info(
                f"Notification sent: {notification_type} for {streamer_name}"
            )

        except Exception as e:
            self.logger.error(f"Error handling notification: {e}", exc_info=True)


def setup(bot: commands.Bot) -> None:
    bot.add_cog(Notifications(bot))
