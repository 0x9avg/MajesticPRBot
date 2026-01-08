import discord
from discord import app_commands
from discord.ext import commands


class Info(commands.Cog):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="info", description="Shows build/version information")
    async def info(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title=f"Информация о {self.bot.user.name}",
            color=discord.Colour.red(),
            description=f"Version: TEST BUILD\nDeveloper: 9avg",
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Info(bot))
