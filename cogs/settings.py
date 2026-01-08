import discord
from discord import app_commands
from discord.ext import commands
import utils


class Settings(commands.Cog):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.database = bot.database
        self.twitch_bot = bot.twitch_bot

    @app_commands.command(name="setup", description="Setup notification channel")
    async def setup(self, interaction: discord.Interaction) -> None:
        await self.database.setup_guild(interaction.guild.id, interaction.channel.id)
        self.bot.channel_id = interaction.channel.id
        self.bot.channel = self.bot.get_channel(self.bot.channel_id)
        await interaction.response.send_message(
            "Notification channel set up successfully."
        )
        streamers = await self.database.get_online_streamers_from_db()
        embeds = utils.generate_streamer_embeds(streamers, chunk_size=15)

        await self.bot.channel.send(embeds=embeds)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Settings(bot))
