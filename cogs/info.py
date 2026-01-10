import disnake
from disnake import ApplicationCommandInteraction, MessageInteraction, Embed
from disnake.ext import commands


class Info(commands.Cog):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.slash_command(name="info", description="Shows build/version information")
    async def info(self, interaction: ApplicationCommandInteraction) -> None:
        embed = Embed(
            title=f"Информация о {self.bot.user.name}",
            color=disnake.Colour.red(),
            description=f"Version: TEST BUILD\nDeveloper: 9avg",
        )
        await interaction.response.send_message(embed=embed)


def setup(bot: commands.Bot) -> None:
    bot.add_cog(Info(bot))
