"""Cog for server settings management."""

import disnake
from disnake import ApplicationCommandInteraction, MessageInteraction, Embed
from disnake.ext import commands


def create_settings_embed(data):
    embed = disnake.Embed(title="⚙️ Настройки сервера", colour=0xC9A6F6)

    embed.add_field(
        name=f"🔔 Канал для уведомлений",
        value=(
            f"<#{data['notification_channel_id']}>"
            if data["notification_channel_id"]
            else "– Канал не выбран."
        ),
        inline=False,
    )

    return embed


class Settings(commands.Cog):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.database = bot.database
        self.twitch_bot = bot.twitch_bot

    @commands.slash_command(
        name="settings", description="View the current server settings"
    )
    async def settings(self, interaction: ApplicationCommandInteraction) -> None:
        if not interaction.author.guild_permissions.administrator:
            self.bot.logger.warning(f"User {interaction.user} tried to access settings without admin permissions")
            await interaction.response.send_message(
                "🚫 У вас нет прав администратора.",
                ephemeral=True,
            )
            return

        try:
            self.bot.logger.debug(f"User {interaction.user} ({interaction.user.id}) viewing settings for guild {interaction.guild.id}")
            await interaction.response.defer()
            data = await self.database.get_guild(interaction.guild.id)
            embed = create_settings_embed(data)
            await interaction.followup.send(
                embed=embed, view=SettingsButton(interaction.user.id), ephemeral=True
            )
        except Exception as e:
            self.bot.logger.error(f"Error displaying settings: {e}", exc_info=True)
            await interaction.followup.send("An error occurred while loading settings.", ephemeral=True)


class NotificationChannelSelect(disnake.ui.ChannelSelect):
    def __init__(self, guild: disnake.Guild):
        super().__init__(
            channel_types=[disnake.ChannelType.text],
            placeholder="Выберите канал для уведомлений",
            min_values=1,
            max_values=1,
        )
        self.guild = guild

    async def callback(self, interaction: disnake.MessageInteraction):
        selected_channel: disnake.TextChannel = self.values[0]

        if not selected_channel:
            await interaction.response.send_message(
                "🚫 Канал не найден.",
                ephemeral=True,
            )
            return

        try:
            interaction.bot.logger.debug(f"Setting notification channel to {selected_channel.id} for guild {interaction.guild.id}")
            await interaction.bot.database.create_or_update_guild(
                guild_id=interaction.guild.id, channel_id=selected_channel.id
            )
            interaction.bot.channel_id = selected_channel.id
            interaction.bot.channel = interaction.bot.get_channel(selected_channel.id)

            await interaction.response.edit_message(
                embed=create_settings_embed(
                    await interaction.bot.database.get_guild(interaction.guild.id),
                ),
                view=SettingsButton(interaction.user.id),
            )
            await interaction.followup.send(
                "✅ Канал {channel} выбран для уведомлений о запуске стримеров.".format(
                    channel=selected_channel.mention
                ),
                ephemeral=True,
            )
            interaction.bot.logger.debug(f"✓ Notification channel updated successfully for guild {interaction.guild.id}")
        except Exception as e:
            interaction.bot.logger.error(f"Error updating notification channel: {e}", exc_info=True)
            await interaction.followup.send("An error occurred while updating the settings.", ephemeral=True)


class NotificationChannelView(disnake.ui.View):
    def __init__(self, guild: disnake.Guild, user_id: int):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.guild = guild

        # Селектор каналов
        self.add_item(NotificationChannelSelect(guild))


class SettingsButton(disnake.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=95)
        self.user_id = user_id

    @disnake.ui.button(
        label="📃 Изменить канал",
        style=disnake.ButtonStyle.secondary,
        row=1,
        custom_id="edit_notification_channel",
    )
    async def edit_notification_channel(
        self, button: disnake.ui.Button, inter: disnake.MessageInteraction
    ):
        await inter.response.edit_message(
            view=NotificationChannelView(inter.guild, self.user_id)
        )


def setup(bot: commands.Bot) -> None:
    bot.add_cog(Settings(bot))
