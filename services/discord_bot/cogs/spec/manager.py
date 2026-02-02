"""Spec Manager - Claim/Unclaim system for PR assistants.
Ported from Legacy to Microservices (API-based).
All interactions via BUTTONS only (per GEMINI.md - no slash commands except /setup).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api_client import APIClient
    from discord_bot import DiscordBot

import disnake
from config import Config
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
        # Store pending transfer requests: {transfer_id: {...}}
        self.pending_transfers = {}

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

        # Filter: only handle spec_ and probation_choice_ buttons
        if not custom_id.startswith(("spec_", "probation_choice_")):
            return

        # Defer for all except probation choice (which shows ephemeral view)
        if not custom_id.startswith("probation_choice_"):
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
            elif custom_id.startswith("spec_transfer_"):
                await self._handle_transfer_button(interaction, custom_id)
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
        except Exception as e:
            self.logger.error(f"Spec button error {custom_id}: {e}", exc_info=True)
            try:
                await interaction.followup.send("❌ Ошибка.", ephemeral=True)
            except:
                pass

    async def _handle_claim_button(
        self, interaction: disnake.MessageInteraction, custom_id: str
    ):
        """Handle claim button click (with Probation support)."""
        try:
            streamer_id = int(custom_id.replace("spec_claim_", ""))
            pr_id = interaction.user.id

            # Check if user has probation capability
            capabilities = await self.api.get_assistant_capabilities(pr_id)

            if capabilities and capabilities.get("can_spec_probation", False):
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
        view = disnake.ui.View(timeout=60)

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
        except:
            pass

        result = await self.api.claim_streamer(
            streamer_id, pr_id, is_probation=is_probation
        )

        if result and result.get("status") == "claimed":
            streamer_name = result.get("streamer_name")
            spec_type = "Стажерский" if is_probation else "Основной"

            # Update notification message to show "Claimed by X"
            try:
                streamer = await self.api.get_streamer(streamer_id)
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

            result = await self.api.unclaim_streamer(streamer_id, reason="manual")

            if result and result.get("status") == "unclaimed":
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

    async def _handle_transfer_button(
        self, interaction: disnake.MessageInteraction, custom_id: str
    ):
        """Handle transfer accept/decline buttons."""
        try:
            # Format: spec_transfer_{action}_{transfer_id}
            parts = custom_id.split("_")
            action = parts[2]  # accept or decline
            transfer_id = parts[3]  # uuid

            if transfer_id not in self.pending_transfers:
                await interaction.followup.send("❌ Запрос истёк.", ephemeral=True)
                return

            transfer_data = self.pending_transfers.pop(transfer_id)
            from_pr_id = transfer_data["from_pr_id"]

            # Verify this is the intended recipient
            if interaction.user.id != transfer_data["to_pr_id"]:
                await interaction.followup.send("❌ Этот запрос не для вас.", ephemeral=True)
                return

            if action == "decline":
                try:
                    await interaction.message.edit(
                        content="❌ Передача отклонена.", components=[]
                    )
                except:
                    pass

                # Notify sender
                try:
                    sender = await self.bot.fetch_user(from_pr_id)
                    await sender.send(
                        f"❌ {interaction.user.display_name} отклонил запрос на передачу."
                    )
                except Exception as e:
                    self.logger.warning(f"Could not notify sender: {e}")
                return

            # Accept transfer
            target_streamer_id = transfer_data.get("target_streamer_id")

            if target_streamer_id:
                # This is a SWAP
                result = await self.api.swap_streamers(from_pr_id, interaction.user.id)

                if result and result.get("status") == "swapped":
                    msg = (
                        f"✅ Обмен завершён!\n"
                        f"• Ты получил: **{result.get('pr2_new_streamer')}**\n"
                        f"• Он получил: **{result.get('pr1_new_streamer')}**"
                    )
                    try:
                        await interaction.message.edit(content=msg, components=[])
                    except:
                        pass
                    await self.update_monitoring()
                else:
                    error = result.get("detail", "Ошибка") if result else "API Error"
                    await interaction.followup.send(f"❌ {error}", ephemeral=True)
            else:
                # One-way transfer
                result = await self.api.transfer_streamer(
                    transfer_data["streamer_id"], from_pr_id, interaction.user.id
                )

                if result and result.get("status") == "transferred":
                    msg = f"✅ Ты принял стримера **{result.get('streamer_name')}**!"
                    try:
                        await interaction.message.edit(content=msg, components=[])
                    except:
                        pass
                    await self.update_monitoring()
                else:
                    error = result.get("detail", "Ошибка") if result else "API Error"
                    await interaction.followup.send(f"❌ {error}", ephemeral=True)

        except Exception as e:
            self.logger.error(f"Transfer error: {e}", exc_info=True)

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
        except:
            pass

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

    async def initiate_transfer(
        self,
        from_user: disnake.Member,
        to_user: disnake.Member,
        streamer_data: dict,
        target_streamer_data: dict | None = None,
    ):
        """
        Initiate a transfer request. Called from assistants admin panel.
        
        Args:
            from_user: User giving the streamer
            to_user: User receiving the streamer
            streamer_data: Current streamer data
            target_streamer_data: Target's streamer (for swap) or None
        """
        if target_streamer_data:
            message_text = (
                f"🔄 **Предложение обмена стримерами**\n\n"
                f"{from_user.mention} предлагает обменяться:\n"
                f"• Ты получишь: **{streamer_data['streamer_name']}**\n"
                f"• Он получит: **{target_streamer_data['streamer_name']}**"
            )
        else:
            message_text = (
                f"📨 **Предложение принять стримера**\n\n"
                f"{from_user.mention} хочет передать тебе стримера:\n"
                f"• **{streamer_data['streamer_name']}**"
            )

        # Generate unique transfer ID
        transfer_id = str(uuid.uuid4())[:8]

        # Store pending transfer with unique ID
        self.pending_transfers[transfer_id] = {
            "from_pr_id": from_user.id,
            "to_pr_id": to_user.id,
            "streamer_id": streamer_data["streamer_id"],
            "target_streamer_id": (
                target_streamer_data["streamer_id"] if target_streamer_data else None
            ),
        }

        # Create accept/decline buttons with unique transfer_id
        view = disnake.ui.View(timeout=None)
        view.add_item(
            disnake.ui.Button(
                label="✅ Принять",
                custom_id=f"spec_transfer_accept_{transfer_id}",
                style=disnake.ButtonStyle.success,
            )
        )
        view.add_item(
            disnake.ui.Button(
                label="❌ Отклонить",
                custom_id=f"spec_transfer_decline_{transfer_id}",
                style=disnake.ButtonStyle.danger,
            )
        )

        # Send DM to target
        await to_user.send(content=message_text, view=view)

    # =========================================================================
    # Monitoring Update
    # =========================================================================

    async def update_monitoring(self):
        """Update monitoring message with current streamer statuses."""
        try:
            settings = await self.api.get_guild_settings()
            if not settings:
                return

            monitoring_channel_id = settings.get("monitoring_channel_id")
            monitoring_message_id = settings.get("monitoring_message_id")

            if not monitoring_channel_id:
                return

            channel = self.bot.get_channel(int(monitoring_channel_id))
            if not channel:
                self.logger.warning("Monitoring channel not found")
                return

            # Get streamers
            streamers = await self.api.list_all_streamers()
            online_streamers = []
            available_streamers = []
            gta_count = 0

            for s in streamers:
                if s.get("is_online"):
                    online_streamers.append(s)
                    is_gta = str(s.get("game_id")) == Config.gta5_game_id
                    if is_gta:
                        gta_count += 1
                        if not s.get("assigned_pr_id"):
                            available_streamers.append(s)

            # Build components
            container = create_streamers_component(
                online_streamers, len(streamers), gta_count
            )
            select_row = create_monitoring_select(available_streamers, [])
            final_components = [container, select_row]

            # Edit or create message
            message = None
            if monitoring_message_id:
                try:
                    message = await channel.fetch_message(int(monitoring_message_id))
                except:
                    message = None

            if message:
                await message.edit(components=final_components)
            else:
                new_message = await channel.send(components=final_components)
                await self.api.update_guild_settings(
                    monitoring_message_id=new_message.id
                )

        except Exception as e:
            self.logger.error(f"Error updating monitoring: {e}", exc_info=True)


def setup(bot: commands.Bot) -> None:
    bot.add_cog(Spec(bot))
