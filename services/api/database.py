"""Модуль работы с базой данных MySQL.
Обрабатывает все операции DB, включая управление стримерами, настройками,
событиями и статистикой. Включает автоматическое создание таблиц и логику повторных попыток.
"""

import aiomysql
from datetime import datetime, timezone, timedelta
import asyncio
import logging
import time
from typing import Optional, List, Dict, Any, Union
from functools import wraps

from utils import split_time_by_day
from config import Config


def db_retry(max_retries: int = 3, base_delay: float = 1.0):
    """
    Декоратор для повторного выполнения асинхронных методов базы данных при сбоях.
    
    Args:
        max_retries: Максимальное количество попыток.
        base_delay: Задержка между попытками в секундах.
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
                        delay = base_delay * (2**attempt)  # Exponential backoff
                        self.logger.warning(
                            f"Database connection error (attempt {attempt + 1}/{max_retries}): {e}. "
                            f"Retrying in {delay:.1f}s..."
                        )
                        await asyncio.sleep(delay)
                    else:
                        self.logger.error(
                            f"Database connection failed after {max_retries} attempts: {e}",
                            exc_info=True,
                        )
            raise last_exception

        return wrapper

    return decorator


class Database:
    """Обертка для базы данных MySQL с пулом соединений.

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
        """Запуск пула соединений с базой данных и инициализация таблиц."""
        try:
            self.logger.debug(
                f"Initializing connection pool and tables at {self.db_host}..."
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

            await self.init_db()
        except Exception as e:
            self.logger.error(f"Failed to create connection pool: {e}", exc_info=True)
            raise

    async def close(self) -> None:
        """Закрытие пула соединений."""
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
        finally:
            self.pool = None

    async def init_db(self):
        """Создание таблиц, если они не существуют."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Suppress warnings for IF NOT EXISTS
                    await cursor.execute("SET sql_notes = 0")

                    # Таблица: Стримеры
                    # Хранит информацию о стримерах Twitch
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS streamers (
                            streamer_id BIGINT UNSIGNED PRIMARY KEY,
                            streamer_name VARCHAR(255) NOT NULL,
                            is_online BOOLEAN DEFAULT FALSE,
                            started_at TIMESTAMP NULL DEFAULT NULL,
                            priority INT DEFAULT 0,
                            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            added_by_id BIGINT UNSIGNED,
                            is_paid BOOLEAN DEFAULT FALSE,
                            game_id BIGINT UNSIGNED,
                            game_name VARCHAR(255),
                            stream_title VARCHAR(255),
                            stream_thumbnail_url VARCHAR(512),
                            assigned_pr_id BIGINT UNSIGNED DEFAULT NULL,
                            assigned_at TIMESTAMP NULL DEFAULT NULL,
                            UNIQUE(streamer_name)
                        )
                        """
                    )

                    # Таблица: Настройки
                    # Настройки для каждой гильдии (каналы, роли, кастомные сообщения)
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS settings (
                            guild_id BIGINT UNSIGNED PRIMARY KEY,
                            notification_channel_id BIGINT UNSIGNED,
                            monitoring_channel_id BIGINT UNSIGNED,
                            monitoring_message_id BIGINT UNSIGNED,
                            pr_actions_channel_id BIGINT UNSIGNED,
                            control_panel_channel_id BIGINT UNSIGNED,
                            control_panel_message_id BIGINT UNSIGNED,
                            assistant_role_id BIGINT UNSIGNED,
                            template_stream_online VARCHAR(500) NULL,
                            template_stream_offline VARCHAR(500) NULL,
                            template_category_to_gta VARCHAR(500) NULL,
                            template_category_from_gta VARCHAR(500) NULL,
                            p0_rate FLOAT,
                            p1_rate FLOAT,
                            p2_rate FLOAT,
                            p3_rate FLOAT
                        )
                        """
                    )

                    # Таблица: Ежедневная статистика
                    # Агрегированная статистика по дням и приоритетам
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS daily_stats (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            pr_id BIGINT UNSIGNED NOT NULL,
                            date DATE NOT NULL,
                            p0_seconds INT DEFAULT 0,
                            p1_seconds INT DEFAULT 0,
                            p2_seconds INT DEFAULT 0,
                            p3_seconds INT DEFAULT 0,
                            total_points FLOAT DEFAULT 0,
                            UNIQUE KEY unique_pr_date (pr_id, date)
                        )
                        """
                    )
                    
                    # Таблица: Ассистенты (Глобальная статистика)
                    # Долгосрочная статистика
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS assistants (
                            pr_id BIGINT UNSIGNED PRIMARY KEY,
                            total_spec_seconds BIGINT DEFAULT 0,
                            session_count INT DEFAULT 0,
                            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )

                    # Таблица: События
                    # Специальные события/мероприятия
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS events (
                            id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            guild_id BIGINT UNSIGNED NOT NULL,
                            name VARCHAR(255) NOT NULL,
                            description TEXT,
                            channel_id BIGINT UNSIGNED,
                            message_id BIGINT UNSIGNED,
                            created_by BIGINT UNSIGNED,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            start_time TIMESTAMP NULL DEFAULT NULL,
                            end_time TIMESTAMP NULL DEFAULT NULL,
                            is_active BOOLEAN DEFAULT TRUE,
                            required_pr_count INT DEFAULT 0,
                            notification_sent BOOLEAN DEFAULT FALSE
                        )
                        """
                    )

                    # Таблица: Участники событий
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS event_participants (
                            event_id INT UNSIGNED,
                            user_id BIGINT UNSIGNED,
                            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            left_at TIMESTAMP NULL DEFAULT NULL,
                            PRIMARY KEY (event_id, user_id, joined_at),
                            FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
                        )
                        """
                    )

                    # Таблица: Логи спека (сессии)
                    # Детальный лог каждой сессии спека
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS specs (
                            id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            pr_id BIGINT UNSIGNED NOT NULL,
                            streamer_id BIGINT UNSIGNED NOT NULL,
                            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            ended_at TIMESTAMP NULL DEFAULT NULL,
                            duration_seconds INT UNSIGNED,
                            end_reason VARCHAR(50)
                        )
                        """
                    )

                    # =========================================================
                    # Web Auth Tables (consolidated from web/backend)
                    # =========================================================

                    # Таблица: Пользователи веб-панели
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS users (
                            id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            discord_id BIGINT UNSIGNED UNIQUE NOT NULL,
                            username VARCHAR(50) UNIQUE NOT NULL,
                            nickname VARCHAR(100) NOT NULL,
                            password_hash VARCHAR(255) NOT NULL,
                            role ENUM('employee', 'senior_employee', 'manager', 'developer') NOT NULL,
                            is_active BOOLEAN DEFAULT TRUE,
                            require_password_change BOOLEAN DEFAULT TRUE,
                            failed_login_attempts INT DEFAULT 0,
                            last_failed_login TIMESTAMP NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            created_by INT UNSIGNED,
                            last_login TIMESTAMP NULL,
                            INDEX idx_discord_id (discord_id),
                            INDEX idx_username (username)
                        )
                        """
                    )

                    # Таблица: Сессии
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS sessions (
                            id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            user_id INT UNSIGNED NOT NULL,
                            refresh_token VARCHAR(512) UNIQUE NOT NULL,
                            ip_address VARCHAR(45),
                            user_agent TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            expires_at TIMESTAMP NOT NULL,
                            revoked BOOLEAN DEFAULT FALSE,
                            revoked_at TIMESTAMP NULL,
                            INDEX idx_user_id (user_id),
                            INDEX idx_refresh_token (refresh_token)
                        )
                        """
                    )

                    # Таблица: Логи аутентификации
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS auth_logs (
                            id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            user_id INT UNSIGNED,
                            username VARCHAR(50),
                            action ENUM('login_success', 'login_failed', 'logout', 'token_refresh', 'password_change') NOT NULL,
                            ip_address VARCHAR(45),
                            user_agent TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            INDEX idx_user_id (user_id),
                            INDEX idx_created_at (created_at)
                        )
                        """
                    )

                    # Таблица: Логи команд
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS command_logs (
                            id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            user_id INT UNSIGNED NOT NULL,
                            command_type VARCHAR(100) NOT NULL,
                            command_data JSON,
                            target_guild_id BIGINT UNSIGNED,
                            target_channel_id BIGINT UNSIGNED,
                            executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            success BOOLEAN DEFAULT TRUE,
                            error_message TEXT NULL,
                            INDEX idx_user_id (user_id),
                            INDEX idx_executed_at (executed_at)
                        )
                        """
                    )

                    # Таблица: Права ролей
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS role_permissions (
                            role ENUM('employee', 'senior_employee', 'manager', 'developer') PRIMARY KEY,
                            permissions JSON NOT NULL,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                        )
                        """
                    )

                    await cursor.execute("SET sql_notes = 1")
                    await conn.commit()
                    
                    # Initialize default permissions
                    await self._init_default_permissions(conn)
                    
                    self.logger.info("Database initialized successfully")
        except Exception as e:
            self.logger.error(f"Failed to initialize database: {e}", exc_info=True)
            raise

    async def _init_default_permissions(self, conn):
        """Initialize default role permissions."""
        import json
        async with conn.cursor() as cursor:
            default_permissions = {
                'employee': {
                    'can_view_dashboard': True,
                    'can_execute_commands': False,
                    'can_view_logs': False,
                },
                'senior_employee': {
                    'can_view_dashboard': True,
                    'can_execute_commands': True,
                    'can_view_logs': True,
                },
                'manager': {
                    'can_view_dashboard': True,
                    'can_execute_commands': True,
                    'can_view_logs': True,
                    'can_register_users': True,
                    'can_manage_permissions': False,
                },
                'developer': {
                    'can_view_dashboard': True,
                    'can_execute_commands': True,
                    'can_view_logs': True,
                    'can_register_users': True,
                    'can_manage_permissions': True,
                    'can_access_admin_panel': True,
                }
            }

            for role, permissions in default_permissions.items():
                await cursor.execute(
                    """
                    INSERT INTO role_permissions (role, permissions)
                    VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE permissions = %s
                    """,
                    (role, json.dumps(permissions), json.dumps(permissions))
                )
            await conn.commit()
            self.logger.debug("  ✓ Default permissions initialized")

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
        """
        Создание или обновление стримера в базе данных.

        Args:
            streamer_id: Twitch ID стримера
            streamer_name: Имя пользователя Twitch
            is_online: Статус онлайн
            started_at: Время начала стрима
            priority: Приоритет (0-3)
            added_by_id: ID пользователя Discord, добавившего стримера
            is_paid: Оплачиваемый ли стример
            game_id: ID игры на Twitch
            game_name: Название игры
            stream_title: Название стрима
            stream_thumbnail_url: URL превью стрима
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
        """
        Получение информации о стримере по ID.

        Args:
            streamer_id: Twitch ID

        Returns:
            Словарь с данными или None
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
        """
        Обновление статуса стримера.

        Args:
            streamer_id: Twitch ID стримера
            is_online: Новый статус
            started_at: Время начала (если онлайн)
            game_id: Текущая игра
            game_name: Название игры
            stream_title: Название стрима
            stream_thumbnail_url: Превью
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
    async def update_streamer(
        self,
        streamer_id: int,
        priority: Optional[int] = None,
        is_paid: Optional[bool] = None,
    ) -> bool:
        """Обновление настроек стримера."""
        try:
            updates = []
            values = []
            
            if priority is not None:
                updates.append("priority = %s")
                values.append(priority)
            if is_paid is not None:
                updates.append("is_paid = %s")
                values.append(is_paid)
            
            if not updates:
                return True
                
            values.append(streamer_id)
            
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        f"UPDATE streamers SET {', '.join(updates)} WHERE streamer_id = %s",
                        values,
                    )
                    await conn.commit()
                    return cursor.rowcount > 0
        except Exception as e:
            self.logger.error(f"Failed to update streamer {streamer_id}: {e}", exc_info=True)
            return False

    @db_retry()
    async def delete_streamer(self, streamer_id: int) -> bool:
        """
        Удаление стримера из базы данных.

        Returns:
            True если удален, False если не найден
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
        """
        Проверка существования стримера в базе.

        Args:
            streamer_id: Twitch ID

        Returns:
            True если существует, иначе False
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
        """
        Получение всех стримеров из базы данных.

        Returns:
            Список словарей с данными стримеров
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
        """
        Получение списка всех онлайн стримеров.

        Returns:
            Список словарей с данными онлайн стримеров
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

    # =========================================================================
    # Notification Template Operations
    # =========================================================================

    async def get_notification_template(self, guild_id: int, event_type: str) -> str:
        """
        Получение шаблона уведомления для события.

        Args:
            guild_id: ID Discord сервера
            event_type: Тип события ('stream_online', 'stream_offline' и т.д.)

        Returns:
            Строка шаблона с плейсхолдерами

        Raises:
            ValueError: Если тип события недопустим
        """
        # SQL injection prevention: validate event_type against whitelist
        if event_type not in Config.ALLOWED_EVENT_TYPES:
            self.logger.error(
                f"Invalid event_type '{event_type}' - possible SQL injection attempt"
            )
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
        """
        Обновление шаблона уведомления.

        Args:
            guild_id: ID Discord сервера
            event_type: Тип события
            template: Новый шаблон
        """
        # SQL injection prevention: validate event_type against whitelist
        if event_type not in Config.ALLOWED_EVENT_TYPES:
            self.logger.error(
                f"Invalid event_type '{event_type}' - possible SQL injection attempt"
            )
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
                        """.format(
                            column=column_name
                        ),
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

    # =========================================================================
    # Spec System Operations
    # =========================================================================

    @db_retry()
    async def assign_pr_to_streamer(self, streamer_id: int, pr_id: int) -> bool:
        """
        Назначение PR-ассистента стримеру.

        Args:
            streamer_id: Twitch ID стримера
            pr_id: Discord ID ассистента

        Returns:
            True если успешно, False если уже назначен
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Check if already assigned
                    await cursor.execute(
                        "SELECT assigned_pr_id FROM streamers WHERE streamer_id = %s",
                        (streamer_id,),
                    )
                    result = await cursor.fetchone()
                    if result and result.get("assigned_pr_id"):
                        return False  # Already assigned

                    # Assign PR to streamer
                    await cursor.execute(
                        """
                        UPDATE streamers 
                        SET assigned_pr_id = %s, assigned_at = NOW()
                        WHERE streamer_id = %s
                        """,
                        (pr_id, streamer_id),
                    )

                    # Create spec log entry
                    await cursor.execute(
                        """
                        INSERT INTO specs (pr_id, streamer_id, started_at)
                        VALUES (%s, %s, NOW())
                        """,
                        (pr_id, streamer_id),
                    )

                    # Ensure assistant exists in assistants table
                    await cursor.execute(
                        """
                        INSERT INTO assistants (pr_id) VALUES (%s)
                        ON DUPLICATE KEY UPDATE pr_id = pr_id
                        """,
                        (pr_id,),
                    )

                    await conn.commit()
                    self.logger.debug(
                        f"✓ PR {pr_id} assigned to streamer {streamer_id}"
                    )
                    return True
        except Exception as e:
            self.logger.error(
                f"Failed to assign PR {pr_id} to streamer {streamer_id}: {e}",
                exc_info=True,
            )
            raise

    @db_retry()
    async def unassign_pr_from_streamer(
        self, streamer_id: int, end_reason: str = "stream_end"
    ) -> Optional[Dict[str, Any]]:
        """
        Снятие PR-ассистента со стримера и обновление статистики.

        Args:
            streamer_id: Twitch ID стримера
            end_reason: Причина завершения ('stream_end', 'manual', 'transfer')

        Returns:
            Словарь с данными сессии или None
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Get current assignment info
                    await cursor.execute(
                        """
                        SELECT assigned_pr_id, assigned_at, streamer_name, priority
                        FROM streamers WHERE streamer_id = %s
                        """,
                        (streamer_id,),
                    )
                    result = await cursor.fetchone()

                    if not result or not result.get("assigned_pr_id"):
                        return None  # No one assigned

                    pr_id = result["assigned_pr_id"]
                    assigned_at = result["assigned_at"]
                    streamer_name = result["streamer_name"]
                    priority = result.get("priority", 0)  # Default to 0 if not set

                    # Calculate duration
                    await cursor.execute("SELECT NOW() as now")
                    now_result = await cursor.fetchone()
                    now = now_result["now"]

                    # Ensure timestamps are aware (UTC) for split logic
                    if assigned_at and assigned_at.tzinfo is None:
                         assigned_at = assigned_at.replace(tzinfo=timezone.utc)
                    if now.tzinfo is None:
                        now = now.replace(tzinfo=timezone.utc)

                    duration_seconds = 0
                    if assigned_at:
                        duration_seconds = int((now - assigned_at).total_seconds())

                    # Update specs - close the session
                    await cursor.execute(
                        """
                        UPDATE specs 
                        SET ended_at = NOW(), duration_seconds = %s, end_reason = %s
                        WHERE pr_id = %s AND streamer_id = %s AND ended_at IS NULL
                        ORDER BY started_at DESC LIMIT 1
                        """,
                        (duration_seconds, end_reason, pr_id, streamer_id),
                    )

                    # Clear assignment from streamer
                    await cursor.execute(
                        """
                        UPDATE streamers 
                        SET assigned_pr_id = NULL, assigned_at = NULL 
                        WHERE streamer_id = %s
                        """,
                        (streamer_id,),
                    )
                    await conn.commit()

            # Record Stats (Outside transaction)
            if duration_seconds > 0:
                await self.record_spec_session(
                    pr_id, Config.GUILD_ID, assigned_at, now, priority
                )

            return {
                "pr_id": pr_id,
                "duration_seconds": duration_seconds,
                "streamer_name": streamer_name,
            }
        except Exception as e:
            self.logger.error(
                f"Failed to unassign PR from streamer {streamer_id}: {e}",
                exc_info=True,
            )
            raise

    @db_retry()
    async def get_streamer_assigned_pr(self, streamer_id: int) -> Optional[int]:
        """
        Получение назначенного PR-ассистента для стримера.

        Args:
            streamer_id: Twitch ID стримера

        Returns:
            Discord ID ассистента или None
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT assigned_pr_id FROM streamers WHERE streamer_id = %s",
                        (streamer_id,),
                    )
                    result = await cursor.fetchone()
                    return result.get("assigned_pr_id") if result else None
        except Exception as e:
            self.logger.error(
                f"Failed to get assigned PR for streamer {streamer_id}: {e}",
                exc_info=True,
            )
            raise

    @db_retry()
    async def get_pr_current_streamer(self, pr_id: int) -> Optional[Dict[str, Any]]:
        """
        Получение стримера, которому назначен ассистент.

        Args:
            pr_id: Discord ID ассистента

        Returns:
            Словарь с данными стримера или None
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT * FROM streamers WHERE assigned_pr_id = %s",
                        (pr_id,),
                    )
                    return await cursor.fetchone()
        except Exception as e:
            self.logger.error(
                f"Failed to get current streamer for PR {pr_id}: {e}",
                exc_info=True,
            )
            raise

    @db_retry()
    async def get_pr_total_time(self, pr_id: int) -> int:
        """
        Получение общего времени спека ассистента.

        Args:
            pr_id: Discord ID ассистента

        Returns:
            Общее время в секундах
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT total_spec_seconds FROM assistants WHERE pr_id = %s",
                        (pr_id,),
                    )
                    result = await cursor.fetchone()
                    return result.get("total_spec_seconds", 0) if result else 0
        except Exception as e:
            self.logger.error(
                f"Failed to get total time for PR {pr_id}: {e}",
                exc_info=True,
            )
            raise

    @db_retry()
    async def add_pr_time(self, pr_id: int, seconds: int) -> int:
        """
        Добавление времени к статистике ассистента.

        Args:
            pr_id: Discord ID ассистента
            seconds: Секунды для добавления

        Returns:
            Новое общее время
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO assistants (pr_id, total_spec_seconds)
                        VALUES (%s, %s)
                        ON DUPLICATE KEY UPDATE total_spec_seconds = total_spec_seconds + %s
                        """,
                        (pr_id, seconds, seconds),
                    )
                    await conn.commit()

                    # Get new total
                    await cursor.execute(
                        "SELECT total_spec_seconds FROM assistants WHERE pr_id = %s",
                        (pr_id,),
                    )
                    result = await cursor.fetchone()
                    return result.get("total_spec_seconds", 0) if result else 0
        except Exception as e:
            self.logger.error(f"Failed to add time for PR {pr_id}: {e}", exc_info=True)
            raise

    @db_retry()
    async def subtract_pr_time(self, pr_id: int, seconds: int) -> int:
        """
        Вычитание времени из статистики ассистента (минимум 0).

        Args:
            pr_id: Discord ID ассистента
            seconds: Секунды для вычитания

        Returns:
            Новое общее время
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        UPDATE assistants 
                        SET total_spec_seconds = GREATEST(0, CAST(total_spec_seconds AS SIGNED) - %s)
                        WHERE pr_id = %s
                        """,
                        (seconds, pr_id),
                    )
                    await conn.commit()

                    # Get new total
                    await cursor.execute(
                        "SELECT total_spec_seconds FROM assistants WHERE pr_id = %s",
                        (pr_id,),
                    )
                    result = await cursor.fetchone()
                    return result.get("total_spec_seconds", 0) if result else 0
        except Exception as e:
            self.logger.error(
                f"Failed to subtract time for PR {pr_id}: {e}", exc_info=True
            )
            raise

    @db_retry()
    async def transfer_streamer(
        self, from_pr_id: int, to_pr_id: int, streamer_id: int
    ) -> Optional[int]:
        """
        Передача стримера от одного ассистента другому.

        Args:
            from_pr_id: ID текущего ассистента
            to_pr_id: ID нового ассистента
            streamer_id: Twitch ID стримера

        Returns:
            Длительность сессии предыдущего ассистента или None
        """
        try:
            # First unassign current PR with 'transfer' reason
            result = await self.unassign_pr_from_streamer(streamer_id, "transfer")
            if not result:
                return None

            # Инициализация таблиц
            await self.init_db()
            await self.assign_pr_to_streamer(streamer_id, to_pr_id)

            return result["duration_seconds"]
        except Exception as e:
            self.logger.error(
                f"Failed to transfer streamer {streamer_id} from {from_pr_id} to {to_pr_id}: {e}",
                exc_info=True,
            )
            raise

    @db_retry()
    async def get_pr_actions_channel(self, guild_id: int) -> Optional[int]:
        """
        Получение канала для логов действий PR.

        Args:
            guild_id: ID Discord сервера

        Returns:
            ID канала или None
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT pr_actions_channel_id FROM settings WHERE guild_id = %s",
                        (guild_id,),
                    )
                    result = await cursor.fetchone()
                    return result.get("pr_actions_channel_id") if result else None
        except Exception as e:
            self.logger.error(
                f"Failed to get PR actions channel for guild {guild_id}: {e}",
                exc_info=True,
            )
            raise

    @db_retry()
    async def set_pr_actions_channel(self, guild_id: int, channel_id: int) -> None:
        """
        Установка канала для логов действий PR.

        Args:
            guild_id: ID Discord сервера
            channel_id: ID канала
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO settings (guild_id, pr_actions_channel_id)
                        VALUES (%s, %s)
                        ON DUPLICATE KEY UPDATE pr_actions_channel_id = %s
                        """,
                        (guild_id, channel_id, channel_id),
                    )
                    await conn.commit()
                    self.logger.debug(
                        f"✓ Set PR actions channel to {channel_id} for guild {guild_id}"
                    )
        except Exception as e:
            self.logger.error(
                f"Failed to set PR actions channel for guild {guild_id}: {e}",
                exc_info=True,
            )
            raise

    @db_retry()
    async def get_available_gta_streamers(self) -> list:
        """
        Получение списка онлайн стримеров GTA 5 без назначенного ассистента.

        Returns:
            Список словарей с ID и именем стримера
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        """
                        SELECT streamer_id, streamer_name
                        FROM streamers
                        WHERE is_online = TRUE 
                        AND game_id = %s
                        AND assigned_pr_id IS NULL
                        ORDER BY streamer_name ASC
                        """,
                        (Config.GTA5_GAME_ID,),
                    )
                    return await cursor.fetchall() or []
        except Exception as e:
            self.logger.error(
                f"Failed to get available GTA streamers: {e}",
                exc_info=True,
            )
            return []

    # =========================================================================
    # Events Management
    # =========================================================================

    @db_retry()
    async def create_event(
        self,
        guild_id: int,
        name: str,
        description: str,
        channel_id: int,
        message_id: int,
        created_by: int,
        required_pr_count: int = 0,
        start_time=None,
        notification_sent: bool = False,
    ) -> int:
        """Создание нового события."""
        try:
            if start_time is None:
                start_time = datetime.now(timezone.utc)

            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO events (
                            guild_id, name, description, channel_id, message_id, 
                            created_by, required_pr_count, start_time, notification_sent
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            guild_id,
                            name,
                            description,
                            channel_id,
                            message_id,
                            created_by,
                            required_pr_count,
                            start_time,
                            notification_sent,
                        ),
                    )
                    await conn.commit()
                    return cursor.lastrowid
        except Exception as e:
            self.logger.error(f"Failed to create event: {e}", exc_info=True)
            return None

    @db_retry()
    async def get_active_events(self, guild_id: int) -> list:
        """Получение активных событий гильдии."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        """
                        SELECT * FROM events 
                        WHERE guild_id = %s AND is_active = TRUE
                        ORDER BY start_time ASC
                        """,
                        (guild_id,),
                    )
                    events = await cursor.fetchall()

                    # For each event, get participant count
                    for event in events:
                        await cursor.execute(
                            """
                            SELECT COUNT(*) as count 
                            FROM event_participants 
                            WHERE event_id = %s AND left_at IS NULL
                            """,
                            (event["id"],),
                        )
                        result = await cursor.fetchone()
                        event["current_participants"] = result["count"]

                    return events
        except Exception as e:
            self.logger.error(f"Failed to get active events: {e}", exc_info=True)
            return []

    @db_retry()
    async def get_event(self, event_id: int) -> dict:
        """Получение события по ID."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        "SELECT * FROM events WHERE id = %s", (event_id,)
                    )
                    return await cursor.fetchone()
        except Exception as e:
            self.logger.error(f"Failed to get event {event_id}: {e}", exc_info=True)
            return None

    @db_retry()
    async def end_event(self, event_id: int) -> list:
        """Завершение события и возврат списка участников с длительностью участия."""
        try:
            now = datetime.now(timezone.utc)
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    # 1. Get all active participants to calculate stats
                    await cursor.execute(
                        """
                        SELECT user_id, joined_at
                        FROM event_participants
                        WHERE event_id = %s AND left_at IS NULL
                        """,
                        (event_id,),
                    )
                    participants = await cursor.fetchall()

                    await cursor.execute(
                        "SELECT start_time, guild_id FROM events WHERE id = %s", (event_id,)
                    )
                    event_data = await cursor.fetchone()
                    if not event_data:
                        return []
                        
                    guild_id = event_data["guild_id"]
                    event_start_time = event_data["start_time"].replace(tzinfo=timezone.utc) if event_data["start_time"] else now

                    # 2. Mark event as inactive
                    await cursor.execute(
                        """
                        UPDATE events 
                        SET is_active = FALSE, end_time = %s 
                        WHERE id = %s
                        """,
                        (now, event_id),
                    )

                    # 3. Mark all active participants as left
                    await cursor.execute(
                        """
                        UPDATE event_participants 
                        SET left_at = %s 
                        WHERE event_id = %s AND left_at IS NULL
                        """,
                        (now, event_id),
                    )

                    # 4. Update assistant stats for each participant
                    results = []
                    for p in participants:
                        user_id = p["user_id"]
                        joined_at = p["joined_at"]
                        if joined_at.tzinfo is None:
                            joined_at = joined_at.replace(tzinfo=timezone.utc)

                        # Effective start time is the later of actual event start or user join
                        # This handles users joining before the scheduled start
                        effective_start = max(joined_at, event_start_time)

                        duration = int((now - effective_start).total_seconds())
                        if duration < 0:
                            duration = 0

                        # Use record_spec_session to handle daily stats splitting and global update
                        # Priority 0 for Events (Default)
                        # We need to call this OUTSIDE the transaction loop if record_spec_session manages its own transaction?
                        # record_spec_session uses `async with self.pool.acquire()`.
                        # Nesting works with aiomysql usually if valid.
                        # However, we are holding a cursor on `conn`.
                        # Ideally we collect data and update after?
                        # Or `record_spec_session` can handle it.
                        # `record_spec_session` does `self.pool.acquire()`.
                        # This creates a NEW connection. It is safe.
                        
                        # BUT we are inside `async with self.pool.acquire() as conn` here (Line 1441).
                        # Calls to other methods that acquire new connections are fine.
                        
                        await self.record_spec_session(user_id, guild_id, effective_start, now, priority=0)
                        
                        results.append({"user_id": user_id, "duration": duration})

                    await conn.commit()
                    return results
        except Exception as e:
            self.logger.error(f"Failed to end event {event_id}: {e}", exc_info=True)
            return []

    @db_retry()
    async def record_daily_stats(self, pr_id: int, date_obj: datetime.date, priority: int, duration_seconds: int, points: float):
        """Обновление ежедневной статистики для конкретной даты и приоритета."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Construct column name based on priority
                    # priority is 0-3
                    col_name = f"p{priority}_seconds"
                    
                    await cursor.execute(
                        f"""
                        INSERT INTO daily_stats (pr_id, date, {col_name}, total_points)
                        VALUES (%s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                        {col_name} = {col_name} + %s,
                        total_points = total_points + %s
                        """,
                        (pr_id, date_obj, duration_seconds, points, duration_seconds, points)
                    )
                    await conn.commit()
        except Exception as e:
            self.logger.error(f"Failed to record daily stats: {e}", exc_info=True)

    @db_retry()
    async def get_daily_stats(self, pr_id: int = None, date_obj: datetime.date = None, start_date=None, end_date=None) -> list:
        """Получение ежедневной статистики с фильтрацией."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    query = "SELECT * FROM daily_stats WHERE 1=1"
                    params = []
                    
                    if pr_id:
                        query += " AND pr_id = %s"
                        params.append(pr_id)
                    
                    if date_obj:
                        query += " AND date = %s"
                        params.append(date_obj)
                    elif start_date:
                        query += " AND date >= %s"
                        params.append(start_date)
                        
                    if end_date:
                        query += " AND date <= %s"
                        params.append(end_date)
                        
                    query += " ORDER BY date DESC, total_points DESC LIMIT 100"
                    
                    await cursor.execute(query, tuple(params))
                    return await cursor.fetchall()
        except Exception as e:
            self.logger.error(f"Failed to get daily stats: {e}")
            return []

    @db_retry()
    async def update_daily_stats_manual(self, pr_id: int, date_obj: datetime.date, p0: int, p1: int, p2: int, p3: int, total_points: float):
        """Ручное обновление ежедневной статистики."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Calculate total time
                    # total_time = p0 + p1 + p2 + p3  # Optional check
                    
                    await cursor.execute(
                        """
                        INSERT INTO daily_stats (pr_id, date, p0_seconds, p1_seconds, p2_seconds, p3_seconds, total_points)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                        p0_seconds = %s, p1_seconds = %s, p2_seconds = %s, p3_seconds = %s, total_points = %s
                        """,
                        (pr_id, date_obj, p0, p1, p2, p3, total_points, p0, p1, p2, p3, total_points)
                    )
                    await conn.commit()
                    return True
        except Exception as e:
            self.logger.error(f"Failed to manual update stats: {e}")
            return False

    @db_retry()
    async def get_points_config(self, guild_id: int) -> dict:
        """Получение конфигурации баллов для гильдии."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        "SELECT p0_rate, p1_rate, p2_rate, p3_rate FROM settings WHERE guild_id = %s",
                        (guild_id,)
                    )
                    result = await cursor.fetchone()
                    if result and result['p0_rate'] is not None:
                        return {
                            0: result['p0_rate'],
                            1: result['p1_rate'],
                            2: result['p2_rate'],
                            3: result['p3_rate']
                        }
                    
                    # Return defaults if not found
                    return {k: v for k, v in Config.DEFAULT_POINTS.items()}
        except Exception as e:
             self.logger.error(f"Failed to get points config: {e}")
             return {k: v for k, v in Config.DEFAULT_POINTS.items()}

    @db_retry()
    async def set_points_config(self, guild_id: int, rates: dict):
        """Установка конфигурации баллов."""
        try:
             async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        UPDATE settings 
                        SET p0_rate = %s, p1_rate = %s, p2_rate = %s, p3_rate = %s
                        WHERE guild_id = %s
                        """,
                        (rates[0], rates[1], rates[2], rates[3], guild_id)
                    )
                    await conn.commit()
        except Exception as e:
             self.logger.error(f"Failed to set points config: {e}")



    @db_retry()
    async def update_streamer_priority(self, streamer_id: int, priority: int):
        """Обновление приоритета стримера."""
        try:
             async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "UPDATE streamers SET priority = %s WHERE streamer_id = %s",
                        (priority, streamer_id)
                    )
                    await conn.commit()
                    return True
        except Exception as e:
            self.logger.error(f"Failed to update streamer {streamer_id}: {e}")
            return False

    @db_retry()
    async def record_spec_session(self, pr_id: int, guild_id: int, start_time: datetime, end_time: datetime, priority: int):
        """Запись сессии спека с разделением по дням и расчетом баллов."""
        try:
            # 1. Split time by day
            chunks = split_time_by_day(start_time, end_time)
            if not chunks:
                return

            # 2. Get Point Rates
            config = await self.get_points_config(guild_id)
            # Default rate if not found for priority
            rate_per_hour = config.get(priority, 0.5) 

            # 3. Record each chunk
            for date_obj, duration in chunks:
                # Calculate points: (duration / 3600) * rate
                points = (duration / 3600.0) * rate_per_hour
                
                await self.record_daily_stats(pr_id, date_obj, priority, duration, points)
            
            # 4. Update Global Assistant Stats (assistants table)
            total_duration = int((end_time - start_time).total_seconds())
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                     await cursor.execute(
                        """
                        INSERT INTO assistants (pr_id, total_spec_seconds, session_count) 
                        VALUES (%s, %s, 1) 
                        ON DUPLICATE KEY UPDATE 
                        total_spec_seconds = total_spec_seconds + %s, 
                        session_count = session_count + 1
                        """,
                        (pr_id, total_duration, total_duration),
                    )
                     await conn.commit()

        except Exception as e:
            self.logger.error(f"Failed to record spec session: {e}", exc_info=True)

    @db_retry()
    async def join_event(self, event_id: int, user_id: int) -> bool:
        """Добавление пользователя в событие."""
        try:
            # Check if already joined
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT 1 FROM event_participants 
                        WHERE event_id = %s AND user_id = %s AND left_at IS NULL
                        """,
                        (event_id, user_id),
                    )
                    if await cursor.fetchone():
                        return False  # Already joined

                    now = datetime.now(timezone.utc)
                    await cursor.execute(
                        """
                        INSERT INTO event_participants (event_id, user_id, joined_at)
                        VALUES (%s, %s, %s)
                        """,
                        (event_id, user_id, now),
                    )
                    await conn.commit()
                    return True
        except Exception as e:
            self.logger.error(f"Failed to join event: {e}", exc_info=True)
            return False

    @db_retry()
    async def leave_event(self, event_id: int, user_id: int) -> int:
        """Удаление пользователя из события, обновление статистики и возврат длительности."""
        try:
            now = datetime.now(timezone.utc)
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    # 1. Get joined_at to calculate duration
                    await cursor.execute(
                        """
                        SELECT joined_at 
                        FROM event_participants 
                        WHERE event_id = %s AND user_id = %s AND left_at IS NULL
                        """,
                        (event_id, user_id),
                    )
                    result = await cursor.fetchone()

                    if not result:
                        return 0

                    joined_at = result["joined_at"]
                    if joined_at.tzinfo is None:
                        joined_at = joined_at.replace(tzinfo=timezone.utc)

                    duration = int((now - joined_at).total_seconds())
                    if duration < 0:
                        duration = 0

                    # 2. Mark as left
                    await cursor.execute(
                        """
                        UPDATE event_participants 
                        SET left_at = %s 
                        WHERE event_id = %s AND user_id = %s AND left_at IS NULL
                        """,
                        (now, event_id, user_id),
                    )

                    # Fetch join time
                    await cursor.execute(
                        "SELECT joined_at FROM event_participants WHERE event_id = %s AND user_id = %s AND joined_at < %s ORDER BY joined_at DESC LIMIT 1",
                        (event_id, user_id, now),
                    )
                    res = await cursor.fetchone()

                    if res:
                        joined_at = res["joined_at"]
                        if joined_at.tzinfo is None:
                            joined_at = joined_at.replace(tzinfo=timezone.utc)

                        # Fetch Event Start Time
                        await cursor.execute(
                            "SELECT start_time FROM events WHERE id = %s", (event_id,)
                        )
                        event_data = await cursor.fetchone()
                        event_start_time = (
                            event_data["start_time"].replace(
                                tzinfo=timezone.utc
                            )
                            if event_data
                            else now
                        )

                        # Effective Start Calculation
                        effective_start = max(joined_at, event_start_time)
                        duration = int((now - effective_start).total_seconds())

                        if duration > 0:
                            await cursor.execute(
                                """
                                INSERT INTO assistants (pr_id, total_spec_seconds, session_count) 
                                VALUES (%s, %s, 1) 
                                ON DUPLICATE KEY UPDATE 
                                total_spec_seconds = total_spec_seconds + %s, 
                                session_count = session_count + 1
                                """,
                                (user_id, duration, duration),
                            )

                    await conn.commit()
                    return duration
        except Exception as e:
            self.logger.error(f"Failed to leave event {event_id}: {e}", exc_info=True)
            return 0

    @db_retry()
    async def set_assistant_role(self, guild_id: int, role_id: int) -> None:
        """Установка роли ассистента для гильдии."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO settings (guild_id, assistant_role_id)
                        VALUES (%s, %s) AS new
                        ON DUPLICATE KEY UPDATE assistant_role_id = new.assistant_role_id
                        """,
                        (guild_id, role_id),
                    )
                    await conn.commit()
        except Exception as e:
            self.logger.error(f"Failed to set assistant role: {e}", exc_info=True)

    @db_retry()
    async def mark_event_notification_sent(self, event_id: int) -> None:
        """Отметка о отправке уведомления о событии."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "UPDATE events SET notification_sent = TRUE WHERE id = %s",
                        (event_id,),
                    )
                    await conn.commit()
        except Exception as e:
            self.logger.error(f"Failed to mark event notif sent: {e}", exc_info=True)

    @db_retry()
    async def get_user_active_event_participation(self, user_id: int) -> Optional[dict]:
        """Проверка участия пользователя в активном событии."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        """
                        SELECT e.id, e.name 
                        FROM event_participants ep
                        JOIN events e ON ep.event_id = e.id
                        WHERE ep.user_id = %s AND ep.left_at IS NULL AND e.is_active = TRUE
                        LIMIT 1
                        """,
                        (user_id,),
                    )
                    return await cursor.fetchone()
        except Exception as e:
            self.logger.error(f"Failed to check user active event: {e}", exc_info=True)
            return None

    @db_retry()
    async def get_event_participants(self, event_id: int) -> list:
        """Получение списка активных участников события."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        """
                        SELECT user_id, joined_at 
                        FROM event_participants 
                        WHERE event_id = %s AND left_at IS NULL
                        """,
                        (event_id,),
                    )
                    return await cursor.fetchall() or []
        except Exception as e:
            self.logger.error(f"Failed to get participants: {e}", exc_info=True)
            return []

    @db_retry()
    async def get_top_assistants(self, limit: int = 10) -> list:
        """Получение топ-PR ассистентов по времени спека."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        """
                        SELECT pr_id, total_spec_seconds, session_count 
                        FROM assistants 
                        ORDER BY total_spec_seconds DESC 
                        LIMIT %s
                        """,
                        (limit,),
                    )
                    return await cursor.fetchall()
        except Exception as e:
            self.logger.error(f"Failed to get top assistants: {e}", exc_info=True)
            return []

    @db_retry()
    async def reset_assistant_stats(self, pr_id: int) -> bool:
        """Сброс статистики для конкретного ассистента."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        UPDATE assistants 
                        SET total_spec_seconds = 0, session_count = 0 
                        WHERE pr_id = %s
                        """,
                        (pr_id,),
                    )
                    await conn.commit()
                    return cursor.rowcount > 0
        except Exception as e:
            self.logger.error(f"Failed to reset assistant stats: {e}", exc_info=True)
            return False

    # =========================================================================
    # Assistant CRUD Operations (for routes refactoring)
    # =========================================================================

    @db_retry()
    async def get_all_assistants(self) -> List[Dict[str, Any]]:
        """Получение всех ассистентов, отсортированных по времени спека."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT * FROM assistants ORDER BY total_spec_seconds DESC"
                    )
                    return await cursor.fetchall()
        except Exception as e:
            self.logger.error(f"Failed to get all assistants: {e}", exc_info=True)
            return []

    @db_retry()
    async def get_assistant(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Получение данных ассистента по Discord ID."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT * FROM assistants WHERE pr_id = %s",
                        (user_id,),
                    )
                    return await cursor.fetchone()
        except Exception as e:
            self.logger.error(f"Failed to get assistant {user_id}: {e}", exc_info=True)
            return None

    @db_retry()
    async def get_assistant_stats(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Получение детальной статистики ассистента с daily_stats."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Get basic info
                    await cursor.execute(
                        "SELECT * FROM assistants WHERE pr_id = %s",
                        (user_id,),
                    )
                    assistant = await cursor.fetchone()
                    
                    if not assistant:
                        return None
                    
                    # Get daily stats
                    await cursor.execute(
                        """
                        SELECT date, p0_seconds, p1_seconds, p2_seconds, p3_seconds, total_points
                        FROM daily_stats
                        WHERE pr_id = %s
                        ORDER BY date DESC
                        LIMIT 30
                        """,
                        (user_id,),
                    )
                    daily_stats = await cursor.fetchall()
                    
                    return {
                        **assistant,
                        "daily_stats": daily_stats
                    }
        except Exception as e:
            self.logger.error(f"Failed to get assistant stats {user_id}: {e}", exc_info=True)
            return None

    @db_retry()
    async def create_assistant(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Создание нового ассистента."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Check if exists
                    await cursor.execute(
                        "SELECT * FROM assistants WHERE pr_id = %s",
                        (user_id,),
                    )
                    existing = await cursor.fetchone()
                    
                    if existing:
                        return None  # Already exists
                    
                    # Create
                    await cursor.execute(
                        """
                        INSERT INTO assistants (pr_id, total_spec_seconds, session_count)
                        VALUES (%s, 0, 0)
                        """,
                        (user_id,),
                    )
                    await conn.commit()
                    
                    # Return created
                    await cursor.execute(
                        "SELECT * FROM assistants WHERE pr_id = %s",
                        (user_id,),
                    )
                    return await cursor.fetchone()
        except Exception as e:
            self.logger.error(f"Failed to create assistant {user_id}: {e}", exc_info=True)
            return None

    @db_retry()
    async def delete_assistant(self, user_id: int) -> bool:
        """Удаление ассистента."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "DELETE FROM assistants WHERE pr_id = %s",
                        (user_id,),
                    )
                    await conn.commit()
                    return cursor.rowcount > 0
        except Exception as e:
            self.logger.error(f"Failed to delete assistant {user_id}: {e}", exc_info=True)
            return False

    @db_retry()
    async def subtract_pr_time(self, user_id: int, seconds: int) -> int:
        """Вычитание времени из total_spec_seconds ассистента."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Get current
                    await cursor.execute(
                        "SELECT total_spec_seconds FROM assistants WHERE pr_id = %s",
                        (user_id,),
                    )
                    result = await cursor.fetchone()
                    current = result["total_spec_seconds"] if result else 0
                    new_total = max(0, current - seconds)
                    
                    # Update
                    await cursor.execute(
                        "UPDATE assistants SET total_spec_seconds = %s WHERE pr_id = %s",
                        (new_total, user_id),
                    )
                    await conn.commit()
                    return new_total
        except Exception as e:
            self.logger.error(f"Failed to subtract PR time: {e}", exc_info=True)
            return 0

    # =========================================================================
    # Guild Extended Settings (for routes refactoring)
    # =========================================================================

    @db_retry()
    async def update_guild_extended_settings(
        self,
        guild_id: int,
        pr_actions_channel_id: Optional[int] = None,
        control_panel_channel_id: Optional[int] = None,
        control_panel_message_id: Optional[int] = None,
        assistant_role_id: Optional[int] = None,
    ) -> bool:
        """Обновление расширенных настроек гильдии."""
        try:
            updates = []
            values = []
            
            if pr_actions_channel_id is not None:
                updates.append("pr_actions_channel_id = %s")
                values.append(pr_actions_channel_id)
            if control_panel_channel_id is not None:
                updates.append("control_panel_channel_id = %s")
                values.append(control_panel_channel_id)
            if control_panel_message_id is not None:
                updates.append("control_panel_message_id = %s")
                values.append(control_panel_message_id)
            if assistant_role_id is not None:
                updates.append("assistant_role_id = %s")
                values.append(assistant_role_id)
            
            if not updates:
                return True
                
            values.append(guild_id)
            
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        f"UPDATE settings SET {', '.join(updates)} WHERE guild_id = %s",
                        values,
                    )
                    await conn.commit()
                    return True
        except Exception as e:
            self.logger.error(f"Failed to update guild extended settings: {e}", exc_info=True)
            return False

    @db_retry()
    async def update_guild_templates(
        self,
        guild_id: int,
        template_stream_online: Optional[str] = None,
        template_stream_offline: Optional[str] = None,
        template_category_to_gta: Optional[str] = None,
        template_category_from_gta: Optional[str] = None,
    ) -> bool:
        """Обновление шаблонов уведомлений гильдии."""
        try:
            updates = []
            values = []
            
            if template_stream_online is not None:
                updates.append("template_stream_online = %s")
                values.append(template_stream_online)
            if template_stream_offline is not None:
                updates.append("template_stream_offline = %s")
                values.append(template_stream_offline)
            if template_category_to_gta is not None:
                updates.append("template_category_to_gta = %s")
                values.append(template_category_to_gta)
            if template_category_from_gta is not None:
                updates.append("template_category_from_gta = %s")
                values.append(template_category_from_gta)
            
            if not updates:
                return True
                
            values.append(guild_id)
            
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        f"UPDATE settings SET {', '.join(updates)} WHERE guild_id = %s",
                        values,
                    )
                    await conn.commit()
                    return True
        except Exception as e:
            self.logger.error(f"Failed to update guild templates: {e}", exc_info=True)
            return False

    @db_retry()
    async def update_guild_rates(
        self,
        guild_id: int,
        p0_rate: Optional[float] = None,
        p1_rate: Optional[float] = None,
        p2_rate: Optional[float] = None,
        p3_rate: Optional[float] = None,
    ) -> bool:
        """Обновление рейтов баллов гильдии."""
        try:
            updates = []
            values = []
            
            if p0_rate is not None:
                updates.append("p0_rate = %s")
                values.append(p0_rate)
            if p1_rate is not None:
                updates.append("p1_rate = %s")
                values.append(p1_rate)
            if p2_rate is not None:
                updates.append("p2_rate = %s")
                values.append(p2_rate)
            if p3_rate is not None:
                updates.append("p3_rate = %s")
                values.append(p3_rate)
            
            if not updates:
                return True
                
            values.append(guild_id)
            
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        f"UPDATE settings SET {', '.join(updates)} WHERE guild_id = %s",
                        values,
                    )
                    await conn.commit()
                    return True
        except Exception as e:
            self.logger.error(f"Failed to update guild rates: {e}", exc_info=True)
            return False

    # =========================================================================
    # Events Extended Operations (for routes refactoring)
    # =========================================================================

    @db_retry()
    async def get_scheduled_events(self) -> List[Dict[str, Any]]:
        """Получение событий, которые должны начаться (для уведомлений)."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT id, guild_id, name, channel_id 
                        FROM events 
                        WHERE is_active = TRUE 
                          AND start_time <= UTC_TIMESTAMP() 
                          AND (notification_sent IS FALSE OR notification_sent IS NULL)
                        """
                    )
                    events = await cursor.fetchall()
            
            # Add participants to each event
            results = []
            for e in events:
                participants = await self.get_event_participants(e['id'])
                e['participants'] = participants
                results.append(e)
            
            return results
        except Exception as e:
            self.logger.error(f"Failed to get scheduled events: {e}", exc_info=True)
            return []

    @db_retry()
    async def update_event_message_id(self, event_id: int, message_id: int) -> bool:
        """Обновление message_id события."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "UPDATE events SET message_id = %s WHERE id = %s",
                        (message_id, event_id),
                    )
                    await conn.commit()
                    return True
        except Exception as e:
            self.logger.error(f"Failed to update event message: {e}", exc_info=True)
            return False

    # =========================================================================
    # Spec Extended Operations (for routes refactoring)
    # =========================================================================

    @db_retry()
    async def get_active_spec_sessions(self) -> List[Dict[str, Any]]:
        """Получение всех активных сессий спека."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT s.streamer_id, s.streamer_name, s.assigned_pr_id, s.assigned_at,
                               TIMESTAMPDIFF(SECOND, s.assigned_at, NOW()) as duration_seconds
                        FROM streamers s
                        WHERE s.assigned_pr_id IS NOT NULL
                        ORDER BY s.assigned_at DESC
                        """
                    )
                    return await cursor.fetchall()
        except Exception as e:
            self.logger.error(f"Failed to get active spec sessions: {e}", exc_info=True)
            return []

    @db_retry()
    async def get_pr_spec_sessions(self, pr_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        """Получение истории сессий спека для PR ассистента."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT * FROM specs
                        WHERE pr_id = %s
                        ORDER BY started_at DESC
                        LIMIT %s
                        """,
                        (pr_id, limit),
                    )
                    return await cursor.fetchall()
        except Exception as e:
            self.logger.error(f"Failed to get PR spec sessions: {e}", exc_info=True)
            return []

    # =========================================================================
    # Web Auth Operations (consolidated from web/backend)
    # =========================================================================

    @db_retry()
    async def create_user(
        self,
        discord_id: int,
        username: str,
        nickname: str,
        password_hash: str,
        role: str,
        created_by: Optional[int] = None,
    ) -> int:
        """Create a new user."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO users (discord_id, username, nickname, password_hash, role, created_by) 
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (discord_id, username, nickname, password_hash, role, created_by),
                    )
                    await conn.commit()
                    return cursor.lastrowid
        except Exception as e:
            self.logger.error(f"Failed to create user {username}: {e}", exc_info=True)
            raise

    @db_retry()
    async def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """Get user by username."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT * FROM users WHERE username = %s",
                        (username,),
                    )
                    return await cursor.fetchone()
        except Exception as e:
            self.logger.error(f"Failed to get user {username}: {e}", exc_info=True)
            raise

    @db_retry()
    async def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get user by ID."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT * FROM users WHERE id = %s",
                        (user_id,),
                    )
                    return await cursor.fetchone()
        except Exception as e:
            self.logger.error(f"Failed to get user {user_id}: {e}", exc_info=True)
            raise

    @db_retry()
    async def get_failed_login_attempts(self, username: str) -> int:
        """Get failed login attempts count for username."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT failed_login_attempts FROM users WHERE username = %s",
                        (username,),
                    )
                    result = await cursor.fetchone()
                    return result["failed_login_attempts"] if result else 0
        except Exception:
            return 0

    @db_retry()
    async def increment_failed_login(self, username: str) -> None:
        """Increment failed login attempts."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        UPDATE users 
                        SET failed_login_attempts = failed_login_attempts + 1, 
                            last_failed_login = CURRENT_TIMESTAMP 
                        WHERE username = %s
                        """,
                        (username,),
                    )
                    await conn.commit()
        except Exception as e:
            self.logger.error(f"Failed to increment login stats: {e}", exc_info=True)

    @db_retry()
    async def reset_failed_login(self, user_id: int) -> None:
        """Reset failed login attempts and update last login."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        UPDATE users 
                        SET failed_login_attempts = 0, 
                            last_failed_login = NULL,
                            last_login = CURRENT_TIMESTAMP
                        WHERE id = %s
                        """,
                        (user_id,),
                    )
                    await conn.commit()
        except Exception as e:
            self.logger.error(f"Failed to reset login stats: {e}", exc_info=True)

    @db_retry()
    async def create_session(
        self, user_id: int, refresh_token: str, expires_at, ip: str, user_agent: str
    ) -> int:
        """Create a new session."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO sessions (user_id, refresh_token, expires_at, ip_address, user_agent) 
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (user_id, refresh_token, expires_at, ip, user_agent),
                    )
                    await conn.commit()
                    return cursor.lastrowid
        except Exception as e:
            self.logger.error(f"Failed to create session: {e}", exc_info=True)
            raise

    @db_retry()
    async def revoke_user_sessions(self, user_id: int) -> None:
        """Revoke all sessions for a user."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "UPDATE sessions SET revoked = TRUE, revoked_at = CURRENT_TIMESTAMP WHERE user_id = %s AND revoked = FALSE",
                        (user_id,),
                    )
                    await conn.commit()
        except Exception as e:
            self.logger.error(f"Failed to revoke sessions: {e}", exc_info=True)
            raise

    @db_retry()
    async def log_auth_event(
        self, user_id: Optional[int], username: str, action: str, ip: str, user_agent: str
    ) -> None:
        """Log an authentication event."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO auth_logs (user_id, username, action, ip_address, user_agent) 
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (user_id, username, action, ip, user_agent),
                    )
                    await conn.commit()
        except Exception as e:
            self.logger.error(f"Failed to log auth event: {e}", exc_info=True)
