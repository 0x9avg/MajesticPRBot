"""Cog for managing streamers - add, remove, and list."""

import disnake
from disnake import ApplicationCommandInteraction, MessageInteraction, Embed
from disnake.ext import commands

from config import Config
from utils import create_streamers_component


class ManageStreamers(commands.Cog):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.database = bot.database
        self.twitch_bot = bot.twitch_bot

    @commands.slash_command(
        name="add_streamer", description="Add new streamer to the database"
    )
    async def add_streamer(
        self,
        interaction: ApplicationCommandInteraction,
        url: str,
        priority: int = 0,
        is_paid: bool = False,
    ) -> None:

        try:
            await interaction.response.defer(ephemeral=True)

            self.bot.logger.debug(
                f"User {interaction.user} ({interaction.user.id}) adding streamer: {url}"
            )

            if url.startswith("https://www.twitch.tv/"):
                username = url.replace("https://www.twitch.tv/", "").rstrip("/").strip()
            else:
                username = url.rstrip("/").strip()

            self.bot.logger.debug(f"Parsed username: {username}")

            streamer_id = await self.twitch_bot.get_streamer_id(username)
            if streamer_id is None:
                self.bot.logger.warning(f"Streamer {username} not found on Twitch")
                await interaction.followup.send(
                    f"Streamer {username} not found on Twitch."
                )
                return

            await self.twitch_bot.add_notification(streamer_id)

            stream_data = await self.twitch_bot.get_stream_info(streamer_id)

            if not await self.database.streamer_exists(streamer_id):
                self.bot.logger.debug(f"Adding new streamer to database: {username}")
                await self.database.create_streamer(
                    streamer_name=username,
                    streamer_id=streamer_id,
                    is_online=stream_data["is_online"],
                    started_at=stream_data["started_at"],
                    game_id=stream_data["game_id"],
                    game_name=stream_data["game_name"],
                    stream_title=stream_data["title"],
                    stream_thumbnail_url=stream_data["thumbnail_url"],
                    priority=priority,
                    added_by_id=interaction.user.id,
                    is_paid=is_paid,
                )

            await self.database.create_subscription(interaction.guild_id, streamer_id)
            self.bot.logger.debug(
                f"✓ Streamer {username} added for guild {interaction.guild_id}"
            )
            
            # Update monitoring message for this guild
            await self.twitch_bot.update_monitoring_messages(interaction.guild_id)
            
            await interaction.followup.send(
                f"Streamer {username} added to the database."
            )
        except Exception as e:
            self.bot.logger.error(f"Error adding streamer {url}: {e}", exc_info=True)
            await interaction.followup.send(
                f"An error occurred while adding the streamer: {str(e)}", ephemeral=True
            )

    @commands.slash_command(
        name="remove_streamer", description="Remove a streamer from the database"
    )
    async def remove_streamer(
        self, interaction: ApplicationCommandInteraction, url: str
    ) -> None:
        try:
            self.bot.logger.debug(
                f"User {interaction.user} ({interaction.user.id}) removing streamer: {url}"
            )

            if url.startswith("https://www.twitch.tv/"):
                username = url.replace("https://www.twitch.tv/", "").rstrip("/")
            else:
                username = url.rstrip("/")

            streamer_id = await self.twitch_bot.get_streamer_id(username)
            if streamer_id is None:
                await interaction.response.send_message(
                    f"Streamer {username} not found on Twitch."
                )
                return

            if await self.database.subscription_exists(
                interaction.guild_id, streamer_id
            ):
                await interaction.response.defer(ephemeral=False)
                await self.database.delete_subscription(
                    interaction.guild_id, streamer_id
                )
                self.bot.logger.debug(
                    f"✓ Removed subscription to {username} for guild {interaction.guild_id}"
                )
                
                # Update monitoring message for this guild
                await self.twitch_bot.update_monitoring_messages(interaction.guild_id)
                
                await interaction.followup.send(
                    f"Streamer {username} removed from the database."
                )
            else:
                self.bot.logger.warning(
                    f"No subscription found for {username} on guild {interaction.guild_id}"
                )
                await interaction.response.send_message(
                    f"You are not followed to {username}."
                )
                return

            if not await self.database.has_any_subscriptions(streamer_id):
                self.bot.logger.debug(
                    f"Removing streamer {username} from database (no more subscriptions)"
                )
                await self.database.delete_streamer(streamer_id)
                await self.twitch_bot.remove_subscription(streamer_id)

        except Exception as e:
            self.bot.logger.error(f"Error removing streamer {url}: {e}", exc_info=True)
            await interaction.response.send_message(
                f"An error occurred while removing the streamer: {str(e)}",
                ephemeral=True,
            )

    @commands.slash_command(
        name="streamers",
        description="Показать онлайн стримеров на которых подписан сервер",
    )
    async def streamers(self, interaction: ApplicationCommandInteraction) -> None:
        """Display online streamers that the guild is subscribed to."""
        try:
            await interaction.response.defer()
        except disnake.errors.NotFound:
            # Interaction expired before we could respond (3 second timeout)
            self.bot.logger.warning(
                f"Interaction expired for /streamers command from user {interaction.user}"
            )
            return

        try:
            # Get subscribed streamer IDs for this guild
            subscribed_ids = await self.database.list_guild_subscriptions(
                interaction.guild_id
            )

            # Get streamer info and filter only online ones
            online_streamers = []
            gta_count = 0

            for streamer_id in subscribed_ids:
                streamer = await self.database.get_streamer(streamer_id)
                if streamer and streamer.get("is_online"):
                    online_streamers.append(streamer)
                    if str(streamer.get("game_id")) == Config.GTA5_GAME_ID:
                        gta_count += 1

            # Use shared component generator
            container = create_streamers_component(
                online_streamers, len(subscribed_ids), gta_count
            )
            await interaction.followup.send(components=container)

        except Exception as e:
            self.bot.logger.error(f"Error in /streamers command: {e}", exc_info=True)
            try:
                await interaction.followup.send("Произошла ошибка.", ephemeral=True)
            except disnake.errors.NotFound:
                pass  # Interaction already expired, nothing we can do


def setup(bot: commands.Bot) -> None:
    bot.add_cog(ManageStreamers(bot))
