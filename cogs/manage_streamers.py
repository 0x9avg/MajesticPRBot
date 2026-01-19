"""Ког для управления стримерами - добавление, удаление и список."""

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
        name="add_streamer", description="Добавить нового стримера в базу данных"
    )
    @commands.has_permissions(administrator=True)
    @commands.cooldown(1, 10, commands.BucketType.user)
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
                    f"Streamer {username} not found on Twitch.", ephemeral=True
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

            self.bot.logger.debug(
                f"✓ Streamer {username} added"
            )

            # Update monitoring message
            await self.twitch_bot.update_monitoring_messages()

            await interaction.followup.send(
                f"Streamer {username} added to the database.", ephemeral=True
            )
        except Exception as e:
            self.bot.logger.error(f"Error adding streamer {url}: {e}", exc_info=True)
            await interaction.followup.send(
                f"An error occurred while adding the streamer: {str(e)}", ephemeral=True
            )

    @commands.slash_command(
        name="remove_streamer", description="Удалить стримера из базы данных"
    )
    @commands.has_permissions(administrator=True)
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def remove_streamer(
        self, interaction: ApplicationCommandInteraction, url: str
    ) -> None:
        try:
            await interaction.response.defer()
        except disnake.errors.NotFound:
            # Interaction expired before we could respond (3 second timeout)
            self.bot.logger.warning(
                f"Interaction expired for /streamers command from user {interaction.user}"
            )
            return
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
                await interaction.followup.send(
                    f"Streamer {username} not found on Twitch.", ephemeral=True
                )
                return

            # Check if streamer exists and delete
            if await self.database.streamer_exists(streamer_id):
                await self.database.delete_streamer(streamer_id)
                await self.twitch_bot.remove_subscription(streamer_id)
                self.bot.logger.debug(
                    f"✓ Removed streamer {username}"
                )

                # Update monitoring message
                await self.twitch_bot.update_monitoring_messages()

                await interaction.followup.send(
                    f"Streamer {username} removed from the database.", ephemeral=True
                )
            else:
                self.bot.logger.warning(
                    f"Streamer {username} not found in database"
                )
                await interaction.followup.send(
                    f"Streamer {username} not found in database.", ephemeral=True
                )
                return

        except Exception as e:
            self.bot.logger.error(f"Error removing streamer {url}: {e}", exc_info=True)
            await interaction.followup.send(
                f"An error occurred while removing the streamer: {str(e)}",
                ephemeral=True,
            )

    @commands.slash_command(
        name="streamers",
        description="Показать онлайн стримеров на которых подписан сервер",
    )
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def streamers(self, interaction: ApplicationCommandInteraction) -> None:
        """Отображение онлайн стримеров, на которых подписан сервер."""
        try:
            await interaction.response.defer()
        except disnake.errors.NotFound:
            # Interaction expired before we could respond (3 second timeout)
            self.bot.logger.warning(
                f"Interaction expired for /streamers command from user {interaction.user}"
            )
            return

        try:
            # Get all streamers
            streamers = await self.database.list_all_streamers()

            # Filter only online ones
            online_streamers = []
            gta_count = 0

            for streamer in streamers:
                if streamer.get("is_online"):
                    online_streamers.append(streamer)
                    if str(streamer.get("game_id")) == Config.GTA5_GAME_ID:
                        gta_count += 1

            # Use shared component generator
            container = create_streamers_component(
                online_streamers, len(streamers), gta_count
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
