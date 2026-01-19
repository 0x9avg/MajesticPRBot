"""Ког для системы спека - закрепление/открепление стримеров для PR ассистентов."""

import disnake
from disnake import ApplicationCommandInteraction
from disnake.ext import commands
from typing import Optional

from config import Config
from utils import format_spec_duration, create_notification_component


class Spec(commands.Cog):
    """Система спека для PR ассистентов для отслеживания стримеров."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.database = bot.database
        self.twitch_bot = bot.twitch_bot
        # Store pending transfer requests: {target_user_id: {from_pr_id, streamer_id, message}}
        self.pending_transfers = {}

    # =========================================================================
    # Button Handlers
    # =========================================================================

    @commands.Cog.listener("on_button_click")
    async def on_spec_button(self, interaction: disnake.MessageInteraction):
        """Обработка кликов по кнопкам спека."""
        custom_id = interaction.component.custom_id

        if not custom_id:
            return

        # Handle claim button
        if custom_id.startswith("spec_claim_"):
            await self._handle_claim_button(interaction, custom_id)
        # Handle unclaim button
        elif custom_id.startswith("spec_unclaim_"):
            await self._handle_unclaim_button(interaction, custom_id)
        # Handle transfer accept/decline
        elif custom_id.startswith("spec_transfer_"):
            await self._handle_transfer_button(interaction, custom_id)
        # Handle event join
        elif custom_id.startswith("event_join_"):
            await self._handle_event_join(interaction, custom_id)

    async def _handle_event_join(
        self, interaction: disnake.MessageInteraction, custom_id: str
    ):
        """Обработка присоединения/выхода из события."""
        await interaction.response.defer(ephemeral=True)
        try:
            event_id = int(custom_id.replace("event_join_", ""))
            user_id = interaction.user.id

            # Check if event exists and is active
            event = await self.database.get_event(event_id)
            if not event or not event["is_active"]:
                await interaction.followup.send(
                    "❌ Событие завершено или не существует.", ephemeral=True
                )
                return

            # Check if user already joined
            participants = await self.database.get_event_participants(event_id)
            is_joined = any(p["user_id"] == user_id for p in participants)
            if is_joined:
                # Leave
                duration = await self.database.leave_event(event_id, user_id)
                msg = "➖ Вы покинули событие."

                # Log to PR Actions
                duration_str = format_spec_duration(duration)
                await self._send_pr_action(
                    interaction.guild_id,
                    f"📤 **Покинул событие**\n"
                    f"🎉 Событие: **{event['name']}**\n"
                    f"🎯 PR: {interaction.user.mention}\n"
                    f"⏱️ Участие: **{duration_str}**",
                )
            else:
                # Check if spectating a streamer
                current_streamer = await self.database.get_pr_current_streamer(user_id)
                if current_streamer:
                    await interaction.followup.send(
                        f"❌ Ты занят стримером **{current_streamer['streamer_name']}**. Сначала закончи спек.",
                        ephemeral=True,
                    )
                    return

                # Check for other active events
                other_active_event = await self.database.get_user_active_event_participation(user_id)
                if other_active_event:
                    await interaction.followup.send(
                        f"❌ Ты уже участвуешь в событии **{other_active_event['name']}**. Сначала покинь его.",
                        ephemeral=True,
                    )
                    return

                # Join
                # Check limit
                if (
                    event["required_pr_count"] > 0
                    and len(participants) >= event["required_pr_count"]
                ):
                    await interaction.followup.send(
                        "❌ Свободных мест нет.", ephemeral=True
                    )
                    return

                await self.database.join_event(event_id, user_id)
                msg = "➕ Вы присоединились к событию."

                # Log to PR Actions
                await self._send_pr_action(
                    interaction.guild_id,
                    f"📥 **Присоединился к событию**\n"
                    f"🎉 Событие: **{event['name']}**\n"
                    f"🎯 PR: {interaction.user.mention}",
                )

            await interaction.followup.send(msg, ephemeral=True)

            # Update Event Message
            await self._update_event_message(interaction.guild, event_id)
            # Update Monitoring
            await self.twitch_bot.update_monitoring_messages()

        except Exception as e:
            self.bot.logger.error(f"Event join error: {e}", exc_info=True)
            try:
                await interaction.followup.send("❌ Ошибка.", ephemeral=True)
            except:
                pass

    async def _update_event_message(self, guild, event_id):
        """Обновление сообщения события с новым количеством участников."""
        try:
            event = await self.database.get_event(event_id)
            if not event:
                return

            channel = guild.get_channel(event["channel_id"])
            if not channel:
                return

            try:
                message = await channel.fetch_message(event["message_id"])
            except:
                return

            participants = await self.database.get_event_participants(event_id)

            embed = message.embeds[0]
            # Update description to show participants
            # Parse original description? Or just rebuild?
            # We stored description in DB.

            part_list = "\n".join([f"<@{p['user_id']}>" for p in participants])
            if not part_list:
                part_list = "*Нет участников*"

            embed.description = f"{event['description']}\n\n**Требуется PR:** {event['required_pr_count']}\n**Участников:** {len(participants)}\n\n{part_list}"

            await message.edit(embed=embed)
        except Exception as e:
            self.bot.logger.error(f"Failed to update event message: {e}")

    @commands.Cog.listener("on_dropdown")
    async def on_spec_dropdown(self, interaction: disnake.MessageInteraction):
        """Обработка выбора в выпадающих списках спека."""
        custom_id = interaction.component.custom_id

        if custom_id == "spec_claim_select":
            selected_value = interaction.values[0]
            if selected_value == "none":
                await interaction.response.send_message(
                    "❌ Нет доступных стримеров.", ephemeral=True
                )
                return

            # Handle Event Selection
            if selected_value.startswith("event_"):
                try:
                    event_id = int(selected_value.replace("event_", ""))
                    await self._handle_event_join(interaction, f"event_join_{event_id}")
                except ValueError:
                    await interaction.response.send_message(
                        "❌ Ошибка ID события.", ephemeral=True
                    )
                return

            try:
                streamer_id = int(selected_value)
                streamer = await self._process_claim(interaction, streamer_id)
                if streamer:
                    # Update monitoring for everyone
                    await self.twitch_bot.update_monitoring_messages()
            except ValueError:
                await interaction.response.send_message(
                    "❌ Ошибка ID стримера.", ephemeral=True
                )

    async def _process_claim(
        self, interaction: disnake.Interaction, streamer_id: int
    ) -> Optional[dict]:
        """Общая логика закрепа (проверки, БД, логи)."""
        pr_id = interaction.user.id

        # Check if already has a streamer
        current_streamer = await self.database.get_pr_current_streamer(pr_id)
        if current_streamer:
            await interaction.followup.send(
                f"❌ Ты уже закреплен за **{current_streamer['streamer_name']}**. "
                f"Сначала открепись командой `/unclaim`.",
                ephemeral=True,
            )
            return None

        # Check if in active event
        active_event = await self.database.get_user_active_event_participation(pr_id)
        if active_event:
            await interaction.followup.send(
                f"❌ Ты участвуешь в событии **{active_event['name']}**. Покинь его сначала.",
                ephemeral=True,
            )
            return None

        # Get streamer info
        streamer = await self.database.get_streamer(streamer_id)
        if not streamer:
            await interaction.followup.send("❌ Стример не найден.", ephemeral=True)
            return None

        # Check if streamer is still in GTA
        if str(streamer.get("game_id")) != Config.GTA5_GAME_ID:
            await interaction.followup.send(
                f"❌ **{streamer['streamer_name']}** больше не в GTA 5.",
                ephemeral=True,
            )
            return None

        # Try to assign
        success = await self.database.assign_pr_to_streamer(streamer_id, pr_id)
        if not success:
            # Already assigned
            assigned_pr = await self.database.get_streamer_assigned_pr(streamer_id)
            await interaction.followup.send(
                f"❌ Стример уже взят: <@{assigned_pr}>",
                ephemeral=True,
            )
            return None

        # Send success message
        await interaction.followup.send(
            f"✅ Ты взял **{streamer['streamer_name']}**!",
            ephemeral=True,
        )

        # Send to PR actions channel
        await self._send_pr_action(
            interaction.guild_id,
            f"📥 **Закрепление**\n"
            f"👤 Стример: **{streamer['streamer_name']}**\n"
            f"🎯 PR: {interaction.user.mention}",
        )

        return streamer

    async def _handle_claim_button(
        self, interaction: disnake.MessageInteraction, custom_id: str
    ):
        """Обработка клика по кнопке закрепа."""
        await interaction.response.defer(ephemeral=True)
        try:
            streamer_id = int(custom_id.replace("spec_claim_", ""))

            streamer = await self._process_claim(interaction, streamer_id)
            if not streamer:
                return

            # Rebuild the notification with claimed button
            # ONLY if this is a notification interaction (checked by context or assumed from button)
            # Since this handler is called for buttons, we update the message.
            try:
                # Recreate notification components with the claimed state
                new_components = create_notification_component(
                    message="",  # Original message text is hidden/preserved by TextDisplay inside component? No, we pass empty here...
                    # Wait, create_notification_component logic: if message is empty, it returns just container.
                    # But the original message content is separate from components.
                    # We are only editing components. The TextDisplay inside component assumes we pass the message text.
                    # If we pass empty string, the TextDisplay for message is removed.
                    # We should probably preserve the message text if we can get it?
                    # Since we can't easily parse it back, let's assume notification buttons hide the text or we don't need it inside the component if it's in the message body.
                    # However, current implementation puts message INSIDE component as TextDisplay.
                    # If we don't pass it, it disappears.
                    # For now, let's keep it empty as per previous code, or try to implement better preservation if needed.
                    # The previous code passed `message=""`.
                    streamer_name=streamer["streamer_name"],
                    stream_title=streamer.get("stream_title") or "",
                    game_name=streamer.get("game_name") or "",
                    thumbnail_url=streamer.get("stream_thumbnail_url") or "",
                    streamer_id=streamer_id,
                    show_claim_button=True,
                    assigned_pr_id=interaction.user.id,
                    assigned_pr_name=interaction.user.display_name,
                )
                await interaction.message.edit(components=new_components)
            except Exception as e:
                self.bot.logger.warning(f"Could not edit claim message: {e}")

            # Update monitoring
            await self.twitch_bot.update_monitoring_messages()

        except Exception as e:
            self.bot.logger.error(f"Error handling claim button: {e}", exc_info=True)
            try:
                # If deferred, use followup
                await interaction.followup.send("❌ Произошла ошибка.", ephemeral=True)
            except:
                pass

    async def _handle_unclaim_button(
        self, interaction: disnake.MessageInteraction, custom_id: str
    ):
        """Обработка клика по кнопке открепления."""
        await interaction.response.defer(ephemeral=True)
        try:
            streamer_id = int(custom_id.replace("spec_unclaim_", ""))
            pr_id = interaction.user.id

            # Verify this PR is assigned to this streamer
            assigned_pr = await self.database.get_streamer_assigned_pr(streamer_id)
            if assigned_pr != pr_id:
                await interaction.followup.send(
                    "❌ Ты не закреплен за этим стримером.",
                    ephemeral=True,
                )
                return

            # Unassign
            result = await self.database.unassign_pr_from_streamer(
                streamer_id, "manual"
            )
            if not result:
                await interaction.followup.send(
                    "❌ Ошибка открепления.", ephemeral=True
                )
                return

            duration_str = format_spec_duration(result["duration_seconds"])

            await interaction.followup.send(
                f"✅ Ты открепился от **{result['streamer_name']}**.\n"
                f"⏱️ Время спека: **{duration_str}**",
                ephemeral=True,
            )

            # Send to PR actions channel
            await self._send_pr_action(
                interaction.guild_id,
                f"📥 **Открепление (ручное)**\n"
                f"👤 Стример: **{result['streamer_name']}**\n"
                f"🎯 PR: {interaction.user.mention}\n"
                f"⏱️ Спек: **{duration_str}**",
            )

            # Update monitoring
            await self.twitch_bot.update_monitoring_messages()

        except Exception as e:
            self.bot.logger.error(f"Error handling unclaim button: {e}", exc_info=True)
            await interaction.followup.send("❌ Произошла ошибка.", ephemeral=True)

    async def _handle_transfer_button(
        self, interaction: disnake.MessageInteraction, custom_id: str
    ):
        """Обработка кнопок принятия/отклонения передачи."""
        try:
            parts = custom_id.split("_")
            action = parts[2]  # accept or decline
            from_pr_id = int(parts[3])

            if interaction.user.id not in self.pending_transfers:
                await interaction.response.send_message(
                    "❌ Запрос на передачу истек.", ephemeral=True
                )
                return

            transfer_data = self.pending_transfers.pop(interaction.user.id)

            if action == "decline":
                await interaction.response.edit_message(
                    content="❌ Ты отклонил передачу стримера.",
                    components=[],
                )
                return

            # Accept
            await interaction.response.defer()

            # Transfer
            streamer = await self.database.get_streamer(transfer_data["streamer_id"])
            if not streamer:
                await interaction.followup.edit_message(
                    message_id=interaction.message.id,
                    content="❌ Стример не найден.",
                    components=[],
                )
                return

            # Perform transfer
            duration = await self.database.transfer_streamer(
                from_pr_id, interaction.user.id, transfer_data["streamer_id"]
            )

            if duration is None:
                await interaction.followup.edit_message(
                    message_id=interaction.message.id,
                    content="❌ Не удалось выполнить передачу.",
                    components=[],
                )
                return

            duration_str = format_spec_duration(duration)

            duration_str = format_spec_duration(duration)

            await interaction.followup.edit_message(
                message_id=interaction.message.id,
                content=f"✅ Ты принял стримера **{streamer['streamer_name']}**!",
                components=[],
            )

            # Send to PR actions channel - two separate messages
            # Use guild_id from transfer_data since this happens in DM
            guild_id = transfer_data.get("guild_id")
            if guild_id:
                # Message 1: Unclaim from first PR
                await self._send_pr_action(
                    guild_id,
                    f"📤 **Открепление (передача)**\n"
                    f"👤 Стример: **{streamer['streamer_name']}**\n"
                    f"🎯 PR: <@{from_pr_id}>\n"
                    f"⏱️ Спек: **{duration_str}**",
                )
                # Message 2: Claim by second PR
                await self._send_pr_action(
                    guild_id,
                    f"📥 **Закрепление (передача)**\n"
                    f"👤 Стример: **{streamer['streamer_name']}**\n"
                    f"🎯 PR: <@{interaction.user.id}>",
                )

            # Update monitoring
            await self.twitch_bot.update_monitoring_messages()

        except Exception as e:
            self.bot.logger.error(f"Error handling transfer button: {e}", exc_info=True)

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
        try:
            # Check if event
            if target_id.startswith("event_"):
                event_id = int(target_id.replace("event_", ""))
                await self._handle_event_join(interaction, f"event_join_{event_id}")
                return

            streamer_id_int = int(target_id)

            streamer = await self._process_claim(interaction, streamer_id_int)
            if streamer:
                # Update monitoring
                await self.twitch_bot.update_monitoring_messages()

        except ValueError:
            await interaction.response.send_message(
                "❌ Некорректный ID.", ephemeral=True
            )
        except Exception as e:
            self.bot.logger.error(f"Error in /claim: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
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
            guild_id = interaction.guild_id
            if guild_id:
                events = await self.database.get_active_events(guild_id)
                for e in events:
                    if current.lower() in e["name"].lower():
                        options[f"🎉 {e['name']}"] = f"event_{e['id']}"

            # 2. Available Streamers
            available = await self.database.get_available_gta_streamers()
            for s in available:
                if current.lower() in s["streamer_name"].lower():
                    # Check if choices limit reached
                    if len(options) >= 25:
                        break
                    options[f"🎥 {s['streamer_name']}"] = str(s["streamer_id"])

            return options
        except Exception as e:
            self.bot.logger.error(f"Autocomplete error: {e}")
            return {}

    # =========================================================================
    # Commands
    # =========================================================================

    @commands.slash_command(name="spec_time", description="Посмотреть время спека")
    async def spec_time(
        self,
        interaction: ApplicationCommandInteraction,
        user: disnake.Member = None,
    ):
        """Просмотр времени спека для себя или другого пользователя."""
        target = user or interaction.user

        self.defer(ephemeral=True)

        try:
            total_seconds = await self.database.get_pr_total_time(target.id)
            current_streamer = await self.database.get_pr_current_streamer(target.id)

            duration_str = (
                format_spec_duration(total_seconds) if total_seconds else "0м"
            )

            embed = disnake.Embed(
                title=f"⏱️ Статистика спека — {target.display_name}",
                color=disnake.Color.blurple(),
            )
            embed.add_field(
                name="📊 Общее время",
                value=f"**{duration_str}**",
                inline=True,
            )

            if current_streamer:
                embed.add_field(
                    name="🎯 Текущий стример",
                    value=f"**{current_streamer['streamer_name']}**",
                    inline=True,
                )
            else:
                embed.add_field(
                    name="🎯 Текущий стример",
                    value="*Не закреплен*",
                    inline=True,
                )

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            self.bot.logger.error(f"Error in /spec_time: {e}", exc_info=True)
            await interaction.followup.send("❌ Произошла ошибка.", ephemeral=True)

    @commands.slash_command(
        name="add_time", description="Добавить время спека ассистенту (Admin)"
    )
    @commands.has_permissions(administrator=True)
    async def add_time(
        self,
        interaction: ApplicationCommandInteraction,
        user: disnake.Member,
        minutes: int,
    ):
        """Добавить время спека ассистенту (только админ)."""
        try:
            if minutes <= 0:
                await interaction.response.send_message(
                    "❌ Количество минут должно быть положительным.", ephemeral=True
                )
                return

            seconds = minutes * 60
            new_total = await self.database.add_pr_time(user.id, seconds)
            new_total_str = format_spec_duration(new_total)
            added_str = format_spec_duration(seconds)

            await interaction.response.send_message(
                f"✅ Добавлено **{added_str}** для {user.mention}.\n"
                f"📊 Новый итог: **{new_total_str}**",
                ephemeral=True,
            )

        except Exception as e:
            self.bot.logger.error(f"Error in /add_time: {e}", exc_info=True)
            await interaction.response.send_message(
                "❌ Произошла ошибка.", ephemeral=True
            )

    @commands.slash_command(
        name="sub_time", description="Вычесть время спека у ассистента (Admin)"
    )
    @commands.has_permissions(administrator=True)
    async def sub_time(
        self,
        interaction: ApplicationCommandInteraction,
        user: disnake.Member,
        minutes: int,
    ):
        """Вычесть время спека у ассистента (только админ)."""
        try:
            if minutes <= 0:
                await interaction.response.send_message(
                    "❌ Количество минут должно быть положительным.", ephemeral=True
                )
                return

            seconds = minutes * 60
            new_total = await self.database.subtract_pr_time(user.id, seconds)
            new_total_str = format_spec_duration(new_total)
            subtracted_str = format_spec_duration(seconds)

            await interaction.response.send_message(
                f"✅ Вычтено **{subtracted_str}** у {user.mention}.\n"
                f"📊 Новый итог: **{new_total_str}**",
                ephemeral=True,
            )

        except Exception as e:
            self.bot.logger.error(f"Error in /sub_time: {e}", exc_info=True)
            await interaction.response.send_message(
                "❌ Произошла ошибка.", ephemeral=True
            )

    @commands.slash_command(
        name="unclaim", description="Открепиться от текущего стримера"
    )
    async def unclaim(self, interaction: ApplicationCommandInteraction):
        """Ручное открепление от текущего стримера."""
        try:
            pr_id = interaction.user.id
            current_streamer = await self.database.get_pr_current_streamer(pr_id)

            if not current_streamer:
                await interaction.response.send_message(
                    "❌ Ты не закреплен ни за каким стримером.",
                    ephemeral=True,
                )
                return

            result = await self.database.unassign_pr_from_streamer(
                current_streamer["streamer_id"], "manual"
            )

            if not result:
                await interaction.response.send_message(
                    "❌ Ошибка открепления.", ephemeral=True
                )
                return

            duration_str = format_spec_duration(result["duration_seconds"])

            await interaction.response.send_message(
                f"✅ Ты открепился от **{result['streamer_name']}**.\n"
                f"⏱️ Время спека: **{duration_str}**",
                ephemeral=True,
            )

            # Send to PR actions channel
            await self._send_pr_action(
                interaction.guild_id,
                f"📤 **Открепление (ручное)**\n"
                f"👤 Стример: **{result['streamer_name']}**\n"
                f"🎯 PR: {interaction.user.mention}\n"
                f"⏱️ Спек: **{duration_str}**",
            )

            # Update monitoring
            await self.twitch_bot.update_monitoring_messages()

        except Exception as e:
            self.bot.logger.error(f"Error in /unclaim: {e}", exc_info=True)
            await interaction.response.send_message(
                "❌ Произошла ошибка.", ephemeral=True
            )

    @commands.slash_command(
        name="give_streamer", description="Передать стримера другому PR ассистенту"
    )
    async def give_streamer(
        self,
        interaction: ApplicationCommandInteraction,
        user: disnake.Member,
    ):
        """Передача текущего стримера другому PR ассистенту."""
        try:
            if user.id == interaction.user.id:
                await interaction.response.send_message(
                    "❌ Нельзя передать стримера самому себе.",
                    ephemeral=True,
                )
                return

            pr_id = interaction.user.id
            current_streamer = await self.database.get_pr_current_streamer(pr_id)

            if not current_streamer:
                await interaction.response.send_message(
                    "❌ У тебя нет закрепленного стримера.",
                    ephemeral=True,
                )
                return

            # Check if target has a streamer (for swap logic)
            target_streamer = await self.database.get_pr_current_streamer(user.id)

            if target_streamer:
                # Swap proposal
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
            view = disnake.ui.View(timeout=120)
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
                await interaction.response.send_message(
                    f"✅ Запрос на передачу отправлен {user.mention}.",
                    ephemeral=True,
                )
            except disnake.Forbidden:
                self.pending_transfers.pop(user.id, None)
                await interaction.response.send_message(
                    f"❌ Не удалось отправить сообщение {user.mention}. "
                    f"Проверь, открыты ли у него личные сообщения.",
                    ephemeral=True,
                )

        except Exception as e:
            self.bot.logger.error(f"Error in /give_streamer: {e}", exc_info=True)
            await interaction.response.send_message(
                "❌ Произошла ошибка.", ephemeral=True
            )

    # =========================================================================
    # Helpers
    # =========================================================================

    async def _send_pr_action(self, guild_id: int, message: str):
        """Отправка сообщения в канал действий PR, если настроен."""
        try:
            channel_id = await self.database.get_pr_actions_channel(guild_id)
            if not channel_id:
                return

            channel = self.bot.get_channel(channel_id)
            if channel:
                await channel.send(message)
        except Exception as e:
            self.bot.logger.error(f"Error sending PR action: {e}", exc_info=True)


def setup(bot: commands.Bot) -> None:
    bot.add_cog(Spec(bot))
