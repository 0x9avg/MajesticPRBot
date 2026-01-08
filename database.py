# SQL
import aiomysql


class Database:
    def __init__(self, db_host, db_user, db_password, db_name, logger):
        self.connection = None
        self.DB_HOST = db_host
        self.DB_USER = db_user
        self.DB_PASSWORD = db_password
        self.DB_NAME = db_name
        self.logger = logger

    async def start(self):
        self.connection = await aiomysql.connect(
            host=self.DB_HOST,
            user=self.DB_USER,
            password=self.DB_PASSWORD,
            db=self.DB_NAME,
            charset="utf8mb4",
            cursorclass=aiomysql.DictCursor,
        )

        await self.init_tables()

        await self.add_streamer_to_db("yamat0pr", 780806587)
        # await self.add_streamer_to_db("everybodysosa", 837647929)
        # await self.add_streamer_to_db("injtyy", 443489032)
        # await self.add_streamer_to_db("mike4h", 493414313)
        # await self.add_streamer_to_db("asiv0y", 808782745)
        # await self.add_streamer_to_db("maurdos", 649944285)
        # await self.add_streamer_to_db("lukeeeqq", 888790927)

    async def init_tables(self):
        cursor = await self.connection.cursor()
        await cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS streamers (
                StreamerName VARCHAR(255),
                StreamerID BIGINT UNSIGNED PRIMARY KEY,
                isOnline boolean DEFAULT FALSE,
                startedAt TIMESTAMP NULL DEFAULT NULL,
                gameID BIGINT UNSIGNED,
                gameName VARCHAR(255),
                title VARCHAR(255),
                Priority int,
                AddedAt TIMESTAMP,
                AddedByID BIGINT UNSIGNED,
                isPaid boolean
            );

            CREATE TABLE IF NOT EXISTS settings (
                GuildID BIGINT UNSIGNED PRIMARY KEY,
                NotificationChannelID BIGINT UNSIGNED
            )
            """
        )
        await self.connection.commit()

    async def add_streamer_to_db(
        self,
        streamer_name,
        streamer_id,
        is_online=False,
        started_at=None,
        priority=0,
        added_by_id=0,
        is_paid=False,
        game_id=None,
        game_name=None,
        title=None,
    ):
        cursor = await self.connection.cursor()
        await cursor.execute(
            """
            INSERT INTO streamers (StreamerName, StreamerID, isOnline, startedAt, Priority, AddedAt, AddedByID, isPaid, gameID, gameName, title)
            VALUES (%s, %s, %s, %s, %s, NOW(), %s, %s, %s, %s, %s) as new_streamers 
            ON DUPLICATE KEY UPDATE StreamerName=new_streamers.StreamerName, isOnline=new_streamers.isOnline, startedAt=new_streamers.startedAt, Priority=new_streamers.Priority, AddedByID=new_streamers.AddedByID, isPaid=new_streamers.isPaid, gameID=new_streamers.gameID, gameName=new_streamers.gameName, title=new_streamers.title
            """,
            (
                streamer_name,
                streamer_id,
                is_online,
                started_at,
                priority,
                added_by_id,
                is_paid,
                game_id,
                game_name,
                title,
            ),
        )
        await self.connection.commit()

    async def remove_streamer_from_db(self, username):
        cursor = await self.connection.cursor()
        await cursor.execute(
            """
            DELETE FROM streamers WHERE StreamerName = %s
            """,
            (username,),
        )
        await self.connection.commit()

    async def get_online_streamers_from_db(self):
        cursor = await self.connection.cursor()
        await cursor.execute(
            """
            SELECT * FROM streamers WHERE isOnline = TRUE
            """
        )
        result = await cursor.fetchall()
        return result

    async def get_all_streamers_from_db(self):
        cursor = await self.connection.cursor()
        await cursor.execute(
            """
            SELECT * FROM streamers
            """
        )
        result = await cursor.fetchall()
        print(result)
        return result

    async def set_streamer_status_in_db(
        self,
        streamer_id,
        is_online,
        started_at=None,
        game_id=None,
        game_name=None,
        title=None,
    ):
        cursor = await self.connection.cursor()
        await cursor.execute(
            """
            UPDATE streamers SET isOnline = %s, startedAt = %s, gameID = %s, gameName = %s, title = %s WHERE StreamerID = %s
            """,
            (is_online, started_at, game_id, game_name, title, streamer_id),
        )
        await self.connection.commit()

    async def isStreamerInDB(self, streamer_name):
        cursor = await self.connection.cursor()
        await cursor.execute(
            """
            SELECT COUNT(*) as count FROM streamers WHERE StreamerName = %s
            """,
            (streamer_name,),
        )
        result = await cursor.fetchone()
        return result["count"] > 0

    async def setup_guild(self, guild_id, channel_id):
        cursor = await self.connection.cursor()
        await cursor.execute(
            """
            INSERT INTO settings (GuildID, NotificationChannelID)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE NotificationChannelID = %s
            """,
            (guild_id, channel_id, channel_id),
        )
        await self.connection.commit()

    def close(self):
        if self.connection:
            self.connection.close()
