"""Admin Server - Server Configuration Settings.
Adapted from old setup.py with button-based navigation.
"""

import disnake
from disnake import MessageInteraction
from disnake.ext import commands

from config import Config
from utils import create_streamers_component
from .core import AdminMainView, get_main_embed


# =============================================================================
# Settings Embed
# =============================================================================


def create_settings_embed(data):
    """Create embed showing current server settings."""
    embed = disnake.Embed(title="⚙️ Первоначальная настройка", colour=0xC9A6F6)

    if data is None:
        data = {}

    embed.description = (
        "Используйте кнопки ниже для выбора каналов.\n"
        "После выбора каналов панель управления будет создана автоматически."
    )

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
        name="🏷️ Роль Ассистента",
        value=(
            f"<@&{data.get('assistant_role_id')}>"
            if data.get("assistant_role_id")
            else "– Роль не выбрана."
        ),
        inline=False,
    )

    return embed


# =============================================================================
# Notification Channel
# =============================================================================


class NotificationChannelSelect(disnake.ui.ChannelSelect):
    def __init__(self, user_id: int):
        super().__init__(
            channel_types=[disnake.ChannelType.text],
            placeholder="Выберите канал для уведомлений",
            min_values=1,
            max_values=1,
        )
        self.user_id = user_id

    async def callback(self, interaction: MessageInteraction):
        selected_channel = self.values[0]
        try:
            await interaction.bot.api_client.update_guild_settings(
                notification_channel_id=selected_channel.id,
            )
            await interaction.response.edit_message(
                embed=create_settings_embed(
                    await interaction.bot.api_client.get_guild_settings(),
                ),
                view=SetupButtonsView(self.user_id),
            )
            await interaction.followup.send(
                f"✅ Канал {selected_channel.mention} выбран для уведомлений.",
                ephemeral=True,
            )
        except Exception as e:
            interaction.bot.logger.error(f"Error updating notification channel: {e}")
            await interaction.followup.send("❌ Ошибка.", ephemeral=True)


class NotificationChannelView(disnake.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.add_item(NotificationChannelSelect(user_id))

    @disnake.ui.button(label="🔙 Назад", style=disnake.ButtonStyle.secondary, row=1)
    async def back_button(self, button: disnake.ui.Button, inter: MessageInteraction):
        data = await inter.bot.api_client.get_guild_settings()
        await inter.response.edit_message(
            embed=create_settings_embed(data), view=SetupButtonsView(self.user_id)
        )


# =============================================================================
# Monitoring Channel
# =============================================================================


class MonitoringChannelSelect(disnake.ui.ChannelSelect):
    def __init__(self, user_id: int):
        super().__init__(
            channel_types=[disnake.ChannelType.text],
            placeholder="Выберите канал для мониторинга",
            min_values=1,
            max_values=1,
        )
        self.user_id = user_id

    async def callback(self, interaction: MessageInteraction):
        selected_channel = self.values[0]
        try:
            # Delete old monitoring message if exists
            old_settings = await interaction.bot.api_client.get_guild_settings()
            if old_settings and old_settings.get("monitoring_message_id"):
                old_channel_id = old_settings.get("monitoring_channel_id")
                if old_channel_id:
                    old_channel = interaction.bot.get_channel(int(old_channel_id))
                    if old_channel:
                        try:
                            old_message = await old_channel.fetch_message(
                                int(old_settings["monitoring_message_id"])
                            )
                            await old_message.delete()
                            interaction.bot.logger.debug(f"Deleted old monitoring message")
                        except Exception as e:
                            interaction.bot.logger.warning(f"Could not delete old monitoring message: {e}")

            # Get streamer data
            streamers = await interaction.bot.api_client.list_all_streamers()
            online = [s for s in streamers if s.get("is_online")]
            gta_count = sum(
                1 for s in online if str(s.get("game_id")) == Config.GTA5_GAME_ID
            )

            # Create monitoring message
            container = create_streamers_component(online, len(streamers), gta_count)
            monitoring_message = await selected_channel.send(components=container)

            # Save to DB
            await interaction.bot.api_client.update_guild_settings(
                monitoring_channel_id=selected_channel.id,
                monitoring_message_id=monitoring_message.id,
            )

            await interaction.response.edit_message(
                embed=create_settings_embed(
                    await interaction.bot.api_client.get_guild_settings(),
                ),
                view=SetupButtonsView(self.user_id),
            )
            await interaction.followup.send(
                f"✅ Канал {selected_channel.mention} выбран для мониторинга.",
                ephemeral=True,
            )
        except Exception as e:
            interaction.bot.logger.error(f"Error updating monitoring channel: {e}")
            await interaction.followup.send("❌ Ошибка.", ephemeral=True)


class MonitoringChannelView(disnake.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.add_item(MonitoringChannelSelect(user_id))

    @disnake.ui.button(label="🔙 Назад", style=disnake.ButtonStyle.secondary, row=1)
    async def back_button(self, button: disnake.ui.Button, inter: MessageInteraction):
        data = await inter.bot.api_client.get_guild_settings()
        await inter.response.edit_message(
            embed=create_settings_embed(data), view=SetupButtonsView(self.user_id)
        )


# =============================================================================
# PR Actions Channel
# =============================================================================


class PRActionsChannelSelect(disnake.ui.ChannelSelect):
    def __init__(self, user_id: int):
        super().__init__(
            channel_types=[disnake.ChannelType.text],
            placeholder="Выберите канал для логов PR",
            min_values=1,
            max_values=1,
        )
        self.user_id = user_id

    async def callback(self, interaction: MessageInteraction):
        selected_channel = self.values[0]
        try:
            await interaction.bot.api_client.update_guild_settings(
                pr_actions_channel_id=selected_channel.id
            )
            await interaction.response.edit_message(
                embed=create_settings_embed(
                    await interaction.bot.api_client.get_guild_settings(),
                ),
                view=SetupButtonsView(self.user_id),
            )
            await interaction.followup.send(
                f"✅ Канал {selected_channel.mention} выбран для логов PR.",
                ephemeral=True,
            )
        except Exception as e:
            interaction.bot.logger.error(f"Error updating PR actions channel: {e}")
            await interaction.followup.send("❌ Ошибка.", ephemeral=True)


class PRActionsChannelView(disnake.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.add_item(PRActionsChannelSelect(user_id))

    @disnake.ui.button(label="🔙 Назад", style=disnake.ButtonStyle.secondary, row=1)
    async def back_button(self, button: disnake.ui.Button, inter: MessageInteraction):
        data = await inter.bot.api_client.get_guild_settings()
        await inter.response.edit_message(
            embed=create_settings_embed(data), view=SetupButtonsView(self.user_id)
        )


# =============================================================================
# Control Panel Channel
# =============================================================================


class ControlPanelChannelSelect(disnake.ui.ChannelSelect):
    def __init__(self, user_id: int):
        super().__init__(
            channel_types=[disnake.ChannelType.text],
            placeholder="Выберите канал для Панели Управления",
            min_values=1,
            max_values=1,
        )
        self.user_id = user_id

    async def callback(self, interaction: MessageInteraction):
        selected_channel = self.values[0]
        try:
            # Delete old panel message if exists
            settings = await interaction.bot.api_client.get_guild_settings()
            if settings and settings.get("control_panel_message_id"):
                old_channel_id = settings.get("control_panel_channel_id")
                if old_channel_id:
                    old_chan = interaction.bot.get_channel(int(old_channel_id))
                    if old_chan:
                        try:
                            old_msg = await old_chan.fetch_message(
                                int(settings["control_panel_message_id"])
                            )
                            await old_msg.delete()
                            interaction.bot.logger.debug(f"Deleted old control panel message")
                        except Exception as e:
                            interaction.bot.logger.warning(f"Could not delete old panel message: {e}")

            # Create new Control Panel message
            try:
                msg = await selected_channel.send(
                    embed=get_main_embed(), view=AdminMainView(interaction.bot)
                )
            except disnake.Forbidden:
                await interaction.response.send_message(
                    f"❌ Нет прав отправлять в {selected_channel.mention}.",
                    ephemeral=True,
                )
                return

            # Save to DB
            await interaction.bot.api_client.update_guild_settings(
                control_panel_channel_id=selected_channel.id,
                control_panel_message_id=msg.id,
            )

            await interaction.response.edit_message(
                embed=create_settings_embed(
                    await interaction.bot.api_client.get_guild_settings(),
                ),
                view=SetupButtonsView(self.user_id),
            )
            await interaction.followup.send(
                f"✅ Панель управления создана в {selected_channel.mention}!",
                ephemeral=True,
            )
        except Exception as e:
            interaction.bot.logger.error(f"Error updating CP channel: {e}")
            await interaction.followup.send("❌ Ошибка.", ephemeral=True)


class ControlPanelChannelView(disnake.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.add_item(ControlPanelChannelSelect(user_id))

    @disnake.ui.button(label="🔙 Назад", style=disnake.ButtonStyle.secondary, row=1)
    async def back_button(self, button: disnake.ui.Button, inter: MessageInteraction):
        data = await inter.bot.api_client.get_guild_settings()
        await inter.response.edit_message(
            embed=create_settings_embed(data), view=SetupButtonsView(self.user_id)
        )


# =============================================================================
# Assistant Role
# =============================================================================


class AssistantRoleSelect(disnake.ui.RoleSelect):
    def __init__(self, user_id: int):
        super().__init__(
            placeholder="Выберите роль ассистента",
            min_values=1,
            max_values=1,
        )
        self.user_id = user_id

    async def callback(self, interaction: MessageInteraction):
        selected_role = self.values[0]
        try:
            await interaction.bot.api_client.update_guild_settings(
                assistant_role_id=selected_role.id
            )
            await interaction.response.edit_message(
                embed=create_settings_embed(
                    await interaction.bot.api_client.get_guild_settings(),
                ),
                view=SetupButtonsView(self.user_id),
            )
            await interaction.followup.send(
                f"✅ Роль {selected_role.mention} выбрана для ассистентов.",
                ephemeral=True,
            )
        except Exception as e:
            interaction.bot.logger.error(f"Error updating assistant role: {e}")
            await interaction.followup.send("❌ Ошибка.", ephemeral=True)


class AssistantRoleView(disnake.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.add_item(AssistantRoleSelect(user_id))

    @disnake.ui.button(label="🔙 Назад", style=disnake.ButtonStyle.secondary, row=1)
    async def back_button(self, button: disnake.ui.Button, inter: MessageInteraction):
        data = await inter.bot.api_client.get_guild_settings()
        await inter.response.edit_message(
            embed=create_settings_embed(data), view=SetupButtonsView(self.user_id)
        )


# =============================================================================
# Main Setup Buttons View
# =============================================================================


class SetupButtonsView(disnake.ui.View):
    """Main setup view with buttons for each setting."""

    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id

    @disnake.ui.button(
        label="🔔 Канал уведомлений",
        style=disnake.ButtonStyle.primary,
        row=0,
    )
    async def notification_button(
        self, button: disnake.ui.Button, inter: MessageInteraction
    ):
        await inter.response.edit_message(view=NotificationChannelView(self.user_id))

    @disnake.ui.button(
        label="📊 Канал мониторинга",
        style=disnake.ButtonStyle.primary,
        row=0,
    )
    async def monitoring_button(
        self, button: disnake.ui.Button, inter: MessageInteraction
    ):
        await inter.response.edit_message(view=MonitoringChannelView(self.user_id))

    @disnake.ui.button(
        label="📢 Канал логов PR",
        style=disnake.ButtonStyle.primary,
        row=1,
    )
    async def logs_button(
        self, button: disnake.ui.Button, inter: MessageInteraction
    ):
        await inter.response.edit_message(view=PRActionsChannelView(self.user_id))

    @disnake.ui.button(
        label="🎛️ Панель Управления",
        style=disnake.ButtonStyle.primary,
        row=1,
    )
    async def panel_button(
        self, button: disnake.ui.Button, inter: MessageInteraction
    ):
        await inter.response.edit_message(view=ControlPanelChannelView(self.user_id))

    @disnake.ui.button(
        label="🏷️ Роль Ассистента",
        style=disnake.ButtonStyle.primary,
        row=2,
    )
    async def role_button(
        self, button: disnake.ui.Button, inter: MessageInteraction
    ):
        await inter.response.edit_message(view=AssistantRoleView(self.user_id))


# =============================================================================
# Admin Server Cog
# =============================================================================


class AdminServer(commands.Cog):
    """Server settings management."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.api = bot.api_client

    @commands.slash_command(name="setup", description="Первоначальная настройка сервера")
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def setup_command(
        self, interaction: disnake.ApplicationCommandInteraction
    ) -> None:
        """Initial setup - channels and roles."""
        if not interaction.author.guild_permissions.administrator:
            await interaction.response.send_message(
                "🚫 У вас нет прав администратора.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        data = await self.api.get_guild_settings()
        embed = create_settings_embed(data)
        await interaction.followup.send(
            embed=embed, view=SetupButtonsView(interaction.user.id), ephemeral=True
        )

    @commands.Cog.listener("on_button_click")
    async def on_server_button(self, interaction: MessageInteraction):
        """Handle admin_server navigation from control panel."""
        if interaction.component.custom_id != "admin_server":
            return

        await interaction.response.defer()
        data = await self.api.get_guild_settings()
        await interaction.edit_original_response(
            embed=create_settings_embed(data),
            view=SetupButtonsView(interaction.user.id),
        )


def setup(bot: commands.Bot) -> None:
    bot.add_cog(AdminServer(bot))
