"""Ког для системы спека - закрепление/открепление стримеров для PR ассистентов.
Ported from Legacy to Microservices (API-based).
"""

import disnake
from disnake import ApplicationCommandInteraction
from disnake.ext import commands
from typing import Optional

from config import Config
from utils import format_spec_duration, create_notification_component, send_pr_action_log


class Spec(commands.Cog):
    """Система спека для PR ассистентов для отслеживания стримеров."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.api = bot.api_client
        self.logger = bot.logger
        # Store pending transfer requests: {target_user_id: {from_pr_id, streamer_id, guild_id}}
        self.pending_transfers = {}

    # =========================================================================
    # Button Handlers
    # =========================================================================

    @commands.Cog.listener("on_button_click")
    async def on_spec_button(self, interaction: disnake.MessageInteraction):
        """Обработка кликов по кнопкам спека."""
        custom_id = interaction.component.custom_id or ""

        if custom_id.startswith("spec_claim_"):
            await self._handle_claim_button(interaction, custom_id)
        elif custom_id.startswith("spec_unclaim_"):
            await self._handle_unclaim_button(interaction, custom_id)
        elif custom_id.startswith("spec_transfer_"):
            await self._handle_transfer_button(interaction, custom_id)
        elif custom_id.startswith("event_join_"):
            await self._handle_event_join(interaction, custom_id)

    async def _handle_event_join(
        self, interaction: disnake.MessageInteraction, custom_id: str
    ):
        """Обработка присоединения/выхода из события."""
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
            
        try:
            event_id = int(custom_id.replace("event_join_", ""))
            user_id = interaction.user.id

            result = await self.api.join_event(event_id, user_id)
            # If logic for "Toggle" exists (join if not in, leave if in)?
            # API `join_event` returns False/Error if already joined?
            # Legacy logic: Check participation. If participating -> Leave. If not -> Join.
            # My API `join_event` returns False if already joined.
            # So if False, try LEAVE?
            
            # Let's check participation first via API
            # I added `get_user_active_event`.
            active = await self.api.get_user_active_event(user_id)
            
            if active and active['id'] == event_id:
                # User IS in this event -> LEAVE
                duration = await self.api.leave_event(event_id, user_id)
                dur_str = format_spec_duration(duration)
                await interaction.followup.send(f"➖ Ты покинул событие **{active['name']}**. (Спек: {dur_str})", ephemeral=True)
                await self._send_pr_action(interaction.guild_id, f"📤 **Покинул событие**\n🎯 {interaction.user.mention}\n⏱️ {dur_str}")
            
            elif active:
                # User in ANOTHER event
                await interaction.followup.send(f"❌ Ты уже участвуешь в событии **{active['name']}**!", ephemeral=True)
                return
            
            else:
                # User not in any event -> JOIN
                success = await self.api.join_event(event_id, user_id)
                if success:
                    await interaction.followup.send(f"➕ Ты присоединился к событию!", ephemeral=True)
                    await self._send_pr_action(interaction.guild_id, f"📥 **Присоединился к событию**\n🎯 {interaction.user.mention}")
                else:
                    await interaction.followup.send("❌ Не удалось присоединиться.", ephemeral=True)

            # Refresh monitoring
            dashboard_cog = self.bot.get_cog("Dashboard")
            if dashboard_cog:
                # Trigger internal update if needed or just let API sync
                pass # API syncs monitoring periodically or via manual refresh
                await self.api.refresh_monitoring()

        except Exception as e:
            self.logger.error(f"Event join error: {e}", exc_info=True)
            try:
                await interaction.followup.send("❌ Ошибка.", ephemeral=True)
            except: pass

    async def _handle_claim_button(
        self, interaction: disnake.MessageInteraction, custom_id: str
    ):
        """Обработка клика по кнопке закрепа."""
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
            
        try:
            streamer_id = int(custom_id.replace("spec_claim_", ""))
            pr_id = interaction.user.id

            result = await self.api.claim_streamer(streamer_id, pr_id)

            if result and result.get("status") == "claimed":
                streamer_name = result.get("streamer_name")
                
                # Update notification message to show "Claimed by X"
                try:
                    # Fetch full streamer data for proper UI rebuild
                    streamer = await self.api.get_streamer(streamer_id)
                    if streamer:
                        new_components = create_notification_component(
                            message="",
                            streamer_name=streamer.get("streamer_name", streamer_name),
                            stream_title=streamer.get("stream_title", ""),
                            game_name=streamer.get("game_name", "GTA 5"),
                            thumbnail_url=streamer.get("stream_thumbnail_url", ""),
                            streamer_id=streamer_id,
                            show_claim_button=True,
                            assigned_pr_id=pr_id,
                            assigned_pr_name=interaction.user.display_name
                        )
                        await interaction.message.edit(components=new_components)
                except Exception as e:
                    self.logger.warning(f"Could not update notification message: {e}")

                await interaction.followup.send(f"✅ Успешно закреплен: **{streamer_name}**", ephemeral=True)
                # PR actions log handled by broker_handlers via spec.claimed event
                await self.api.refresh_monitoring()
            else:
                error = result.get("detail", "Ошибка") if result else "API Error"
                await interaction.followup.send(f"❌ {error}", ephemeral=True)

        except Exception as e:
            self.logger.error(f"Error claim button: {e}", exc_info=True)
            await interaction.followup.send("❌ Ошибка.", ephemeral=True)

    async def _handle_unclaim_button(
        self, interaction: disnake.MessageInteraction, custom_id: str
    ):
        """Обработка клика по кнопке открепления."""
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
            
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
                await interaction.response.send_message("❌ Запрос истёк.", ephemeral=True)
                return

            transfer_data = self.pending_transfers.pop(interaction.user.id)

            if action == "decline":
                await interaction.response.edit_message(content="❌ Передача отклонена.", components=[])
                
                # Notify the sender that their request was declined
                try:
                    sender = await self.bot.fetch_user(from_pr_id)
                    await sender.send(
                        f"❌ {interaction.user.display_name} отклонил ваш запрос на передачу стримера."
                    )
                except Exception as e:
                    self.logger.warning(f"Could not notify sender about decline: {e}")
                return

            await interaction.response.defer()

            # Check if this is a swap (both PRs have streamers) or a one-way transfer
            target_streamer_id = transfer_data.get("target_streamer_id")
            
            if target_streamer_id:
                # This is a SWAP (both have streamers)
                result = await self.api.swap_streamers(from_pr_id, interaction.user.id)
                
                if result and result.get("status") == "swapped":
                    await interaction.followup.edit_message(
                        message_id=interaction.message.id,
                        content=(
                            f"✅ Обмен завершён!\n"
                            f"• Ты получил: **{result.get('pr2_new_streamer')}**\n"
                            f"• Он получил: **{result.get('pr1_new_streamer')}**"
                        ),
                        components=[]
                    )
                    await self.api.refresh_monitoring()
                else:
                    error_msg = result.get("detail", "Неизвестная ошибка") if result else "Ошибка API"
                    await interaction.followup.edit_message(
                        message_id=interaction.message.id,
                        content=f"❌ Не удалось обменяться: {error_msg}", 
                        components=[]
                    )
            else:
                # This is a one-way TRANSFER
                result = await self.api.transfer_streamer(
                    transfer_data["streamer_id"],
                    from_pr_id,
                    interaction.user.id
                )

                if result and result.get("status") == "transferred":
                    await interaction.followup.edit_message(
                        message_id=interaction.message.id,
                        content=f"✅ Ты принял стримера **{result.get('streamer_name')}**!",
                        components=[]
                    )
                    # PR actions log handled by broker_handlers via spec.transferred event
                    await self.api.refresh_monitoring()
                else:
                    error_msg = result.get("detail", "Неизвестная ошибка") if result else "Ошибка API"
                    await interaction.followup.edit_message(
                        message_id=interaction.message.id,
                        content=f"❌ Не удалось передать: {error_msg}", 
                        components=[]
                    )

        except Exception as e:
            self.logger.error(f"Transfer error: {e}")


    @commands.Cog.listener("on_dropdown")
    async def on_spec_dropdown(self, interaction: disnake.MessageInteraction):
        """Обработка выбора в выпадающих списках (Monitoring)."""
        custom_id = interaction.component.custom_id
        if custom_id == "spec_claim_select":
            selected = interaction.values[0]
            if selected == "none":
                await interaction.response.send_message("❌ Нет доступных.", ephemeral=True)
                return
            
            if selected.startswith("event_"):
                 await self._handle_event_join(interaction, f"event_join_{selected.replace('event_', '')}")
                 return
            
            try:
                streamer_id = int(selected)
                await self._handle_claim_button(interaction, f"spec_claim_{streamer_id}")
            except ValueError:
                await interaction.response.send_message("❌ Ошибка ID.", ephemeral=True)


    # =========================================================================
    # Slash Commands
    # =========================================================================

    @commands.slash_command(
        name="claim",
        description="Взять медиа или событие (GTA 5)",
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
            # Check if event
            if target_id.startswith("event_"):
                event_id = int(target_id.replace("event_", ""))
                await self._handle_event_join(interaction, f"event_join_{event_id}")
                return

            streamer_id_int = int(target_id)
            
            # Reuse button logic which handles API call + logging
            await self._handle_claim_button(interaction, f"spec_claim_{streamer_id_int}")

        except ValueError:
            await interaction.followup.send(
                "❌ Некорректный ID.", ephemeral=True
            )
        except Exception as e:
            self.bot.logger.error(f"Error in /claim: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ Произошла ошибка.", ephemeral=True
            )

    @claim.autocomplete("target_id")
    async def claim_target_autocomplete(
        self, interaction: ApplicationCommandInteraction, current: str
    ):
        """Автозаполнение доступных стримеров GTA 5 и активных событий."""
        try:
            options = {}

            # 1. Active Events
            events = await self.api.get_active_events(interaction.guild_id)
            for e in events:
                if current.lower() in e["name"].lower():
                    options[f"🎉 {e['name']}"] = f"event_{e['id']}"

            # 2. Available Streamers
            streamers = await self.api.list_all_streamers()
            for s in streamers:
                if (
                    s.get("is_online") 
                    and str(s.get("game_id")) == Config.GTA5_GAME_ID
                    and not s.get("assigned_pr_id")
                    and current.lower() in s["streamer_name"].lower()
                ):
                     if len(options) >= 25: break
                     options[f"🎥 {s['streamer_name']}"] = str(s["streamer_id"])

            return options
        except Exception as e:
            self.logger.error(f"Autocomplete error: {e}")
            return {}

    @commands.slash_command(name="spec_time", description="Посмотреть время спека")
    async def spec_time(self, interaction: ApplicationCommandInteraction, user: disnake.Member = None):
        user = user or interaction.user
        await interaction.response.defer(ephemeral=True)
        stats = await self.api.get_assistant_stats(user.id)
        if stats:
            total = format_spec_duration(stats.get("total_spec_seconds", 0))
            embed = disnake.Embed(title=f"⏱️ Статистика — {user.display_name}", color=disnake.Color.blurple())
            embed.add_field(name="Общее время", value=f"**{total}**")
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send("Нет данных.", ephemeral=True)

    @commands.slash_command(name="unclaim", description="Открепиться")
    async def unclaim(self, interaction: ApplicationCommandInteraction):
        await interaction.response.defer(ephemeral=True)
        # Find current
        try:
            # Check event first (since unclaim applies to events too usually? or just streams?)
            # Legacy unclaim worked for events too if participating?
            # My _handle_unclaim_button is specifically for STREAMERS (calls unclaim_streamer).
            # If user in event, they should use leave event?
            # But user might think "/unclaim" works for everything.
            
            # Check event
            active_event = await self.api.get_user_active_event(interaction.user.id)
            if active_event:
                 await self._handle_event_join(interaction, f"event_join_{active_event['id']}")
                 return

            # Check streamer
            current = await self.api.get_pr_current_streamer(interaction.user.id)
            if current:
                await self._handle_unclaim_button(interaction, f"spec_unclaim_{current['streamer_id']}")
            else:
                await interaction.followup.send("❌ Не закреплен ни за стримером, ни за событием.", ephemeral=True)
        except Exception as e:
            self.logger.error(f"Unclaim error: {e}")
            await interaction.followup.send("❌ Ошибка.", ephemeral=True)

    @commands.slash_command(name="add_time", description="Добавить время (Admin)")
    @commands.has_permissions(administrator=True)
    async def add_time(self, interaction: ApplicationCommandInteraction, user: disnake.Member, minutes: int):
         await interaction.response.defer(ephemeral=True)
         result = await self.api.add_assistant_time(user.id, minutes * 60)
         if result:
             await interaction.followup.send(f"✅ Добавлено {minutes}м.", ephemeral=True)
         else:
             await interaction.followup.send("❌ Ошибка.", ephemeral=True)

    @commands.slash_command(name="sub_time", description="Вычесть время (Admin)")
    @commands.has_permissions(administrator=True)
    async def sub_time(self, interaction: ApplicationCommandInteraction, user: disnake.Member, minutes: int):
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
            await interaction.followup.send(
                "❌ Произошла ошибка.", ephemeral=True
            )

    # Helper
    async def _send_pr_action(self, guild_id, message):
        """Send message to PR actions log channel."""
        await send_pr_action_log(self.bot, message)

    async def update_monitoring(self):
        """Update monitoring message with current streamer statuses."""
        try:
            from utils import create_streamers_component, create_monitoring_select
            
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
                    is_gta = str(s.get("game_id")) == Config.GTA5_GAME_ID
                    if is_gta:
                        gta_count += 1
                        if not s.get("assigned_pr_id"):
                            available_streamers.append(s)
            
            # Build components
            container = create_streamers_component(online_streamers, len(streamers), gta_count)
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
                await self.api.update_guild_settings(monitoring_message_id=new_message.id)
                
        except Exception as e:
            self.bot.logger.error(f"Error updating monitoring: {e}", exc_info=True)

def setup(bot: commands.Bot) -> None:
    bot.add_cog(Spec(bot))
