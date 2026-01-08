import twitchio
from twitchio import eventsub, AutoClient
import logging


class TwitchBot(AutoClient):
    def __init__(self, client_id, client_secret, bot_id, logger, database) -> None:
        self.subs: list[eventsub.SubscriptionPayload] = []
        self.LOGGER = logger
        self.CLIENT_ID = client_id
        self.CLIENT_SECRET = client_secret
        self.BOT_ID = bot_id
        self.database = database
        self._is_ready_ = False

        twitchio.utils.setup_logging(level=logging.INFO)

        super().__init__(
            client_id=self.CLIENT_ID,
            client_secret=self.CLIENT_SECRET,
            bot_id=self.BOT_ID,
            subscriptions=self.subs,
            force_subscribe=True,
        )

    async def get_streamer_id(self, username: str) -> int:
        user = await self.fetch_user(login=username)
        return user.id if user else None

    async def sync_streamers(self):
        streamers = await self.database.get_all_streamers_from_db()
        for streamer in streamers:
            if streamer["StreamerID"] == self.BOT_ID:
                continue

            self.subs.extend(
                [
                    eventsub.StreamOnlineSubscription(
                        broadcaster_user_id=streamer["StreamerID"]
                    ),
                    eventsub.StreamOfflineSubscription(
                        broadcaster_user_id=streamer["StreamerID"]
                    ),
                ]
            )

            data = await self.get_stream_info(streamer["StreamerID"])
            await self.database.set_streamer_status_in_db(
                streamer["StreamerID"],
                data["is_online"] if data["is_online"] else False,
                data["started_at"] if data["is_online"] else None,
                data["game_id"] if data["is_online"] else None,
                data["game_name"] if data["is_online"] else None,
                data["title"] if data["is_online"] else None,
            )

    async def get_stream_info(self, streamer_id: int):
        streams = await self.fetch_streams(user_ids=[streamer_id])

        is_online = len(streams) > 0

        return {
            "id": streamer_id,
            "is_online": is_online,
            "user": streams[0].user if is_online else None,
            "title": streams[0].title if is_online else None,
            "started_at": streams[0].started_at if is_online else None,
            "game_id": streams[0].game_id if is_online else None,
            "game_name": streams[0].game_name if is_online else None,
            "viewer_count": streams[0].viewer_count if is_online else None,
        }

    # TODO : REMOVE IT LATER
    async def print_channels_status(self):
        streamers = await self.database.get_all_streamers_from_db()
        result = []
        for streamer in streamers:
            status = "ONLINE" if streamer["isOnline"] else "OFFLINE"
            started_info = (
                f", started at {streamer['startedAt']}"
                if streamer["isOnline"] and streamer["startedAt"]
                else ""
            )
            priority = streamer.get("Priority", "N/A")
            added_at = streamer.get("AddedAt", "N/A")
            added_by = streamer.get("AddedByID", "N/A")
            is_paid = streamer.get("isPaid", False)
            self.LOGGER.info(
                f"Streamer: {streamer['StreamerName']} (ID: {streamer['StreamerID']}) is {status}{started_info}, priority: {priority}, added at: {added_at}, added by ID: {added_by}, is paid: {is_paid}"
            )
            result.append(
                f"Streamer: {streamer['StreamerName']} (ID: {streamer['StreamerID']}) is {status}{started_info}, priority: {priority}, added at: {added_at}, added by ID: {added_by}, is paid: {is_paid}"
            )
        return "\n".join(result)

    async def event_ready(self) -> None:
        self.LOGGER.info("Successfully logged in as: %s", self.user)

        await self.sync_streamers()

        await self.get_stream_info(184663047)

        self._is_ready_ = True
        await self.print_channels_status()

    # TODO: Добавить обновление данных о стриме при смене категории (twitchio.eventsub.ChannelUpdateSubscription)

    async def event_stream_online(self, payload: twitchio.StreamOnline) -> None:
        self.LOGGER.info("[%s] started a stream!", payload.broadcaster)
        await self.discord_bot.channel.send(
            f"{payload.broadcaster.name} is now ONLINE!)"
        )

        await self.database.set_streamer_status_in_db(
            payload.broadcaster.id,
            True,
            started_at=payload.started_at,
            game_id=payload.game_id,
            game_name=payload.game_name,
            title=payload.title,
        )
        await self.print_channels_status()

    async def event_stream_offline(self, payload: twitchio.StreamOffline) -> None:
        self.LOGGER.info("[%s] ended a stream!", payload.broadcaster)
        await self.discord_bot.channel.send(
            f"{payload.broadcaster.name} is now OFFLINE!)"
        )

        await self.database.set_streamer_status_in_db(
            payload.broadcaster.id, False, started_at=None
        )
        await self.print_channels_status()

    async def add_notification(self, streamer_id: int) -> None:
        if streamer_id == self.BOT_ID:
            return

        subs: list[eventsub.SubscriptionPayload] = [
            eventsub.StreamOnlineSubscription(broadcaster_user_id=streamer_id),
            eventsub.StreamOfflineSubscription(broadcaster_user_id=streamer_id),
        ]

        resp: twitchio.MultiSubscribePayload = await self.multi_subscribe(subs)
        if resp.errors:
            self.LOGGER.warning(
                "Failed to subscribe to: %r, for user: %s", resp.errors, streamer_id
            )

    # TODO : Not to delete all the subscriptions every time instead only the necessary ones
    async def sync_subscriptions(self) -> None:
        self.subs.clear()
        await self.delete_all_eventsub_subscriptions()

        streamers_ids = await self.database.get_all_streamers_id_from_db()
        for user_id in streamers_ids:
            if user_id == self.BOT_ID:
                continue

            self.subs.extend(
                [
                    eventsub.StreamOnlineSubscription(broadcaster_user_id=user_id),
                    eventsub.StreamOfflineSubscription(broadcaster_user_id=user_id),
                ]
            )
        await self.multi_subscribe(self.subs)
