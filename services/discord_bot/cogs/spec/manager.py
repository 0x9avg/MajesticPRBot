"""Spec Manager - Claim/Unclaim system for PR assistants.

All interactions via BUTTONS only (per GEMINI.md - no slash commands except /setup).
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
from utils import (
    create_monitoring_select,
    create_notification_component,
    create_streamers_component,
    format_spec_duration,
)


class Spec(commands.Cog):
    """Spec system for PR assistants to track streamers.

    All spec interactions are through BUTTONS:
    - spec_claim_{streamer_id} - Claim a streamer
    - spec_unclaim_{streamer_id} - Unclaim a streamer
    - probation_choice_main_{streamer_id} - Choose main spec
    - probation_choice_prob_{streamer_id} - Choose probation spec

    Transfer is initiated from AssistantsView in admin panel.
    """

    bot: "DiscordBot"
    api: "APIClient"

    def __init__(self, bot: "DiscordBot") -> None:
        self.bot = bot
        self.api = bot.api_client
        self.logger = bot.logger

        # Lock to prevent concurrent monitoring updates
        self._monitoring_lock = asyncio.Lock()

    @commands.Cog.listener()
    async def on_ready(self):
        """Refresh monitoring on bot startup."""
        self.logger.info("Spec cog ready - Refreshing monitoring...")
        try:
            await self.update_monitoring()
        except Exception as e:
            self.logger.error(f"Failed to refresh monitoring on ready: {e}")

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
                # Format: claim_page_{direction}_{current_page}
                parts = custom_id.split("_")
                direction = parts[2]  # "next" or "prev"
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
            streamer_id = int(custom_id.replace("spec_claim_", ""))
            pr_id = interaction.user.id

            data = await self.api.get_claimable_streamers(pr_id)
            if not data:
                await interaction.followup.send("❌ Ошибка при проверке статуса стримера.", ephemeral=True)
                return

            # Check if PR is already assigned
            if data.get("assigned_to_type"):
                target_name = data.get("assigned_to_name", "кем-то")
                await interaction.followup.send(
                    f"❌ Вы уже закреплены за {data.get('assigned_to_type') == 'event' and 'событием' or 'стримером'} **{target_name}**.",
                    ephemeral=True
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
        # Ensure deferred
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except Exception as e:
            self.logger.debug(f"Defer failed: {e}")

        self.logger.debug(f"[User {pr_id}] Claiming streamer {streamer_id}. Probation: {is_probation}. BEFORE: sending API request.")
        result = await self.api.claim_streamer(
            streamer_id, pr_id, is_probation=is_probation
        )
        self.logger.debug(f"[User {pr_id}] Claim streamer {streamer_id} result AFTER: {result}")

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

            # Refresh monitoring
            await self.update_monitoring()
        else:
            error = result.get("detail", "Ошибка") if result else "API Error"
            await interaction.followup.send(f"❌ {error}", ephemeral=True)

    async def _handle_unclaim_button(
        self, interaction: disnake.MessageInteraction, custom_id: str
    ):
        """Handle unclaim button click."""
        try:
            streamer_id = int(custom_id.replace("spec_unclaim_", ""))
            pr_id = interaction.user.id

            self.logger.debug(f"[User {pr_id}] Unclaiming streamer {streamer_id}. BEFORE: sending API request.")
            result = await self.api.unclaim_streamer(
                streamer_id, pr_id=pr_id, reason="manual_unclaim"
            )
            self.logger.debug(f"[User {pr_id}] Unclaim streamer {streamer_id} result AFTER: {result}")

            if result and "duration_seconds" in result:
                duration_str = format_spec_duration(result.get("duration_seconds", 0))

                await interaction.followup.send(
                    f"✅ Ты открепился от **{result.get('streamer_name')}**.\n"
                    f"⏱️ Время спека: **{duration_str}**",
                    ephemeral=True,
                )

                # Refresh monitoring
                await self.update_monitoring()
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
                await self.update_monitoring()
            else:
                error = result.get("detail", "Ошибка") if result else "API Error"
                await interaction.followup.send(f"❌ {error}", ephemeral=True)
        elif "event_id" in current:
            event_id = current.get("event_id")
            # For events, the unclaim route is /events/{event_id}/leave
            result = await self.api._request(
                "POST", f"/events/{event_id}/leave", data={"user_id": pr_id}
            )
            if result and "event_id" in result:
                await interaction.followup.send("✅ Вы покинули событие.", ephemeral=True)
                await self.update_monitoring()
            else:
                error = result.get("detail", result.get("message", "Ошибка")) if isinstance(result, dict) else "API Error"
                await interaction.followup.send(f"❌ {error}", ephemeral=True)

    async def _handle_monitoring_claim(self, interaction: disnake.MessageInteraction):
        """Handle 'Claim' button from monitoring UI - show paginated selector."""
        await self._show_claim_selector(interaction, page=0)

    async def _show_claim_selector(
        self, interaction: disnake.MessageInteraction, page: int = 0
    ):
        """Show paginated claim selector."""
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
            if page > 0:
                view.add_item(
                    disnake.ui.Button(
                        label="◀ Назад",
                        custom_id=f"claim_page_prev_{page}",
                        style=disnake.ButtonStyle.secondary,
                    )
                )
            if page < total_pages - 1:
                view.add_item(
                    disnake.ui.Button(
                        label="Вперёд ▶",
                        custom_id=f"claim_page_next_{page}",
                        style=disnake.ButtonStyle.secondary,
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
                
                result = await self.api.join_event(event_id, user_id)
                if result and "event_id" in result:
                    join_status = result.get("join_status", "joined")
                    if join_status == "reserved":
                        await interaction.followup.send("✅ Вы закреплены за событием. Спек начнётся при старте события.", ephemeral=True)
                    else:
                        await interaction.followup.send("✅ Успешно закреплен за событием", ephemeral=True)
                    await self.update_monitoring()
                else:
                    error = result.get("detail", result.get("message", "Ошибка")) if isinstance(result, dict) else "API Error"
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
                    ephemeral=True
                )
                return

            can_spec_probation = data.get("can_spec_probation", False)

            # Find selected streamer info
            selected = None
            for s in data.get("streamers", []):
                if str(s.get("streamer_id")) == str(streamer_id) or str(s.get("event_id")) == str(streamer_id):
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
    # Monitoring Update
    # =========================================================================

    async def update_monitoring(self):
        """Update monitoring messages with current streamer statuses.

        Uses multi-message pagination and Chain Repair algorithm:
        - Attempts to edit existing messages by ID
        - If a message is missing (404), marks chain as broken
        - Recreates broken chain from that point
        - Cleans up orphan messages
        """
        async with self._monitoring_lock:
            try:
                # Get monitoring status from API
                status = await self.api.get_monitoring_status()
                if not status:
                    self.logger.warning("Failed to get monitoring status from API")
                    return

                settings = await self.api.get_guild_settings()
                if not settings:
                    return

                monitoring_channel_id = settings.get("monitoring_channel_id")
                if not monitoring_channel_id:
                    return

                channel = self.bot.get_channel(int(monitoring_channel_id))
                if not channel:
                    self.logger.warning("Monitoring channel not found")
                    return

                # Get saved message IDs (list)
                saved_ids = settings.get("monitoring_message_ids") or []
                if isinstance(saved_ids, str):
                    import json

                    saved_ids = json.loads(saved_ids)
                saved_ids = [int(mid) for mid in saved_ids] if saved_ids else []

                # Generate pages
                online_streamers = status.get("online_streamers", [])
                available_streamers = status.get("available_for_claim", [])
                active_events = status.get("active_events", [])
                total_count = status.get("total_streamers", 0)
                gta_count = status.get("gta_count", 0)
                online_count = status.get("online_count", len(online_streamers))

                # Apply GTA filter if enabled
                gta_filter = settings.get("monitoring_filter_gta", False)
                if gta_filter:
                    from config import Config

                    online_streamers = [
                        s
                        for s in online_streamers
                        if str(s.get("game_id")) == Config.gta5_game_id
                    ]
                    available_streamers = [
                        s
                        for s in available_streamers
                        if str(s.get("game_id")) == Config.gta5_game_id
                    ]

                pages = create_streamers_component(
                    online_streamers, total_count, gta_count, events=active_events, online_count=online_count
                )

                # Add select row to last page
                select_row = create_monitoring_select(available_streamers, [])

                # Sync Loop with Chain Repair
                new_ids = []
                broken_chain = False

                for i, page in enumerate(pages):
                    # Build components for this page
                    if i == len(pages) - 1:
                        # Last page: add select row
                        page_components = [page, select_row]
                    else:
                        page_components = [page]

                    if i < len(saved_ids) and not broken_chain:
                        # Try to edit existing message
                        try:
                            msg = await channel.fetch_message(saved_ids[i])
                            await msg.edit(components=page_components)
                            new_ids.append(msg.id)
                            self.logger.debug(
                                f"Edited monitoring message {i+1}/{len(pages)}"
                            )
                        except disnake.NotFound:
                            # Message was deleted - chain is broken
                            self.logger.warning(
                                f"Monitoring message {saved_ids[i]} not found - chain broken"
                            )
                            broken_chain = True
                            # Send new message
                            msg = await channel.send(components=page_components)
                            new_ids.append(msg.id)
                        except Exception as e:
                            self.logger.error(f"Failed to edit message: {e}")
                            broken_chain = True
                            msg = await channel.send(components=page_components)
                            new_ids.append(msg.id)
                    else:
                        # Chain broken or new page - delete old if exists, send new
                        if i < len(saved_ids):
                            try:
                                old_msg = await channel.fetch_message(saved_ids[i])
                                await old_msg.delete()
                                self.logger.debug(
                                    f"Deleted orphan message {saved_ids[i]}"
                                )
                            except:  # noqa: E722
                                pass  # Already deleted

                        msg = await channel.send(components=page_components)
                        new_ids.append(msg.id)
                        self.logger.debug(
                            f"Sent new monitoring message {i+1}/{len(pages)}"
                        )

                # Cleanup: delete extra old messages
                for i in range(len(pages), len(saved_ids)):
                    try:
                        old_msg = await channel.fetch_message(saved_ids[i])
                        await old_msg.delete()
                        self.logger.debug(f"Deleted extra message {saved_ids[i]}")
                    except:  # noqa: E722
                        pass

                # Save new IDs if changed
                if new_ids != saved_ids:
                    await self.api.update_guild_settings(monitoring_message_ids=new_ids)
                    self.logger.info(f"Updated monitoring: {len(new_ids)} messages")

            except Exception as e:
                self.logger.error(f"Error updating monitoring: {e}", exc_info=True)


def setup(bot: commands.Bot) -> None:
    bot.add_cog(Spec(bot))
