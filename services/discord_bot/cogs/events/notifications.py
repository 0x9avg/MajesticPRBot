"""
Notifications Cog.
Handles sending stream status notifications to configured Discord channels.
"""

import disnake
from disnake.ext import commands
import logging
from string import Template
from config import Config

class Notifications(commands.Cog):
    """Event notifications system."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.api = bot.api_client
        self.logger = bot.logger

    async def handle_stream_event(self, event_type: str, data: dict):
        """
        Handle stream state events with robust legacy logic.
        """
        try:
            guild_id = data.get("guild_id")
            streamer_name = data.get("streamer_name", "Unknown")
            streamer_id = data.get("streamer_id")
            
            # Fetch Settings
            settings = await self.api.get_guild_settings()
            if not settings:
                self.logger.warning("Notification skipped: No guild settings found")
                return

            notification_channel_id = settings.get("notification_channel_id")
            
            self.logger.info(f"DEBUG Notification: Processing {event_type} for {streamer_name} | Channel: {notification_channel_id}")

            # Prepare common variables
            stream_title = data.get("stream_title") or ""
            game_name = data.get("game_name") or ""
            thumbnail_url = data.get("thumbnail_url") or ""
            
            # Helper to send notification
            async def send_notification(evt_type, components=None):
                if not notification_channel_id: 
                    self.logger.warning(f"Notification skipped: No channel set for {evt_type}")
                    return
                
                channel = self.bot.get_channel(int(notification_channel_id))
                if not channel: 
                    self.logger.error(f"Notification failed: Channel {notification_channel_id} not found")
                    return
                
                # Correctly fetch template from flat settings dict
                template = settings.get(f"template_{evt_type}")
                
                # Fallback templates
                if not template:
                    self.logger.debug(f"Using default template for {evt_type}")
                    defaults = {
                        "stream_online": "**{streamer_name}** is now live! Playing **{game_name}**\n{streamer_link}",
                        "stream_offline": "**{streamer_name}** went offline.",
                        "category_to_gta": "**{streamer_name}** switched to GTA 5!",
                        "category_from_gta": "**{streamer_name}** left GTA 5."
                    }
                    template = defaults.get(evt_type, "")

                if not template: 
                    self.logger.warning(f"Notification skipped: No template for {evt_type}")
                    return

                # Use utils formatter
                from utils import format_notification_template, create_notification_component
                message = format_notification_template(
                    template, streamer_name, stream_title, game_name
                )
                
                # If components not passed, create generic ones (without buttons)
                if components is None:
                    # Logic to decide if claim button needed
                    # Only for online/to_gta AND if game is GTA 5
                    is_gta = str(data.get("new_game_id") or data.get("game_id")) == Config.gta5_game_id
                    show_claim = is_gta and (evt_type in ["stream_online", "category_to_gta"])
                    
                    components = create_notification_component(
                        message, streamer_name, stream_title, game_name, thumbnail_url,
                        streamer_id=streamer_id,
                        show_claim_button=show_claim
                    )

                await channel.send(components=components)
                self.logger.info(f"Notification sent: {evt_type} for {streamer_name}")

            # Handle Event Types
            if event_type == "stream_online":
                await send_notification("stream_online")

            elif event_type == "stream_offline":
                await send_notification("stream_offline")


            elif event_type == "category_to_gta":
                # Ensure we show claim button
                # Re-use send_notification logic which adds button if is_gta
                await send_notification("category_to_gta")

            elif event_type == "category_from_gta":
                await send_notification("category_from_gta")

            
            elif event_type == "category_change":
                # Generic log? Or ignore if neither to/from GTA?
                # Legacy didn't notify generic changes, only GTA specific.
                pass

        except Exception as e:
            self.logger.error(f"Error handling notification: {e}", exc_info=True)

def setup(bot: commands.Bot) -> None:
    bot.add_cog(Notifications(bot))
