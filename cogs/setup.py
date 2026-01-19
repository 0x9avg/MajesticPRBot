"""Ког для управления настройками сервера."""

import disnake
from disnake import ApplicationCommandInteraction, MessageInteraction, Embed
from disnake.ext import commands
from utils import create_streamers_component
from config import Config
from cogs.dashboard import DashboardView  # Import DashboardView for persistent panel


def create_settings_embed(data):
    embed = disnake.Embed(title="⚙️ Первоначальная настройка", colour=0xC9A6F6)

    # Обработка случая, когда данных нет (настройки гильдии отсутствуют)
    if data is None:
        data = {
            "notification_channel_id": None,
            "monitoring_channel_id": None,
            "pr_actions_channel_id": None,
            "control_panel_channel_id": None,
        }

    embed.description = (
        "Используйте кнопки ниже для выбора каналов.\n"
        "После выбора каналов панель управления будет создана автоматически."
    )

    embed.add_field(
        name="🔔 Канал для уведомлений (Анонсы)",
        value=(
            f"<#{data['notification_channel_id']}>"
            if data.get("notification_channel_id")
            else "– Канал не выбран."
        ),
        inline=False,
    )

    embed.add_field(
        name="📊 Канал для мониторинга (Статус)",
        value=(
            f"<#{data['monitoring_channel_id']}>"
            if data.get("monitoring_channel_id")
            else "– Канал не выбран."
        ),
        inline=False,
    )

    embed.add_field(
        name="📢 Канал действий PR (Логи)",
        value=(
            f"<#{data['pr_actions_channel_id']}>"
            if data.get("pr_actions_channel_id")
            else "– Канал не выбран."
        ),
        inline=False,
    )

    embed.add_field(
        name="🎛️ Канал Панели Управления",
        value=(
            f"<#{data.get('control_panel_channel_id')}>"
            if data.get("control_panel_channel_id")
            else "– Канал не выбран."
        ),
        inline=False,
    )

    embed.add_field(
        name="🏷️ Роль Ассистента (Для упоминания)",
        value=(
            f"<@&{data.get('assistant_role_id')}>"
            if data.get("assistant_role_id")
            else "– Роль не выбрана."
        ),
        inline=False,
    )

    return embed


class Setup(commands.Cog):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.database = bot.database
        self.twitch_bot = bot.twitch_bot

    @commands.slash_command(name="setup", description="Начальная настройка сервера (Каналы)")
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def setup(self, interaction: ApplicationCommandInteraction) -> None:
        if not interaction.author.guild_permissions.administrator:
            self.bot.logger.warning(
                f"User {interaction.user} tried to access setup without admin permissions"
            )
            await interaction.response.send_message(
                "🚫 У вас нет прав администратора.",
                ephemeral=True,
            )
            return

        try:
            self.bot.logger.debug(
                f"User {interaction.user} ({interaction.user.id}) viewing setup for guild {interaction.guild.id}"
            )
            await interaction.response.defer()
            data = await self.database.get_guild(interaction.guild.id)
            embed = create_settings_embed(data)
            await interaction.followup.send(
                embed=embed, view=SetupButton(interaction.user.id), ephemeral=True
            )
        except Exception as e:
            self.bot.logger.error(f"Error displaying setup: {e}", exc_info=True)
            await interaction.followup.send(
                "An error occurred while loading setup.", ephemeral=True
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
                view=SetupButton(interaction.user.id),
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
        await inter.response.edit_message(embed=embed, view=SetupButton(self.user_id))


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

            # Get all streamer data
            streamers = await interaction.bot.database.list_all_streamers()

            online_streamers = []
            gta_count = 0

            for streamer in streamers:
                if streamer.get("is_online"):
                    online_streamers.append(streamer)
                    if str(streamer.get("game_id")) == Config.GTA5_GAME_ID:
                        gta_count += 1

            # Fetch events for monitoring
            events = await interaction.bot.database.get_active_events(
                interaction.guild.id
            )
            if not events:
                events = []

            # Create monitoring container
            container = create_streamers_component(
                online_streamers, len(streamers), gta_count, events=events
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
                view=SetupButton(interaction.user.id),
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
        await inter.response.edit_message(embed=embed, view=SetupButton(self.user_id))


# =============================================================================
# Настройки канала действий PR
# =============================================================================


class PRActionsChannelSelect(disnake.ui.ChannelSelect):
    def __init__(self, guild: disnake.Guild):
        super().__init__(
            channel_types=[disnake.ChannelType.text],
            placeholder="Выберите канал для логов действий PR",
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
                f"Setting PR actions channel to {selected_channel.id} for guild {interaction.guild.id}"
            )
            await interaction.bot.database.set_pr_actions_channel(
                interaction.guild.id, selected_channel.id
            )

            await interaction.response.edit_message(
                embed=create_settings_embed(
                    await interaction.bot.database.get_guild(interaction.guild.id),
                ),
                view=SetupButton(interaction.user.id),
            )
            await interaction.followup.send(
                "✅ Канал {channel} выбран для логов действий PR.".format(
                    channel=selected_channel.mention
                ),
                ephemeral=True,
            )
            interaction.bot.logger.debug(
                f"✓ PR actions channel updated successfully for guild {interaction.guild.id}"
            )
        except Exception as e:
            interaction.bot.logger.error(
                f"Error updating PR actions channel: {e}", exc_info=True
            )
            await interaction.followup.send(
                "An error occurred while updating the settings.", ephemeral=True
            )


class PRActionsChannelView(disnake.ui.View):
    def __init__(self, guild: disnake.Guild, user_id: int, database):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.guild = guild
        self.database = database

        # Селектор каналов
        self.add_item(PRActionsChannelSelect(guild))

    @disnake.ui.button(
        label="🔙 Назад",
        style=disnake.ButtonStyle.secondary,
        row=1,
        custom_id="back_to_settings_pr_actions",
    )
    async def back_to_settings(
        self, button: disnake.ui.Button, inter: disnake.MessageInteraction
    ):
        data = await self.database.get_guild(inter.guild_id)
        embed = create_settings_embed(data)
        await inter.response.edit_message(embed=embed, view=SetupButton(self.user_id))


# =============================================================================
# Настройки канала Панели Управления
# =============================================================================


class ControlPanelChannelSelect(disnake.ui.ChannelSelect):
    def __init__(self, guild: disnake.Guild):
        super().__init__(
            channel_types=[disnake.ChannelType.text],
            placeholder="Выберите канал для Панели Управления",
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
                f"Setting control panel channel to {selected_channel.id} for guild {interaction.guild.id}"
            )

            # --- Логика создания ---

            # Получение существующих настроек
            settings = await interaction.bot.database.get_guild(interaction.guild.id)

            # Удаление старого сообщения, если существует
            if settings and settings.get("control_panel_message_id"):
                old_channel_id = settings.get("control_panel_channel_id")
                if old_channel_id:
                    old_chan = interaction.bot.get_channel(old_channel_id)
                    if old_chan:
                        try:
                            old_msg = await old_chan.fetch_message(
                                settings["control_panel_message_id"]
                            )
                            await old_msg.delete()
                        except disnake.NotFound:
                            pass
                        except Exception:
                            pass

            # Send new Control Panel message
            embed_cp = disnake.Embed(
                title="🎛️ Панель Управления",
                description="Добро пожаловать в панель управления PRMajesticBot.\nВыберите раздел в меню ниже.",
                color=0x2B2D31,
            )
            embed_cp.set_footer(text="Используйте кнопки для навигации")

            try:
                msg = await selected_channel.send(
                    embed=embed_cp, view=DashboardView(interaction.bot)
                )
            except disnake.Forbidden:
                await interaction.response.send_message(
                    f"❌ Нет прав отправлять сообщения в канал {selected_channel.mention}.",
                    ephemeral=True,
                )
                return

            # Update Database using Raw Query (same as in dashboard before)
            async with interaction.bot.database.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                         INSERT INTO settings (guild_id, control_panel_channel_id, control_panel_message_id)
                         VALUES (%s, %s, %s) AS new
                         ON DUPLICATE KEY UPDATE
                         control_panel_channel_id = new.control_panel_channel_id,
                         control_panel_message_id = new.control_panel_message_id
                         """,
                        (interaction.guild_id, selected_channel.id, msg.id),
                    )
                    await conn.commit()

            # -------------------

            await interaction.response.edit_message(
                embed=create_settings_embed(
                    await interaction.bot.database.get_guild(interaction.guild.id),
                ),
                view=SetupButton(interaction.user.id),
            )
            await interaction.followup.send(
                "✅ Канал {channel} выбран. **Панель управления** создана!".format(
                    channel=selected_channel.mention
                ),
                ephemeral=True,
            )

        except Exception as e:
            interaction.bot.logger.error(
                f"Error updating CP channel: {e}", exc_info=True
            )
            await interaction.followup.send(
                "An error occurred while updating the settings.", ephemeral=True
            )


class ControlPanelChannelView(disnake.ui.View):
    def __init__(self, guild: disnake.Guild, user_id: int, database):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.guild = guild
        self.database = database
        self.add_item(ControlPanelChannelSelect(guild))

    @disnake.ui.button(
        label="🔙 Назад",
        style=disnake.ButtonStyle.secondary,
        row=1,
        custom_id="back_to_settings_cp",
    )
    async def back_to_settings(
        self, button: disnake.ui.Button, inter: disnake.MessageInteraction
    ):
        data = await self.database.get_guild(inter.guild_id)
        embed = create_settings_embed(data)
        await inter.response.edit_message(embed=embed, view=SetupButton(self.user_id))


# =============================================================================
# Настройки роли Ассистента
# =============================================================================


class AssistantRoleSelect(disnake.ui.RoleSelect):
    def __init__(self, guild: disnake.Guild):
        super().__init__(
            placeholder="Выберите роль ассистента",
            min_values=1,
            max_values=1,
        )
        self.guild = guild

    async def callback(self, interaction: disnake.MessageInteraction):
        selected_role: disnake.Role = self.values[0]

        if not selected_role:
            await interaction.response.send_message(
                "🚫 Роль не найдена.",
                ephemeral=True,
            )
            return

        try:
            interaction.bot.logger.debug(
                f"Setting assistant role to {selected_role.id} for guild {interaction.guild.id}"
            )
            await interaction.bot.database.set_assistant_role(
                interaction.guild.id, selected_role.id
            )

            await interaction.response.edit_message(
                embed=create_settings_embed(
                    await interaction.bot.database.get_guild(interaction.guild.id),
                ),
                view=SetupButton(interaction.user.id),
            )
            await interaction.followup.send(
                "✅ Роль {role} выбрана для упоминания при старте событий.".format(
                    role=selected_role.mention
                ),
                ephemeral=True,
            )
        except Exception as e:
            interaction.bot.logger.error(
                f"Error updating assistant role: {e}", exc_info=True
            )
            await interaction.followup.send(
                "An error occurred while updating the settings.", ephemeral=True
            )


class AssistantRoleView(disnake.ui.View):
    def __init__(self, guild: disnake.Guild, user_id: int, database):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.guild = guild
        self.database = database
        self.add_item(AssistantRoleSelect(guild))

    @disnake.ui.button(
        label="🔙 Назад",
        style=disnake.ButtonStyle.secondary,
        row=1,
        custom_id="back_to_settings_role",
    )
    async def back_to_settings(
        self, button: disnake.ui.Button, inter: disnake.MessageInteraction
    ):
        data = await self.database.get_guild(inter.guild_id)
        embed = create_settings_embed(data)
        await inter.response.edit_message(embed=embed, view=SetupButton(self.user_id))


class SetupButton(disnake.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=180)
        self.user_id = user_id

    @disnake.ui.button(
        label="🔔 Канал уведомлений",
        style=disnake.ButtonStyle.primary,
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
        label="📊 Канал мониторинга",
        style=disnake.ButtonStyle.primary,
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
        label="📢 Канал действий PR",
        style=disnake.ButtonStyle.primary,
        row=1,
        custom_id="edit_pr_actions_channel",
    )
    async def edit_pr_actions_channel(
        self, button: disnake.ui.Button, inter: disnake.MessageInteraction
    ):
        await inter.response.edit_message(
            view=PRActionsChannelView(inter.guild, self.user_id, inter.bot.database)
        )

    @disnake.ui.button(
        label="🎛️ Панель Управления",
        style=disnake.ButtonStyle.primary,
        row=1,
        custom_id="edit_cp_channel",
    )
    async def edit_cp_channel(
        self, button: disnake.ui.Button, inter: disnake.MessageInteraction
    ):
        await inter.response.edit_message(
            view=ControlPanelChannelView(inter.guild, self.user_id, inter.bot.database)
        )

    @disnake.ui.button(
        label="🏷️ Роль Ассистента",
        style=disnake.ButtonStyle.primary,
        row=2,
        custom_id="edit_assistant_role",
    )
    async def edit_assistant_role(
        self, button: disnake.ui.Button, inter: disnake.MessageInteraction
    ):
        await inter.response.edit_message(
            view=AssistantRoleView(inter.guild, self.user_id, inter.bot.database)
        )


def setup(bot: commands.Bot) -> None:
    bot.add_cog(Setup(bot))
