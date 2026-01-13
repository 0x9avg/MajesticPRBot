"""Database module for PRMajesticBot.

Handles all MySQL database operations with error handling and logging.
Uses aiomysql connection pool for async database connectivity.
"""

import aiomysql
import asyncio
import time
from typing import Optional, List, Dict, Any
from functools import wraps

from config import Config


def db_retry(max_retries: int = 3, base_delay: float = 1.0):
    """Decorator for automatic retry on transient database errors.
    
    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds (exponential backoff applied)
    
    Returns:
        Decorated async function with retry logic
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return await func(self, *args, **kwargs)
                except (aiomysql.OperationalError, aiomysql.InterfaceError) as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)  # Exponential backoff
                        self.logger.warning(
                            f"Database connection error (attempt {attempt + 1}/{max_retries}): {e}. "
                            f"Retrying in {delay:.1f}s..."
                        )
                        await asyncio.sleep(delay)
                    else:
                        self.logger.error(
                            f"Database connection failed after {max_retries} attempts: {e}",
                            exc_info=True
                        )
            raise last_exception
        return wrapper
    return decorator


class Database:
    """MySQL database handler for PRMajesticBot.

    Manages connection pool and provides CRUD operations for:
    - Streamers (Twitch streamers being tracked)
    - Subscriptions (Guild-to-Streamer relationships)
    - Guilds (Discord server settings)
    """

    def __init__(
        self, db_host: str, db_user: str, db_password: str, db_name: str, logger
    ) -> None:
        """Initialize database configuration.

        Args:
            db_host: MySQL server hostname
            db_user: Database username
            db_password: Database password
            db_name: Database name
            logger: Logger instance for this module
        """
        self.pool: Optional[aiomysql.Pool] = None
        self.db_host = db_host
        self.db_user = db_user
        self.db_password = db_password
        self.db_name = db_name
        self.logger = logger

    # =========================================================================
    # Connection Management
    # =========================================================================

    async def start(self) -> None:
        """Start database connection pool and initialize tables."""
        try:
            self.logger.debug(
                f"Creating connection pool to database at {self.db_host}..."
            )
            start_time = time.time()

            self.pool = await aiomysql.create_pool(
                host=self.db_host,
                user=self.db_user,
                password=self.db_password,
                db=self.db_name,
                charset="utf8mb4",
                cursorclass=aiomysql.DictCursor,
                minsize=1,
                maxsize=10,
                pool_recycle=3600,  # Recreate connections every hour to prevent stale connections
            )

            elapsed = time.time() - start_time
            self.logger.debug(f"✓ Connection pool created in {elapsed:.2f}s")

            await self._init_tables()
        except Exception as e:
            self.logger.error(f"Failed to create connection pool: {e}", exc_info=True)
            raise

    async def close(self) -> None:
        """Close database connection pool."""
        try:
            if self.pool:
                self.logger.debug("Closing database connection pool...")
                self.pool.close()
                await self.pool.wait_closed()
                self.logger.info("✓ Database connection pool closed")
        except Exception as e:
            self.logger.error(
                f"Error closing database connection pool: {e}", exc_info=True
            )

    async def _init_tables(self) -> None:
        """Initialize database tables if they don't exist."""
        try:
            self.logger.debug("Initializing database tables...")
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS streamers (
                            streamer_id BIGINT UNSIGNED PRIMARY KEY,
                            streamer_name VARCHAR(255) NOT NULL,
                            is_online BOOLEAN DEFAULT FALSE,
                            started_at TIMESTAMP NULL DEFAULT NULL,
                            game_id BIGINT UNSIGNED,
                            game_name VARCHAR(255),
                            stream_title VARCHAR(255),
                            stream_thumbnail_url VARCHAR(512),
                            priority INT DEFAULT 0,
                            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            added_by_id BIGINT UNSIGNED,
                            is_paid BOOLEAN DEFAULT FALSE
                        );

                        CREATE TABLE IF NOT EXISTS settings (
                            guild_id BIGINT UNSIGNED PRIMARY KEY,
                            notification_channel_id BIGINT UNSIGNED,
                            monitoring_channel_id BIGINT UNSIGNED,
                            monitoring_message_id BIGINT UNSIGNED,
                            template_stream_online VARCHAR(500) NULL,
                            template_stream_offline VARCHAR(500) NULL,
                            template_category_to_gta VARCHAR(500) NULL,
                            template_category_from_gta VARCHAR(500) NULL
                        );

                        CREATE TABLE IF NOT EXISTS subscriptions (
                            guild_id BIGINT UNSIGNED,
                            streamer_id BIGINT UNSIGNED,
                            PRIMARY KEY (guild_id, streamer_id),
                            FOREIGN KEY (streamer_id) REFERENCES streamers(streamer_id) ON DELETE CASCADE
                        );
                    """
                    )
                    await conn.commit()
            self.logger.debug("✓ Database tables initialized")
        except Exception as e:
            self.logger.error(f"Failed to initialize tables: {e}", exc_info=True)
            raise

    # =========================================================================
    # Streamer Operations
    # =========================================================================

    @db_retry()
    async def create_streamer(
        self,
        streamer_id: int,
        streamer_name: str,
        is_online: bool = False,
        started_at: Optional[str] = None,
        priority: int = 0,
        added_by_id: int = 0,
        is_paid: bool = False,
        game_id: Optional[int] = None,
        game_name: Optional[str] = None,
        stream_title: Optional[str] = None,
        stream_thumbnail_url: Optional[str] = None,
    ) -> None:
        """Create or update a streamer in the database.

        Args:
            streamer_id: Twitch user ID
            streamer_name: Twitch username
            is_online: Current online status
            started_at: Stream start timestamp
            priority: Display priority
            added_by_id: Discord user ID who added this streamer
            is_paid: Whether this is a paid promotion
            game_id: Current game/category ID
            game_name: Current game/category name
            stream_title: Current stream title
            stream_thumbnail_url: URL of the stream thumbnail
        """
        try:
            self.logger.debug(
                f"Creating/updating streamer: {streamer_name} (ID: {streamer_id})"
            )
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO streamers (
                            streamer_id, streamer_name, is_online, started_at, priority, 
                            added_at, added_by_id, is_paid, game_id, game_name, stream_title, stream_thumbnail_url
                        )
                        VALUES (%s, %s, %s, %s, %s, NOW(), %s, %s, %s, %s, %s, %s) AS new_data
                        ON DUPLICATE KEY UPDATE 
                            streamer_name = new_data.streamer_name,
                            is_online = new_data.is_online,
                            started_at = new_data.started_at,
                            priority = new_data.priority,
                            added_by_id = new_data.added_by_id,
                            is_paid = new_data.is_paid,
                            game_id = new_data.game_id,
                            game_name = new_data.game_name,
                            stream_title = new_data.stream_title,
                            stream_thumbnail_url = new_data.stream_thumbnail_url
                        """,
                        (
                            streamer_id,
                            streamer_name,
                            is_online,
                            started_at,
                            priority,
                            added_by_id,
                            is_paid,
                            game_id,
                            game_name,
                            stream_title,
                            stream_thumbnail_url,
                        ),
                    )
                    await conn.commit()
            self.logger.debug(f"✓ Streamer {streamer_name} saved")
        except Exception as e:
            self.logger.error(
                f"Failed to create streamer {streamer_name}: {e}", exc_info=True
            )
            raise

    @db_retry()
    async def get_streamer(self, streamer_id: int) -> Optional[Dict[str, Any]]:
        """Get streamer information by ID.

        Args:
            streamer_id: Twitch user ID

        Returns:
            Streamer data dict or None if not found
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT * FROM streamers WHERE streamer_id = %s",
                        (streamer_id,),
                    )
                    return await cursor.fetchone()
        except Exception as e:
            self.logger.error(
                f"Failed to get streamer {streamer_id}: {e}", exc_info=True
            )
            raise

    @db_retry()
    async def update_streamer_status(
        self,
        streamer_id: int,
        is_online: bool,
        started_at: Optional[str] = None,
        game_id: Optional[int] = None,
        game_name: Optional[str] = None,
        stream_title: Optional[str] = None,
        stream_thumbnail_url: Optional[str] = None,
    ) -> None:
        """Update streamer's online status and stream info.

        Args:
            streamer_id: Twitch user ID
            is_online: Current online status
            started_at: Stream start timestamp
            game_id: Current game/category ID
            game_name: Current game/category name
            stream_title: Current stream title
            stream_thumbnail_url: URL of the stream thumbnail
        """
        try:
            self.logger.debug(
                f"Updating streamer {streamer_id} status: online={is_online}"
            )
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        UPDATE streamers 
                        SET is_online = %s, started_at = %s, game_id = %s, 
                            game_name = %s, stream_title = %s, stream_thumbnail_url = %s
                        WHERE streamer_id = %s
                        """,
                        (
                            is_online,
                            started_at,
                            game_id,
                            game_name,
                            stream_title,
                            stream_thumbnail_url,
                            streamer_id,
                        ),
                    )
                    await conn.commit()
        except Exception as e:
            self.logger.error(
                f"Failed to update streamer {streamer_id}: {e}", exc_info=True
            )
            raise

    @db_retry()
    async def delete_streamer(self, streamer_id: int) -> None:
        """Delete a streamer from the database.

        Args:
            streamer_id: Twitch user ID
        """
        try:
            self.logger.debug(f"Deleting streamer {streamer_id}")
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "DELETE FROM streamers WHERE streamer_id = %s",
                        (streamer_id,),
                    )
                    await conn.commit()
            self.logger.debug(f"✓ Streamer {streamer_id} deleted")
        except Exception as e:
            self.logger.error(
                f"Failed to delete streamer {streamer_id}: {e}", exc_info=True
            )
            raise

    @db_retry()
    async def streamer_exists(self, streamer_id: int) -> bool:
        """Check if a streamer exists in the database.

        Args:
            streamer_id: Twitch user ID

        Returns:
            True if streamer exists, False otherwise
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT COUNT(*) as count FROM streamers WHERE streamer_id = %s",
                        (streamer_id,),
                    )
                    result = await cursor.fetchone()
                    return result["count"] > 0
        except Exception as e:
            self.logger.error(
                f"Failed to check streamer {streamer_id}: {e}", exc_info=True
            )
            raise

    @db_retry()
    async def list_all_streamers(self) -> List[Dict[str, Any]]:
        """Get all streamers from the database.

        Returns:
            List of all streamer data dicts
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("SELECT * FROM streamers")
                    return await cursor.fetchall()
        except Exception as e:
            self.logger.error(f"Failed to list streamers: {e}", exc_info=True)
            raise

    @db_retry()
    async def list_online_streamers(self) -> List[Dict[str, Any]]:
        """Get all currently online streamers.

        Returns:
            List of online streamer data dicts
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT * FROM streamers WHERE is_online = TRUE"
                    )
                    return await cursor.fetchall()
        except Exception as e:
            self.logger.error(f"Failed to list online streamers: {e}", exc_info=True)
            raise

    # =========================================================================
    # Subscription Operations
    # =========================================================================

    async def create_subscription(self, guild_id: int, streamer_id: int) -> None:
        """Create a subscription (guild follows streamer).

        Args:
            guild_id: Discord guild ID
            streamer_id: Twitch user ID
        """
        try:
            self.logger.debug(
                f"Creating subscription: guild={guild_id}, streamer={streamer_id}"
            )
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO subscriptions (guild_id, streamer_id)
                        VALUES (%s, %s)
                        ON DUPLICATE KEY UPDATE guild_id = guild_id
                        """,
                        (guild_id, streamer_id),
                    )
                    await conn.commit()
        except Exception as e:
            self.logger.error(f"Failed to create subscription: {e}", exc_info=True)
            raise

    async def delete_subscription(self, guild_id: int, streamer_id: int) -> None:
        """Delete a subscription.

        Args:
            guild_id: Discord guild ID
            streamer_id: Twitch user ID
        """
        try:
            self.logger.debug(
                f"Deleting subscription: guild={guild_id}, streamer={streamer_id}"
            )
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "DELETE FROM subscriptions WHERE guild_id = %s AND streamer_id = %s",
                        (guild_id, streamer_id),
                    )
                    await conn.commit()
        except Exception as e:
            self.logger.error(f"Failed to delete subscription: {e}", exc_info=True)
            raise

    async def subscription_exists(self, guild_id: int, streamer_id: int) -> bool:
        """Check if a subscription exists.

        Args:
            guild_id: Discord guild ID
            streamer_id: Twitch user ID

        Returns:
            True if subscription exists, False otherwise
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT COUNT(*) as count FROM subscriptions WHERE guild_id = %s AND streamer_id = %s",
                        (guild_id, streamer_id),
                    )
                    result = await cursor.fetchone()
                    return result["count"] > 0
        except Exception as e:
            self.logger.error(f"Failed to check subscription: {e}", exc_info=True)
            raise

    async def list_guild_subscriptions(self, guild_id: int) -> List[int]:
        """Get all streamer IDs that a guild is subscribed to.

        Args:
            guild_id: Discord guild ID

        Returns:
            List of streamer IDs
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT streamer_id FROM subscriptions WHERE guild_id = %s",
                        (guild_id,),
                    )
                    result = await cursor.fetchall()
                    return [row["streamer_id"] for row in result]
        except Exception as e:
            self.logger.error(
                f"Failed to list guild subscriptions for {guild_id}: {e}", exc_info=True
            )
            raise

    async def has_any_subscriptions(self, streamer_id: int) -> bool:
        """Check if any guild is subscribed to a streamer.

        Used to determine if a streamer can be safely deleted.

        Args:
            streamer_id: Twitch user ID

        Returns:
            True if at least one subscription exists, False otherwise
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT COUNT(*) as count FROM subscriptions WHERE streamer_id = %s",
                        (streamer_id,),
                    )
                    result = await cursor.fetchone()
                    return result["count"] > 0
        except Exception as e:
            self.logger.error(
                f"Failed to check subscriptions for {streamer_id}: {e}", exc_info=True
            )
            raise

    async def list_streamer_guilds(self, streamer_id: int) -> List[int]:
        """Get all guild IDs that are subscribed to a streamer.

        Args:
            streamer_id: Twitch user ID

        Returns:
            List of guild IDs
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT guild_id FROM subscriptions WHERE streamer_id = %s",
                        (streamer_id,),
                    )
                    result = await cursor.fetchall()
                    return [row["guild_id"] for row in result]
        except Exception as e:
            self.logger.error(
                f"Failed to list streamer guilds for {streamer_id}: {e}", exc_info=True
            )
            raise

    # =========================================================================
    # Guild Operations
    # =========================================================================

    async def create_or_update_guild(
        self,
        guild_id: int,
        *,
        notification_channel_id: Optional[int] = None,
        monitoring_channel_id: Optional[int] = None,
        monitoring_message_id: Optional[int] = None,
    ) -> None:
        """Create or update guild settings.

        Args:
            guild_id: Discord guild ID
            notification_channel_id: Discord channel ID for notifications (optional)
            monitoring_channel_id: Discord channel ID for monitoring (optional)
            monitoring_message_id: Discord message ID for monitoring embed (optional)
        """
        try:
            self.logger.debug(
                f"Saving guild settings: guild={guild_id}, notification channel={notification_channel_id}, monitoring channel={monitoring_channel_id}, monitoring message={monitoring_message_id}"
            )
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # First, get existing settings using the same cursor to ensure consistency
                    await cursor.execute(
                        "SELECT * FROM settings WHERE guild_id = %s",
                        (guild_id,),
                    )
                    existing = await cursor.fetchone()

                    # Use existing values if new ones not provided
                    final_notification = (
                        notification_channel_id
                        if notification_channel_id is not None
                        else (
                            existing.get("notification_channel_id")
                            if existing
                            else None
                        )
                    )
                    final_monitoring = (
                        monitoring_channel_id
                        if monitoring_channel_id is not None
                        else (
                            existing.get("monitoring_channel_id") if existing else None
                        )
                    )
                    final_message = (
                        monitoring_message_id
                        if monitoring_message_id is not None
                        else (
                            existing.get("monitoring_message_id") if existing else None
                        )
                    )

                    await cursor.execute(
                        """
                        INSERT INTO settings (guild_id, notification_channel_id, monitoring_channel_id, monitoring_message_id)
                        VALUES (%s, %s, %s, %s) AS new_settings
                        ON DUPLICATE KEY UPDATE 
                            notification_channel_id = new_settings.notification_channel_id, 
                            monitoring_channel_id = new_settings.monitoring_channel_id, 
                            monitoring_message_id = new_settings.monitoring_message_id
                        """,
                        (
                            guild_id,
                            final_notification,
                            final_monitoring,
                            final_message,
                        ),
                    )
                    await conn.commit()
                    self.logger.debug(f"✓ Guild {guild_id} settings saved successfully")
        except Exception as e:
            self.logger.error(f"Failed to save guild {guild_id}: {e}", exc_info=True)
            raise

    async def get_guild(self, guild_id: int) -> Optional[Dict[str, Any]]:
        """Get guild settings.

        Args:
            guild_id: Discord guild ID

        Returns:
            Guild settings dict or None if not found
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT * FROM settings WHERE guild_id = %s",
                        (guild_id,),
                    )
                    return await cursor.fetchone()
        except Exception as e:
            self.logger.error(f"Failed to get guild {guild_id}: {e}", exc_info=True)
            raise

    async def list_guilds_with_monitoring(self) -> List[Dict[str, Any]]:
        """Get all guilds that have monitoring channel configured.

        Returns:
            List of guild settings dicts with monitoring_channel_id set
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT * FROM settings 
                        WHERE monitoring_channel_id IS NOT NULL
                        """
                    )
                    return await cursor.fetchall()
        except Exception as e:
            self.logger.error(
                f"Failed to list guilds with monitoring: {e}", exc_info=True
            )
            raise

    async def list_guild_streamers(self, guild_id: int) -> List[Dict[str, Any]]:
        """Get all streamer data for streamers a guild is subscribed to.

        Args:
            guild_id: Discord guild ID

        Returns:
            List of streamer data dicts
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT s.* FROM streamers s
                        INNER JOIN subscriptions sub ON s.streamer_id = sub.streamer_id
                        WHERE sub.guild_id = %s
                        """,
                        (guild_id,),
                    )
                    return await cursor.fetchall()
        except Exception as e:
            self.logger.error(
                f"Failed to list streamers for guild {guild_id}: {e}", exc_info=True
            )
            raise

    # =========================================================================
    # Notification Template Operations
    # =========================================================================

    async def get_notification_template(
        self, guild_id: int, event_type: str
    ) -> str:
        """Get notification template for a specific event.

        Args:
            guild_id: Discord guild ID
            event_type: One of 'stream_online', 'stream_offline', 
                       'category_to_gta', 'category_from_gta'

        Returns:
            Template string with placeholders
        
        Raises:
            ValueError: If event_type is not in allowed list
        """
        # SQL injection prevention: validate event_type against whitelist
        if event_type not in Config.ALLOWED_EVENT_TYPES:
            self.logger.error(f"Invalid event_type '{event_type}' - possible SQL injection attempt")
            raise ValueError(f"Invalid event type: {event_type}")
        
        column_name = f"template_{event_type}"
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        f"SELECT {column_name} FROM settings WHERE guild_id = %s",
                        (guild_id,),
                    )
                    result = await cursor.fetchone()
                    if result and result.get(column_name):
                        return result[column_name]
                    return Config.TEMPLATE_DEFAULTS.get(event_type, "")
        except Exception as e:
            self.logger.error(
                f"Failed to get template for guild {guild_id}: {e}", exc_info=True
            )
            return Config.TEMPLATE_DEFAULTS.get(event_type, "")

    async def update_notification_template(
        self, guild_id: int, event_type: str, template: str
    ) -> None:
        """Update notification template for a specific event.

        Args:
            guild_id: Discord guild ID
            event_type: One of 'stream_online', 'stream_offline',
                       'category_to_gta', 'category_from_gta'
            template: New template string
        
        Raises:
            ValueError: If event_type is not in allowed list
        """
        # SQL injection prevention: validate event_type against whitelist
        if event_type not in Config.ALLOWED_EVENT_TYPES:
            self.logger.error(f"Invalid event_type '{event_type}' - possible SQL injection attempt")
            raise ValueError(f"Invalid event type: {event_type}")
        
        column_name = f"template_{event_type}"
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Ensure guild exists in settings
                    await cursor.execute(
                        """
                        INSERT INTO settings (guild_id, {column}) 
                        VALUES (%s, %s)
                        ON DUPLICATE KEY UPDATE {column} = %s
                        """.format(column=column_name),
                        (guild_id, template, template),
                    )
                    await conn.commit()
                    self.logger.debug(
                        f"✓ Updated {event_type} template for guild {guild_id}"
                    )
        except Exception as e:
            self.logger.error(
                f"Failed to update template for guild {guild_id}: {e}", exc_info=True
            )
            raise
