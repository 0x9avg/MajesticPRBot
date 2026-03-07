"""Admin Service - System Tools.
Force sync, refresh monitoring, recreate panels, bot status.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api_client import APIClient
    from discord_bot import DiscordBot

from datetime import datetime

import disnake
from disnake import MessageInteraction
from disnake.ext import commands

from .core import AdminControlPanelView, get_main_embed

SERVICE_SECTION_PERMS = ["monitoring.view", "monitoring.refresh"]
SERVICE_VIEW_PERMS = ["monitoring.view"]
SERVICE_REFRESH_PERMS = ["monitoring.refresh"]

# =============================================================================
# Service Embed
# =============================================================================


async def get_service_embed(bot) -> disnake.Embed:
    """Create embed showing bot status."""
    ping = round(bot.latency * 1000)

    # Calculate uptime if available
    uptime_str = "N/A"
    if hasattr(bot, "_start_time"):
        delta = datetime.now() - bot._start_time
        days = delta.days
        hours, rem = divmod(delta.seconds, 3600)
        minutes = rem // 60
        uptime_str = f"{days}д {hours}ч {minutes}м"

    # Get stats
    try:
        streamers = await bot.api_client.list_all_streamers()
        streamer_count = len(streamers)
        dashboard = await bot.api_client.get_dashboard_stats()
        session_count = (
            int(dashboard.get("assigned_pr_count", 0))
            if isinstance(dashboard, dict)
            else 0
        )
    except Exception:
        streamer_count, session_count = "?", "?"

    embed = disnake.Embed(
        title="🛠️ Сервисное Меню",
        description=(
            f"**Статус бота:**\n"
            f"📶 Пинг API: `{ping}ms`\n"
            f"⏱️ Uptime: `{uptime_str}`\n"
            f"🎥 Стримеров: `{streamer_count}`\n"
            f"📌 Активных сессий: `{session_count}`"
        ),
        color=0x607D8B,
    )
    return embed


# =============================================================================
# Service View
# =============================================================================


class ServiceView(disnake.ui.View):
    """View for system tools."""

    bot: "DiscordBot"

    def __init__(self, bot: "DiscordBot", permissions: dict[str, bool] | None = None):
        super().__init__(timeout=None)
        self.bot = bot
        permissions_map = permissions or {}

        def has_any(required: list[str]) -> bool:
            return any(bool(permissions_map.get(key, False)) for key in required)

        if has_any(SERVICE_REFRESH_PERMS):
            self.add_item(
                disnake.ui.Button(
                    label="🔄 Синхронизация Twitch",
                    custom_id="admin_svc_sync",
                    style=disnake.ButtonStyle.primary,
                    row=0,
                )
            )
            self.add_item(
                disnake.ui.Button(
                    label="🔄 Обновить мониторинг",
                    custom_id="admin_svc_refresh",
                    style=disnake.ButtonStyle.secondary,
                    row=0,
                )
            )
            self.add_item(
                disnake.ui.Button(
                    label="🔄 Пересоздать панели",
                    custom_id="admin_svc_respawn",
                    style=disnake.ButtonStyle.secondary,
                    row=1,
                )
            )

        if has_any(SERVICE_VIEW_PERMS):
            self.add_item(
                disnake.ui.Button(
                    label="📊 Статистика API",
                    custom_id="admin_svc_api_stats",
                    style=disnake.ButtonStyle.secondary,
                    row=1,
                )
            )

        self.add_item(
            disnake.ui.Button(
                label="Назад",
                custom_id="admin_home",
                style=disnake.ButtonStyle.secondary,
                emoji="🔙",
                row=2,
            )
        )


# =============================================================================
# Admin Service Cog
# =============================================================================


class AdminService(commands.Cog):
    """System tools and maintenance."""

    bot: "DiscordBot"
    api: "APIClient"

    def __init__(self, bot: "DiscordBot") -> None:
        self.bot = bot
        self.api = bot.api_client
        # Record start time for uptime
        if not hasattr(bot, "_start_time"):
            bot._start_time = datetime.now()

    @commands.Cog.listener("on_button_click")
    async def on_service_button(self, interaction: MessageInteraction):
        """Handle admin_service navigation and sub-buttons."""
        custom_id = interaction.component.custom_id or ""

        # 1. STRICT FILTER
        if not custom_id.startswith("admin_service") and not custom_id.startswith(
            "admin_svc_"
        ):
            return

        if not await self.bot.ensure_user_permissions(
            interaction,
            require_any=SERVICE_SECTION_PERMS,
            error_message="❌ Нет доступа к сервисному разделу.",
        ):
            return

        # 2. SAFE DEFER
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except Exception as e:
            self.bot.logger.warning(f"Failed to defer {custom_id}: {e}")

        # 3. EXECUTE
        try:
            if custom_id == "admin_service":
                permissions = await self.bot.get_user_permissions(interaction.user.id)
                embed = await get_service_embed(self.bot)
                await interaction.edit_original_response(
                    embed=embed, view=ServiceView(self.bot, permissions)
                )

            elif custom_id == "admin_svc_sync":
                if not await self.bot.ensure_user_permissions(
                    interaction,
                    require_any=SERVICE_REFRESH_PERMS,
                    error_message="❌ Нет прав на запуск синхронизации.",
                ):
                    return
                await self.bot.api_client.sync_streamers()
                await interaction.followup.send(
                    "✅ Синхронизация запущена! Стримеры будут обновлены.",
                    ephemeral=True,
                )

            elif custom_id == "admin_svc_refresh":
                if not await self.bot.ensure_user_permissions(
                    interaction,
                    require_any=SERVICE_REFRESH_PERMS,
                    error_message="❌ Нет прав на обновление мониторинга.",
                ):
                    return
                # Monitoring is now ephemeral/on-demand, no persistent messages to refresh
                await interaction.followup.send(
                    "ℹ️ Мониторинг теперь работает по запросу (кнопка 'Открыть мониторинг').",
                    ephemeral=True,
                )

            elif custom_id == "admin_svc_api_stats":
                if not await self.bot.ensure_user_permissions(
                    interaction,
                    require_any=SERVICE_VIEW_PERMS,
                    error_message="❌ Нет прав на просмотр системной статистики.",
                ):
                    return
                stats = await self.bot.api_client.get_health()

                # Format uptime
                uptime = stats.get("uptime_seconds", 0)
                hours, remainder = divmod(uptime, 3600)
                minutes, seconds = divmod(remainder, 60)
                uptime_str = f"{hours}h {minutes}m {seconds}s"

                # Status emoji
                status = stats.get("status", "unknown")
                status_emoji = (
                    "🟢"
                    if status == "healthy"
                    else "🟡" if status == "degraded" else "🔴"
                )

                # Components
                components = stats.get("components", {})
                db_emoji = "✅" if components.get("database") == "connected" else "❌"
                broker_emoji = "✅" if components.get("broker") == "connected" else "❌"

                # Entity stats
                entity_stats = stats.get("stats", {})

                embed = disnake.Embed(
                    title="📊 Статистика API",
                    description=f"{status_emoji} **Статус**: {status.capitalize()}",
                    color=0x00BCD4 if status == "healthy" else 0xFFC107,
                )
                embed.add_field(name="⏱️ Аптайм", value=uptime_str, inline=True)
                embed.add_field(
                    name="📦 Версия", value=stats.get("version", "?"), inline=True
                )
                embed.add_field(name="\u200b", value="\u200b", inline=True)  # spacer

                embed.add_field(
                    name="💾 Компоненты",
                    value=f"{db_emoji} База данных\n{broker_emoji} RabbitMQ",
                    inline=True,
                )
                embed.add_field(
                    name="📈 Сущности",
                    value=(
                        f"**Стримеров**: {entity_stats.get('streamers_total', 0)}\n"
                        f"**Онлайн**: {entity_stats.get('streamers_online', 0)}\n"
                        f"**Активных спеков**: {entity_stats.get('active_specs', 0)}"
                    ),
                    inline=True,
                )

                await interaction.followup.send(embed=embed, ephemeral=True)

            elif custom_id == "admin_svc_respawn":
                if not await self.bot.ensure_user_permissions(
                    interaction,
                    require_any=SERVICE_REFRESH_PERMS,
                    error_message="❌ Нет прав на пересоздание сервисных панелей.",
                ):
                    return
                settings = await self.bot.api_client.get_guild_settings()
                if not settings:
                    await interaction.followup.send(
                        "❌ Настройки не найдены", ephemeral=True
                    )
                    return

                messages_recreated = []

                # Recreate Control Panel
                cp_channel_id = settings.get("control_panel_channel_id")
                if cp_channel_id:
                    channel = self.bot.get_channel(int(cp_channel_id))
                    if channel:
                        old_msg_id = settings.get("control_panel_message_id")
                        if old_msg_id:
                            try:
                                old_msg = await channel.fetch_message(int(old_msg_id))
                                await old_msg.delete()
                            except Exception:
                                pass

                        embed = get_main_embed()
                        msg = await channel.send(
                            embed=embed, view=AdminControlPanelView(self.bot)
                        )
                        await self.bot.api_client.update_guild_settings(
                            control_panel_message_id=msg.id
                        )
                        messages_recreated.append("Панель управления")

                # Recreate Monitoring launcher
                mon_channel_id = settings.get("monitoring_channel_id")
                if mon_channel_id:
                    channel = self.bot.get_channel(int(mon_channel_id))
                    if channel:
                        # Delete old monitoring messages
                        old_mon_msg_id = settings.get("monitoring_message_id")
                        if old_mon_msg_id:
                            try:
                                old_msg = await channel.fetch_message(int(old_mon_msg_id))
                                await old_msg.delete()
                            except Exception:
                                pass

                        # Send new launcher message
                        from cogs.spec.manager import MonitoringLauncherView
                        embed = disnake.Embed(
                            title="📊 Мониторинг стримеров",
                            description=(
                                "Нажмите кнопку ниже, чтобы открыть мониторинг.\n\n"
                                "Мониторинг показывает текущий статус всех стримеров, "
                                "а также позволяет закрепиться или открепиться."
                            ),
                            color=0x2B2D31,
                        )
                        msg = await channel.send(embed=embed, view=MonitoringLauncherView())
                        await self.bot.api_client.update_guild_settings(
                            monitoring_message_id=msg.id,
                        )
                        messages_recreated.append("Мониторинг")

                if messages_recreated:
                    await interaction.followup.send(
                        f"✅ Пересозданы: {', '.join(messages_recreated)}",
                        ephemeral=True,
                    )
                else:
                    await interaction.followup.send(
                        "ℹ️ Нечего пересоздавать", ephemeral=True
                    )

        except Exception as e:
            self.bot.logger.error(
                f"Service button error {custom_id}: {e}", exc_info=True
            )
            try:
                await interaction.followup.send(f"❌ Ошибка: {e}", ephemeral=True)
            except:  # noqa: E722
                pass


def setup(bot: commands.Bot) -> None:
    bot.add_cog(AdminService(bot))
