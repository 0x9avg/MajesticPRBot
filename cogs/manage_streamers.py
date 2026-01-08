import discord
from discord import app_commands
from discord.ext import commands


class ManageStreamers(commands.Cog):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.database = bot.database
        self.twitch_bot = bot.twitch_bot

    @app_commands.command(
        name="add_streamer", description="Add new streamer to the database"
    )
    async def add_streamer(
        self,
        interaction: discord.Interaction,
        url: str,
        priority: int = 0,
        is_paid: bool = False,
    ) -> None:

        await interaction.response.defer(ephemeral=True)

        if url.startswith("https://www.twitch.tv/"):
            username = url.replace("https://www.twitch.tv/", "").rstrip("/").strip()
        else:
            username = url.rstrip("/").strip()

        streamer_id = await self.twitch_bot.get_streamer_id(username)
        if streamer_id is None:
            await interaction.followup.send(f"Streamer {username} not found on Twitch.")
            return

        await self.twitch_bot.add_notification(streamer_id)

        stream_data = await self.twitch_bot.get_stream_info(streamer_id)

        await self.database.add_streamer_to_db(
            streamer_name=username,
            streamer_id=streamer_id,
            is_online=stream_data["is_online"],
            started_at=stream_data["started_at"],
            game_id=stream_data["game_id"],
            game_name=stream_data["game_name"],
            title=stream_data["title"],
            priority=priority,
            added_by_id=interaction.user.id,
            is_paid=is_paid,
        )

        await interaction.followup.send(f"Streamer {username} added to the database.")

    @app_commands.command(
        name="remove_streamer", description="Remove a streamer from the database"
    )
    async def remove_streamer(self, interaction: discord.Interaction, url: str) -> None:
        if url.startswith("https://www.twitch.tv/"):
            username = url.replace("https://www.twitch.tv/", "").rstrip("/")
        else:
            username = url.rstrip("/")

        if await self.database.isStreamerInDB(username):
            await self.database.remove_streamer_from_db(username)
            await interaction.response.defer(ephemeral=False)
            await self.twitch_bot.sync_subscriptions()
            await interaction.followup.send(
                f"Streamer {username} removed from the database."
            )
        else:
            await interaction.response.send_message(
                f"Streamer {username} not found in the database."
            )

    @app_commands.command(
        name="streamers_online", description="List all online streamers"
    )
    async def streamers_online(self, interaction: discord.Interaction) -> None:
        result = await self.twitch_bot.print_channels_status()
        await interaction.response.send_message(result)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ManageStreamers(bot))
