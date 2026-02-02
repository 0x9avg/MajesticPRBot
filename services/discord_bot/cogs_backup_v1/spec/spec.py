"""Ког для системы спека - закрепление/открепление стримеров для PR ассистентов.
Ported from Legacy to Microservices (API-based).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ...api_client import APIClient
    from ...discord_bot import DiscordBot

import disnake
from config import Config
from disnake import ApplicationCommandInteraction
from disnake.ext import commands
from utils import (
    create_notification_component,
    format_spec_duration,
    send_pr_action_log,
)


class Spec(commands.Cog):
    """Система спека для PR ассистентов для отслеживания стримеров."""

    bot: "DiscordBot"
    api: "APIClient"

    def __init__(self, bot: "DiscordBot") -> None:
        self.bot = bot
        self.api = bot.api_client
        self.logger = bot.logger
        # Store pending transfer requests: {target_user_id: {from_pr_id, streamer_id, guild_id}}
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
        """Обработка кликов по кнопкам спека."""
        custom_id = interaction.component.custom_id or ""

        # Early defer to prevent "Unknown interaction" errors
        if custom_id.startswith(("spec_claim_", "spec_unclaim_", "spec_transfer_")):
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)

        if custom_id.startswith("spec_claim_"):
            await self._handle_claim_button(interaction, custom_id)
        elif custom_id.startswith("spec_unclaim_"):
            await self._handle_unclaim_button(interaction, custom_id)
        elif custom_id.startswith("spec_transfer_"):
            await self._handle_transfer_button(interaction, custom_id)

    async def _handle_claim_button(
        self, interaction: disnake.MessageInteraction, custom_id: str
    ):
        """Обработка клика по кнопке закрепа (с поддержкой Probation)."""

        try:
            streamer_id = int(custom_id.replace("spec_claim_", ""))
            pr_id = interaction.user.id

            # Check if user has probation capability
            capabilities = await self.api.get_assistant_capabilities(pr_id)

            if capabilities.get("can_spec_probation", False):
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
        """Show probation/main spec choice buttons."""
        view = disnake.ui.View(timeout=60)

        main_btn = disnake.ui.Button(
            label="🔵 Main Spec",
            style=disnake.ButtonStyle.primary,
            custom_id=f"probation_choice_main_{streamer_id}",
        )
        probation_btn = disnake.ui.Button(
            label="🟡 Probation Spec",
            style=disnake.ButtonStyle.secondary,
            custom_id=f"probation_choice_prob_{streamer_id}",
        )

        async def main_callback(btn_inter: disnake.MessageInteraction):
            await btn_inter.response.defer(ephemeral=True)
            await self._do_claim(
                btn_inter, streamer_id, btn_inter.user.id, is_probation=False
            )

        async def prob_callback(btn_inter: disnake.MessageInteraction):
            await btn_inter.response.defer(ephemeral=True)
            await self._do_claim(
                btn_inter, streamer_id, btn_inter.user.id, is_probation=True
            )

        main_btn.callback = main_callback
        probation_btn.callback = prob_callback

        view.add_item(main_btn)
        view.add_item(probation_btn)

        await interaction.followup.send(
            "**Выберите тип спека:**\n"
            "🔵 **Main Spec** — обычный спек\n"
            "🟡 **Probation Spec** — стажерский спек",
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
        result = await self.api.claim_streamer(
            streamer_id, pr_id, is_probation=is_probation
        )

        if result and result.get("status") == "claimed":
            streamer_name = result.get("streamer_name")
            spec_type = "Probation" if is_probation else "Main"

            # Update notification message to show "Claimed by X"
            try:
                # Fetch full streamer data for proper UI rebuild
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
            # PR actions log handled by broker_handlers via spec.claimed event
            await self.api.refresh_monitoring()
        else:
            error = result.get("detail", "Ошибка") if result else "API Error"
            await interaction.followup.send(f"❌ {error}", ephemeral=True)

    async def _handle_unclaim_button(
        self, interaction: disnake.MessageInteraction, custom_id: str
    ):
        """Обработка клика по кнопке открепления."""

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
                # PR actions log handled by broker_handlers via spec.unclaimed event
                await self.api.refresh_monitoring()
            else:
                error = result.get("detail", "Ошибка") if result else "API Error"
                await interaction.followup.send(f"❌ {error}", ephemeral=True)

        except Exception as e:
            self.logger.error(f"Error unclaim button: {e}")
            await interaction.followup.send("❌ Ошибка.", ephemeral=True)

    async def _handle_transfer_button(
        self, interaction: disnake.MessageInteraction, custom_id: str
    ):
        """Обработка кнопок передачи."""
        try:
            parts = custom_id.split("_")
            action = parts[2]
            from_pr_id = int(parts[3])

            if interaction.user.id not in self.pending_transfers:
                await interaction.response.send_message(
                    "❌ Запрос истёк.", ephemeral=True
                )
                return

            transfer_data = self.pending_transfers.pop(interaction.user.id)

            if action == "decline":
                # Edit the message to remove buttons
                try:
                    await interaction.message.edit(
                        content="❌ Передача отклонена.", components=[]
                    )
                except Exception:
                    pass

                # Update the ephemeral response
                await interaction.edit_original_response(
                    content="❌ Передача отклонена."
                )

                # Notify the sender that their request was declined
                try:
                    sender = await self.bot.fetch_user(from_pr_id)
                    await sender.send(
                        f"❌ {interaction.user.display_name} отклонил ваш запрос на передачу стримера."
                    )
                except Exception as e:
                    self.logger.warning(f"Could not notify sender about decline: {e}")
                return

            # Already deferred in on_spec_button

            # Check if this is a swap (both PRs have streamers) or a one-way transfer
            target_streamer_id = transfer_data.get("target_streamer_id")

            if target_streamer_id:
                # This is a SWAP (both have streamers)
                result = await self.api.swap_streamers(from_pr_id, interaction.user.id)

                if result and result.get("status") == "swapped":
                    # Update message
                    msg_content = (
                        f"✅ Обмен завершён!\n"
                        f"• Ты получил: **{result.get('pr2_new_streamer')}**\n"
                        f"• Он получил: **{result.get('pr1_new_streamer')}**"
                    )
                    try:
                        await interaction.message.edit(
                            content=msg_content, components=[]
                        )
                    except:
                        pass

                    await interaction.edit_original_response(content=msg_content)
                    await self.api.refresh_monitoring()
                else:
                    error_msg = (
                        result.get("detail", "Неизвестная ошибка")
                        if result
                        else "Ошибка API"
                    )
                    # Update message to show error? Or just ephemeral?
                    # Keep message with buttons? Or fail it?
                    # Let's show error in ephemeral only, keep buttons?
                    await interaction.edit_original_response(
                        content=f"❌ Не удалось обменяться: {error_msg}"
                    )
            else:
                # This is a one-way TRANSFER
                result = await self.api.transfer_streamer(
                    transfer_data["streamer_id"], from_pr_id, interaction.user.id
                )

                if result and result.get("status") == "transferred":
                    msg_content = (
                        f"✅ Ты принял стримера **{result.get('streamer_name')}**!"
                    )
                    try:
                        await interaction.message.edit(
                            content=msg_content, components=[]
                        )
                    except:
                        pass

                    await interaction.edit_original_response(content=msg_content)
                    # PR actions log handled by broker_handlers via spec.transferred event
                    await self.api.refresh_monitoring()
                else:
                    error_msg = (
                        result.get("detail", "Неизвестная ошибка")
                        if result
                        else "Ошибка API"
                    )
                    await interaction.edit_original_response(
                        content=f"❌ Не удалось передать: {error_msg}"
                    )

        except Exception as e:
            self.logger.error(f"Transfer error: {e}")

    @commands.Cog.listener("on_dropdown")
    async def on_spec_dropdown(self, interaction: disnake.MessageInteraction):
        """Обработка выбора в выпадающих списках (Monitoring)."""
        custom_id = interaction.component.custom_id
        if custom_id == "spec_claim_select":
            try:
                if not interaction.response.is_done():
                    await interaction.response.defer(ephemeral=True)
            except:
                pass

            selected = interaction.values[0]
            if selected == "none":
                await interaction.response.send_message(
                    "❌ Нет доступных.", ephemeral=True
                )
                return

            try:
                streamer_id = int(selected)
                await self._handle_claim_button(
                    interaction, f"spec_claim_{streamer_id}"
                )
            except ValueError:
                await interaction.response.send_message("❌ Ошибка ID.", ephemeral=True)

    # =========================================================================
    # Slash Commands
    # =========================================================================

    @commands.slash_command(
        name="claim",
        description="Взять медиа (GTA 5)",
    )
    async def claim(
        self,
        interaction: ApplicationCommandInteraction,
        target_id: str = commands.Param(
            desc="Выберите стримера или событие", autocomplete=True
        ),
    ):
        """Ручное взятие стримера или события (для ассистента)."""
        await interaction.response.defer(ephemeral=True)
        try:
            streamer_id_int = int(target_id)

            # Reuse button logic which handles API call + logging
            await self._handle_claim_button(
                interaction, f"spec_claim_{streamer_id_int}"
            )

        except ValueError:
            await interaction.followup.send("❌ Некорректный ID.", ephemeral=True)
        except Exception as e:
            self.bot.logger.error(f"Error in /claim: {e}", exc_info=True)
            await interaction.followup.send("❌ Произошла ошибка.", ephemeral=True)

    @claim.autocomplete("target_id")
    async def claim_target_autocomplete(
        self, interaction: ApplicationCommandInteraction, current: str
    ):
        """Автозаполнение доступных стримеров GTA 5."""
        try:
            options = {}

            # Available Streamers
            streamers = await self.api.list_all_streamers()
            for s in streamers:
                if (
                    s.get("is_online")
                    and str(s.get("game_id")) == Config.gta5_game_id
                    and not s.get("assigned_pr_id")
                    and current.lower() in s["streamer_name"].lower()
                ):
                    if len(options) >= 25:
                        break
                    options[f"🎥 {s['streamer_name']}"] = str(s["streamer_id"])

            return options
        except Exception as e:
            self.logger.error(f"Autocomplete error: {e}")
            return {}

    @commands.slash_command(name="spec_time", description="Посмотреть время спека")
    async def spec_time(
        self, interaction: ApplicationCommandInteraction, user: disnake.Member = None
    ):
        user = user or interaction.user
        await interaction.response.defer(ephemeral=True)
        stats = await self.api.get_assistant_stats(user.id)
        if stats:
            total = format_spec_duration(stats.get("total_spec_seconds", 0))
            embed = disnake.Embed(
                title=f"⏱️ Статистика — {user.display_name}",
                color=disnake.Color.blurple(),
            )
            embed.add_field(name="Общее время", value=f"**{total}**")
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send("Нет данных.", ephemeral=True)

    @commands.slash_command(name="unclaim", description="Открепиться")
    async def unclaim(self, interaction: ApplicationCommandInteraction):
        await interaction.response.defer(ephemeral=True)
        # Find current
        try:
            # Check streamer
            current = await self.api.get_pr_current_streamer(interaction.user.id)
            if current:
                await self._handle_unclaim_button(
                    interaction, f"spec_unclaim_{current['streamer_id']}"
                )
            else:
                await interaction.followup.send(
                    "❌ Не закреплен ни за стримером.", ephemeral=True
                )
        except Exception as e:
            self.logger.error(f"Unclaim error: {e}")
            await interaction.followup.send("❌ Ошибка.", ephemeral=True)

    @commands.slash_command(name="add_time", description="Добавить время (Admin)")
    @commands.has_permissions(administrator=True)
    async def add_time(
        self,
        interaction: ApplicationCommandInteraction,
        user: disnake.Member,
        minutes: int,
    ):
        await interaction.response.defer(ephemeral=True)
        result = await self.api.add_assistant_time(user.id, minutes * 60)
        if result:
            await interaction.followup.send(f"✅ Добавлено {minutes}м.", ephemeral=True)
        else:
            await interaction.followup.send("❌ Ошибка.", ephemeral=True)

    @commands.slash_command(name="sub_time", description="Вычесть время (Admin)")
    @commands.has_permissions(administrator=True)
    async def sub_time(
        self,
        interaction: ApplicationCommandInteraction,
        user: disnake.Member,
        minutes: int,
    ):
        await interaction.response.defer(ephemeral=True)
        result = await self.api.subtract_assistant_time(user.id, minutes * 60)
        if result:
            await interaction.followup.send(f"✅ Вычтено {minutes}м.", ephemeral=True)
        else:
            await interaction.followup.send("❌ Ошибка.", ephemeral=True)

    @commands.slash_command(
        name="give_streamer", description="Передать стримера другому PR ассистенту"
    )
    async def give_streamer(
        self,
        interaction: ApplicationCommandInteraction,
        user: disnake.Member,
    ):
        """Передача текущего стримера другому PR ассистенту."""
        await interaction.response.defer(ephemeral=True)
        try:
            if user.id == interaction.user.id:
                await interaction.followup.send(
                    "❌ Нельзя передать стримера самому себе.",
                    ephemeral=True,
                )
                return

            pr_id = interaction.user.id
            current_streamer = await self.api.get_pr_current_streamer(pr_id)

            if not current_streamer:
                await interaction.followup.send(
                    "❌ У тебя нет закрепленного стримера.",
                    ephemeral=True,
                )
                return

            # Check if target has a streamer
            target_streamer = await self.api.get_pr_current_streamer(user.id)

            if target_streamer:
                message_text = (
                    f"🔄 **Предложение обмена стримерами**\n\n"
                    f"{interaction.user.mention} предлагает обменяться:\n"
                    f"• Ты получишь: **{current_streamer['streamer_name']}**\n"
                    f"• Он получит: **{target_streamer['streamer_name']}**"
                )
            else:
                message_text = (
                    f"📨 **Предложение принять стримера**\n\n"
                    f"{interaction.user.mention} хочет передать тебе стримера:\n"
                    f"• **{current_streamer['streamer_name']}**"
                )

            # Store pending transfer
            self.pending_transfers[user.id] = {
                "from_pr_id": pr_id,
                "streamer_id": current_streamer["streamer_id"],
                "target_streamer_id": (
                    target_streamer["streamer_id"] if target_streamer else None
                ),
                "guild_id": interaction.guild_id,
            }

            # Create accept/decline buttons
            view = disnake.ui.View(timeout=None)
            view.add_item(
                disnake.ui.Button(
                    label="✅ Принять",
                    custom_id=f"spec_transfer_accept_{pr_id}",
                    style=disnake.ButtonStyle.success,
                )
            )
            view.add_item(
                disnake.ui.Button(
                    label="❌ Отклонить",
                    custom_id=f"spec_transfer_decline_{pr_id}",
                    style=disnake.ButtonStyle.danger,
                )
            )

            # Send DM to target
            try:
                await user.send(content=message_text, view=view)
                await interaction.followup.send(
                    f"✅ Запрос на передачу отправлен {user.mention}.",
                    ephemeral=True,
                )
            except disnake.Forbidden:
                self.pending_transfers.pop(user.id, None)
                await interaction.followup.send(
                    f"❌ Не удалось отправить сообщение {user.mention}. "
                    f"Проверь, открыты ли у него личные сообщения.",
                    ephemeral=True,
                )

        except Exception as e:
            self.logger.error(f"Error in /give_streamer: {e}", exc_info=True)
            await interaction.followup.send("❌ Произошла ошибка.", ephemeral=True)

    # Helper
    async def _send_pr_action(self, guild_id, message):
        """Send message to PR actions log channel."""
        await send_pr_action_log(self.bot, message)

    async def update_monitoring(self):
        """Update monitoring message with current streamer statuses."""
        try:
            from utils import create_monitoring_select, create_streamers_component

            settings = await self.api.get_guild_settings()
            if not settings:
                return

            monitoring_channel_id = settings.get("monitoring_channel_id")
            monitoring_message_id = settings.get("monitoring_message_id")

            if not monitoring_channel_id:
                return

            channel = self.bot.get_channel(int(monitoring_channel_id))
            if not channel:
                self.bot.logger.warning(f"Monitoring channel not found")
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
                except Exception:
                    message = None

            if message:
                await message.edit(components=final_components)
            else:
                new_message = await channel.send(components=final_components)
                await self.api.update_guild_settings(
                    monitoring_message_id=new_message.id
                )

        except Exception as e:
            self.bot.logger.error(f"Error updating monitoring: {e}", exc_info=True)


def setup(bot: commands.Bot) -> None:
    bot.add_cog(Spec(bot))
