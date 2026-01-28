"""Ког для управления стримерами.
Ported from Legacy to Microservices (API-based).
"""

import disnake
from disnake import ApplicationCommandInteraction
from disnake.ext import commands
from typing import Optional

from config import Config
from utils import create_streamers_component


class ManageStreamers(commands.Cog):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.api = bot.api_client

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
    ) -> None:

        try:
            await interaction.response.defer(ephemeral=True)

            self.bot.logger.debug(
                f"User {interaction.user} ({interaction.user.id}) adding streamer: {url}"
            )

            # Basic URL parsing logic from legacy
            if url.startswith("https://www.twitch.tv/"):
                username = url.replace("https://www.twitch.tv/", "").rstrip("/").strip()
            else:
                username = url.rstrip("/").strip()

            self.bot.logger.debug(f"Parsed username: {username}")

            # API Call
            # Note: Validation of Twitch existence happens asynchronously in this new architecture
            # unless API service implements it synchronously.
            result = await self.api.add_streamer(
                twitch_url=username, priority=priority, added_by_id=interaction.user.id
            )

            if result:
                if result.get("status") == "pending_verification":
                    await interaction.followup.send(
                        f"⏳ Запрос на добавление стримера **{username}** принят.\n"
                        "Бот проверяет существование канала...",
                        ephemeral=True,
                    )
                elif "error" not in result:
                    await interaction.followup.send(
                        f"✅ Стример **{username}** добавлен.", ephemeral=True
                    )
                else:
                    error_msg = result.get("detail", "Unknown error")
                    await interaction.followup.send(
                        f"❌ Ошибка при добавлении: {error_msg}", ephemeral=True
                    )
            else:
                await interaction.followup.send(f"❌ Ошибка API.", ephemeral=True)

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
            return

        try:
            # Parse username to be safe, though this command takes URL usually
            username = url
            if url.startswith("https://www.twitch.tv/"):
                username = url.replace("https://www.twitch.tv/", "").rstrip("/")
            else:
                username = url.rstrip("/")

            # Need ID to delete via API.
            # First, search for streamer by name?
            # API endpoint delete_streamer takes ID.
            # We need a way to get ID from name.
            # List all and find? Inefficient but works for small lists.
            streamers = await self.api.list_all_streamers()
            target_id = None
            for s in streamers:
                if s["streamer_name"].lower() == username.lower():
                    target_id = s["streamer_id"]
                    break

            if target_id:
                success = await self.api.delete_streamer(target_id)
                if success:
                    await interaction.followup.send(
                        f"✅ Стример **{username}** удален из базы.", ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        f"❌ Не удалось удалить стримера (API Error).", ephemeral=True
                    )
            else:
                await interaction.followup.send(
                    f"❌ Стример **{username}** не найден в базе.", ephemeral=True
                )

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
            return

        try:
            # Get all streamers from API
            streamers = await self.api.list_all_streamers()

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
                pass


def setup(bot: commands.Bot) -> None:
    bot.add_cog(ManageStreamers(bot))
