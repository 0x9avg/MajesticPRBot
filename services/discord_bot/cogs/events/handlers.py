"""Events Handlers - Event Join/Leave Buttons.
Handles event_join_{id} button clicks and updates event messages.
"""

import disnake
from disnake import MessageInteraction
from disnake.ext import commands

from utils import format_spec_duration, send_pr_action_log


class EventsHandlers(commands.Cog):
    """Event button handlers for join/leave."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.api = bot.api_client

    async def _update_event_message(self, event_id: int):
        """Update event message embed with current participant count."""
        try:
            event = await self.api.get_event(event_id)
            if not event:
                return

            channel_id = event.get("channel_id")
            message_id = event.get("message_id")
            
            if not channel_id or not message_id:
                return

            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                return

            try:
                msg = await channel.fetch_message(int(message_id))
            except disnake.NotFound:
                return

            if not msg.embeds:
                return

            embed = msg.embeds[0]
            current_count = event.get("current_participants", 0)
            required = event.get("required_pr_count", "?")

            # Update description with new count
            desc_lines = embed.description.split("\n") if embed.description else []
            new_lines = []
            for line in desc_lines:
                if line.startswith("**Участников:**"):
                    line = f"**Участников:** {current_count}"
                new_lines.append(line)
            
            # If no participants line found, add it
            if not any(l.startswith("**Участников:**") for l in new_lines):
                new_lines.append(f"**Участников:** {current_count}")

            embed.description = "\n".join(new_lines)

            # Update button style based on capacity
            components = msg.components
            if current_count >= int(required) if str(required).isdigit() else False:
                # Event is full - disable button
                embed.color = disnake.Color.green()
            
            await msg.edit(embed=embed)

        except Exception as e:
            self.bot.logger.error(f"Update event message error: {e}")

    async def _send_pr_action(self, guild_id: int, message: str):
        """Send message to PR actions log channel."""

        await send_pr_action_log(self.bot, message)

    @commands.Cog.listener("on_button_click")
    async def on_event_button(self, interaction: MessageInteraction):
        """Handle event join/leave buttons."""
        custom_id = interaction.component.custom_id or ""
        
        # 1. STRICT FILTER
        if not custom_id.startswith(("event_join_", "event_leave_")):
            return

        # 2. SAFE DEFER
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except Exception as e:
            self.bot.logger.warning(f"Failed to defer {custom_id}: {e}")

        # 3. EXECUTE
        try:
            if custom_id.startswith("event_join_"):
                event_id = int(custom_id.replace("event_join_", ""))
                await self._handle_event_join(interaction, event_id)
            elif custom_id.startswith("event_leave_"):
                event_id = int(custom_id.replace("event_leave_", ""))
                await self._handle_event_leave(interaction, event_id)
        except Exception as e:
            self.bot.logger.error(f"Error handling event button {custom_id}: {e}", exc_info=True)
            try:
                await interaction.followup.send("❌ Произошла ошибка обработки.", ephemeral=True)
            except: pass

    async def _handle_event_join(self, interaction: MessageInteraction, event_id: int):
        """Handle user joining an event."""
        user_id = interaction.user.id

        try:
            # Check if already joined
            result = await self.api.join_event(event_id, user_id)
            
            if result.get("already_joined"):
                # Already in event - offer to leave
                leave_btn = disnake.ui.Button(
                    label="Покинуть событие",
                    custom_id=f"event_leave_{event_id}",
                    style=disnake.ButtonStyle.danger,
                    emoji="🚪",
                )
                view = disnake.ui.View(timeout=None)
                view.add_item(leave_btn)
                await interaction.followup.send(
                    "ℹ️ Вы уже участвуете в этом событии.", view=view, ephemeral=True
                )
                return

            if result.get("error"):
                await interaction.followup.send(f"❌ {result['error']}", ephemeral=True)
                return

            await interaction.followup.send("✅ Вы присоединились к событию!", ephemeral=True)

            # Update event message
            await self._update_event_message(event_id)

            # Log to PR actions
            event = await self.api.get_event(event_id)
            if event:
                await self._send_pr_action(
                    interaction.guild_id,
                    f"📥 **Присоединение к событию**\n"
                    f"📅 Событие: **{event.get('name')}**\n"
                    f"🎯 PR: <@{user_id}>"
                )

        except Exception as e:
            self.bot.logger.error(f"Event join error: {e}")
            await interaction.followup.send("❌ Ошибка", ephemeral=True)

    async def _handle_event_leave(self, interaction: MessageInteraction, event_id: int):
        """Handle user leaving an event."""
        user_id = interaction.user.id

        try:
            result = await self.api.leave_event(event_id, user_id)
            
            if result.get("error"):
                await interaction.followup.send(f"❌ {result['error']}", ephemeral=True)
                return

            duration = result.get("duration", 0)
            duration_str = format_spec_duration(duration) if duration else "0м"

            await interaction.followup.send(
                f"✅ Вы покинули событие. Время: **{duration_str}**", ephemeral=True
            )

            # Update event message
            await self._update_event_message(event_id)

            # Log to PR actions
            event = await self.api.get_event(event_id)
            if event:
                await self._send_pr_action(
                    interaction.guild_id,
                    f"📤 **Выход из события**\n"
                    f"📅 Событие: **{event.get('name')}**\n"
                    f"🎯 PR: <@{user_id}>\n"
                    f"⏱️ Время: **{duration_str}**"
                )

        except Exception as e:
            self.bot.logger.error(f"Event leave error: {e}")
            await interaction.followup.send("❌ Ошибка", ephemeral=True)


def setup(bot: commands.Bot) -> None:
    bot.add_cog(EventsHandlers(bot))
