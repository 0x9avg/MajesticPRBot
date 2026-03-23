"""Spec Manager - Claim/Unclaim system for PR assistants.

All interactions via BUTTONS only.
Monitoring uses ephemeral paginated messages triggered by a launcher button.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api_client import APIClient
    from discord_bot import DiscordBot

import disnake
from disnake.ext import commands
from config import Config
from utils import (
    create_notification_component,
    create_streamers_component,
    format_spec_duration,
    safe_defer,
)

SPEC_VIEW_CLAIMABLE_PERMS = ["spec.claimable.view"]
SPEC_CLAIM_MAIN_PERMS = ["spec.claim.main"]
SPEC_CLAIM_PROBATION_ALL_PERMS = ["spec.claim.probation"]
SPEC_UNCLAIM_PERMS = ["spec.unclaim.self"]
EVENT_JOIN_PERMS = ["events.participation.self.join"]
EVENT_LEAVE_PERMS = ["events.participation.self.leave"]


class MonitoringLauncherView(disnake.ui.View):
    """Persistent launcher view for opening per-user monitoring panel."""

    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(
            disnake.ui.Button(
                label="Открыть мониторинг",
                custom_id="monitoring_open",
                emoji="📊",
                style=disnake.ButtonStyle.primary,
            )
        )


class Spec(commands.Cog):
    """Spec system for PR assistants to track streamers.

    All spec interactions are through BUTTONS:
    - spec_claim_{streamer_id} - Claim a streamer
    - spec_unclaim_{streamer_id} - Unclaim a streamer
    - probation_choice_main_{streamer_id} - Choose main spec
    - probation_choice_prob_{streamer_id} - Choose probation spec
    - monitoring_open - Open ephemeral monitoring panel
    - monitoring_page_prev/next - Paginate monitoring

    Transfer is initiated from AssistantsView in admin panel.
    """

    bot: "DiscordBot"
    api: "APIClient"

    def __init__(self, bot: "DiscordBot") -> None:
        self.bot = bot
        self.api = bot.api_client
        self.logger = bot.logger

    @commands.Cog.listener()
    async def on_ready(self):
        """Register persistent views and ensure launcher message exists."""
        self.bot.add_view(MonitoringLauncherView())
        self.logger.info("✓ MonitoringLauncherView registered")
        try:
            await self._ensure_monitoring_message()
        except Exception as e:
            self.logger.error(f"Failed to ensure monitoring message on ready: {e}")

    async def _ensure_spec_action_permission(
        self,
        interaction: disnake.MessageInteraction,
        custom_id: str,
    ) -> bool:
        """Enforce per-action RBAC for spec/event actions in Discord UI."""
        if custom_id.startswith("spec_claim_"):
            return await self.bot.ensure_user_permissions(
                interaction,
                require_any=SPEC_CLAIM_MAIN_PERMS,
                error_message="❌ Нет прав на закрепление.",
            )
        if custom_id.startswith("spec_unclaim_"):
            return await self.bot.ensure_user_permissions(
                interaction,
                require_any=SPEC_UNCLAIM_PERMS,
                error_message="❌ Нет прав на открепление.",
            )
        if custom_id.startswith("probation_choice_main_"):
            return await self.bot.ensure_user_permissions(
                interaction,
                require_any=SPEC_CLAIM_MAIN_PERMS,
                error_message="❌ Нет прав на закрепление.",
            )
        if custom_id.startswith("probation_choice_prob_"):
            return await self.bot.ensure_user_permissions(
                interaction,
                require_all=SPEC_CLAIM_PROBATION_ALL_PERMS,
                error_message="❌ Нет прав на стажерский спек.",
            )
        if custom_id == "monitoring_open":
            return await self.bot.ensure_user_permissions(
                interaction,
                require_any=SPEC_VIEW_CLAIMABLE_PERMS,
                error_message="❌ Нет прав на просмотр мониторинга.",
            )
        if custom_id == "monitoring_claim":
            return await self.bot.ensure_user_permissions(
                interaction,
                require_any=SPEC_VIEW_CLAIMABLE_PERMS,
                error_message="❌ Нет прав на просмотр доступных закреплений.",
            )
        if custom_id == "monitoring_unclaim":
            return await self.bot.ensure_user_permissions(
                interaction,
                require_any=[*SPEC_UNCLAIM_PERMS, *EVENT_LEAVE_PERMS],
                error_message="❌ Нет прав на открепление.",
            )
        if custom_id.startswith("monitoring_page_"):
            return await self.bot.ensure_user_permissions(
                interaction,
                require_any=SPEC_VIEW_CLAIMABLE_PERMS,
                error_message="❌ Нет прав на просмотр мониторинга.",
            )
        if custom_id.startswith("claim_page_"):
            return await self.bot.ensure_user_permissions(
                interaction,
                require_any=SPEC_VIEW_CLAIMABLE_PERMS,
                error_message="❌ Нет прав на просмотр доступных закреплений.",
            )
        return True

    # =========================================================================
    # Button Handlers
    # =========================================================================

    @commands.Cog.listener("on_button_click")
    async def on_spec_button(self, interaction: disnake.MessageInteraction):
        """Handle all spec-related button clicks."""
        custom_id = interaction.component.custom_id or ""

        if not custom_id.startswith(
            (
                "spec_",
                "probation_choice_",
                "monitoring_",
                "claim_page_",
                "claim_select_",
            )
        ):
            return

        # monitoring_open gets a fresh ephemeral response, not deferred
        if custom_id == "monitoring_open":
            if not await self._ensure_spec_action_permission(interaction, custom_id):
                return
            await self._handle_monitoring_open(interaction)
            return

        # monitoring_page_* edits the existing ephemeral response
        if custom_id.startswith("monitoring_page_"):
            if not await self._ensure_spec_action_permission(interaction, custom_id):
                return
            await self._handle_monitoring_page(interaction, custom_id)
            return

        if not await self._ensure_spec_action_permission(interaction, custom_id):
            return

        if not custom_id.startswith(("probation_choice_", "claim_select_")):
            try:
                if not interaction.response.is_done():
                    await interaction.response.defer(ephemeral=True)
            except Exception as e:
                self.logger.warning(f"Defer failed: {e}")

        try:
            if custom_id.startswith("spec_claim_"):
                await self._handle_claim_button(interaction, custom_id)
            elif custom_id.startswith("spec_unclaim_"):
                await self._handle_unclaim_button(interaction, custom_id)

            elif custom_id.startswith("probation_choice_main_"):
                streamer_id = int(custom_id.replace("probation_choice_main_", ""))
                await self._do_claim(
                    interaction, streamer_id, interaction.user.id, is_probation=False
                )
            elif custom_id.startswith("probation_choice_prob_"):
                streamer_id = int(custom_id.replace("probation_choice_prob_", ""))
                await self._do_claim(
                    interaction, streamer_id, interaction.user.id, is_probation=True
                )
            elif custom_id == "monitoring_claim":
                await self._handle_monitoring_claim(interaction)
            elif custom_id == "monitoring_unclaim":
                await self._handle_monitoring_unclaim(interaction)
            elif custom_id.startswith("claim_page_"):
                parts = custom_id.split("_")
                direction = parts[2]
                current_page = int(parts[3])
                new_page = current_page + 1 if direction == "next" else current_page - 1
                await self._show_claim_selector(interaction, page=new_page)
        except Exception as e:
            self.logger.error(f"Spec button error {custom_id}: {e}", exc_info=True)
            try:
                await interaction.followup.send("❌ Ошибка.", ephemeral=True)
            except Exception as e:
                self.logger.debug(f"Failed to send error response: {e}")

    async def _handle_claim_button(
        self, interaction: disnake.MessageInteraction, custom_id: str
    ):
        """Handle claim button click (with Probation support)."""
        try:
            if not await self.bot.ensure_user_permissions(
                interaction,
                require_any=SPEC_CLAIM_MAIN_PERMS,
                error_message="❌ Нет прав на закрепление.",
            ):
                return

            streamer_id = int(custom_id.replace("spec_claim_", ""))
            pr_id = interaction.user.id

            data = await self.api.get_claimable_streamers(pr_id)
            if not data:
                await interaction.followup.send(
                    "❌ Ошибка при проверке статуса стримера.", ephemeral=True
                )
                return

            # Check if PR is already assigned
            if data.get("assigned_to_type"):
                target_name = data.get("assigned_to_name", "кем-то")
                await interaction.followup.send(
                    f"❌ Вы уже закреплены за {data.get('assigned_to_type') == 'event' and 'событием' or 'стримером'} **{target_name}**.",
                    ephemeral=True,
                )
                return

            claimable = False
            for s in data.get("streamers", []):
                if str(s.get("streamer_id")) == str(streamer_id):
                    claimable = True
                    break

            if not claimable:
                from config import Config

                streamer = await self.api.get_streamer(streamer_id)
                error_msg = "❌ Стример больше не доступен для закрепления."
                if streamer:
                    if not streamer.get("is_online"):
                        error_msg = "❌ Стример в оффлайне."
                    elif str(streamer.get("game_id", "")) != Config.gta5_game_id:
                        error_msg = "❌ Стример не в категории GTA 5."
                    else:
                        error_msg = "❌ Слоты для закрепления уже заняты."
                await interaction.followup.send(error_msg, ephemeral=True)
                return

            can_spec_probation = data.get("can_spec_probation", False)

            if can_spec_probation:
                # Show probation prompt for eligible users
                await self._show_probation_prompt(interaction, streamer_id)
                return

            # Standard flow for regular users
            await self._do_claim(interaction, streamer_id, pr_id, is_probation=False)

        except Exception as e:
            self.logger.error(f"Error claim button: {e}", exc_info=True)
            await interaction.followup.send("❌ Ошибка.", ephemeral=True)

    async def _show_probation_prompt(
        self, interaction: disnake.MessageInteraction, streamer_id: int
    ):
        """Show probation/main spec choice buttons (ephemeral)."""
        view = disnake.ui.View(timeout=None)

        main_btn = disnake.ui.Button(
            label="🔵 Основной спек",
            style=disnake.ButtonStyle.primary,
            custom_id=f"probation_choice_main_{streamer_id}",
        )
        probation_btn = disnake.ui.Button(
            label="🟡 Стажерский спек",
            style=disnake.ButtonStyle.secondary,
            custom_id=f"probation_choice_prob_{streamer_id}",
        )

        view.add_item(main_btn)
        view.add_item(probation_btn)

        await interaction.followup.send(
            "**Выберите тип спека:**\n"
            "🔵 **Основной спек** — полная ставка баллов\n"
            "🟡 **Стажерский спек** — стажерская ставка",
            view=view,
            ephemeral=True,
        )

    async def _do_claim(
        self,
        interaction: disnake.MessageInteraction,
        streamer_id: int,
        pr_id: int,
        is_probation: bool,
    ):
        """Perform the actual claim operation."""
        if is_probation:
            if not await self.bot.ensure_user_permissions(
                interaction,
                require_all=SPEC_CLAIM_PROBATION_ALL_PERMS,
                error_message="❌ Нет прав на стажерский спек.",
            ):
                return
        else:
            if not await self.bot.ensure_user_permissions(
                interaction,
                require_any=SPEC_CLAIM_MAIN_PERMS,
                error_message="❌ Нет прав на закрепление.",
            ):
                return

        # Ensure deferred
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except Exception as e:
            self.logger.debug(f"Defer failed: {e}")

        self.logger.debug(
            f"[User {pr_id}] Claiming streamer {streamer_id}. Probation: {is_probation}. BEFORE: sending API request."
        )
        result = await self.api.claim_streamer(
            streamer_id, pr_id, is_probation=is_probation
        )
        self.logger.debug(
            f"[User {pr_id}] Claim streamer {streamer_id} result AFTER: {result}"
        )

        if result and "streamer_id" in result:
            streamer_name = result.get("streamer_name")
            spec_type = "Стажерский" if is_probation else "Основной"

            # Update notification message to show "Claimed by X"
            try:
                streamer = await self.api.get_streamer(streamer_id)
                # streamer can be None if not found
                if streamer and hasattr(interaction, "message") and interaction.message:
                    new_components = create_notification_component(
                        message="",
                        streamer_name=streamer.get("streamer_name", streamer_name),
                        stream_title=streamer.get("stream_title", ""),
                        game_name=streamer.get("game_name", "GTA 5"),
                        thumbnail_url=streamer.get("stream_thumbnail_url", ""),
                        streamer_id=streamer_id,
                        show_claim_button=True,
                        assigned_pr_id=pr_id,
                        assigned_pr_name=interaction.user.display_name,
                        is_probation=is_probation,
                    )
                    await interaction.message.edit(components=new_components)
            except Exception as e:
                self.logger.warning(f"Could not update notification message: {e}")

            await interaction.followup.send(
                f"✅ Успешно закреплен ({spec_type}): **{streamer_name}**",
                ephemeral=True,
            )
        else:
            error = result.get("detail", "Ошибка") if result else "API Error"
            await interaction.followup.send(f"❌ {error}", ephemeral=True)

    async def _handle_unclaim_button(
        self, interaction: disnake.MessageInteraction, custom_id: str
    ):
        """Handle unclaim button click."""
        try:
            if not await self.bot.ensure_user_permissions(
                interaction,
                require_any=SPEC_UNCLAIM_PERMS,
                error_message="❌ Нет прав на открепление.",
            ):
                return

            streamer_id = int(custom_id.replace("spec_unclaim_", ""))
            pr_id = interaction.user.id

            self.logger.debug(
                f"[User {pr_id}] Unclaiming streamer {streamer_id}. BEFORE: sending API request."
            )
            result = await self.api.unclaim_streamer(
                streamer_id, pr_id=pr_id, reason="manual_unclaim"
            )
            self.logger.debug(
                f"[User {pr_id}] Unclaim streamer {streamer_id} result AFTER: {result}"
            )

            if result and "duration_seconds" in result:
                duration_str = format_spec_duration(result.get("duration_seconds", 0))

                await interaction.followup.send(
                    f"✅ Ты открепился от **{result.get('streamer_name')}**.\n"
                    f"⏱️ Время спека: **{duration_str}**",
                    ephemeral=True,
                )
            else:
                error = result.get("detail", "Ошибка") if result else "API Error"
                await interaction.followup.send(f"❌ {error}", ephemeral=True)

        except Exception as e:
            self.logger.error(f"Error unclaim button: {e}")
            await interaction.followup.send("❌ Ошибка.", ephemeral=True)

    # =========================================================================
    # Monitoring Claim/Unclaim Flow (new UI)
    # =========================================================================

    async def _handle_monitoring_unclaim(self, interaction: disnake.MessageInteraction):
        """Handle 'Unclaim' button from monitoring UI."""
        pr_id = interaction.user.id

        # Check if user has active spec
        current = await self.api.get_pr_current_streamer(pr_id)

        if not current:
            await interaction.followup.send(
                "❌ Ты не закреплен ни за кем.", ephemeral=True
            )
            return

        # Unclaim
        if "streamer_id" in current:
            if not await self.bot.ensure_user_permissions(
                interaction,
                require_any=SPEC_UNCLAIM_PERMS,
                error_message="❌ Нет прав на открепление от стримеров.",
            ):
                return
            streamer_id = current["streamer_id"]
            result = await self.api.unclaim_streamer(
                streamer_id, pr_id=pr_id, reason="manual_unclaim"
            )

            if result and "duration_seconds" in result:
                duration_str = format_spec_duration(result.get("duration_seconds", 0))
                await interaction.followup.send(
                    f"✅ Ты открепился от **{result.get('streamer_name')}**.\n"
                    f"⏱️ Время спека: **{duration_str}**",
                    ephemeral=True,
                )
            else:
                error = result.get("detail", "Ошибка") if result else "API Error"
                await interaction.followup.send(f"❌ {error}", ephemeral=True)
        elif "event_id" in current:
            if not await self.bot.ensure_user_permissions(
                interaction,
                require_any=EVENT_LEAVE_PERMS,
                error_message="❌ Нет прав на выход из события.",
            ):
                return
            event_id = current.get("event_id")
            # For events, service route explicitly targets PR id.
            result = await self.api._request(
                "POST", f"/events/{event_id}/leave/{pr_id}"
            )
            if result and "event_id" in result:
                await interaction.followup.send(
                    "✅ Вы покинули событие.", ephemeral=True
                )
            else:
                error = (
                    result.get("detail", result.get("message", "Ошибка"))
                    if isinstance(result, dict)
                    else "API Error"
                )
                await interaction.followup.send(f"❌ {error}", ephemeral=True)

    async def _handle_monitoring_claim(self, interaction: disnake.MessageInteraction):
        """Handle 'Claim' button from monitoring UI - show paginated selector."""
        if not await self.bot.ensure_user_permissions(
            interaction,
            require_any=SPEC_VIEW_CLAIMABLE_PERMS,
            error_message="❌ Нет прав на просмотр доступных закреплений.",
        ):
            return
        await self._show_claim_selector(interaction, page=0)

    async def _show_claim_selector(
        self, interaction: disnake.MessageInteraction, page: int = 0
    ):
        """Show paginated claim selector."""
        if not await self.bot.ensure_user_permissions(
            interaction,
            require_any=SPEC_VIEW_CLAIMABLE_PERMS,
            error_message="❌ Нет прав на просмотр доступных закреплений.",
        ):
            return

        user_id = interaction.user.id

        # Get claimable streamers from API
        data = await self.api.get_claimable_streamers(user_id)
        streamers = data.get("streamers", [])
        can_spec_probation = data.get("can_spec_probation", False)

        if not streamers:
            await interaction.followup.send(
                "❌ Нет доступных стримеров для закрепления.",
                ephemeral=True,
            )
            return

        # Pagination
        per_page = 6
        total_pages = (len(streamers) + per_page - 1) // per_page
        page = max(0, min(page, total_pages - 1))
        start = page * per_page
        end = start + per_page
        page_streamers = streamers[start:end]

        # Build select options
        options = []
        for s in page_streamers:
            streamer_id = s["streamer_id"]
            streamer_name = s["streamer_name"]
            priority = s.get("priority", 3)
            main_free = s.get("main_free", True)
            prob_free = s.get("probation_free", True)

            # Determine description based on availability
            if can_spec_probation:
                if main_free and prob_free:
                    desc = "Доступен: Основной / Стажерский"
                elif main_free:
                    desc = "Доступен: Основной"
                else:
                    desc = "Доступен: Стажерский"
            else:
                desc = "Доступен: Основной"

            options.append(
                disnake.SelectOption(
                    label=f"[P{priority}] {streamer_name}",
                    value=str(streamer_id),
                    description=desc,
                )
            )

        # Build view with select and pagination buttons
        view = disnake.ui.View(timeout=None)

        select = disnake.ui.StringSelect(
            custom_id="claim_select_streamer",
            placeholder=f"Выбери стримера (стр. {page + 1}/{total_pages})",
            options=options,
        )
        view.add_item(select)

        # Pagination buttons
        if total_pages > 1:
            view.add_item(
                disnake.ui.Button(
                    label="◀ Назад",
                    custom_id=f"claim_page_prev_{page}",
                    style=disnake.ButtonStyle.secondary,
                    disabled=(page <= 0),
                )
            )
            view.add_item(
                disnake.ui.Button(
                    label="Вперёд ▶",
                    custom_id=f"claim_page_next_{page}",
                    style=disnake.ButtonStyle.secondary,
                    disabled=(page >= total_pages - 1),
                )
            )

        # Edit or send message
        try:
            await interaction.edit_original_response(
                content=f"**Выбери стримера для закрепления** ({len(streamers)} доступно)",
                view=view,
            )
        except:  # noqa: E722
            await interaction.followup.send(
                content=f"**Выбери стримера для закрепления** ({len(streamers)} доступно)",
                view=view,
                ephemeral=True,
            )

    @commands.Cog.listener("on_dropdown")
    async def on_claim_select(self, interaction: disnake.MessageInteraction):
        """Handle streamer selection from claim selector."""
        custom_id = interaction.component.custom_id or ""

        if custom_id != "claim_select_streamer":
            return

        if not await self.bot.ensure_user_permissions(
            interaction,
            require_any=SPEC_VIEW_CLAIMABLE_PERMS,
            error_message="❌ Нет прав на просмотр доступных закреплений.",
        ):
            return

        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except:  # noqa: E722
            pass

        try:
            # Handle Event claim
            if str(interaction.values[0]).startswith("event_"):
                event_id = int(str(interaction.values[0]).replace("event_", ""))
                user_id = interaction.user.id
                if not await self.bot.ensure_user_permissions(
                    interaction,
                    require_any=EVENT_JOIN_PERMS,
                    error_message="❌ Нет прав на присоединение к событиям.",
                ):
                    return

                result = await self.api.join_event(event_id, user_id)
                if result and "event_id" in result:
                    join_status = result.get("join_status", "joined")
                    if join_status == "reserved":
                        await interaction.followup.send(
                            "✅ Вы закреплены за событием. Спек начнётся при старте события.",
                            ephemeral=True,
                        )
                    else:
                        await interaction.followup.send(
                            "✅ Успешно закреплен за событием", ephemeral=True
                        )
                else:
                    error = (
                        result.get("detail", result.get("message", "Ошибка"))
                        if isinstance(result, dict)
                        else "API Error"
                    )
                    await interaction.followup.send(f"❌ {error}", ephemeral=True)
                return

            streamer_id = int(interaction.values[0])
            user_id = interaction.user.id

            # Get user capabilities and streamer info
            data = await self.api.get_claimable_streamers(user_id)

            # Check if PR is already assigned
            if data.get("assigned_to_type"):
                target_name = data.get("assigned_to_name", "кем-то")
                await interaction.followup.send(
                    f"❌ Вы уже закреплены за {data.get('assigned_to_type') == 'event' and 'событием' or 'стримером'} **{target_name}**.",
                    ephemeral=True,
                )
                return

            can_spec_probation = data.get("can_spec_probation", False)

            # Find selected streamer info
            selected = None
            for s in data.get("streamers", []):
                if str(s.get("streamer_id")) == str(streamer_id) or str(
                    s.get("event_id")
                ) == str(streamer_id):
                    selected = s
                    break

            if not selected:
                from config import Config

                streamer = await self.api.get_streamer(streamer_id)
                error_msg = "❌ Канал больше недоступен."
                if streamer:
                    if not streamer.get("is_online"):
                        error_msg = "❌ Стример в оффлайне."
                    elif str(streamer.get("game_id", "")) != Config.gta5_game_id:
                        error_msg = "❌ Стример не в категории GTA 5."
                    else:
                        error_msg = "❌ Слот занят."

                await interaction.followup.send(error_msg, ephemeral=True)
                return

            main_free = selected.get("main_free", True)
            prob_free = selected.get("probation_free", True)

            # Decision logic
            if not can_spec_probation:
                # Regular user -> auto main
                await self._do_claim(
                    interaction, streamer_id, user_id, is_probation=False
                )
            else:
                # Junior with probation capability
                if not main_free and prob_free:
                    # Main taken -> auto probation
                    await self._do_claim(
                        interaction, streamer_id, user_id, is_probation=True
                    )
                elif main_free and prob_free:
                    # Both free -> prompt choice
                    await self._show_probation_prompt(interaction, streamer_id)
                elif main_free:
                    # Only main free -> auto main
                    await self._do_claim(
                        interaction, streamer_id, user_id, is_probation=False
                    )
                else:
                    # Shouldn't happen, but fallback
                    await interaction.followup.send(
                        "❌ Нет доступных слотов.", ephemeral=True
                    )

        except Exception as e:
            self.logger.error(f"Claim select error: {e}", exc_info=True)
            await interaction.followup.send("❌ Ошибка.", ephemeral=True)

    # =========================================================================
    # Dropdown Handler (Monitoring Select)
    # =========================================================================

    @commands.Cog.listener("on_dropdown")
    async def on_spec_dropdown(self, interaction: disnake.MessageInteraction):
        """Handle dropdown selections from monitoring message."""
        custom_id = interaction.component.custom_id or ""

        if custom_id != "spec_claim_select":
            return

        if not await self.bot.ensure_user_permissions(
            interaction,
            require_any=SPEC_VIEW_CLAIMABLE_PERMS,
            error_message="❌ Нет прав на просмотр доступных закреплений.",
        ):
            return

        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except Exception as e:
            self.logger.debug(f"Defer failed: {e}")

        try:
            selected = interaction.values[0]
            if selected == "none":
                await interaction.followup.send(
                    "❌ Нет доступных стримеров.", ephemeral=True
                )
                return

            streamer_id = int(selected)
            # Reuse claim logic
            await self._handle_claim_button(interaction, f"spec_claim_{streamer_id}")

        except ValueError:
            await interaction.followup.send("❌ Некорректный ID.", ephemeral=True)
        except Exception as e:
            self.logger.error(f"Dropdown error: {e}", exc_info=True)
            await interaction.followup.send("❌ Ошибка.", ephemeral=True)

    # =========================================================================
    # Transfer Initiation (called from admin assistants panel)
    # =========================================================================

    # =========================================================================
    # Monitoring Launcher & Ephemeral Pagination
    # =========================================================================

    async def _ensure_monitoring_message(self):
        """Ensure the monitoring launcher message exists in the configured channel.

        Similar to AdminCore._ensure_control_panel: creates or updates a single
        persistent message with a 'Open monitoring' button.
        """
        try:
            settings = await self.api.get_guild_settings()
            if not settings:
                self.logger.warning(
                    "No guild settings found, skipping monitoring launcher"
                )
                return

            monitoring_channel_id = settings.get("monitoring_channel_id")
            if not monitoring_channel_id:
                self.logger.debug("No monitoring channel configured")
                return

            channel = self.bot.get_channel(int(monitoring_channel_id))
            if not channel:
                self.logger.warning(
                    f"Monitoring channel {monitoring_channel_id} not found"
                )
                return

            old_msg_id = settings.get("monitoring_message_id")
            old_msg = None

            if old_msg_id:
                try:
                    old_msg = await channel.fetch_message(int(old_msg_id))
                except (disnake.NotFound, disnake.Forbidden):
                    self.logger.info(
                        "Old monitoring launcher message not found, will create new"
                    )
                    old_msg = None
                except Exception as e:
                    self.logger.warning(
                        f"Error fetching monitoring launcher message: {e}"
                    )
                    old_msg = None

            embed = disnake.Embed(
                title="📊 Мониторинг стримеров",
                description=(
                    "Нажмите кнопку ниже, чтобы открыть мониторинг.\n\n"
                    "Мониторинг показывает текущий статус всех стримеров, "
                    "а также позволяет закрепиться или открепиться."
                ),
                color=0x2B2D31,
            )

            if old_msg:
                try:
                    await old_msg.edit(embed=embed, view=MonitoringLauncherView())
                    self.logger.info(
                        f"✓ Updated monitoring launcher in #{channel.name}"
                    )
                except Exception as e:
                    self.logger.error(f"Failed to edit monitoring launcher: {e}")
            else:
                # Delete old monitoring message
                old_msg_id = settings.get("monitoring_message_id")
                if old_msg_id:
                    try:
                        old_msg = await channel.fetch_message(int(old_msg_id))
                        await old_msg.delete()
                    except Exception:
                        pass

                msg = await channel.send(embed=embed, view=MonitoringLauncherView())
                await self.api.update_guild_settings(
                    monitoring_message_id=msg.id,
                )
                self.logger.info(f"✓ Monitoring launcher created in #{channel.name}")

        except Exception as e:
            self.logger.error(
                f"Failed to ensure monitoring launcher: {e}", exc_info=True
            )

    async def _handle_monitoring_open(self, interaction: disnake.MessageInteraction):
        """Handle 'Open monitoring' button — send ephemeral paginated monitoring."""
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except Exception as e:
            self.logger.warning(f"Defer failed for monitoring_open: {e}")
            return

        await self._send_monitoring_ephemeral(interaction, page=0)

    async def _handle_monitoring_page(
        self, interaction: disnake.MessageInteraction, custom_id: str
    ):
        """Handle monitoring pagination buttons."""
        # Format: monitoring_page_{next|prev}_{current_page}
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except Exception as e:
            self.logger.warning(f"Defer failed for monitoring page: {e}")
            return

        try:
            parts = custom_id.split("_")
            direction = parts[2]  # "next" or "prev"
            current_page = int(parts[3])
            new_page = current_page + 1 if direction == "next" else current_page - 1
            await self._send_monitoring_ephemeral(interaction, page=new_page)
        except (IndexError, ValueError) as e:
            self.logger.error(f"Invalid monitoring page custom_id: {custom_id}: {e}")
            await interaction.followup.send("❌ Ошибка пагинации.", ephemeral=True)

    async def _send_monitoring_ephemeral(
        self, interaction: disnake.MessageInteraction, page: int = 0
    ):
        """Build and send/edit an ephemeral monitoring page for the user."""
        try:
            # Fetch data from API
            status = await self.api.get_monitoring_status()
            if not status:
                await interaction.followup.send(
                    "❌ Не удалось получить данные мониторинга.", ephemeral=True
                )
                return

            settings = await self.api.get_guild_settings()

            online_streamers = status.get("online_streamers", [])
            active_events = status.get("active_events", [])
            total_count = status.get("total_streamers", 0)
            gta_count = status.get("gta_count", 0)
            online_count = status.get("online_count", len(online_streamers))

            # Apply GTA filter if enabled
            if settings:
                gta_filter = settings.get("monitoring_filter_gta", False)
                if gta_filter:
                    online_streamers = [
                        s
                        for s in online_streamers
                        if str(s.get("game_id")) == Config.gta5_game_id
                    ]

            # Generate all pages
            pages = create_streamers_component(
                online_streamers,
                total_count,
                gta_count,
                events=active_events,
                online_count=online_count,
            )

            total_pages = len(pages)
            page = max(0, min(page, total_pages - 1))

            # Current page container
            current_container = pages[page]

            # Build action row with pagination + claim/unclaim
            pr_id = interaction.user.id
            current_assignment = await self.api.get_pr_current_streamer(pr_id)

            buttons = []
            # Pagination: prev
            buttons.append(
                disnake.ui.Button(
                    label="◀",
                    custom_id=f"monitoring_page_prev_{page}",
                    style=disnake.ButtonStyle.secondary,
                    disabled=(page <= 0),
                )
            )

            # Context-aware claim / unclaim
            if current_assignment:
                buttons.append(
                    disnake.ui.Button(
                        label="📤 Открепиться",
                        custom_id="monitoring_unclaim",
                        style=disnake.ButtonStyle.danger,
                    )
                )
            else:
                buttons.append(
                    disnake.ui.Button(
                        label="📥 Закрепиться",
                        custom_id="monitoring_claim",
                        style=disnake.ButtonStyle.success,
                    )
                )

            # Pagination: next
            buttons.append(
                disnake.ui.Button(
                    label="▶",
                    custom_id=f"monitoring_page_next_{page}",
                    style=disnake.ButtonStyle.secondary,
                    disabled=(page >= total_pages - 1),
                )
            )

            action_row = disnake.ui.ActionRow(*buttons)
            page_components = [current_container, action_row]

            # Send or edit
            try:
                await interaction.edit_original_response(components=page_components)
            except Exception:
                await interaction.followup.send(
                    components=page_components, ephemeral=True
                )

        except Exception as e:
            self.logger.error(f"Error sending monitoring ephemeral: {e}", exc_info=True)
            try:
                await interaction.followup.send(
                    "❌ Ошибка загрузки мониторинга.", ephemeral=True
                )
            except Exception:
                pass


def setup(bot: commands.Bot) -> None:
    bot.add_cog(Spec(bot))
