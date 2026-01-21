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
                return

            notification_channel_id = settings.get("notification_channel_id")
            pr_actions_channel_id = settings.get("pr_actions_channel_id")
            templates = settings.get("templates", {})

            # Prepare common variables
            stream_title = data.get("stream_title") or ""
            game_name = data.get("game_name") or ""
            thumbnail_url = data.get("thumbnail_url") or ""
            
            # Helper to send notification
            async def send_notification(evt_type, components=None):
                if not notification_channel_id: return
                channel = self.bot.get_channel(notification_channel_id)
                if not channel: return
                
                template = templates.get(evt_type)
                # Fallback templates
                if not template:
                    defaults = {
                        "stream_online": "**{streamer_name}** is now live! Playing **{game_name}**\n{streamer_link}",
                        "stream_offline": "**{streamer_name}** went offline.",
                        "category_to_gta": "**{streamer_name}** switched to GTA 5!",
                        "category_from_gta": "**{streamer_name}** left GTA 5."
                    }
                    template = defaults.get(evt_type, "")

                if not template: return

                # Use utils formatter
                from utils import format_notification_template, create_notification_component
                message = format_notification_template(
                    template, streamer_name, stream_title, game_name
                )
                
                # If components not passed, create generic ones (without buttons)
                if components is None:
                    # Logic to decide if claim button needed
                    # Only for online/to_gta AND if game is GTA 5
                    is_gta = str(data.get("new_game_id") or data.get("game_id")) == Config.GTA5_GAME_ID
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
                
                # Unassign PR and Log
                if streamer_id:
                    # Check if assigned before unclaiming to avoid 400 error
                    streamer = await self.api.get_streamer(streamer_id)
                    if streamer and streamer.get("assigned_pr_id"):
                        result = await self.api.unclaim_streamer(streamer_id, reason="stream_end")
                        if result and result.get("unclaimed"):
                            # Log to PR Actions
                            if pr_actions_channel_id:
                                pr_channel = self.bot.get_channel(pr_actions_channel_id)
                                if pr_channel:
                                    from utils import format_spec_duration
                                    duration_str = format_spec_duration(result.get("duration_seconds", 0))
                                    await pr_channel.send(
                                        f"⚫ **Стрим завершен**\n"
                                        f"👤 Стример: **{streamer_name}**\n"
                                        f"🎯 PR: <@{result.get('pr_id')}>\n"
                                        f"⏱️ Спек: **{duration_str}**"
                                    )

            elif event_type == "category_to_gta":
                # Ensure we show claim button
                # Re-use send_notification logic which adds button if is_gta
                await send_notification("category_to_gta")

            elif event_type == "category_from_gta":
                # Notify
                await send_notification("category_from_gta")
                
                # Unassign PR and Log
                if streamer_id:
                    # Check if assigned before unclaiming
                    streamer = await self.api.get_streamer(streamer_id)
                    if streamer and streamer.get("assigned_pr_id"):
                        result = await self.api.unclaim_streamer(streamer_id, reason="stream_end") # category change treats as stream end for spec session
                        if result and result.get("unclaimed"):
                            if pr_actions_channel_id:
                                pr_channel = self.bot.get_channel(pr_actions_channel_id)
                                if pr_channel:
                                    from utils import format_spec_duration
                                    duration_str = format_spec_duration(result.get("duration_seconds", 0))
                                    await pr_channel.send(
                                        f"🔄 **Смена категории (выход из GTA)**\n"
                                        f"👤 Стример: **{streamer_name}**\n"
                                        f"🎯 PR: <@{result.get('pr_id')}>\n"
                                        f"⏱️ Спек: **{duration_str}**"
                                    )
            
            elif event_type == "category_change":
                # Generic log? Or ignore if neither to/from GTA?
                # Legacy didn't notify generic changes, only GTA specific.
                pass

        except Exception as e:
            self.logger.error(f"Error handling notification: {e}", exc_info=True)

def setup(bot: commands.Bot) -> None:
    bot.add_cog(Notifications(bot))
