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


# =============================================================================
# Component IDs
# =============================================================================
ID_SETUP_NOTIF = "server_setup_notif"
ID_SETUP_MON = "server_setup_mon"
ID_SETUP_LOGS = "server_setup_logs"
ID_SETUP_PANEL = "server_setup_panel"
ID_SETUP_ROLE = "server_setup_role"

ID_SELECT_NOTIF = "server_sel_notif"
ID_SELECT_MON = "server_sel_mon"
ID_SELECT_LOGS = "server_sel_logs"
ID_SELECT_PANEL = "server_sel_panel"
ID_SELECT_ROLE = "server_sel_role"

ID_BTN_BACK = "server_btn_back"


# =============================================================================
# Views (Dumb Containers)
# =============================================================================


class SetupButtonsView(disnake.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id
        
        self.add_item(disnake.ui.Button(label="🔔 Канал уведомлений", custom_id=ID_SETUP_NOTIF, style=disnake.ButtonStyle.primary, row=0))
        self.add_item(disnake.ui.Button(label="📊 Канал мониторинга", custom_id=ID_SETUP_MON, style=disnake.ButtonStyle.primary, row=0))
        self.add_item(disnake.ui.Button(label="📢 Канал логов PR", custom_id=ID_SETUP_LOGS, style=disnake.ButtonStyle.primary, row=1))
        self.add_item(disnake.ui.Button(label="🎛️ Панель Управления", custom_id=ID_SETUP_PANEL, style=disnake.ButtonStyle.primary, row=1))
        self.add_item(disnake.ui.Button(label="🏷️ Роль Ассистента", custom_id=ID_SETUP_ROLE, style=disnake.ButtonStyle.primary, row=2))


class NotificationChannelView(disnake.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.add_item(disnake.ui.ChannelSelect(custom_id=ID_SELECT_NOTIF, channel_types=[disnake.ChannelType.text], placeholder="Выберите канал...", min_values=1, max_values=1))
        self.add_item(disnake.ui.Button(label="🔙 Назад", custom_id=ID_BTN_BACK, style=disnake.ButtonStyle.secondary, row=1))


class MonitoringChannelView(disnake.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.add_item(disnake.ui.ChannelSelect(custom_id=ID_SELECT_MON, channel_types=[disnake.ChannelType.text], placeholder="Выберите канал...", min_values=1, max_values=1))
        self.add_item(disnake.ui.Button(label="🔙 Назад", custom_id=ID_BTN_BACK, style=disnake.ButtonStyle.secondary, row=1))


class PRActionsChannelView(disnake.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.add_item(disnake.ui.ChannelSelect(custom_id=ID_SELECT_LOGS, channel_types=[disnake.ChannelType.text], placeholder="Выберите канал...", min_values=1, max_values=1))
        self.add_item(disnake.ui.Button(label="🔙 Назад", custom_id=ID_BTN_BACK, style=disnake.ButtonStyle.secondary, row=1))


class ControlPanelChannelView(disnake.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.add_item(disnake.ui.ChannelSelect(custom_id=ID_SELECT_PANEL, channel_types=[disnake.ChannelType.text], placeholder="Выберите канал...", min_values=1, max_values=1))
        self.add_item(disnake.ui.Button(label="🔙 Назад", custom_id=ID_BTN_BACK, style=disnake.ButtonStyle.secondary, row=1))


class AssistantRoleView(disnake.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.add_item(disnake.ui.RoleSelect(custom_id=ID_SELECT_ROLE, placeholder="Выберите роль...", min_values=1, max_values=1))
        self.add_item(disnake.ui.Button(label="🔙 Назад", custom_id=ID_BTN_BACK, style=disnake.ButtonStyle.secondary, row=1))


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
    async def on_server_button_interaction(self, interaction: MessageInteraction):
        """Handle all server config buttons."""
        custom_id = interaction.component.custom_id or ""
        
        # 1.Strict Filter
        if not custom_id.startswith(("server_setup_", "server_btn_", "admin_server")):
            return

        # 2. Safe Defer
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except Exception as e:
            self.bot.logger.warning(f"Defer failed: {e}")

        # 3. Execute
        try:
            user_id = interaction.user.id
            if custom_id == "admin_server":
                 data = await self.api.get_guild_settings()
                 await interaction.edit_original_response(embed=create_settings_embed(data), view=SetupButtonsView(user_id))
            
            elif custom_id == ID_BTN_BACK:
                 data = await self.api.get_guild_settings()
                 await interaction.edit_original_response(embed=create_settings_embed(data), view=SetupButtonsView(user_id))

            elif custom_id == ID_SETUP_NOTIF:
                 await interaction.edit_original_response(view=NotificationChannelView(user_id))
            
            elif custom_id == ID_SETUP_MON:
                 await interaction.edit_original_response(view=MonitoringChannelView(user_id))

            elif custom_id == ID_SETUP_LOGS:
                 await interaction.edit_original_response(view=PRActionsChannelView(user_id))

            elif custom_id == ID_SETUP_PANEL:
                 await interaction.edit_original_response(view=ControlPanelChannelView(user_id))
            
            elif custom_id == ID_SETUP_ROLE:
                 await interaction.edit_original_response(view=AssistantRoleView(user_id))

        except Exception as e:
             self.bot.logger.error(f"Server button error {custom_id}: {e}", exc_info=True)
             try: await interaction.followup.send("❌ Ошибка.", ephemeral=True)
             except: pass


    @commands.Cog.listener("on_dropdown")
    async def on_server_dropdown_interaction(self, interaction: MessageInteraction):
        """Handle server config dropdowns."""
        custom_id = interaction.component.custom_id or ""
        
        if not custom_id.startswith("server_sel_"):
            return

        try:
             if not interaction.response.is_done():
                 await interaction.response.defer(ephemeral=True)
        except: pass

        try:
            user_id = interaction.user.id
            val = interaction.values[0] # Channel/Role object or ID string depending on select type? 
            # disnake ChannelSelect/RoleSelect returns objects in values if resolved, but interaction.values usually lists raw IDs (strings).
            # WAIT. interaction.values for ChannelSelect are IDs (strings). interaction.data['resolved'] has objects.
            # But the 'values' property in interaction usually gives the IDs.
            # Let's resolve safely.
            
            # Helper to get settings refresh
            async def back_to_main():
                data = await self.api.get_guild_settings()
                await interaction.edit_original_response(embed=create_settings_embed(data), view=SetupButtonsView(user_id))

            if custom_id == ID_SELECT_NOTIF:
                await self.api.update_guild_settings(notification_channel_id=int(val))
                await back_to_main()
                try: await interaction.followup.send(f"✅ Канал уведомлений обновлен: <#{val}>", ephemeral=True)
                except: pass

            elif custom_id == ID_SELECT_LOGS:
                await self.api.update_guild_settings(pr_actions_channel_id=int(val))
                await back_to_main()
                try: await interaction.followup.send(f"✅ Канал логов обновлен: <#{val}>", ephemeral=True)
                except: pass

            elif custom_id == ID_SELECT_ROLE:
                await self.api.update_guild_settings(assistant_role_id=int(val))
                await back_to_main()
                try: await interaction.followup.send(f"✅ Роль ассистента обновлена: <@&{val}>", ephemeral=True)
                except: pass

            elif custom_id == ID_SELECT_PANEL:
                 # Logic for Panel
                 channel_id = int(val)
                 channel = self.bot.get_channel(channel_id)
                 if channel:
                     try:
                         msg = await channel.send(embed=get_main_embed(), view=AdminMainView(self.bot))
                         await self.api.update_guild_settings(
                              control_panel_channel_id=channel_id,
                              control_panel_message_id=msg.id
                         )
                         await back_to_main()
                         await interaction.followup.send(f"✅ Панель создана: <#{val}>", ephemeral=True)
                     except Exception as e:
                         await interaction.followup.send(f"❌ Ошибка создания панели: {e}", ephemeral=True)
                 else:
                     await interaction.followup.send("❌ Канал не найден.", ephemeral=True)

            elif custom_id == ID_SELECT_MON:
                 # Logic for Monitoring
                 channel_id = int(val)
                 channel = self.bot.get_channel(channel_id)
                 if channel:
                     streamers = await self.api.list_all_streamers()
                     online = [s for s in streamers if s.get("is_online")]
                     gta_count = sum(1 for s in online if str(s.get("game_id")) == Config.gta5_game_id)
                     container = create_streamers_component(online, len(streamers), gta_count)
                     
                     msg = await channel.send(components=container)
                     await self.api.update_guild_settings(
                          monitoring_channel_id=channel_id,
                          monitoring_message_id=msg.id
                     )
                     await back_to_main()
                     await interaction.followup.send(f"✅ Мониторинг настроен: <#{val}>", ephemeral=True)
                 else:
                     await interaction.followup.send("❌ Канал не найден.", ephemeral=True)

        except Exception as e:
             self.bot.logger.error(f"Dropdown error {custom_id}: {e}", exc_info=True)
             try: await interaction.followup.send("❌ Ошибка.", ephemeral=True)
             except: pass


def setup(bot: commands.Bot) -> None:
    bot.add_cog(AdminServer(bot))
