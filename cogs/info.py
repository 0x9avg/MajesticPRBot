"""Ког для информационных команд бота."""

import disnake
from disnake import ApplicationCommandInteraction, Embed
from disnake.ext import commands

from config import Config


class Info(commands.Cog):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.slash_command(name="info", description="Показать информацию о версии/сборке")
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def info(self, interaction: ApplicationCommandInteraction) -> None:
        """Отображение информации о версии бота и разработчике."""
        try:
            embed = Embed(
                title=f"Информация о {self.bot.user.name}",
                color=disnake.Colour.red(),
                description=f"**Version:** {Config.VERSION}\n**Developer:** 9avg",
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            self.bot.logger.error(f"Error in /info command: {e}", exc_info=True)
            try:
                await interaction.response.send_message(
                    "Произошла ошибка при получении информации.",
                    ephemeral=True,
                )
            except disnake.errors.InteractionResponded:
                pass  # Already responded


def setup(bot: commands.Bot) -> None:
    bot.add_cog(Info(bot))
