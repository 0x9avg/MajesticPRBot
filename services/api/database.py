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
        """Initialize the database schema."""
        try:
            self.logger.info("Initializing database schema...")
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("SET sql_notes = 0")

                    # =========================================================
                    # 1. Streamers Table
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS streamers (
                            streamer_id BIGINT UNSIGNED PRIMARY KEY,
                            streamer_name VARCHAR(25) NOT NULL,
                            is_online BOOLEAN DEFAULT FALSE,
                            stream_title VARCHAR(255),
                            stream_thumbnail_url VARCHAR(512),
                            stream_game_id BIGINT UNSIGNED,
                            stream_game_name VARCHAR(255),
                            stream_started_at TIMESTAMP NULL,
                            priority INT DEFAULT 0,
                            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            added_by_id BIGINT UNSIGNED,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            UNIQUE(streamer_name)
                        )
                        """
                    )

                    # =========================================================
                    # 2. Settings Table
                    # =========================================================
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
                            template_stream_online VARCHAR(500),
                            template_stream_offline VARCHAR(500),
                            template_category_to_gta VARCHAR(500),
                            template_category_from_gta VARCHAR(500),
                            p0_rate FLOAT DEFAULT 1.0,
                            p1_rate FLOAT DEFAULT 1.2,
                            p2_rate FLOAT DEFAULT 1.5,
                            p3_rate FLOAT DEFAULT 2.0,
                            probation_rate FLOAT DEFAULT 1.2
                        )
                        """
                    )

                    # =========================================================
                    # 3. Assistants Table
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS assistants (
                            pr_id BIGINT UNSIGNED PRIMARY KEY,
                            nickname VARCHAR(100),
                            role ENUM('junior_employee', 'employee', 'senior_employee', 'manager', 'developer') NOT NULL,
                            
                            -- Current Assignment State
                            assigned_to_type ENUM('streamer', 'event') NULL,
                            assigned_to_id BIGINT UNSIGNED NULL,
                            
                            total_spec_seconds BIGINT DEFAULT 0,
                            session_count INT DEFAULT 0,
                            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )

                    # =========================================================
                    # 4. Spec Sessions Table
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS spec_sessions (
                            id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            pr_id BIGINT UNSIGNED NOT NULL,
                            
                            target_type ENUM('streamer', 'event') NOT NULL DEFAULT 'streamer',
                            target_id BIGINT UNSIGNED NOT NULL,
                            is_probation BOOLEAN DEFAULT FALSE,
                            
                            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            ended_at TIMESTAMP NULL,
                            end_reason VARCHAR(50),
                            
                            INDEX idx_pr_history (pr_id, started_at),
                            INDEX idx_active_sessions (ended_at)
                        )
                        """
                    )

                    # =========================================================
                    # 5. Daily Stats Table
                    # =========================================================
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
                            probation_seconds INT DEFAULT 0,
                            
                            total_points FLOAT DEFAULT 0,
                            
                            UNIQUE KEY unique_pr_date (pr_id, date)
                        )
                        """
                    )

                    # =========================================================
                    # 6. Events Table
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS events (
                            id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            name VARCHAR(255) NOT NULL,
                            description TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            start_time TIMESTAMP NULL,
                            is_active BOOLEAN DEFAULT TRUE,
                            notification_sent BOOLEAN DEFAULT FALSE,
                            required_pr_count INT DEFAULT 1,
                            
                            channel_id BIGINT UNSIGNED,
                            message_id BIGINT UNSIGNED,
                            created_by BIGINT UNSIGNED
                        )
                        """
                    )

                    # =========================================================
                    # 7. Web Auth Table (ex Users)
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS web_auth (
                            id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            discord_id BIGINT UNSIGNED UNIQUE NOT NULL,
                            username VARCHAR(50) UNIQUE NOT NULL,
                            password_hash VARCHAR(255) NOT NULL,
                            is_active BOOLEAN DEFAULT TRUE,
                            require_password_change BOOLEAN DEFAULT TRUE,
                            failed_login_attempts INT DEFAULT 0,
                            last_login TIMESTAMP NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )

                    # Sessions (System)
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS sessions (
                            id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            user_id INT UNSIGNED NOT NULL, 
                            refresh_token VARCHAR(255) UNIQUE NOT NULL,
                            expires_at TIMESTAMP NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            revoked BOOLEAN DEFAULT FALSE,
                            revoked_at TIMESTAMP NULL,
                            ip_address VARCHAR(45),
                            user_agent TEXT,
                            INDEX idx_user_id (user_id),
                            INDEX idx_refresh_token (refresh_token)
                        )
                        """
                    )

                    # Auth Logs (System)
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

                    # Role Permissions (System)
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS role_permissions (
                            role VARCHAR(50) PRIMARY KEY,
                            permissions JSON NOT NULL,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                        )
                        """
                    )

                    # =========================================================
                    # Admin Logs Table (GEMINI.md: Audit Logs for admin actions)
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS admin_logs (
                            id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            admin_id BIGINT UNSIGNED NOT NULL,
                            action VARCHAR(50) NOT NULL,
                            target_type VARCHAR(50),
                            target_id VARCHAR(100),
                            details JSON,
                            ip_address VARCHAR(45),
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            INDEX idx_admin_id (admin_id),
                            INDEX idx_action (action),
                            INDEX idx_created_at (created_at)
                        )
                        """
                    )

                    await cursor.execute("SET sql_notes = 1")
                    await conn.commit()

                    # Initialize default permissions
                    await self._init_default_permissions(conn)

                    self.logger.info("Database initialized successfully (V2 Final)")
        except Exception as e:
            self.logger.error(f"Failed to initialize database: {e}", exc_info=True)
            raise

    async def _init_default_permissions(self, conn):
        """Initialize default role permissions."""
        import json

        async with conn.cursor() as cursor:
            default_permissions = {
                "junior_employee": {
                    "can_view_dashboard": True,
                    "can_spec_probation": True,
                    "can_manage_events": False,
                    "can_manage_streamers": False,
                    "can_execute_commands": False,
                    "can_view_logs": False,
                },
                "employee": {
                    "can_view_dashboard": True,
                    "can_spec_probation": False,
                    "can_manage_events": False,
                    "can_manage_streamers": False,
                    "can_execute_commands": False,
                    "can_view_logs": False,
                },
                "senior_employee": {
                    "can_view_dashboard": True,
                    "can_spec_probation": False,
                    "can_manage_events": False,
                    "can_manage_streamers": False,
                    "can_execute_commands": False,
                    "can_view_logs": False,
                },
                "manager": {
                    "can_view_dashboard": True,
                    "can_spec_probation": True,
                    "can_manage_events": True,
                    "can_manage_streamers": True,
                    "can_register_users": True,
                    "can_execute_commands": True,
                    "can_view_logs": True,
                    "can_manage_permissions": False,
                },
                "developer": {
                    "can_view_dashboard": True,
                    "can_spec_probation": True,
                    "can_manage_events": True,
                    "can_manage_streamers": True,
                    "can_register_users": True,
                    "can_manage_permissions": True,
                    "can_access_admin_panel": True,
                    "can_execute_commands": True,
                    "can_view_logs": True,
                },
            }

            for role, permissions in default_permissions.items():
                await cursor.execute(
                    """
                    INSERT INTO role_permissions (role, permissions)
                    VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE permissions = %s
                    """,
                    (role, json.dumps(permissions), json.dumps(permissions)),
                )
            await conn.commit()
            self.logger.debug("  ✓ Default permissions initialized")

    async def get_role_permissions(self, role: str) -> dict:
        """Get permissions for a role from role_permissions table."""
        import json
        
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT permissions FROM role_permissions WHERE role = %s",
                    (role,)
                )
                row = await cursor.fetchone()
                if row:
                    permissions = row.get("permissions", "{}")
                    if isinstance(permissions, str):
                        return json.loads(permissions)
                    return permissions
                
                # Return default (no permissions) for unknown roles
                return {
                    "can_view_dashboard": False,
                    "can_spec_probation": False,
                    "can_manage_events": False,
                    "can_manage_streamers": False,
                    "can_execute_commands": False,
                    "can_view_logs": False,
                }

    @db_retry()
    async def log_admin_action(
        self,
        admin_id: int,
        action: str,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        details: Optional[dict] = None,
        ip_address: Optional[str] = None,
    ) -> None:
        """
        Log an admin action to the admin_logs table for auditing.
        
        Args:
            admin_id: Discord ID of the admin performing the action
            action: Action name (e.g., 'update_streamer', 'delete_assistant')
            target_type: Type of target entity (e.g., 'streamer', 'assistant')
            target_id: ID of the target entity
            details: Optional JSON details (old_value, new_value, etc.)
            ip_address: Optional IP address of the request source
        """
        import json
        
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO admin_logs 
                            (admin_id, action, target_type, target_id, details, ip_address)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            admin_id,
                            action,
                            target_type,
                            target_id,
                            json.dumps(details) if details else None,
                            ip_address,
                        ),
                    )
                    await conn.commit()
                    self.logger.debug(f"Admin log: {action} by {admin_id}")
        except Exception as e:
            self.logger.error(f"Failed to log admin action: {e}", exc_info=True)
            # Don't raise - logging failure shouldn't break the main operation

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
                        "SELECT streamer_id FROM streamers WHERE streamer_name = %s", 
                        (streamer_name,)
                    )
                    existing_by_name = await cursor.fetchone()
                    
                    if existing_by_name and existing_by_name['streamer_id'] != streamer_id:
                        # Conflict! Name exists but ID is different.
                        # This happens if a streamer channel was recycled or ID changed.
                        old_id = existing_by_name['streamer_id']
                        # Rename old record to free the name
                        new_name_old = f"old_{old_id}"
                        self.logger.warning(
                            f"Streamer Name Collision: '{streamer_name}' is taken by ID {old_id}. "
                            f"Renaming {old_id} to '{new_name_old}' to insert new ID {streamer_id}."
                        )
                        await cursor.execute(
                            "UPDATE streamers SET streamer_name = %s WHERE streamer_id = %s",
                            (new_name_old, old_id)
                        )
                    
                    await cursor.execute(
                        """
                        INSERT INTO streamers (
                            streamer_id, streamer_name, is_online, stream_started_at, priority, 
                            added_at, added_by_id, stream_game_id, stream_game_name, stream_title, stream_thumbnail_url
                        )
                        VALUES (%s, %s, %s, %s, %s, NOW(), %s, %s, %s, %s, %s) AS new_data
                        ON DUPLICATE KEY UPDATE 
                            streamer_name = new_data.streamer_name,
                            is_online = new_data.is_online,
                            stream_started_at = new_data.stream_started_at,
                            priority = new_data.priority,
                            added_by_id = new_data.added_by_id,
                            stream_game_id = new_data.stream_game_id,
                            stream_game_name = new_data.stream_game_name,
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
        Получение информации о стримере по ID с поддержкой множественных назначений.
        
        Returns dict with 'assignments' list containing Main and Probation slots.
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # 1. Get streamer base info
                    await cursor.execute(
                        """
                        SELECT 
                            streamer_id, streamer_name, is_online, stream_title, stream_thumbnail_url,
                            stream_game_id as game_id, stream_game_name as game_name, stream_started_at as started_at,
                            priority, added_at, added_by_id, updated_at
                        FROM streamers
                        WHERE streamer_id = %s
                        """,
                        (streamer_id,),
                    )
                    streamer = await cursor.fetchone()
                    if not streamer:
                        return None
                    
                    # 2. Get all assignments for this streamer (Main + Probation)
                    # Probation status comes from spec_sessions.is_probation, not assistants table
                    await cursor.execute(
                        """
                        SELECT 
                            a.pr_id, 
                            ss.is_probation,
                            ss.started_at as assigned_at
                        FROM assistants a
                        INNER JOIN spec_sessions ss ON ss.pr_id = a.pr_id 
                            AND ss.target_type = 'streamer' 
                            AND ss.target_id = a.assigned_to_id 
                            AND ss.ended_at IS NULL
                        WHERE a.assigned_to_type = 'streamer' AND a.assigned_to_id = %s
                        """,
                        (streamer_id,),
                    )
                    assignments = await cursor.fetchall()
                    
                    # 3. Build result with assignments list
                    result = dict(streamer)
                    result["assignments"] = [
                        {
                            "pr_id": str(a["pr_id"]),
                            "is_probation": a.get("is_probation", False),
                            "assigned_at": a.get("assigned_at"),
                        }
                        for a in assignments
                    ] if assignments else []
                    
                    # Legacy compatibility: set assigned_pr_id to Main slot if exists
                    main_assignment = next(
                        (a for a in result["assignments"] if not a["is_probation"]), 
                        None
                    )
                    result["assigned_pr_id"] = main_assignment["pr_id"] if main_assignment else None
                    result["assigned_at"] = main_assignment["assigned_at"] if main_assignment else None
                    
                    return result
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
                        SET is_online = %s, stream_started_at = %s, stream_game_id = %s, 
                            stream_game_name = %s, stream_title = %s, stream_thumbnail_url = %s
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
    async def update_streamers_status_bulk(
        self,
        updates: List[Dict[str, Any]],
    ) -> int:
        """
        Bulk update streamer statuses (max 100 per call).
        
        Args:
            updates: List of dicts with keys:
                - streamer_id (required)
                - is_online (required)
                - started_at (optional)
                - game_id (optional)
                - game_name (optional)
                - stream_title (optional)
                - stream_thumbnail_url (optional)
                
        Returns:
            Number of streamers updated
        """
        if not updates:
            return 0
            
        if len(updates) > 100:
            self.logger.warning("Bulk update limited to 100 streamers, truncating")
            updates = updates[:100]
        
        try:
            updated_count = 0
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    for update in updates:
                        streamer_id = update.get("streamer_id")
                        if not streamer_id:
                            continue
                            
                        await cursor.execute(
                            """
                            UPDATE streamers 
                            SET is_online = %s, stream_started_at = %s, stream_game_id = %s, 
                                stream_game_name = %s, stream_title = %s, stream_thumbnail_url = %s
                            WHERE streamer_id = %s
                            """,
                            (
                                update.get("is_online", False),
                                update.get("started_at"),
                                update.get("game_id"),
                                update.get("game_name"),
                                update.get("stream_title"),
                                update.get("stream_thumbnail_url"),
                                streamer_id,
                            ),
                        )
                        if cursor.rowcount > 0:
                            updated_count += 1
                    
                    await conn.commit()
            
            self.logger.info(f"✓ Bulk updated {updated_count} streamers")
            return updated_count
        except Exception as e:
            self.logger.error(f"Failed to bulk update streamers: {e}", exc_info=True)
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
            self.logger.error(
                f"Failed to update streamer {streamer_id}: {e}", exc_info=True
            )
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
        Returns unique streamers without duplicates from multiple assignments.
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Query streamers with GROUP BY to avoid duplicates
                    # For assignments, we take the first (Main) slot if exists
                    await cursor.execute(
                        """
                        SELECT 
                            s.streamer_id, s.streamer_name, s.is_online, s.stream_title, s.stream_thumbnail_url,
                            s.stream_game_id as game_id, s.stream_game_name as game_name, s.stream_started_at as started_at,
                            s.priority, s.added_at, s.added_by_id, s.updated_at,
                            MIN(a.pr_id) as assigned_pr_id,
                            MIN(ss.started_at) as assigned_at
                        FROM streamers s
                        LEFT JOIN assistants a ON a.assigned_to_type = 'streamer' AND a.assigned_to_id = s.streamer_id
                        LEFT JOIN spec_sessions ss ON ss.pr_id = a.pr_id 
                             AND ss.target_type = 'streamer' 
                             AND ss.target_id = s.streamer_id 
                             AND ss.ended_at IS NULL
                        GROUP BY s.streamer_id
                        ORDER BY s.priority DESC, s.streamer_name ASC
                        """
                    )
                    return await cursor.fetchall()
        except Exception as e:
            self.logger.error(f"Failed to list streamers: {e}", exc_info=True)
            raise

    @db_retry()
    async def list_online_streamers(self) -> List[Dict[str, Any]]:
        """
        Получение списка всех онлайн стримеров.
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT 
                            s.streamer_id, s.streamer_name, s.is_online, s.stream_title, s.stream_thumbnail_url,
                            s.stream_game_id as game_id, s.stream_game_name as game_name, s.stream_started_at as started_at,
                            s.priority, s.added_at, s.added_by_id, s.updated_at,
                            a.pr_id as assigned_pr_id, 
                            ss.started_at as assigned_at
                        FROM streamers s
                        LEFT JOIN assistants a ON a.assigned_to_type = 'streamer' AND a.assigned_to_id = s.streamer_id
                        LEFT JOIN spec_sessions ss ON ss.pr_id = a.pr_id 
                             AND ss.target_type = 'streamer' 
                             AND ss.target_id = s.streamer_id 
                             AND ss.ended_at IS NULL
                        WHERE s.is_online = TRUE
                        """
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
        guild_id: str,
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
                        "SELECT guild_id, notification_channel_id, monitoring_channel_id, monitoring_message_id, pr_actions_channel_id, control_panel_channel_id, control_panel_message_id, assistant_role_id, template_stream_online, template_stream_offline, template_category_to_gta, template_category_from_gta, p0_rate, p1_rate, p2_rate, p3_rate, probation_rate FROM settings WHERE guild_id = %s",
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

    async def get_guild(self, guild_id: str) -> Optional[Dict[str, Any]]:
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
                        "SELECT guild_id, notification_channel_id, monitoring_channel_id, monitoring_message_id, pr_actions_channel_id, control_panel_channel_id, control_panel_message_id, assistant_role_id, template_stream_online, template_stream_offline, template_category_to_gta, template_category_from_gta, p0_rate, p1_rate, p2_rate, p3_rate, probation_rate FROM settings WHERE guild_id = %s",
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
                        SELECT guild_id, notification_channel_id, monitoring_channel_id, monitoring_message_id, pr_actions_channel_id, control_panel_channel_id, control_panel_message_id, assistant_role_id, template_stream_online, template_stream_offline, template_category_to_gta, template_category_from_gta, p0_rate, p1_rate, p2_rate, p3_rate, probation_rate FROM settings 
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

    async def get_notification_template(self, guild_id: str, event_type: str) -> str:
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
        if event_type not in Config.allowed_event_types:
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
                    return Config.template_defaults.get(event_type, "")
        except Exception as e:
            self.logger.error(
                f"Failed to get template for guild {guild_id}: {e}", exc_info=True
            )
            return Config.template_defaults.get(event_type, "")

    async def update_notification_template(
        self, guild_id: str, event_type: str, template: str
    ) -> None:
        """
        Обновление шаблона уведомления.

        Args:
            guild_id: ID Discord сервера
            event_type: Тип события
            template: Новый шаблон
        """
        # SQL injection prevention: validate event_type against whitelist
        if event_type not in Config.allowed_event_types:
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
    async def assign_pr_to_streamer(
        self, streamer_id: int, pr_id: int, is_probation: bool = False
    ) -> bool:
        """
        Назначение PR-ассистента стримеру с поддержкой Probation (Slot Logic).

        Args:
            streamer_id: Twitch ID стримера
            pr_id: Discord ID ассистента
            is_probation: True если это спек стажера (второй слот)

        Returns:
            True если успешно, False если слот занят

        Slot Logic:
            - Каждый стример может иметь до 2 назначенных: 1 Main + 1 Probation
            - Slot type is determined by spec_sessions.is_probation flag
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Check if the PR is already assigned to something
                    await cursor.execute(
                        "SELECT assigned_to_type FROM assistants WHERE pr_id = %s",
                        (pr_id,),
                    )
                    pr_status = await cursor.fetchone()
                    if pr_status and pr_status.get("assigned_to_type"):
                        self.logger.warning(f"PR {pr_id} is already assigned")
                        return False

                    # Check if requested slot is available for this streamer
                    # Slot availability is based on active spec_sessions, not assistants.is_probation_mode
                    await cursor.execute(
                        """
                        SELECT ss.pr_id, ss.is_probation 
                        FROM spec_sessions ss
                        WHERE ss.target_type = 'streamer' 
                          AND ss.target_id = %s 
                          AND ss.ended_at IS NULL
                        """,
                        (streamer_id,),
                    )
                    existing_sessions = await cursor.fetchall()

                    # Check slot availability
                    for session in existing_sessions:
                        if session.get("is_probation") == is_probation:
                            # Slot is occupied
                            slot_name = "Probation" if is_probation else "Main"
                            self.logger.warning(
                                f"{slot_name} slot for streamer {streamer_id} is occupied by PR {session['pr_id']}"
                            )
                            return False

                    # Assign PR to streamer in assistants table (no is_probation_mode)
                    await cursor.execute(
                        """
                        INSERT INTO assistants (pr_id, assigned_to_type, assigned_to_id) 
                        VALUES (%s, 'streamer', %s)
                        ON DUPLICATE KEY UPDATE 
                            assigned_to_type = 'streamer',
                            assigned_to_id = %s
                        """,
                        (pr_id, streamer_id, streamer_id),
                    )

                    # Create new spec session with is_probation flag
                    await cursor.execute(
                        """
                        INSERT INTO spec_sessions (pr_id, target_type, target_id, is_probation, started_at)
                        VALUES (%s, 'streamer', %s, %s, NOW())
                        """,
                        (pr_id, streamer_id, is_probation),
                    )

                    await conn.commit()
                    slot_name = "Probation" if is_probation else "Main"
                    self.logger.debug(
                        f"✓ PR {pr_id} assigned to streamer {streamer_id} as {slot_name}"
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
            end_reason: Причина завершения

        Returns:
            Словарь с данными сессии или None
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Get assigned PR
                    await cursor.execute(
                        """
                        SELECT a.pr_id, s.started_at, st.streamer_name, st.priority
                        FROM assistants a
                        JOIN spec_sessions s ON s.pr_id = a.pr_id 
                            AND s.target_type = 'streamer' 
                            AND s.target_id = a.assigned_to_id
                            AND s.ended_at IS NULL
                        JOIN streamers st ON st.streamer_id = a.assigned_to_id
                        WHERE a.assigned_to_type = 'streamer' AND a.assigned_to_id = %s
                        """,
                        (streamer_id,),
                    )
                    result = await cursor.fetchone()

                    if not result:
                        return None  # No one assigned

                    pr_id = result["pr_id"]
                    started_at = result["started_at"]
                    streamer_name = result["streamer_name"]
                    priority = result.get("priority", 0)

                    # Calculate duration
                    await cursor.execute("SELECT NOW() as now")
                    now_result = await cursor.fetchone()
                    now = now_result["now"]

                    if started_at and started_at.tzinfo is None:
                        started_at = started_at.replace(tzinfo=timezone.utc)
                    if now.tzinfo is None:
                        now = now.replace(tzinfo=timezone.utc)

                    duration_seconds = 0
                    if started_at:
                        duration_seconds = int((now - started_at).total_seconds())

                    # Close spec session
                    await cursor.execute(
                        """
                        UPDATE spec_sessions 
                        SET ended_at = NOW(), end_reason = %s
                        WHERE pr_id = %s AND target_type = 'streamer' AND target_id = %s AND ended_at IS NULL
                        """,
                        (end_reason, pr_id, streamer_id),
                    )

                    # Free assistant
                    await cursor.execute(
                        """
                        UPDATE assistants 
                        SET assigned_to_type = NULL, assigned_to_id = NULL
                        WHERE pr_id = %s
                        """,
                        (pr_id,),
                    )
                    await conn.commit()

            # Record Stats (Outside transaction)
            if duration_seconds > 0:
                await self.record_spec_session(
                    pr_id, Config.guild_id, started_at, now, priority
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
    async def swap_pr_streamers(self, pr1_id: int, pr2_id: int) -> Dict[str, Any]:
        """
        Atomically swap claimed streamers between two PRs.
        
        Args:
            pr1_id: Discord ID of first assistant
            pr2_id: Discord ID of second assistant
            
        Returns:
            Dict with swap details
            
        Raises:
            ValueError: If either PR has no claimed streamer
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Get PR1's current assignment
                    await cursor.execute(
                        """
                        SELECT a.assigned_to_id as streamer_id, s.streamer_name
                        FROM assistants a
                        JOIN streamers s ON s.streamer_id = a.assigned_to_id
                        WHERE a.pr_id = %s AND a.assigned_to_type = 'streamer'
                        """,
                        (pr1_id,),
                    )
                    pr1_assignment = await cursor.fetchone()
                    
                    if not pr1_assignment:
                        raise ValueError(f"PR {pr1_id} has no claimed streamer")
                    
                    # Get PR2's current assignment
                    await cursor.execute(
                        """
                        SELECT a.assigned_to_id as streamer_id, s.streamer_name
                        FROM assistants a
                        JOIN streamers s ON s.streamer_id = a.assigned_to_id
                        WHERE a.pr_id = %s AND a.assigned_to_type = 'streamer'
                        """,
                        (pr2_id,),
                    )
                    pr2_assignment = await cursor.fetchone()
                    
                    if not pr2_assignment:
                        raise ValueError(f"PR {pr2_id} has no claimed streamer")
                    
                    streamer1_id = pr1_assignment["streamer_id"]
                    streamer2_id = pr2_assignment["streamer_id"]
                    
                    # Close existing spec sessions for both PRs (with reason 'swap')
                    await cursor.execute(
                        """
                        UPDATE spec_sessions 
                        SET ended_at = NOW(), end_reason = 'swap'
                        WHERE pr_id IN (%s, %s) AND ended_at IS NULL
                        """,
                        (pr1_id, pr2_id),
                    )
                    
                    # Swap assignments in assistants table
                    # PR1 now gets PR2's streamer
                    await cursor.execute(
                        """
                        UPDATE assistants 
                        SET assigned_to_id = %s
                        WHERE pr_id = %s AND assigned_to_type = 'streamer'
                        """,
                        (streamer2_id, pr1_id),
                    )
                    
                    # PR2 now gets PR1's streamer
                    await cursor.execute(
                        """
                        UPDATE assistants 
                        SET assigned_to_id = %s
                        WHERE pr_id = %s AND assigned_to_type = 'streamer'
                        """,
                        (streamer1_id, pr2_id),
                    )
                    
                    # Create new spec sessions
                    await cursor.execute(
                        """
                        INSERT INTO spec_sessions (pr_id, target_type, target_id, started_at)
                        VALUES (%s, 'streamer', %s, NOW()), (%s, 'streamer', %s, NOW())
                        """,
                        (pr1_id, streamer2_id, pr2_id, streamer1_id),
                    )
                    
                    await conn.commit()
                    
                    self.logger.info(
                        f"✓ Swapped: PR {pr1_id} ({pr1_assignment['streamer_name']}) <-> PR {pr2_id} ({pr2_assignment['streamer_name']})"
                    )
                    
                    return {
                        "pr1_id": pr1_id,
                        "pr2_id": pr2_id,
                        "pr1_new_streamer": pr2_assignment,
                        "pr2_new_streamer": pr1_assignment,
                    }
        except ValueError:
            raise
        except Exception as e:
            self.logger.error(f"Failed to swap PR streamers: {e}", exc_info=True)
            raise

    @db_retry()
    async def get_active_sessions(self) -> List[Dict[str, Any]]:
        """Get all active spec sessions."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT * FROM spec_sessions 
                        WHERE ended_at IS NULL
                        """
                    )
                    return await cursor.fetchall()
        except Exception as e:
            self.logger.error(f"Failed to get active sessions: {e}", exc_info=True)
            return []

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
                        "SELECT pr_id FROM assistants WHERE assigned_to_type = 'streamer' AND assigned_to_id = %s",
                        (streamer_id,),
                    )
                    result = await cursor.fetchone()
                    return result.get("pr_id") if result else None
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
                        """
                        SELECT s.streamer_id, s.streamer_name, s.is_online, s.stream_title, s.stream_thumbnail_url, s.stream_game_id, s.stream_game_name, s.stream_started_at, s.priority, s.added_at, s.added_by_id, s.updated_at 
                        FROM assistants a
                        JOIN streamers s ON s.streamer_id = a.assigned_to_id
                        WHERE a.pr_id = %s AND a.assigned_to_type = 'streamer'
                        """,
                        (pr_id,),
                    )
                    result = await cursor.fetchone()
                    if result:
                        result["streamer_id"] = str(result["streamer_id"])
                        if result.get("added_by_id"):
                            result["added_by_id"] = str(result["added_by_id"])
                        if result.get("stream_game_id"):
                            result["stream_game_id"] = str(result["stream_game_id"])
                    return result
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

    # NOTE: transfer_streamer method moved to Spec Extended Operations section (line ~2669)

    @db_retry()
    async def get_pr_actions_channel(self, guild_id: str) -> Optional[int]:
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
    async def set_pr_actions_channel(self, guild_id: str, channel_id: int) -> None:
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
                        (Config.gta5_game_id,),
                    )
                    results = await cursor.fetchall() or []
                    for r in results:
                        r["streamer_id"] = str(r["streamer_id"])
                    return results
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
        guild_id: str,
        name: str,
        description: str,
        channel_id: int,
        message_id: int,
        created_by: int,
        start_time=None,
        required_pr_count=1,
        notification_sent=False,
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
                             name, description, channel_id, message_id, required_pr_count,
                            created_by, start_time, notification_sent
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            name,
                            description,
                            channel_id,
                            message_id,
                            required_pr_count,
                            created_by,
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
    async def get_active_events(self, guild_id: str) -> list:
        """Получение активных событий гильдии."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        """
                        SELECT id, name, description, created_at, start_time, is_active, channel_id, message_id, created_by, notification_sent, required_pr_count FROM events 
                        WHERE is_active = TRUE
                        ORDER BY start_time ASC
                        """
                    )
                    events = await cursor.fetchall()

                    # For each event, get participant count from assistants table
                    for event in events:
                        await cursor.execute(
                            """
                            SELECT COUNT(*) as count 
                            FROM assistants 
                            WHERE assigned_to_type = 'event' AND assigned_to_id = %s
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
                        "SELECT id, name, description, created_at, start_time, is_active, channel_id, message_id, created_by, notification_sent, required_pr_count FROM events WHERE id = %s",
                        (event_id,),
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
                    # 1. Get all active participants (from spec_sessions that are open)
                    await cursor.execute(
                        """
                        SELECT pr_id, started_at
                        FROM spec_sessions
                        WHERE target_type = 'event' AND target_id = %s AND ended_at IS NULL
                        """,
                        (event_id,),
                    )
                    participants = await cursor.fetchall()

                    await cursor.execute(
                        "SELECT start_time FROM events WHERE id = %s", (event_id,)
                    )
                    event_data = await cursor.fetchone()
                    if not event_data:
                        return []

                    event_start_time = (
                        event_data["start_time"].replace(tzinfo=timezone.utc)
                        if event_data["start_time"]
                        else now
                    )

                    # 2. Mark event as inactive
                    await cursor.execute(
                        """
                        UPDATE events 
                        SET is_active = FALSE 
                        WHERE id = %s
                        """,
                        (event_id,),
                    )

                    # 3. Close open sessions
                    await cursor.execute(
                        """
                        UPDATE spec_sessions 
                        SET ended_at = %s, end_reason = 'event_end'
                        WHERE target_type = 'event' AND target_id = %s AND ended_at IS NULL
                        """,
                        (now, event_id),
                    )

                    # 4. Free assistants
                    await cursor.execute(
                        """
                        UPDATE assistants 
                        SET assigned_to_type = NULL, assigned_to_id = NULL
                        WHERE assigned_to_type = 'event' AND assigned_to_id = %s
                        """,
                        (event_id,),
                    )

                    # 5. Update assistant stats for each participant
                    results = []
                    for p in participants:
                        user_id = p["pr_id"]
                        started_at = p["started_at"]
                        if started_at.tzinfo is None:
                            started_at = started_at.replace(tzinfo=timezone.utc)

                        # Effective start time is the later of actual event start or user join
                        effective_start = max(started_at, event_start_time)

                        duration = int((now - effective_start).total_seconds())
                        if duration < 0:
                            duration = 0

                        await self.record_spec_session(
                            user_id, Config.guild_id, effective_start, now, priority=0
                        )

                        results.append({"user_id": user_id, "duration": duration})

                    await conn.commit()
                    return results
        except Exception as e:
            self.logger.error(f"Failed to end event {event_id}: {e}", exc_info=True)
            return []

    @db_retry()
    async def record_daily_stats(
        self,
        pr_id: int,
        date_obj: datetime.date,
        priority: int,
        duration_seconds: int,
        points: float,
        is_probation: bool = False,
    ):
        """Обновление ежедневной статистики для конкретной даты и приоритета/пробации."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Route to correct column based on probation flag
                    if is_probation:
                        col_name = "probation_seconds"
                    else:
                        # Construct column name based on priority (0-3)
                        col_name = f"p{priority}_seconds"

                    await cursor.execute(
                        f"""
                        INSERT INTO daily_stats (pr_id, date, {col_name}, total_points, probation_seconds)
                        VALUES (%s, %s, %s, %s, 0)
                        ON DUPLICATE KEY UPDATE
                        {col_name} = {col_name} + %s,
                        total_points = total_points + %s
                        """,
                        (
                            pr_id,
                            date_obj,
                            duration_seconds,
                            points,
                            duration_seconds,
                            points,
                        ),
                    )
                    await conn.commit()
        except Exception as e:
            self.logger.error(f"Failed to record daily stats: {e}", exc_info=True)

    @db_retry()
    async def get_daily_stats(
        self,
        pr_id: int = None,
        date_obj: datetime.date = None,
        start_date=None,
        end_date=None,
    ) -> list:
        """Получение ежедневной статистики с фильтрацией."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    query = "SELECT id, pr_id, date, p0_seconds, p1_seconds, p2_seconds, p3_seconds, probation_seconds, total_points FROM daily_stats WHERE 1=1"
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
                    results = await cursor.fetchall()
                    for r in results:
                         r["pr_id"] = str(r["pr_id"])
                    return results
        except Exception as e:
            self.logger.error(f"Failed to get daily stats: {e}")
            return []

    @db_retry()
    async def update_daily_stats_manual(
        self,
        pr_id: int,
        date_obj: datetime.date,
        p0_seconds: int,
        p1_seconds: int,
        p2_seconds: int,
        p3_seconds: int,
        total_points: float,
        probation_seconds: int = 0,
    ):
        """Ручное обновление ежедневной статистики."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO daily_stats (pr_id, date, p0_seconds, p1_seconds, p2_seconds, p3_seconds, probation_seconds, total_points)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                        p0_seconds = %s, p1_seconds = %s, p2_seconds = %s, p3_seconds = %s, probation_seconds = %s, total_points = %s
                        """,
                        (
                            pr_id,
                            date_obj,
                            p0_seconds,
                            p1_seconds,
                            p2_seconds,
                            p3_seconds,
                            probation_seconds,
                            total_points,
                            p0_seconds,
                            p1_seconds,
                            p2_seconds,
                            p3_seconds,
                            probation_seconds,
                            total_points,
                        ),
                    )
                    await conn.commit()
                    return True
        except Exception as e:
            self.logger.error(f"Failed to manual update stats: {e}")
            return False

    @db_retry()
    async def get_points_config(self, guild_id: str) -> dict:
        """Получение конфигурации баллов для гильдии."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        "SELECT p0_rate, p1_rate, p2_rate, p3_rate FROM settings WHERE guild_id = %s",
                        (guild_id,),
                    )
                    result = await cursor.fetchone()
                    if result and result["p0_rate"] is not None:
                        return {
                            0: result["p0_rate"],
                            1: result["p1_rate"],
                            2: result["p2_rate"],
                            3: result["p3_rate"],
                        }

                    # Return defaults if not found
                    return {k: v for k, v in Config.default_points.items()}
        except Exception as e:
            self.logger.error(f"Failed to get points config: {e}")
            return {k: v for k, v in Config.default_points.items()}

    @db_retry()
    async def set_points_config(self, guild_id: str, rates: dict):
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
                        (rates[0], rates[1], rates[2], rates[3], guild_id),
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
                        (priority, streamer_id),
                    )
                    await conn.commit()
                    return True
        except Exception as e:
            self.logger.error(f"Failed to update streamer {streamer_id}: {e}")
            return False

    @db_retry()
    async def record_spec_session(
        self,
        pr_id: int,
        guild_id: str,
        start_time: datetime,
        end_time: datetime,
        priority: int,
        is_probation: bool = False,
    ):
        """Запись сессии спека с разделением по дням и расчетом баллов (с поддержкой пробации)."""
        try:
            # 1. Split time by day
            chunks = split_time_by_day(start_time, end_time)
            if not chunks:
                return

            # 2. Get Point Rates
            config = await self.get_points_config(guild_id)
            
            # Use probation_rate if probation, else use priority rate
            if is_probation:
                # Get probation_rate from settings (default 1.2)
                rate_per_hour = await self._get_probation_rate(guild_id)
            else:
                # Default rate if not found for priority
                rate_per_hour = config.get(priority, 0.5)

            # 3. Record each chunk
            for date_obj, duration in chunks:
                # Calculate points: (duration / 3600) * rate
                points = (duration / 3600.0) * rate_per_hour

                await self.record_daily_stats(
                    pr_id, date_obj, priority, duration, points, is_probation=is_probation
                )

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
    
    async def _get_probation_rate(self, guild_id: str) -> float:
        """Get probation rate from settings."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT probation_rate FROM settings WHERE guild_id = %s",
                        (guild_id,),
                    )
                    result = await cursor.fetchone()
                    return result.get("probation_rate", 1.2) if result else 1.2
        except Exception:
            return 1.2

    @db_retry()
    async def join_event(self, event_id: int, user_id: int) -> bool:
        """Добавление пользователя в событие."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Check if already assigned to ANYTHING
                    await cursor.execute(
                        "SELECT assigned_to_type FROM assistants WHERE pr_id = %s",
                        (user_id,),
                    )
                    result = await cursor.fetchone()

                    if result and result.get("assigned_to_type"):
                        return False  # Busy

                    # Update assistant status
                    await cursor.execute(
                        """
                         INSERT INTO assistants (pr_id, assigned_to_type, assigned_to_id)
                         VALUES (%s, 'event', %s)
                         ON DUPLICATE KEY UPDATE assigned_to_type = 'event', assigned_to_id = %s
                         """,
                        (user_id, event_id, event_id),
                    )

                    # Create spec session
                    await cursor.execute(
                        """
                        INSERT INTO spec_sessions (pr_id, target_type, target_id, started_at)
                        VALUES (%s, 'event', %s, NOW())
                        """,
                        (user_id, event_id),
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
                    # 1. Get started_at to calculate duration
                    await cursor.execute(
                        """
                        SELECT started_at 
                        FROM spec_sessions 
                        WHERE target_type = 'event' AND target_id = %s AND pr_id = %s AND ended_at IS NULL
                        """,
                        (event_id, user_id),
                    )
                    result = await cursor.fetchone()

                    if not result:
                        return 0

                    started_at = result["started_at"]
                    if started_at.tzinfo is None:
                        started_at = started_at.replace(tzinfo=timezone.utc)

                    duration = int((now - started_at).total_seconds())
                    if duration < 0:
                        duration = 0

                    # 2. Close session
                    await cursor.execute(
                        """
                        UPDATE spec_sessions 
                        SET ended_at = %s, end_reason = 'manual_leave'
                        WHERE target_type = 'event' AND target_id = %s AND pr_id = %s AND ended_at IS NULL
                        """,
                        (now, event_id, user_id),
                    )

                    # 3. Free assistant
                    await cursor.execute(
                        """
                        UPDATE assistants 
                        SET assigned_to_type = NULL, assigned_to_id = NULL
                        WHERE pr_id = %s
                        """,
                        (user_id,),
                    )

                    if duration > 0:
                        # 4. Record stats
                        event_data = await self.get_event(event_id)
                        event_start_time = (
                            event_data["start_time"].replace(tzinfo=timezone.utc)
                            if event_data and event_data["start_time"]
                            else now
                        )

                        effective_start = max(started_at, event_start_time)

                        await self.record_spec_session(
                            user_id, Config.guild_id, effective_start, now, priority=0
                        )

                    await conn.commit()
                    return duration
        except Exception as e:
            self.logger.error(f"Failed to leave event {event_id}: {e}", exc_info=True)
            return

    @db_retry()
    async def set_assistant_role(self, guild_id: str, role_id: int) -> None:
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
                        FROM assistants a
                        JOIN events e ON a.assigned_to_id = e.id
                        WHERE a.pr_id = %s AND a.assigned_to_type = 'event' AND e.is_active = TRUE
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
                        SELECT pr_id as user_id, started_at as joined_at 
                        FROM spec_sessions
                        WHERE target_type = 'event' AND target_id = %s AND ended_at IS NULL
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
                        """
                        SELECT 
                            a.pr_id, a.nickname, a.role, 
                            DATEDIFF(NOW(), a.added_at) as experience_days,
                            CASE WHEN a.assigned_to_type IS NOT NULL THEN 'assigned' ELSE 'free' END as status,
                            a.assigned_to_type, a.assigned_to_id, 
                            a.total_spec_seconds, a.session_count, a.added_at,
                            COALESCE(s.streamer_name, e.name) as assigned_to_name,
                            ROUND(a.total_spec_seconds / 3600, 1) as total_spec_hours
                        FROM assistants a
                        LEFT JOIN streamers s ON a.assigned_to_type = 'streamer' AND a.assigned_to_id = s.streamer_id
                        LEFT JOIN events e ON a.assigned_to_type = 'event' AND a.assigned_to_id = e.id
                        ORDER BY a.total_spec_seconds DESC
                        """
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
                        """
                        SELECT 
                            a.pr_id, a.nickname, a.role, 
                            DATEDIFF(NOW(), a.added_at) as experience_days,
                            CASE WHEN a.assigned_to_type IS NOT NULL THEN 'assigned' ELSE 'free' END as status,
                            a.assigned_to_type, a.assigned_to_id, 
                            a.total_spec_seconds, a.session_count, a.added_at,
                            COALESCE(s.streamer_name, e.name) as assigned_to_name,
                            ROUND(a.total_spec_seconds / 3600, 1) as total_spec_hours
                        FROM assistants a
                        LEFT JOIN streamers s ON a.assigned_to_type = 'streamer' AND a.assigned_to_id = s.streamer_id
                        LEFT JOIN events e ON a.assigned_to_type = 'event' AND a.assigned_to_id = e.id
                        WHERE a.pr_id = %s
                        """,
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
                        """
                        SELECT 
                            a.pr_id, a.nickname, a.role, 
                            DATEDIFF(NOW(), a.added_at) as experience_days,
                            CASE WHEN a.assigned_to_type IS NOT NULL THEN 'assigned' ELSE 'free' END as status,
                            a.assigned_to_type, a.assigned_to_id, 
                            a.total_spec_seconds, a.session_count, a.added_at,
                            COALESCE(s.streamer_name, e.name) as assigned_to_name,
                            ROUND(a.total_spec_seconds / 3600, 1) as total_spec_hours
                        FROM assistants a
                        LEFT JOIN streamers s ON a.assigned_to_type = 'streamer' AND a.assigned_to_id = s.streamer_id
                        LEFT JOIN events e ON a.assigned_to_type = 'event' AND a.assigned_to_id = e.id
                        WHERE a.pr_id = %s
                        """,
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

                    return {**assistant, "daily_stats": daily_stats}
        except Exception as e:
            self.logger.error(
                f"Failed to get assistant stats {user_id}: {e}", exc_info=True
            )
            return None

    @db_retry()
    async def create_assistant(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Создание нового ассистента."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Check if exists
                    await cursor.execute(
                        "SELECT pr_id FROM assistants WHERE pr_id = %s",
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
                        """
                        SELECT 
                            a.pr_id, a.nickname, a.role, 
                            DATEDIFF(NOW(), a.added_at) as experience_days,
                            CASE WHEN a.assigned_to_type IS NOT NULL THEN 'assigned' ELSE 'free' END as status,
                            a.assigned_to_type, a.assigned_to_id, 
                            a.total_spec_seconds, a.session_count, a.added_at,
                            COALESCE(s.streamer_name, e.name) as assigned_to_name,
                            ROUND(a.total_spec_seconds / 3600, 1) as total_spec_hours
                        FROM assistants a
                        LEFT JOIN streamers s ON a.assigned_to_type = 'streamer' AND a.assigned_to_id = s.streamer_id
                        LEFT JOIN events e ON a.assigned_to_type = 'event' AND a.assigned_to_id = e.id
                        WHERE a.pr_id = %s
                        """,
                        (user_id,),
                    )
                    return await cursor.fetchone()
        except Exception as e:
            self.logger.error(
                f"Failed to create assistant {user_id}: {e}", exc_info=True
            )
            return None

    @db_retry()
    async def create_or_update_assistant(
        self, pr_id: int, nickname: str, role: str, experience_days: int = 0
    ) -> bool:
        """Create or update assistant profile."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO assistants (pr_id, nickname, role, added_at, total_spec_seconds, session_count)
                        VALUES (%s, %s, %s, DATE_SUB(NOW(), INTERVAL %s DAY), 0, 0)
                        ON DUPLICATE KEY UPDATE
                            nickname = VALUES(nickname),
                            role = VALUES(role),
                            added_at = DATE_SUB(NOW(), INTERVAL %s DAY)
                        """,
                        (pr_id, nickname, role, experience_days, experience_days),
                    )
                    await conn.commit()
                    return True
        except Exception as e:
            self.logger.error(f"Failed to save assistant {pr_id}: {e}", exc_info=True)
            raise

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
            self.logger.error(
                f"Failed to delete assistant {user_id}: {e}", exc_info=True
            )
            return False

    # =========================================================================
    # Guild Extended Settings (for routes refactoring)
    # =========================================================================

    @db_retry()
    async def update_guild_extended_settings(
        self,
        guild_id: str,
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
            self.logger.error(
                f"Failed to update guild extended settings: {e}", exc_info=True
            )
            return False

    @db_retry()
    async def update_guild_templates(
        self,
        guild_id: str,
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
        guild_id: str,
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
                        SELECT id, name, channel_id 
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
                e["channel_id"] = str(e["channel_id"]) if e.get("channel_id") else None
                participants = await self.get_event_participants(e["id"])
                e["participants"] = participants
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
                        SELECT s.streamer_id, s.streamer_name, a.pr_id as assigned_pr_id, ss.started_at as assigned_at,
                               TIMESTAMPDIFF(SECOND, ss.started_at, NOW()) as duration_seconds
                        FROM assistants a
                        JOIN spec_sessions ss ON ss.pr_id = a.pr_id 
                             AND ss.target_type = 'streamer' 
                             AND ss.target_id = a.assigned_to_id 
                             AND ss.ended_at IS NULL
                        JOIN streamers s ON s.streamer_id = a.assigned_to_id
                        WHERE a.assigned_to_type = 'streamer'
                        ORDER BY ss.started_at DESC
                        """
                    )
                    results = await cursor.fetchall()
                    for r in results:
                        r["streamer_id"] = str(r["streamer_id"])
                        r["assigned_pr_id"] = str(r["assigned_pr_id"])
                    return results
        except Exception as e:
            self.logger.error(f"Failed to get active spec sessions: {e}", exc_info=True)
            return []

    @db_retry()
    async def get_pr_spec_sessions(
        self, pr_id: int, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Получение истории сессий спека для PR ассистента (только стримеры)."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Fetch from spec_sessions, aliasing target_id -> streamer_id
                    # Also calculate duration
                    await cursor.execute(
                        """
                        SELECT id, pr_id, target_type, target_id, started_at, ended_at, end_reason, target_id as streamer_id,
                               TIMESTAMPDIFF(SECOND, started_at, COALESCE(ended_at, UTC_TIMESTAMP())) as duration_seconds
                        FROM spec_sessions
                        WHERE pr_id = %s AND target_type = 'streamer'
                        ORDER BY started_at DESC
                        LIMIT %s
                        """,
                        (pr_id, limit),
                    )
                    results = await cursor.fetchall()
                    for r in results:
                         r["pr_id"] = str(r["pr_id"])
                         if r.get("target_id"):
                             r["target_id"] = str(r["target_id"])
                         if r.get("streamer_id"):
                             r["streamer_id"] = str(r["streamer_id"])
                    return results
        except Exception as e:
            self.logger.error(f"Failed to get PR spec sessions: {e}", exc_info=True)
            return []

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

            # Assign new PR
            await self.assign_pr_to_streamer(streamer_id, to_pr_id)

            return result.get("duration_seconds")
        except Exception as e:
            self.logger.error(
                f"Failed to transfer streamer {streamer_id} from {from_pr_id} to {to_pr_id}: {e}",
                exc_info=True,
            )
            raise

    # =========================================================================
    # Web Auth Operations (consolidated from web/backend)
    # =========================================================================

    @db_retry()
    async def create_user(
        self,
        discord_id: int,
        username: str,
        password_hash: str,
        created_by: Optional[int] = None,
    ) -> int:
        """Create a new web user (web_auth)."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO web_auth (discord_id, username, password_hash, created_at) 
                        VALUES (%s, %s, %s, NOW())
                        """,
                        (discord_id, username, password_hash),
                    )
                    await conn.commit()
                    return cursor.lastrowid
        except Exception as e:
            self.logger.error(f"Failed to create user {username}: {e}", exc_info=True)
            raise

    @db_retry()
    async def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """Get user by username (joins assistants for role)."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT w.id, w.discord_id, w.username, w.password_hash, w.is_active, w.require_password_change, w.failed_login_attempts, w.last_login, w.created_at, a.role, a.nickname 
                        FROM web_auth w
                        LEFT JOIN assistants a ON a.pr_id = w.discord_id
                        WHERE w.username = %s
                        """,
                        (username,),
                    )
                    return await cursor.fetchone()
        except Exception as e:
            self.logger.error(f"Failed to get user {username}: {e}", exc_info=True)
            raise

    @db_retry()
    async def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get user by ID (joins assistants for role)."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Assuming id is web_auth.id
                    await cursor.execute(
                        """
                        SELECT w.id, w.discord_id, w.username, w.is_active, w.require_password_change, w.failed_login_attempts, w.last_login, w.created_at, a.role, a.nickname 
                        FROM web_auth w
                        LEFT JOIN assistants a ON a.pr_id = w.discord_id
                        WHERE w.id = %s
                        """,
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
                        "SELECT failed_login_attempts FROM web_auth WHERE username = %s",
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
                        UPDATE web_auth 
                        SET failed_login_attempts = failed_login_attempts + 1, 
                            last_login = CURRENT_TIMESTAMP 
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
                        UPDATE web_auth 
                        SET failed_login_attempts = 0, 
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
        self,
        user_id: Optional[int],
        username: str,
        action: str,
        ip: str,
        user_agent: str,
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

    # =========================================================================
    # Dashboard Operations
    # =========================================================================

    @db_retry()
    async def get_dashboard_stats(self) -> Dict[str, int]:
        """Get aggregated statistics for the main dashboard."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # 1. Count assigned PR assistants
                    await cursor.execute(
                        "SELECT COUNT(*) as count FROM assistants WHERE assigned_to_type IS NOT NULL"
                    )
                    assigned_pr_count = (await cursor.fetchone())["count"]

                    # 2. Count unassigned streamers (online but no PR)
                    try:
                        await cursor.execute(
                            """
                            SELECT COUNT(*) as count 
                            FROM streamers s
                            LEFT JOIN assistants a ON a.assigned_to_type = 'streamer' AND a.assigned_to_id = s.streamer_id
                            WHERE s.is_online = TRUE AND a.pr_id IS NULL
                            """
                        )
                        result = await cursor.fetchone()
                        unassigned_media_count = result["count"] if result else 0
                    except Exception:
                        unassigned_media_count = 0

                    # 3. Count events for today
                    try:
                        await cursor.execute(
                            """
                            SELECT COUNT(*) as count FROM events 
                            WHERE is_active = TRUE
                            """
                        )
                        result = await cursor.fetchone()
                        events_today_count = result["count"] if result else 0
                    except Exception:
                        events_today_count = 0

                    return {
                        "assigned_pr_count": assigned_pr_count,
                        "unassigned_media_count": unassigned_media_count,
                        "events_today_count": events_today_count,
                    }
        except Exception as e:
            self.logger.error(f"Failed to get dashboard stats: {e}", exc_info=True)
            return {
                "assigned_pr_count": 0,
                "unassigned_media_count": 0,
                "events_today_count": 0,
            }
