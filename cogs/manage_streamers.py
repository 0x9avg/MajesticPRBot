"""Cog for managing streamers - add, remove, and list."""

import disnake
from disnake import ApplicationCommandInteraction, MessageInteraction, Embed
from disnake.ext import commands
from datetime import timezone
import calendar


class ManageStreamers(commands.Cog):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.database = bot.database
        self.twitch_bot = bot.twitch_bot

    @commands.slash_command(
        name="add_streamer", description="Add new streamer to the database"
    )
    async def add_streamer(
        self,
        interaction: ApplicationCommandInteraction,
        url: str,
        priority: int = 0,
        is_paid: bool = False,
    ) -> None:

        try:
            await interaction.response.defer(ephemeral=True)
            
            self.bot.logger.debug(f"User {interaction.user} ({interaction.user.id}) adding streamer: {url}")

            if url.startswith("https://www.twitch.tv/"):
                username = url.replace("https://www.twitch.tv/", "").rstrip("/").strip()
            else:
                username = url.rstrip("/").strip()
            
            self.bot.logger.debug(f"Parsed username: {username}")

            streamer_id = await self.twitch_bot.get_streamer_id(username)
            if streamer_id is None:
                self.bot.logger.warning(f"Streamer {username} not found on Twitch")
                await interaction.followup.send(f"Streamer {username} not found on Twitch.")
                return

            await self.twitch_bot.add_notification(streamer_id)

            stream_data = await self.twitch_bot.get_stream_info(streamer_id)

            if not await self.database.streamer_exists(streamer_id):
                self.bot.logger.debug(f"Adding new streamer to database: {username}")
                await self.database.create_streamer(
                    streamer_name=username,
                    streamer_id=streamer_id,
                    is_online=stream_data["is_online"],
                    started_at=stream_data["started_at"],
                    game_id=stream_data["game_id"],
                    game_name=stream_data["game_name"],
                    stream_title=stream_data["title"],
                    priority=priority,
                    added_by_id=interaction.user.id,
                    is_paid=is_paid,
                )

            await self.database.create_subscription(interaction.guild_id, streamer_id)
            self.bot.logger.debug(f"✓ Streamer {username} added for guild {interaction.guild_id}")
            await interaction.followup.send(f"Streamer {username} added to the database.")
        except Exception as e:
            self.bot.logger.error(f"Error adding streamer {url}: {e}", exc_info=True)
            await interaction.followup.send(f"An error occurred while adding the streamer: {str(e)}", ephemeral=True)

    @commands.slash_command(
        name="remove_streamer", description="Remove a streamer from the database"
    )
    async def remove_streamer(
        self, interaction: ApplicationCommandInteraction, url: str
    ) -> None:
        try:
            self.bot.logger.debug(f"User {interaction.user} ({interaction.user.id}) removing streamer: {url}")
            
            if url.startswith("https://www.twitch.tv/"):
                username = url.replace("https://www.twitch.tv/", "").rstrip("/")
            else:
                username = url.rstrip("/")

            streamer_id = await self.twitch_bot.get_streamer_id(username)
            if streamer_id is None:
                await interaction.response.send_message(
                    f"Streamer {username} not found on Twitch."
                )
                return

            if await self.database.subscription_exists(
                interaction.guild_id, streamer_id
            ):
                await interaction.response.defer(ephemeral=False)
                await self.database.delete_subscription(interaction.guild_id, streamer_id)
                self.bot.logger.debug(f"✓ Removed subscription to {username} for guild {interaction.guild_id}")
                await interaction.followup.send(
                    f"Streamer {username} removed from the database."
                )
            else:
                self.bot.logger.warning(f"No subscription found for {username} on guild {interaction.guild_id}")
                await interaction.response.send_message(
                    f"You are not followed to {username}."
                )
                return

            if not await self.database.has_any_subscriptions(streamer_id):
                self.bot.logger.debug(f"Removing streamer {username} from database (no more subscriptions)")
                await self.database.delete_streamer(streamer_id)
                await self.twitch_bot.sync_subscriptions()
        except Exception as e:
            self.bot.logger.error(f"Error removing streamer {url}: {e}", exc_info=True)
            await interaction.response.send_message(f"An error occurred while removing the streamer: {str(e)}", ephemeral=True)

    @commands.slash_command(
        name="streamers", description="Показать онлайн стримеров на которых подписан сервер"
    )
    async def streamers(self, interaction: ApplicationCommandInteraction) -> None:
        """Display online streamers that the guild is subscribed to."""
        try:
            await interaction.response.defer()
            
            # Get subscribed streamer IDs for this guild
            subscribed_ids = await self.database.list_guild_subscriptions(interaction.guild_id)
            
            # Check if guild has any subscriptions
            if not subscribed_ids:
                await interaction.followup.send(
                    embed=disnake.Embed(
                        title="📭 Нет подписок",
                        description="Этот сервер не подписан ни на одного стримера.\n"
                                    "Используйте `/add_streamer` чтобы добавить стримера.",
                        color=disnake.Color.orange()
                    )
                )
                return
            
            # Get streamer info and filter only online ones
            online_streamers = []
            gta_count = 0
            
            for streamer_id in subscribed_ids:
                streamer = await self.database.get_streamer(streamer_id)
                if streamer and streamer.get("is_online"):
                    online_streamers.append(streamer)
                    if str(streamer.get("game_id")) == "32982":
                        gta_count += 1
            
            # Check if any streamers are online
            if not online_streamers:
                await interaction.followup.send(
                    embed=disnake.Embed(
                        title="😴 Все офлайн",
                        description=f"Из **{len(subscribed_ids)}** подписанных стримеров сейчас никто не в эфире.",
                        color=disnake.Color.greyple()
                    )
                )
                return
            
            # Build embed with online streamers
            embed = disnake.Embed(
                title="🎥 Стримеры онлайн — Majestic",
                description=f"**🟢 в GTA** · **🟠 не в GTA**\n\n"
                            f"**Онлайн:** {len(online_streamers)} · **В GTA:** {gta_count} · "
                            f"**Всего подписок:** {len(subscribed_ids)}",
                color=disnake.Color.green()
            )
            
            online_streamers.sort(key=lambda s: s.get("priority", 0), reverse=True)
            
            for streamer in online_streamers:
                streamer_name = streamer["streamer_name"]
                started_at = streamer.get("started_at")
                # Convert naive datetime (UTC from DB) to unix timestamp properly
                if started_at:
                    started_at_unix = int(calendar.timegm(started_at.timetuple()))
                else:
                    started_at_unix = 0
                stream_title = streamer.get("stream_title") or "Без названия"
                game_name = streamer.get("game_name") or "Не в игре"
                priority = streamer.get("priority", 0)
                game_id = str(streamer.get("game_id", ""))
                game_emoji = "🟢" if game_id == "32982" else "🟠"
                
                embed.add_field(
                    name=f"{game_emoji} {streamer_name}",
                    value=f"**{stream_title[:50]}{'...' if len(stream_title) > 50 else ''}**\n"
                          f"🏷 Приоритет: **{priority}**  🎮 **{game_name}**\n"
                          f"🕒 Стримит: <t:{started_at_unix}:R>\n"
                          f"🔗 https://twitch.tv/{streamer_name}",
                    inline=False
                )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            self.bot.logger.error(f"Error in /streamers command: {e}", exc_info=True)
            await interaction.followup.send("Произошла ошибка.", ephemeral=True)


def setup(bot: commands.Bot) -> None:
    bot.add_cog(ManageStreamers(bot))
