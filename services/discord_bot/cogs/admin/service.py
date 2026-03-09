"""Admin Service - runtime tools, sync actions, and service overview."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api_client import APIClient
    from discord_bot import DiscordBot

from datetime import datetime, timezone

import disnake
from disnake import MessageInteraction
from disnake.ext import commands

from .core import AdminControlPanelView, get_main_embed
from versioning import APP_VERSION

SERVICE_SECTION_PERMS = [
    "monitoring.view",
    "streamers.status.update",
    "guild.settings.update",
]
SERVICE_VIEW_PERMS = ["monitoring.view"]
SERVICE_SYNC_PERMS = ["streamers.status.update"]
SERVICE_PANEL_PERMS = ["guild.settings.update"]


def _status_icon(value: str) -> str:
    return {
        "healthy": "🟢",
        "online": "🟢",
        "connected": "🟢",
        "ready": "🟢",
        "syncing": "🟡",
        "degraded": "🟡",
        "stale": "🟠",
        "offline": "🔴",
        "disconnected": "🔴",
        "error": "🔴",
    }.get(value, "⚪")


def _severity_rank(value: str) -> int:
    return {
        "error": 3,
        "offline": 3,
        "disconnected": 3,
        "stale": 2,
        "degraded": 2,
        "syncing": 1,
        "healthy": 0,
        "online": 0,
        "connected": 0,
        "ready": 0,
    }.get(value, 1)


def _severity_label(rank: int) -> str:
    return {
        3: "Критично",
        2: "Деградация",
        1: "Активность",
        0: "Стабильно",
    }.get(rank, "Неизвестно")


def _severity_color(rank: int) -> int:
    return {
        3: 0xD32F2F,
        2: 0xF57C00,
        1: 0xFBC02D,
        0: 0x009688,
    }.get(rank, 0x607D8B)


def _format_duration(seconds: int | float | None) -> str:
    if seconds is None:
        return "n/a"

    total = max(0, int(seconds))
    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)

    if days:
        return f"{days}д {hours}ч {minutes}м"
    if hours:
        return f"{hours}ч {minutes}м"
    if minutes:
        return f"{minutes}м {secs}с"
    return f"{secs}с"


def _format_bool(value: object) -> str:
    return "да" if bool(value) else "нет"


def _format_heartbeat_age(value: object) -> str:
    if value is None:
        return "нет heartbeat"
    if not isinstance(value, (int, float)):
        return "unknown"
    return _format_duration(int(value))


def _build_incident_summary(
    api_stats: dict,
    discord_service: dict,
    twitch_service: dict,
) -> tuple[int, list[str]]:
    incidents: list[tuple[int, str]] = []

    api_status = str(api_stats.get("status", "unknown"))
    if api_status != "healthy":
        incidents.append(
            (_severity_rank(api_status), f"{_status_icon(api_status)} API: `{api_status}`")
        )

    db_status = str(api_stats.get("components", {}).get("database", {}).get("status", "unknown"))
    if db_status != "connected":
        incidents.append(
            (_severity_rank(db_status), f"{_status_icon(db_status)} БД: `{db_status}`")
        )

    broker_status = str(api_stats.get("components", {}).get("broker", {}).get("status", "unknown"))
    if broker_status != "connected":
        incidents.append(
            (
                _severity_rank(broker_status),
                f"{_status_icon(broker_status)} RabbitMQ: `{broker_status}`",
            )
        )

    for name, service in (
        ("Discord", discord_service),
        ("Twitch", twitch_service),
    ):
        service_status = str(service.get("status", "offline"))
        if service_status not in {"online"}:
            incidents.append(
                (
                    _severity_rank(service_status),
                    f"{_status_icon(service_status)} {name}: `{service_status}`",
                )
            )

    twitch_sync_status = str(twitch_service.get("details", {}).get("last_sync_status", "unknown"))
    if twitch_sync_status in {"error", "syncing"}:
        incidents.append(
            (
                _severity_rank(twitch_sync_status),
                f"{_status_icon(twitch_sync_status)} Twitch sync: `{twitch_sync_status}`",
            )
        )

    incidents.sort(key=lambda item: item[0], reverse=True)
    if not incidents:
        return 0, ["🟢 Инцидентов не обнаружено"]

    highest = incidents[0][0]
    return highest, [item[1] for item in incidents[:4]]


# =============================================================================
# Service Embed
# =============================================================================


async def get_service_embed(bot) -> disnake.Embed:
    """Create embed showing bot status."""
    ping = round(bot.latency * 1000)

    # Calculate uptime if available
    uptime_str = "N/A"
    if hasattr(bot, "_start_time"):
        delta = datetime.now(timezone.utc) - bot._start_time
        days = delta.days
        hours, rem = divmod(delta.seconds, 3600)
        minutes = rem // 60
        uptime_str = f"{days}д {hours}ч {minutes}м"

    service_overview = await bot.api_client.get_service_overview()
    api_status = service_overview.get("api", {}) if isinstance(service_overview, dict) else {}
    domain = service_overview.get("domain", {}) if isinstance(service_overview, dict) else {}
    services = {
        item.get("service_name"): item
        for item in (service_overview.get("services", []) if isinstance(service_overview, dict) else [])
        if isinstance(item, dict)
    }
    discord_service = services.get("discord_service", {})
    twitch_service = services.get("twitch_service", {})
    severity_rank, incidents = _build_incident_summary(
        api_status,
        discord_service,
        twitch_service,
    )
    service_state = _severity_label(severity_rank)

    embed = disnake.Embed(
        title="🛠️ Сервисное Меню",
        description=(
            f"**Состояние контура:** `{service_state}`\n"
            f"{incidents[0]}\n\n"
            f"**Discord Bot**\n"
            f"📶 Gateway: `{ping}ms`\n"
            f"⏱️ Uptime: `{uptime_str}`\n"
            f"📦 Версия: `v{APP_VERSION}`\n\n"
            f"**Коротко**\n"
            f"API: `{api_status.get('status', 'unknown')}`\n"
            f"Стримеров online: `{domain.get('streamers_online', '?')}` / `{domain.get('streamers_total', '?')}`\n"
            f"Активных спеков: `{domain.get('active_spec_sessions', '?')}`\n"
            f"Событий: `{domain.get('active_events', '?')}`"
        ),
        color=_severity_color(severity_rank),
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

        if has_any(SERVICE_SYNC_PERMS):
            self.add_item(
                disnake.ui.Button(
                    label="🔄 Синхронизация Twitch",
                    custom_id="admin_svc_sync",
                    style=disnake.ButtonStyle.primary,
                    row=0,
                )
            )
        if has_any(SERVICE_PANEL_PERMS):
            self.add_item(
                disnake.ui.Button(
                    label="🔄 Пересоздать панели",
                    custom_id="admin_svc_respawn",
                    style=disnake.ButtonStyle.secondary,
                    row=0,
                )
            )

        if has_any(SERVICE_VIEW_PERMS):
            self.add_item(
                disnake.ui.Button(
                    label="📊 Статус сервисов",
                    custom_id="admin_svc_service_stats",
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
            bot._start_time = datetime.now(timezone.utc)

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
                    require_any=SERVICE_SYNC_PERMS,
                    error_message="❌ Нет прав на запуск синхронизации.",
                ):
                    return
                sync_started = await self.bot.api_client.trigger_twitch_sync()
                if sync_started:
                    await interaction.followup.send(
                        "✅ Полная синхронизация Twitch запущена. Бот пересоберет подписки и заново обновит статусы всех стримеров.",
                        ephemeral=True,
                    )
                else:
                    await interaction.followup.send(
                        "❌ Не удалось запустить синхронизацию. Проверь API и RabbitMQ.",
                        ephemeral=True,
                    )

            elif custom_id == "admin_svc_service_stats":
                if not await self.bot.ensure_user_permissions(
                    interaction,
                    require_any=SERVICE_VIEW_PERMS,
                    error_message="❌ Нет прав на просмотр системной статистики.",
                ):
                    return
                overview = await self.bot.api_client.get_service_overview() or {}
                api_stats = overview.get("api", {})
                domain = overview.get("domain", {})
                services = {
                    item.get("service_name"): item
                    for item in overview.get("services", [])
                    if isinstance(item, dict)
                }
                twitch = services.get("twitch_service", {})
                discord_service = services.get("discord_service", {})
                api_status = api_stats.get("status", "unknown")
                db = api_stats.get("components", {}).get("database", {})
                broker = api_stats.get("components", {}).get("broker", {})
                twitch_details = twitch.get("details", {})
                discord_details = discord_service.get("details", {})
                severity_rank, incidents = _build_incident_summary(
                    api_stats,
                    discord_service,
                    twitch,
                )
                uptime_str = _format_duration(api_stats.get("uptime_seconds"))
                service_state = _severity_label(severity_rank)
                incident_text = "\n".join(incidents)
                sync_duration = _format_duration(
                    twitch_details.get("last_sync_duration_seconds")
                )

                embed = disnake.Embed(
                    title="📊 Статус сервисов",
                    description=(
                        f"**Общий статус:** `{service_state}`\n"
                        f"**Инциденты:**\n{incident_text}"
                    ),
                    color=_severity_color(severity_rank),
                )
                embed.add_field(
                    name="🧭 Контур",
                    value=(
                        f"{_status_icon(api_status)} API: `{api_status}`\n"
                        f"{_status_icon(discord_service.get('status', 'offline'))} Discord: `{discord_service.get('status', 'offline')}`\n"
                        f"{_status_icon(twitch.get('status', 'offline'))} Twitch: `{twitch.get('status', 'offline')}`"
                    ),
                    inline=True,
                )
                embed.add_field(
                    name="📦 API",
                    value=(
                        f"Версия: `v{api_stats.get('version', '?')}`\n"
                        f"Аптайм: `{uptime_str}`\n"
                        f"Обновлено: `{overview.get('generated_at', 'unknown')}`"
                    ),
                    inline=True,
                )
                embed.add_field(
                    name="🧩 Зависимости",
                    value=(
                        f"{_status_icon(db.get('status', 'unknown'))} DB: `{db.get('status', 'unknown')}` ({db.get('latency_ms', '?')} ms)\n"
                        f"{_status_icon(broker.get('status', 'unknown'))} RabbitMQ: `{broker.get('status', 'unknown')}`"
                    ),
                    inline=True,
                )
                embed.add_field(
                    name="📈 Домен",
                    value=(
                        f"Стримеров: `{domain.get('streamers_total', 0)}`\n"
                        f"Online: `{domain.get('streamers_online', 0)}`\n"
                        f"GTA: `{domain.get('gta_online', 0)}`\n"
                        f"Спеки: `{domain.get('active_spec_sessions', 0)}`\n"
                        f"Стажёрские: `{domain.get('probation_sessions', 0)}`\n"
                        f"События: `{domain.get('active_events', 0)}`"
                    ),
                    inline=True,
                )
                embed.add_field(
                    name="🤖 Discord",
                    value=(
                        f"Gateway: `{discord_details.get('gateway_latency_ms', round(self.bot.latency * 1000))} ms`\n"
                        f"Target guild: `{_format_bool(discord_details.get('target_guild_connected', True))}`\n"
                        f"Broker: `{_format_bool(discord_details.get('broker_connected', False))}`\n"
                        f"Heartbeat age: `{_format_heartbeat_age(discord_service.get('heartbeat_age_seconds'))}`"
                    ),
                    inline=True,
                )
                embed.add_field(
                    name="🛰️ Twitch",
                    value=(
                        f"Sync: `{twitch_details.get('last_sync_status', 'unknown')}`\n"
                        f"Длительность sync: `{sync_duration}`\n"
                        f"Стримеров: `{twitch_details.get('tracked_streamers', 0)}`\n"
                        f"Online: `{twitch_details.get('online_streamers', 0)}`\n"
                        f"Подписок: `{twitch_details.get('subscription_targets', 0)}`\n"
                        f"Heartbeat age: `{_format_heartbeat_age(twitch.get('heartbeat_age_seconds'))}`"
                    ),
                    inline=True,
                )
                embed.add_field(
                    name="🗂️ Управление",
                    value=(
                        f"Ассистентов: `{domain.get('assistants_total', 0)}`\n"
                        f"Web users: `{domain.get('web_users_total', 0)}`\n"
                        f"Admin actions 24h: `{domain.get('admin_actions_24h', 0)}`"
                    ),
                    inline=True,
                )
                if twitch_details.get("last_sync_error"):
                    embed.add_field(
                        name="⚠️ Последняя ошибка Twitch sync",
                        value=f"`{twitch_details.get('last_sync_error')}`",
                        inline=False,
                    )

                await interaction.followup.send(embed=embed, ephemeral=True)

            elif custom_id == "admin_svc_respawn":
                if not await self.bot.ensure_user_permissions(
                    interaction,
                    require_any=SERVICE_PANEL_PERMS,
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
