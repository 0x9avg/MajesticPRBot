"""Cog for server settings management."""

import disnake
from disnake import ApplicationCommandInteraction, MessageInteraction, Embed
from disnake.ext import commands
from utils import create_streamers_component
from config import Config


def create_settings_embed(data):
    embed = disnake.Embed(title="⚙️ Настройки сервера", colour=0xC9A6F6)

    # Handle case when data is None (guild has no settings yet)
    if data is None:
        data = {
            "notification_channel_id": None,
            "monitoring_channel_id": None,
        }

    embed.add_field(
        name="🔔 Канал для уведомлений",
        value=(
            f"<#{data['notification_channel_id']}>"
            if data.get("notification_channel_id")
            else "– Канал не выбран."
        ),
        inline=False,
    )

    embed.add_field(
        name="📊 Канал для мониторинга",
        value=(
            f"<#{data['monitoring_channel_id']}>"
            if data.get("monitoring_channel_id")
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
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def settings(self, interaction: ApplicationCommandInteraction) -> None:
        if not interaction.author.guild_permissions.administrator:
            self.bot.logger.warning(
                f"User {interaction.user} tried to access settings without admin permissions"
            )
            await interaction.response.send_message(
                "🚫 У вас нет прав администратора.",
                ephemeral=True,
            )
            return

        try:
            self.bot.logger.debug(
                f"User {interaction.user} ({interaction.user.id}) viewing settings for guild {interaction.guild.id}"
            )
            await interaction.response.defer()
            data = await self.database.get_guild(interaction.guild.id)
            embed = create_settings_embed(data)
            await interaction.followup.send(
                embed=embed, view=SettingsButton(interaction.user.id), ephemeral=True
            )
        except Exception as e:
            self.bot.logger.error(f"Error displaying settings: {e}", exc_info=True)
            await interaction.followup.send(
                "An error occurred while loading settings.", ephemeral=True
            )


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
            interaction.bot.logger.debug(
                f"Setting notification channel to {selected_channel.id} for guild {interaction.guild.id}"
            )
            await interaction.bot.database.create_or_update_guild(
                guild_id=interaction.guild.id,
                notification_channel_id=selected_channel.id,
            )

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
            interaction.bot.logger.debug(
                f"✓ Notification channel updated successfully for guild {interaction.guild.id}"
            )
        except Exception as e:
            interaction.bot.logger.error(
                f"Error updating notification channel: {e}", exc_info=True
            )
            await interaction.followup.send(
                "An error occurred while updating the settings.", ephemeral=True
            )


class NotificationChannelView(disnake.ui.View):
    def __init__(self, guild: disnake.Guild, user_id: int, database):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.guild = guild
        self.database = database

        # Селектор каналов
        self.add_item(NotificationChannelSelect(guild))

    @disnake.ui.button(
        label="🔙 Назад",
        style=disnake.ButtonStyle.secondary,
        row=1,
        custom_id="back_to_settings_notification",
    )
    async def back_to_settings(
        self, button: disnake.ui.Button, inter: disnake.MessageInteraction
    ):
        data = await self.database.get_guild(inter.guild_id)
        embed = create_settings_embed(data)
        await inter.response.edit_message(
            embed=embed, view=SettingsButton(self.user_id)
        )


class MonitoringChannelSelect(disnake.ui.ChannelSelect):
    def __init__(self, guild: disnake.Guild):
        super().__init__(
            channel_types=[disnake.ChannelType.text],
            placeholder="Выберите канал для мониторинга",
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
            interaction.bot.logger.debug(
                f"Setting monitoring channel to {selected_channel.id} for guild {interaction.guild.id}"
            )

            # Get existing guild settings to check for old monitoring message
            old_settings = await interaction.bot.database.get_guild(
                interaction.guild.id
            )

            # Delete old monitoring message if exists
            if old_settings and old_settings.get("monitoring_message_id"):
                old_channel_id = old_settings.get("monitoring_channel_id")
                if old_channel_id:
                    old_channel = interaction.bot.get_channel(old_channel_id)
                    if old_channel:
                        try:
                            old_message = await old_channel.fetch_message(
                                old_settings["monitoring_message_id"]
                            )
                            await old_message.delete()
                            interaction.bot.logger.debug(
                                f"Deleted old monitoring message {old_settings['monitoring_message_id']}"
                            )
                        except Exception:
                            pass  # Old message might already be deleted

            # Get streamer data for this guild
            subscribed_ids = await interaction.bot.database.list_guild_subscriptions(
                interaction.guild.id
            )

            online_streamers = []
            gta_count = 0

            for streamer_id in subscribed_ids:
                streamer = await interaction.bot.database.get_streamer(streamer_id)
                if streamer and streamer.get("is_online"):
                    online_streamers.append(streamer)
                    if str(streamer.get("game_id")) == Config.GTA5_GAME_ID:
                        gta_count += 1

            # Create monitoring container
            container = create_streamers_component(
                online_streamers, len(subscribed_ids), gta_count
            )

            # Send monitoring message to selected channel
            monitoring_message = await selected_channel.send(components=container)

            # Save channel ID and message ID to database
            await interaction.bot.database.create_or_update_guild(
                guild_id=interaction.guild.id,
                monitoring_channel_id=selected_channel.id,
                monitoring_message_id=monitoring_message.id,
            )

            await interaction.response.edit_message(
                embed=create_settings_embed(
                    await interaction.bot.database.get_guild(interaction.guild.id),
                ),
                view=SettingsButton(interaction.user.id),
            )

            await interaction.followup.send(
                "✅ Канал {channel} выбран для мониторинга. Сообщение мониторинга создано.".format(
                    channel=selected_channel.mention
                ),
                ephemeral=True,
            )
            interaction.bot.logger.debug(
                f"✓ Monitoring channel updated successfully for guild {interaction.guild.id}, message ID: {monitoring_message.id}"
            )
        except Exception as e:
            interaction.bot.logger.error(
                f"Error updating monitoring channel: {e}", exc_info=True
            )
            await interaction.followup.send(
                "An error occurred while updating the settings.", ephemeral=True
            )


class MonitoringChannelView(disnake.ui.View):
    def __init__(self, guild: disnake.Guild, user_id: int, database):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.guild = guild
        self.database = database

        # Селектор каналов
        self.add_item(MonitoringChannelSelect(guild))

    @disnake.ui.button(
        label="🔙 Назад",
        style=disnake.ButtonStyle.secondary,
        row=1,
        custom_id="back_to_settings_monitoring",
    )
    async def back_to_settings(
        self, button: disnake.ui.Button, inter: disnake.MessageInteraction
    ):
        data = await self.database.get_guild(inter.guild_id)
        embed = create_settings_embed(data)
        await inter.response.edit_message(
            embed=embed, view=SettingsButton(self.user_id)
        )


# =============================================================================
# Notification Templates Settings
# =============================================================================


class NotificationTemplateModal(disnake.ui.Modal):
    def __init__(self, event_type: str, current_template: str, database):
        self.event_type = event_type
        self.database = database
        label = Config.EVENT_TYPE_LABELS.get(event_type, event_type)

        super().__init__(
            title=f"Редактировать: {label}",
            custom_id=f"edit_template_{event_type}",
            components=[
                disnake.ui.TextInput(
                    label="Шаблон ({streamer_name}, {game_name}, {stream_title}, {streamer_link})",
                    placeholder="Введите текст уведомления",
                    custom_id="template_input",
                    style=disnake.TextInputStyle.paragraph,
                    value=current_template,
                    required=True,
                    max_length=500,
                ),
            ],
        )

    async def callback(self, interaction: disnake.ModalInteraction):
        new_template = interaction.text_values["template_input"]

        await self.database.update_notification_template(
            interaction.guild_id,
            self.event_type,
            new_template,
        )

        await interaction.response.send_message(
            f"✅ Шаблон для **{Config.EVENT_TYPE_LABELS.get(self.event_type)}** обновлён!",
            ephemeral=True,
        )


class NotificationTemplateSelect(disnake.ui.StringSelect):
    def __init__(self, database):
        self.database = database
        options = [
            disnake.SelectOption(label=label, value=event_type, emoji=label.split()[0])
            for event_type, label in Config.EVENT_TYPE_LABELS.items()
        ]
        super().__init__(
            placeholder="Выберите событие для редактирования",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: disnake.MessageInteraction):
        event_type = self.values[0]
        current_template = await self.database.get_notification_template(
            interaction.guild_id, event_type
        )

        modal = NotificationTemplateModal(event_type, current_template, self.database)
        await interaction.response.send_modal(modal)


class NotificationTemplatesView(disnake.ui.View):
    def __init__(self, user_id: int, database):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.database = database
        self.add_item(NotificationTemplateSelect(database))

    @disnake.ui.button(
        label="🔙 Назад",
        style=disnake.ButtonStyle.secondary,
        row=1,
        custom_id="back_to_settings",
    )
    async def back_to_settings(
        self, button: disnake.ui.Button, inter: disnake.MessageInteraction
    ):
        data = await self.database.get_guild(inter.guild_id)
        embed = create_settings_embed(data)
        await inter.response.edit_message(
            embed=embed, view=SettingsButton(self.user_id)
        )


class SettingsButton(disnake.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=95)
        self.user_id = user_id

    @disnake.ui.button(
        label="📃 Изменить канал для уведомлений",
        style=disnake.ButtonStyle.secondary,
        row=0,
        custom_id="edit_notification_channel",
    )
    async def edit_notification_channel(
        self, button: disnake.ui.Button, inter: disnake.MessageInteraction
    ):
        await inter.response.edit_message(
            view=NotificationChannelView(inter.guild, self.user_id, inter.bot.database)
        )

    @disnake.ui.button(
        label="📃 Изменить канал для мониторинга",
        style=disnake.ButtonStyle.secondary,
        row=0,
        custom_id="edit_monitoring_channel",
    )
    async def edit_monitoring_channel(
        self, button: disnake.ui.Button, inter: disnake.MessageInteraction
    ):
        await inter.response.edit_message(
            view=MonitoringChannelView(inter.guild, self.user_id, inter.bot.database)
        )

    @disnake.ui.button(
        label="📝 Шаблоны уведомлений",
        style=disnake.ButtonStyle.secondary,
        row=1,
        custom_id="edit_notification_templates",
    )
    async def edit_notification_templates(
        self, button: disnake.ui.Button, inter: disnake.MessageInteraction
    ):
        # Create embed with available variables
        embed = disnake.Embed(
            title="📝 Шаблоны уведомлений",
            description="Выберите событие для редактирования шаблона.",
            color=disnake.Color.blurple(),
        )
        embed.add_field(
            name="📌 Доступные переменные",
            value=(
                "`{streamer_name}` — имя стримера\n"
                "`{stream_title}` — название стрима\n"
                "`{game_name}` — название игры\n"
                "`{streamer_link}` — ссылка на канал"
            ),
            inline=False,
        )
        await inter.response.edit_message(
            embed=embed,
            view=NotificationTemplatesView(self.user_id, inter.bot.database),
        )


def setup(bot: commands.Bot) -> None:
    bot.add_cog(Settings(bot))
