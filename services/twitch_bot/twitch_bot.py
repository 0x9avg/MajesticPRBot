"""
Twitch Bot - полностью независимый микросервис.
Обрабатывает EventSub события и общается через API и RabbitMQ.
"""

import twitchio
from twitchio import eventsub, AutoClient
import logging
import asyncio
from typing import Optional

from config import Config


class TwitchBot(AutoClient):
    """
    Twitch Bot микросервис.
    
    НЕ имеет прямых ссылок на:
    - database
    - discord_bot
    
    Использует только:
    - api_client для HTTP запросов к API
    - broker для публикации событий в RabbitMQ
    """
    
    def __init__(self, api_client, broker_publisher=None, logger=None):
        self.api = api_client
        self.broker = broker_publisher
        self.logger = logger or Config.setup_logging("TwitchBot")
        self.subs: list[eventsub.SubscriptionPayload] = []
        
        # Enable twitchio logging
        twitchio.utils.setup_logging(level=logging.INFO)
        
        super().__init__(
            client_id=Config.TWITCH_CLIENT_ID,
            client_secret=Config.TWITCH_CLIENT_SECRET,
            bot_id=Config.TWITCH_BOT_ID,
            subscriptions=self.subs,
            force_subscribe=True,
        )
    
    async def get_streamer_id(self, username: str) -> Optional[int]:
        """Get Twitch user ID by username."""
        try:
            user = await self.fetch_user(login=username)
            return user.id if user else None
        except Exception as e:
            self.logger.error(f"Error fetching user ID for {username}: {e}")
            return None
    
    async def get_stream_info(self, streamer_id: int) -> dict:
        """Get current stream info."""
        try:
            streams = await self.fetch_streams(user_ids=[streamer_id])
            is_online = len(streams) > 0
            
            if is_online:
                s = streams[0]
                return {
                    "is_online": True,
                    "title": s.title,
                    "started_at": s.started_at,
                    "game_id": s.game_id,
                    "game_name": s.game_name,
                    "thumbnail_url": s.thumbnail.url if s.thumbnail else None,
                }
            
            return {
                "is_online": False,
                "title": None,
                "started_at": None,
                "game_id": None,
                "game_name": None,
                "thumbnail_url": None,
            }
        except Exception as e:
            self.logger.error(f"Error fetching stream info: {e}")
            return {"is_online": False, "title": None, "started_at": None, 
                    "game_id": None, "game_name": None, "thumbnail_url": None}
    
    async def sync_streamers(self):
        """Sync streamers from API and subscribe to EventSub."""
        try:
            self.logger.info("Syncing streamers from API...")
            streamers = await self.api.list_all_streamers()
            self.logger.info(f"Found {len(streamers)} streamers")
            
            streamer_ids = [
                s["streamer_id"] for s in streamers 
                if s["streamer_id"] != Config.TWITCH_BOT_ID
            ]
            
            # Batch fetch online status
            online_streams = {}
            for i in range(0, len(streamer_ids), 100):
                chunk = streamer_ids[i:i+100]
                streams = await self.fetch_streams(user_ids=chunk)
                for stream in streams:
                    online_streams[str(stream.user.id)] = stream
                await asyncio.sleep(0)
            
            self.logger.info(f"Found {len(online_streams)} streamers online")
            
            new_subs = []
            
            # Update each streamer and prepare subscriptions
            for streamer in streamers:
                streamer_id = streamer["streamer_id"]
                
                if streamer_id == Config.TWITCH_BOT_ID:
                    continue
                
                # Add to subscription list
                new_subs.extend([
                    eventsub.StreamOnlineSubscription(broadcaster_user_id=str(streamer_id)),
                    eventsub.StreamOfflineSubscription(broadcaster_user_id=str(streamer_id)),
                    eventsub.ChannelUpdateSubscription(broadcaster_user_id=str(streamer_id)),
                ])
                
                # Update status via API
                stream = online_streams.get(str(streamer_id))
                is_online = stream is not None
                
                await self.api.update_streamer_status(
                    streamer_id,
                    is_online,
                    started_at=str(stream.started_at) if is_online else None,
                    game_id=stream.game_id if is_online else None,
                    game_name=stream.game_name if is_online else None,
                    stream_title=stream.title if is_online else None,
                    stream_thumbnail_url=stream.thumbnail.url if is_online and stream.thumbnail else None,
                )
                
                await asyncio.sleep(0)
            
            # Perform subscriptions in batches
            if new_subs:
                self.logger.info(f"Subscribing to {len(new_subs)} events...")
                
                # Batch size for EventSub subscriptions (safe limit)
                batch_size = 100
                for i in range(0, len(new_subs), batch_size):
                    batch = new_subs[i:i + batch_size]
                    try:
                        resp = await self.multi_subscribe(batch)
                        if resp and resp.errors:
                             self.logger.warning(f"Subscription errors in batch {i//batch_size}: {resp.errors}")
                    except Exception as ex:
                        self.logger.error(f"Subscription batch {i//batch_size} failed: {ex}")
                    
                    # Small delay between batches
                    await asyncio.sleep(0.1)

            self.logger.info(f"✓ Synced {len(streamers)} streamers")
            
            # Request monitoring refresh
            if self.broker:
                await self.broker.emit_monitoring_refresh(Config.GUILD_ID)
                
        except Exception as e:
            self.logger.error(f"Error syncing streamers: {e}", exc_info=True)
            raise
    
    async def event_ready(self) -> None:
        """Called when bot is ready."""
        self.logger.info(f"✓ Twitch bot ready as {self.user}")
        
        await self.sync_streamers()
    
    async def event_stream_online(self, payload: twitchio.StreamOnline) -> None:
        """Handle stream online event."""
        self.logger.info(f"🔴 Stream ONLINE: {payload.broadcaster.name}")
        
        try:
            stream = await self.get_stream_info(payload.broadcaster.id)
            
            # Update via API
            await self.api.update_streamer_status(
                payload.broadcaster.id,
                True,
                started_at=str(stream["started_at"]) if stream["started_at"] else None,
                game_id=stream["game_id"],
                game_name=stream["game_name"],
                stream_title=stream["title"],
                stream_thumbnail_url=stream["thumbnail_url"],
            )
            
            # Publish event to broker
            if self.broker:
                await self.broker.emit_stream_online(
                    streamer_id=payload.broadcaster.id,
                    streamer_name=payload.broadcaster.name,
                    game_id=str(stream["game_id"]) if stream["game_id"] else None,
                    game_name=stream["game_name"],
                    stream_title=stream["title"],
                    thumbnail_url=stream["thumbnail_url"],
                    guild_id=Config.GUILD_ID,
                )
            
            self.logger.debug(f"✓ Stream online processed: {payload.broadcaster.name}")
            
        except Exception as e:
            self.logger.error(f"Error handling stream online: {e}", exc_info=True)
    
    async def event_stream_offline(self, payload: twitchio.StreamOffline) -> None:
        """Handle stream offline event."""
        self.logger.info(f"⚫ Stream OFFLINE: {payload.broadcaster.name}")
        
        try:
            # Check if claimed
            streamer = await self.api.get_streamer(payload.broadcaster.id)
            
            result = None
            if streamer and streamer.get("assigned_pr_id"):
                # Auto-unclaim via API
                result = await self.api.unclaim_streamer(payload.broadcaster.id, "stream_end")
            
                # Publish unclaim event if there was an assignment
                if result and result.get("status") == "unclaimed" and self.broker:
                    await self.broker.emit_spec_unclaimed(
                        streamer_id=payload.broadcaster.id,
                        streamer_name=payload.broadcaster.name,
                        pr_id=result.get("pr_id", 0),
                        duration_seconds=result.get("duration_seconds", 0),
                        reason="stream_end",
                        guild_id=Config.GUILD_ID,
                    )
            
            # Update status via API
            await self.api.update_streamer_status(
                payload.broadcaster.id,
                False,
                started_at=None,
                game_id=None,
                game_name=None,
                stream_title=None,
                stream_thumbnail_url=None,
            )
            
            # Publish offline event
            if self.broker:
                await self.broker.emit_stream_offline(
                    streamer_id=payload.broadcaster.id,
                    streamer_name=payload.broadcaster.name,
                    guild_id=Config.GUILD_ID,
                )
            
            self.logger.debug(f"✓ Stream offline processed: {payload.broadcaster.name}")
            
        except Exception as e:
            self.logger.error(f"Error handling stream offline: {e}", exc_info=True)
    
    async def event_channel_update(self, payload: twitchio.ChannelUpdate) -> None:
        """Handle channel update (category change)."""
        try:
            self.logger.debug(f"Channel update: {payload.broadcaster.name}")
            
            # Get current data from API
            streamer = await self.api.get_streamer(payload.broadcaster.id)
            
            if not streamer or not streamer.get("is_online"):
                return  # Skip if offline
            
            old_game_id = str(streamer.get("game_id")) if streamer.get("game_id") else None
            new_game_id = payload.category_id if payload.category_id else None
            new_game_name = payload.category_name if payload.category_name else None
            
            # Update via API
            await self.api.update_streamer_status(
                payload.broadcaster.id,
                True,
                started_at=str(streamer.get("started_at")) if streamer.get("started_at") else None,
                game_id=payload.category_id,
                game_name=payload.category_name,
                stream_title=payload.title,
                stream_thumbnail_url=streamer.get("stream_thumbnail_url"),
            )
            
            # Check for GTA category changes
            switched_to_gta = new_game_id == Config.GTA5_GAME_ID and old_game_id != Config.GTA5_GAME_ID
            switched_from_gta = old_game_id == Config.GTA5_GAME_ID and new_game_id != Config.GTA5_GAME_ID
            
            if switched_to_gta or switched_from_gta:
                self.logger.info(f"🎮 Category change: {payload.broadcaster.name} {'→' if switched_to_gta else '←'} GTA 5")
                
                # Auto-unclaim on leaving GTA
                if switched_from_gta and streamer.get("assigned_pr_id"):
                    result = await self.api.unclaim_streamer(payload.broadcaster.id, "category_change")
                    if result and result.get("status") == "unclaimed" and self.broker:
                        await self.broker.emit_spec_unclaimed(
                            streamer_id=payload.broadcaster.id,
                            streamer_name=payload.broadcaster.name,
                            pr_id=result.get("pr_id", 0),
                            duration_seconds=result.get("duration_seconds", 0),
                            reason="category_change",
                            guild_id=Config.GUILD_ID,
                        )
                
                # Publish category change event
                if self.broker:
                    await self.broker.emit_category_change(
                        streamer_id=payload.broadcaster.id,
                        streamer_name=payload.broadcaster.name,
                        old_game_id=old_game_id,
                        new_game_id=new_game_id,
                        new_game_name=new_game_name,
                        stream_title=payload.title,
                        thumbnail_url=streamer.get("stream_thumbnail_url"),
                        guild_id=Config.GUILD_ID,
                    )
            
            # Request monitoring refresh
            if self.broker:
                await self.broker.emit_monitoring_refresh(Config.GUILD_ID)
                
        except Exception as e:
            self.logger.error(f"Error handling channel update: {e}", exc_info=True)
    
    async def add_notification(self, streamer_id: int) -> None:
        """Add EventSub subscriptions for a streamer."""
        if streamer_id == Config.TWITCH_BOT_ID:
            return
        
        try:
            subs = [
                eventsub.StreamOnlineSubscription(broadcaster_user_id=str(streamer_id)),
                eventsub.StreamOfflineSubscription(broadcaster_user_id=str(streamer_id)),
                eventsub.ChannelUpdateSubscription(broadcaster_user_id=str(streamer_id)),
            ]
            
            resp = await self.multi_subscribe(subs)
            if resp.errors:
                self.logger.warning(f"Failed to subscribe for {streamer_id}: {resp.errors}")
            else:
                self.logger.debug(f"✓ Subscribed to events for {streamer_id}")
        except Exception as e:
            self.logger.error(f"Error subscribing: {e}")
    
    async def remove_subscription(self, streamer_id: int) -> None:
        """Remove EventSub subscriptions for a streamer."""
        try:
            subs_response = await self.fetch_eventsub_subscriptions(user_id=str(streamer_id))
            async for sub in subs_response.subscriptions:
                await self.delete_eventsub_subscription(sub.id)
                self.logger.debug(f"Deleted subscription {sub.id}")
        except Exception as e:
            self.logger.error(f"Error removing subscription: {e}")
