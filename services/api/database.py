"""Модуль работы с базой данных MySQL.
Обрабатывает все операции DB, включая управление стримерами, настройками,
событиями и статистикой. Включает автоматическое создание таблиц и логику повторных попыток.
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Dict, List, Optional

import aiomysql
from config import Config
from utils import split_time_by_day  # NOTE: kept for potential future use by views migration


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
                autocommit=True,  # Ensure commits are immediately visible
                init_command="SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED",  # Prevent stale reads
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
                            is_pinned BOOLEAN DEFAULT FALSE,
                            stream_points_override FLOAT DEFAULT NULL,
                            stream_title VARCHAR(255),
                            stream_thumbnail_url VARCHAR(512),
                            profile_image_url VARCHAR(512),
                            stream_game_id BIGINT UNSIGNED,
                            stream_game_name VARCHAR(255),
                            stream_started_at TIMESTAMP NULL,
                            priority INT DEFAULT 0,
                            pr_slots INT DEFAULT 1,
                            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            added_by_id BIGINT UNSIGNED,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            UNIQUE(streamer_name)
                        )
                        """
                    )
                    try:
                        await cursor.execute(
                            "ALTER TABLE streamers ADD COLUMN is_pinned BOOLEAN DEFAULT FALSE"
                        )
                    except Exception:
                        pass

                    try:
                        await cursor.execute(
                            "ALTER TABLE streamers ADD COLUMN stream_points_override FLOAT DEFAULT NULL"
                        )
                    except Exception:
                        pass  # Column likely exists

                    try:
                        await cursor.execute(
                            "ALTER TABLE streamers ADD COLUMN pr_slots INT DEFAULT 1"
                        )
                    except Exception:
                        pass  # Column likely exists

                    # =========================================================
                    # 2. Settings Table
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS settings (
                            id INT PRIMARY KEY DEFAULT 1,
                            notification_channel_id BIGINT UNSIGNED,
                            monitoring_channel_id BIGINT UNSIGNED,
                            monitoring_message_ids JSON,
                            pr_actions_channel_id BIGINT UNSIGNED,
                            control_panel_channel_id BIGINT UNSIGNED,
                            control_panel_message_id BIGINT UNSIGNED,
                            notification_templates JSON,
                            p0_rate FLOAT DEFAULT 1.0,
                            p1_rate FLOAT DEFAULT 1.2,
                            p2_rate FLOAT DEFAULT 1.5,
                            p3_rate FLOAT DEFAULT 2.0,
                            probation_rate FLOAT DEFAULT 1.2,
                            monitoring_filter_gta BOOLEAN DEFAULT FALSE
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
                            role ENUM('junior_employee', 'employee', 'senior_employee', 'manager', 'developer') NOT NULL DEFAULT 'employee',
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
                            
                            target_type ENUM('streamer', 'event', 'manual') NOT NULL DEFAULT 'streamer',
                            target_id BIGINT UNSIGNED NULL,
                            is_probation BOOLEAN DEFAULT FALSE,
                            
                            started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            ended_at TIMESTAMP NULL,
                            end_reason VARCHAR(50),
                            
                            # Priority snapshot & override
                            priority_auto TINYINT UNSIGNED NOT NULL DEFAULT 0,
                            priority_override TINYINT UNSIGNED NULL,
                            applied_priority_level TINYINT UNSIGNED GENERATED ALWAYS AS (
                                COALESCE(priority_override, priority_auto)
                            ) STORED,
                            
                            # Rate snapshot & override
                            rate_auto FLOAT NOT NULL DEFAULT 1.00,
                            rate_override FLOAT NULL,
                            applied_hourly_rate FLOAT GENERATED ALWAYS AS (
                                COALESCE(rate_override, rate_auto)
                            ) STORED,
                            
                            # Computed duration
                            duration_seconds INT UNSIGNED GENERATED ALWAYS AS (
                                CASE WHEN ended_at IS NULL THEN NULL
                                     ELSE TIMESTAMPDIFF(SECOND, started_at, ended_at)
                                END
                            ) STORED,
                            
                            # Admin comment if manual spec 
                            manual_comment VARCHAR(255) NULL,
                            
                            # Soft-delete
                            deleted_at TIMESTAMP NULL,
                            deleted_by_id BIGINT UNSIGNED NULL,
                            delete_reason VARCHAR(255) NULL,
                            
                            # One active session per PR constraint helper
                            active_pr_id BIGINT UNSIGNED GENERATED ALWAYS AS (
                                CASE WHEN ended_at IS NULL AND deleted_at IS NULL THEN pr_id
                                     ELSE NULL
                                END
                            ) STORED,
                            
                            # Constraints
                            CONSTRAINT chk_ended_after_started CHECK (ended_at IS NULL OR ended_at > started_at),
                            CONSTRAINT chk_manual_no_target CHECK (target_type != 'manual' OR target_id IS NULL),
                            CONSTRAINT chk_non_manual_has_target CHECK (target_type = 'manual' OR target_id IS NOT NULL),
                            CONSTRAINT chk_priority_range CHECK (priority_auto BETWEEN 0 AND 3 AND (priority_override IS NULL OR priority_override BETWEEN 0 AND 3)),
                            CONSTRAINT chk_rate_positive CHECK (rate_auto >= 0 AND (rate_override IS NULL OR rate_override >= 0)),
                            
                            # Indexes
                            UNIQUE INDEX uq_one_active_session_per_pr (active_pr_id),
                            INDEX idx_pr_started (pr_id, started_at),
                            INDEX idx_pr_ended (pr_id, ended_at),
                            INDEX idx_target_started (target_type, target_id, started_at)
                        )
                        """
                    )

                    # =========================================================
                    # 5. Daily Stats Table
                    # =========================================================
                    # 5. Day-Slicing View (Recursive CTE)
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE OR REPLACE VIEW spec_session_day_slices AS
                        WITH RECURSIVE day_slices AS (
                            # Anchor: start of each completed, non-deleted session
                            SELECT
                                ss.id AS session_id,
                                ss.pr_id,
                                ss.target_type,
                                ss.target_id,
                                ss.is_probation,
                                ss.applied_priority_level,
                                ss.applied_hourly_rate,
                                ss.started_at,
                                ss.ended_at,
                                # slice_start = started_at for the first day
                                ss.started_at AS slice_start,
                                # slice_end = midnight of the next day, or ended_at (whichever is earlier)
                                LEAST(
                                    DATE_ADD(DATE(ss.started_at), INTERVAL 1 DAY),
                                    ss.ended_at
                                ) AS slice_end
                            FROM spec_sessions ss
                            WHERE ss.ended_at IS NOT NULL
                              AND ss.deleted_at IS NULL
                            
                            UNION ALL
                            
                            # Recursive: next day slices
                            SELECT
                                ds.session_id,
                                ds.pr_id,
                                ds.target_type,
                                ds.target_id,
                                ds.is_probation,
                                ds.applied_priority_level,
                                ds.applied_hourly_rate,
                                ds.started_at,
                                ds.ended_at,
                                ds.slice_end AS slice_start,
                                LEAST(
                                    DATE_ADD(DATE(ds.slice_end), INTERVAL 1 DAY),
                                    ds.ended_at
                                ) AS slice_end
                            FROM day_slices ds
                            WHERE ds.slice_end < ds.ended_at
                        )
                        SELECT
                            session_id,
                            pr_id,
                            target_type,
                            target_id,
                            is_probation,
                            applied_priority_level,
                            applied_hourly_rate,
                            DATE(slice_start) AS work_date,
                            TIMESTAMPDIFF(SECOND, slice_start, slice_end) AS seconds_in_day,
                            ROUND(
                                (TIMESTAMPDIFF(SECOND, slice_start, slice_end) / 3600.0) * applied_hourly_rate,
                                4
                            ) AS points_in_day
                        FROM day_slices
                        """
                    )

                    # =========================================================
                    # 6. Aggregated Daily Stats View
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE OR REPLACE VIEW daily_stats AS
                        SELECT
                            pr_id,
                            work_date AS date,
                            SUM(CASE WHEN applied_priority_level = 0 AND NOT is_probation THEN seconds_in_day ELSE 0 END) AS p0_seconds,
                            SUM(CASE WHEN applied_priority_level = 1 AND NOT is_probation THEN seconds_in_day ELSE 0 END) AS p1_seconds,
                            SUM(CASE WHEN applied_priority_level = 2 AND NOT is_probation THEN seconds_in_day ELSE 0 END) AS p2_seconds,
                            SUM(CASE WHEN applied_priority_level = 3 AND NOT is_probation THEN seconds_in_day ELSE 0 END) AS p3_seconds,
                            SUM(CASE WHEN is_probation THEN seconds_in_day ELSE 0 END) AS probation_seconds,
                            SUM(points_in_day) AS total_points
                        FROM spec_session_day_slices
                        GROUP BY pr_id, work_date
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
                            priority INT DEFAULT 0,
                            pr_slots INT DEFAULT 1,
                            
                            channel_id BIGINT UNSIGNED,
                            message_id BIGINT UNSIGNED,
                            created_by BIGINT UNSIGNED
                        )
                        """
                    )

                    # Migration: Add columns if they don't exist
                    try:
                        await cursor.execute(
                            "ALTER TABLE events ADD COLUMN priority INT DEFAULT 0"
                        )
                    except Exception:
                        pass  # Column likely exists

                    try:
                        await cursor.execute(
                            "ALTER TABLE events ADD COLUMN pr_slots INT DEFAULT 1"
                        )
                    except Exception:
                        pass  # Column likely exists

                    try:
                        await cursor.execute(
                            "ALTER TABLE events ADD COLUMN is_pinned BOOLEAN DEFAULT FALSE"
                        )
                    except Exception:
                        pass

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
                            last_failed_login TIMESTAMP NULL,
                            last_login TIMESTAMP NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )

                    try:
                        await cursor.execute(
                            "ALTER TABLE web_auth ADD COLUMN last_failed_login TIMESTAMP NULL"
                        )
                    except Exception:
                        pass

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

                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS role_permissions (
                            role VARCHAR(50) PRIMARY KEY,
                            permissions JSON NOT NULL,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                        )
                        """
                    )

                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS admin_logs (
                            id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            admin_name VARCHAR(255) NOT NULL,
                            admin_role VARCHAR(50),
                            action VARCHAR(50) NOT NULL,
                            target_type VARCHAR(50),
                            target_id VARCHAR(100),
                            details JSON,
                            ip_address VARCHAR(45),
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            INDEX idx_admin_name (admin_name),
                            INDEX idx_action (action),
                            INDEX idx_created_at (created_at)
                        )
                        """
                    )

                    await cursor.execute("SET sql_notes = 1")
                    await conn.commit()

                    await self._init_default_permissions(conn)
                    await self._ensure_singleton_settings(conn)

                    self.logger.info("Database initialized successfully (V2 Final)")
        except Exception as e:
            self.logger.error(f"Failed to initialize database: {e}", exc_info=True)
            raise

    async def _init_default_permissions(self, conn):
        """Initialize default role permissions."""
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
                    "can_view_admin_logs": True,
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
                    "can_view_admin_logs": True,
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

    async def _ensure_singleton_settings(self, conn):
        """Ensure settings table has exactly one row."""
        async with conn.cursor() as cursor:

            await cursor.execute("SELECT COUNT(*) as count FROM settings")

            result = await cursor.fetchone()
            row_count = result["count"]

            if row_count == 0:
                self.logger.debug(
                    "  ℹ No settings row found, will be created on first update"
                )
            elif row_count == 1:
                self.logger.debug("  ✓ Settings table has exactly 1 row")
            else:
                self.logger.warning(
                    f"  ⚠ Settings table has {row_count} rows, cleaning up to keep only 1..."
                )
                await cursor.execute("SELECT * FROM settings LIMIT 1")

                survivor = await cursor.fetchone()

                await cursor.execute("DELETE FROM settings")
                if survivor:

                    columns = list(survivor.keys())
                    values = [survivor[col] for col in columns]
                    placeholders = ", ".join(["%s"] * len(columns))
                    column_names = ", ".join(columns)

                    await cursor.execute(
                        f"INSERT INTO settings ({column_names}) VALUES ({placeholders})",
                        tuple(values),
                    )
                    self.logger.info("  ✓ Settings table cleaned up to 1 row")

                await conn.commit()

    async def get_role_permissions(self, role: str) -> dict:
        """Get permissions for a role from role_permissions table."""
        import json

        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT permissions FROM role_permissions WHERE role = %s", (role,)
                )
                row = await cursor.fetchone()
                if row:
                    permissions = row.get("permissions", "{}")
                    if isinstance(permissions, str):
                        return json.loads(permissions)
                    return permissions
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
        admin_name: str,
        action: str,
        admin_role: Optional[str] = None,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        details: Optional[dict] = None,
        ip_address: Optional[str] = None,
    ) -> None:
        """
        Log an admin action to the admin_logs table for auditing.

        Args:
            admin_name: Nickname/Username of the admin performing the action
            action: Action name (e.g., 'update_streamer', 'delete_assistant')
            admin_role: Role of the admin (e.g. 'manager')
            target_type: Type of target entity (e.g., 'streamer', 'assistant')
            target_id: ID of the target entity
            details: Optional JSON details (old_value, new_value, etc.)
            ip_address: Optional IP address of the request source
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO admin_logs 
                            (admin_name, admin_role, action, target_type, target_id, details, ip_address)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            admin_name,
                            admin_role,
                            action,
                            target_type,
                            target_id,
                            json.dumps(details) if details else None,
                            ip_address,
                        ),
                    )
                    await conn.commit()
                    self.logger.debug(f"Admin log: {action} by {admin_name}")
        except Exception as e:
            self.logger.error(f"Failed to log admin action: {e}", exc_info=True)

    @db_retry()
    async def get_admin_logs(
        self,
        limit: int = 100,
        offset: int = 0,
        filters: dict = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ):
        """
        Get admin logs with optional filtering and pagination.

        Args:
            limit: Number of records to fetch
            offset: Offset for pagination
            filters: Optional dictionary with filters:
                - action: str
                - admin_name: str (partial match)
                - start_date: datetime
                - end_date: datetime
                - target_type: str

        Returns:
            List of log dictionaries with admin info
        """
        try:
            filters = filters or {}
            where_clauses = []
            params = []
            allowed_sorts = {
                "created_at": "al.id",
                "admin_name": "al.admin_name",
                "action": "al.action",
                "target_name": "target_name",
            }
            sort_column = allowed_sorts.get(sort_by, "al.created_at")
            sort_dir = "ASC" if sort_order.lower() == "asc" else "DESC"

            if filters.get("action"):
                actions = filters["action"]
                if isinstance(actions, list) and len(actions) > 0:
                    placeholders = ", ".join(["%s"] * len(actions))
                    where_clauses.append(f"al.action IN ({placeholders})")
                    params.extend(actions)
                elif isinstance(actions, str) and actions != "all":
                    where_clauses.append("al.action = %s")
                    params.append(actions)

            if filters.get("admin_name"):
                where_clauses.append("al.admin_name LIKE %s")
                params.append(f"%{filters['admin_name']}%")

            if filters.get("target_type") and filters["target_type"] != "all":
                where_clauses.append("al.target_type = %s")
                params.append(filters["target_type"])

            if filters.get("start_date"):
                where_clauses.append("al.created_at >= %s")
                params.append(filters["start_date"])

            if filters.get("end_date"):
                where_clauses.append("al.created_at <= %s")
                params.append(filters["end_date"])

            where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

            params.append(limit)
            params.append(offset)

            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    sql_query = f"""
                        SELECT 
                            al.id,
                            al.admin_name,
                            al.admin_role,
                            al.action,
                            al.target_type,
                            al.target_id,
                            al.details,
                            al.ip_address,
                            al.created_at,
                            CASE 
                                WHEN al.target_type = 'streamer' THEN s.streamer_name
                                WHEN al.target_type = 'event' THEN e.name
                                ELSE al.target_id
                            END as target_name
                        FROM admin_logs al
                        LEFT JOIN streamers s ON al.target_type = 'streamer' AND al.target_id COLLATE utf8mb4_general_ci = CAST(s.streamer_id AS CHAR)
                        LEFT JOIN events e ON al.target_type = 'event' AND al.target_id COLLATE utf8mb4_general_ci = CAST(e.id AS CHAR)
                        {where_sql}
                        ORDER BY {sort_column} {sort_dir}
                        LIMIT %s OFFSET %s
                        """
                    await cursor.execute(sql_query, tuple(params))

                    logs = await cursor.fetchall()
                    result = []

                    for log in logs:
                        log_dict = dict(log)
                        if log_dict.get("details"):
                            try:
                                if isinstance(log_dict["details"], str):
                                    log_dict["details"] = json.loads(
                                        log_dict["details"]
                                    )
                            except (json.JSONDecodeError, TypeError):
                                pass
                        result.append(log_dict)

                    return result
        except Exception as e:
            self.logger.error(f"Failed to fetch admin logs: {e}", exc_info=True)
            return []

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
        pr_slots: int = 1,
        added_by_id: int = 0,
        game_id: Optional[int] = None,
        game_name: Optional[str] = None,
        stream_title: Optional[str] = None,
        stream_thumbnail_url: Optional[str] = None,
        profile_image_url: Optional[str] = None,
    ) -> None:
        """

        Создание или обновление стримера в базе данных.

        Args:
            streamer_id: Twitch ID стримера
            streamer_name: Имя пользователя Twitch
            is_online: Статус онлайн
            started_at: Время начала стрима
            priority: Приоритет (0-3)
            pr_slots: Количество слотов для PR ассистентов (1-10)
            added_by_id: ID пользователя Discord, добавившего стримера
            game_id: ID игры на Twitch
            game_name: Название игры
            stream_title: Название стрима
            stream_thumbnail_url: URL превью стрима
            profile_image_url: URL аватара стримера
        """

        try:
            self.logger.debug(
                f"Creating/updating streamer: {streamer_name} (ID: {streamer_id}, profile_image: {profile_image_url[:50] if profile_image_url else 'None'}...)"
            )
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT streamer_id FROM streamers WHERE streamer_name = %s",
                        (streamer_name,),
                    )
                    existing_by_name = await cursor.fetchone()

                    if (
                        existing_by_name
                        and existing_by_name["streamer_id"] != streamer_id
                    ):
                        old_id = existing_by_name["streamer_id"]
                        new_name_old = f"old_{old_id}"
                        self.logger.warning(
                            f"Streamer Name Collision: '{streamer_name}' is taken by ID {old_id}. "
                            f"Renaming {old_id} to '{new_name_old}' to insert new ID {streamer_id}."
                        )
                        await cursor.execute(
                            "UPDATE streamers SET streamer_name = %s WHERE streamer_id = %s",
                            (new_name_old, old_id),
                        )

                    await cursor.execute(
                        """
                        INSERT INTO streamers (
                            streamer_id, streamer_name, is_online, stream_started_at, priority, pr_slots,
                            added_at, added_by_id, stream_game_id, stream_game_name, stream_title, 
                            stream_thumbnail_url, profile_image_url
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s, %s, %s, %s, %s, %s) AS new_data
                        ON DUPLICATE KEY UPDATE 
                            streamer_name = new_data.streamer_name,
                            is_online = new_data.is_online,
                            stream_started_at = new_data.stream_started_at,
                            priority = new_data.priority,
                            pr_slots = new_data.pr_slots,
                            added_by_id = new_data.added_by_id,
                            stream_game_id = new_data.stream_game_id,
                            stream_game_name = new_data.stream_game_name,
                            stream_title = new_data.stream_title,
                            stream_thumbnail_url = new_data.stream_thumbnail_url,
                            profile_image_url = new_data.profile_image_url
                        """,
                        (
                            streamer_id,
                            streamer_name,
                            is_online,
                            started_at,
                            priority,
                            pr_slots,
                            added_by_id,
                            game_id,
                            game_name,
                            stream_title,
                            stream_thumbnail_url,
                            profile_image_url,
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
                    await cursor.execute(
                        """
                        SELECT 
                            streamer_id, streamer_name, is_online, is_pinned, stream_points_override,
                            stream_title, stream_thumbnail_url,
                            profile_image_url,
                            stream_game_id as game_id, stream_game_name as game_name, stream_started_at as started_at,
                            priority, pr_slots, added_at, added_by_id, updated_at
                        FROM streamers
                        WHERE streamer_id = %s
                        """,
                        (streamer_id,),
                    )
                    streamer = await cursor.fetchone()
                    self.logger.debug(
                        f"get_streamer({streamer_id}) raw result: {streamer is not None}"
                    )
                    if not streamer:
                        return None

                    await cursor.execute(
                        """
                        SELECT 
                            ss.pr_id, 
                            a.nickname,
                            ss.is_probation,
                            ss.started_at as assigned_at
                        FROM spec_sessions ss
                        LEFT JOIN assistants a ON a.pr_id = ss.pr_id
                        WHERE ss.target_type = 'streamer' AND ss.target_id = %s
                            AND ss.ended_at IS NULL AND ss.deleted_at IS NULL
                        """,
                        (streamer_id,),
                    )
                    assignments = await cursor.fetchall()

                    result = dict(streamer)
                    result["assignments"] = (
                        [
                            {
                                "pr_id": str(a["pr_id"]),
                                "nickname": a["nickname"],
                                "is_probation": a.get("is_probation", False),
                                "assigned_at": a.get("assigned_at"),
                            }
                            for a in assignments
                        ]
                        if assignments
                        else []
                    )

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
        profile_image_url: Optional[str] = None,
    ) -> tuple[dict, dict]:
        """
        Атомарное обновление статуса стримера с блокировкой строки.

        Использует SELECT ... FOR UPDATE для предотвращения гонок.
        Возвращает (old_state, new_state) для определения изменений.

        Returns:
            Tuple of (old_state, new_state) dicts with keys:
            - is_online, game_id, game_name, stream_title, streamer_name
        """

        try:
            self.logger.debug(
                f"Atomic update streamer {streamer_id}: online={is_online} game_id={game_id}"
            )

            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Lock the row and get current state atomically
                    await cursor.execute(
                        """
                        SELECT 
                            streamer_name, is_online, 
                            stream_game_id as game_id, stream_game_name as game_name,
                            stream_title
                        FROM streamers 
                        WHERE streamer_id = %s 
                        FOR UPDATE
                        """,
                        (streamer_id,),
                    )
                    row = await cursor.fetchone()

                    if not row:
                        # Streamer not found
                        return (None, None)

                    old_state = {
                        "streamer_name": row["streamer_name"],
                        "is_online": row["is_online"],
                        "game_id": str(row["game_id"]) if row["game_id"] else None,
                        "game_name": row["game_name"],
                        "stream_title": row["stream_title"],
                    }

                    # Build dynamic SET clause
                    set_parts = ["is_online = %s"]
                    params = [is_online]

                    set_parts.append("stream_started_at = %s")
                    params.append(started_at)
                    set_parts.append("stream_game_id = %s")
                    params.append(game_id)
                    set_parts.append("stream_game_name = %s")
                    params.append(game_name)
                    set_parts.append("stream_title = %s")
                    params.append(stream_title)
                    set_parts.append("stream_thumbnail_url = %s")
                    params.append(stream_thumbnail_url)

                    if profile_image_url is not None:
                        set_parts.append("profile_image_url = %s")
                        params.append(profile_image_url)

                    # Reset pin and overrides if stream goes offline
                    if is_online is False:
                        set_parts.append("is_pinned = FALSE")
                        set_parts.append("stream_points_override = NULL")

                    params.append(streamer_id)

                    query = f"UPDATE streamers SET {', '.join(set_parts)} WHERE streamer_id = %s"
                    await cursor.execute(query, tuple(params))
                    await conn.commit()

                    new_state = {
                        "streamer_name": old_state["streamer_name"],
                        "is_online": is_online,
                        "game_id": str(game_id) if game_id else None,
                        "game_name": game_name,
                        "stream_title": stream_title,
                    }

                    return (old_state, new_state)

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
        Only updates fields that are explicitly provided in each update dict.

        Args:
            updates: List of dicts with keys:
                - streamer_id (required)
                - is_online (required)
                - started_at (optional)
                - game_id (optional)
                - game_name (optional)
                - stream_title (optional)
                - stream_thumbnail_url (optional)
                - profile_image_url (optional) - only updated if provided

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

                        set_parts = ["is_online = %s"]
                        params = [update.get("is_online", False)]

                        set_parts.append("stream_started_at = %s")
                        params.append(update.get("started_at"))
                        set_parts.append("stream_game_id = %s")
                        params.append(update.get("game_id"))
                        set_parts.append("stream_game_name = %s")
                        params.append(update.get("game_name"))
                        set_parts.append("stream_title = %s")
                        params.append(update.get("stream_title"))
                        set_parts.append("stream_thumbnail_url = %s")
                        params.append(update.get("stream_thumbnail_url"))

                        # Only update profile_image_url if provided
                        if (
                            "profile_image_url" in update
                            and update["profile_image_url"] is not None
                        ):
                            set_parts.append("profile_image_url = %s")
                            params.append(update["profile_image_url"])

                        params.append(streamer_id)

                        query = f"UPDATE streamers SET {', '.join(set_parts)} WHERE streamer_id = %s"
                        await cursor.execute(query, tuple(params))

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
        pr_slots: Optional[int] = None,
        is_pinned: Optional[bool] = None,
        stream_points_override: Optional[float] = None,
    ) -> bool:
        """Обновление настроек стримера."""
        try:
            set_parts = []
            params = []

            if priority is not None:
                set_parts.append("priority = %s")
                params.append(priority)

            if pr_slots is not None:
                set_parts.append("pr_slots = %s")
                params.append(pr_slots)

            if is_pinned is not None:
                set_parts.append("is_pinned = %s")
                params.append(is_pinned)

            if stream_points_override is not None:
                # Handle clearing the override (if passed as specific value to clear, or handle None carefully)
                # But here passing None usually means 'no change'.
                # To clear it, we might need a specific sentinel or just assume the frontend passes -1 or something,
                # but better to assume standard update logic: if passed, update it.
                # If we want to clear it, we pass None? No, None means no change here.
                # Let's assume frontend passes a value. If value is -1, set to NULL?
                # Or simply: optional float.
                # Wait, Pydantic will pass None if not provided.
                set_parts.append("stream_points_override = %s")
                params.append(stream_points_override)

            if not set_parts:
                return False

            params.append(streamer_id)

            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        f"UPDATE streamers SET {', '.join(set_parts)} WHERE streamer_id = %s",
                        tuple(params),
                    )
                    await conn.commit()
                    return cursor.rowcount > 0
        except Exception as e:
            self.logger.error(
                f"Failed to update streamer {streamer_id}: {e}", exc_info=True
            )
            return False

    @db_retry()
    async def update_event(
        self,
        event_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        required_pr_count: Optional[int] = None,
        priority: Optional[int] = None,
        is_pinned: Optional[bool] = None,
        points: Optional[float] = None,
    ) -> bool:
        """Update event settings."""
        try:
            set_parts = []
            params = []

            if name is not None:
                set_parts.append("name = %s")
                params.append(name)

            if description is not None:
                set_parts.append("description = %s")
                params.append(description)

            if required_pr_count is not None:
                set_parts.append("required_pr_count = %s")
                params.append(required_pr_count)
                set_parts.append("pr_slots = %s")
                params.append(required_pr_count)

            if priority is not None:
                set_parts.append("priority = %s")
                params.append(priority)

            if is_pinned is not None:
                set_parts.append("is_pinned = %s")
                params.append(is_pinned)

            if not set_parts:
                return False

            params.append(event_id)

            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        f"UPDATE events SET {', '.join(set_parts)} WHERE id = %s",
                        tuple(params),
                    )
                    await conn.commit()
                    return cursor.rowcount > 0
        except Exception as e:
            self.logger.error(f"Failed to update event {event_id}: {e}", exc_info=True)
            return False

    @db_retry()
    async def remove_streamer(self, streamer_id: int) -> bool:
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
                    await cursor.execute(
                        """
                        SELECT 
                            s.streamer_id, s.streamer_name, s.is_online, s.stream_title, s.stream_thumbnail_url,
                            s.is_pinned, s.stream_points_override, s.profile_image_url,
                            s.stream_game_id as game_id, s.stream_game_name as game_name, s.stream_started_at as started_at,
                            s.priority, s.pr_slots, s.added_at, s.added_by_id, s.updated_at,
                            MIN(a.pr_id) as assigned_pr_id,
                            COALESCE(
                                JSON_ARRAYAGG(
                                    CASE WHEN a.pr_id IS NOT NULL THEN
                                        JSON_OBJECT(
                                            'pr_id', CAST(a.pr_id AS CHAR),
                                            'nickname', a.nickname,
                                            'is_probation', COALESCE(ss.is_probation, FALSE),
                                            'assigned_at', ss.started_at
                                        )
                                    ELSE NULL END
                                ),
                                JSON_ARRAY()
                            ) as assignments
                        FROM streamers s
                        LEFT JOIN spec_sessions ss ON ss.target_type = 'streamer' 
                             AND ss.target_id = s.streamer_id 
                             AND ss.ended_at IS NULL AND ss.deleted_at IS NULL
                        LEFT JOIN assistants a ON a.pr_id = ss.pr_id
                        GROUP BY s.streamer_id
                        ORDER BY s.is_pinned DESC, s.priority DESC, s.streamer_name ASC
                        """
                    )
                    results = await cursor.fetchall()
                    for r in results:
                        if isinstance(r.get("assignments"), str):
                            r["assignments"] = json.loads(r["assignments"])
                        if r.get("assignments"):
                            r["assignments"] = [
                                x for x in r["assignments"] if x is not None
                            ]
                    return results
        except Exception as e:
            self.logger.error(f"Failed to list streamers: {e}", exc_info=True)
            raise

    @db_retry()
    async def list_online_streamers(self) -> List[Dict[str, Any]]:
        """
        Получение списка всех онлайн стримеров с агрегированными назначениями.
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT 
                            s.streamer_id, s.streamer_name, s.is_online, s.stream_title, s.stream_thumbnail_url,
                            s.is_pinned, s.stream_points_override, s.profile_image_url,
                            s.stream_game_id as game_id, s.stream_game_name as game_name, s.stream_started_at as started_at,
                            s.priority, s.pr_slots, s.added_at, s.added_by_id, s.updated_at,
                            MIN(ss.pr_id) as assigned_pr_id,
                            COALESCE(
                                JSON_ARRAYAGG(
                                    CASE WHEN a.pr_id IS NOT NULL THEN
                                        JSON_OBJECT(
                                            'pr_id', CAST(a.pr_id AS CHAR),
                                            'nickname', a.nickname,
                                            'is_probation', COALESCE(ss.is_probation, FALSE),
                                            'assigned_at', ss.started_at
                                        )
                                    ELSE NULL END
                                ),
                                JSON_ARRAY()
                            ) as assignments
                        FROM streamers s
                        LEFT JOIN spec_sessions ss ON ss.target_type = 'streamer' 
                             AND ss.target_id = s.streamer_id 
                             AND ss.ended_at IS NULL AND ss.deleted_at IS NULL
                        LEFT JOIN assistants a ON a.pr_id = ss.pr_id
                        WHERE s.is_online = TRUE
                        GROUP BY s.streamer_id
                        ORDER BY s.is_pinned DESC, s.priority DESC, s.streamer_name ASC
                        """
                    )
                    results = await cursor.fetchall()
                    for r in results:
                        if isinstance(r.get("assignments"), str):
                            r["assignments"] = json.loads(r["assignments"])
                        if r.get("assignments"):
                            r["assignments"] = [
                                x for x in r["assignments"] if x is not None
                            ]
                    return results
        except Exception as e:
            self.logger.error(f"Failed to list online streamers: {e}", exc_info=True)
            raise

    # =========================================================================
    # Guild Operations
    # =========================================================================

    async def create_or_update_guild(
        self,
        notification_channel_id: Optional[int] = None,
        monitoring_channel_id: Optional[int] = None,
        monitoring_message_ids: Optional[list] = None,
        monitoring_filter_gta: Optional[bool] = None,
        pr_actions_channel_id: Optional[int] = None,
        control_panel_channel_id: Optional[int] = None,
        control_panel_message_id: Optional[int] = None,
    ) -> None:
        """Create or update guild settings.

        Args:
            notification_channel_id: Discord channel ID for notifications (optional)
            monitoring_channel_id: Discord channel ID for monitoring (optional)
            monitoring_message_ids: List of Discord message IDs for monitoring (optional)
            monitoring_filter_gta: Filter monitoring to GTA streamers only (optional)
            pr_actions_channel_id: Discord channel ID for PR actions (optional)
            control_panel_channel_id: Discord channel ID for control panel (optional)
            control_panel_message_id: Discord message ID for control panel embed (optional)
        """
        try:
            self.logger.debug(
                f"""Saving guild settings: notification channel={notification_channel_id}, monitoring channel={monitoring_channel_id}, 
                PR actions channel={pr_actions_channel_id}, control panel channel={control_panel_channel_id}, control panel message={control_panel_message_id}"""
            )
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # First, get existing settings using the same cursor to ensure consistency
                    await cursor.execute(
                        "SELECT notification_channel_id, monitoring_channel_id, monitoring_message_ids, monitoring_filter_gta, pr_actions_channel_id, control_panel_channel_id, control_panel_message_id FROM settings",
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
                    final_monitoring_channel = (
                        monitoring_channel_id
                        if monitoring_channel_id is not None
                        else (
                            existing.get("monitoring_channel_id") if existing else None
                        )
                    )

                    # Handle monitoring_message_ids (JSON list)
                    existing_ids = (
                        existing.get("monitoring_message_ids") if existing else None
                    )
                    if isinstance(existing_ids, str):
                        import json as json_module

                        existing_ids = json_module.loads(existing_ids)
                    final_monitoring_message_ids = (
                        monitoring_message_ids
                        if monitoring_message_ids is not None
                        else existing_ids
                    )
                    # Serialize to JSON for MySQL
                    import json as json_module

                    final_monitoring_ids_json = (
                        json_module.dumps(final_monitoring_message_ids)
                        if final_monitoring_message_ids is not None
                        else None
                    )
                    final_pr_actions_channel = (
                        pr_actions_channel_id
                        if pr_actions_channel_id is not None
                        else (
                            existing.get("pr_actions_channel_id") if existing else None
                        )
                    )
                    final_control_panel_channel = (
                        control_panel_channel_id
                        if control_panel_channel_id is not None
                        else (
                            existing.get("control_panel_channel_id")
                            if existing
                            else None
                        )
                    )
                    final_control_panel_message = (
                        control_panel_message_id
                        if control_panel_message_id is not None
                        else (
                            existing.get("control_panel_message_id")
                            if existing
                            else None
                        )
                    )

                    final_filter_gta = (
                        monitoring_filter_gta
                        if monitoring_filter_gta is not None
                        else (
                            existing.get("monitoring_filter_gta") if existing else False
                        )
                    )

                    # 1. Update if exists
                    # Atomic UPSERT to prevent race conditions
                    await cursor.execute(
                        """
                        INSERT INTO settings (
                            id, 
                            notification_channel_id, 
                            monitoring_channel_id, 
                            monitoring_message_ids, 
                            monitoring_filter_gta, 
                            pr_actions_channel_id, 
                            control_panel_channel_id, 
                            control_panel_message_id
                        )
                        VALUES (1, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            notification_channel_id = VALUES(notification_channel_id),
                            monitoring_channel_id = VALUES(monitoring_channel_id),
                            monitoring_message_ids = VALUES(monitoring_message_ids),
                            monitoring_filter_gta = VALUES(monitoring_filter_gta),
                            pr_actions_channel_id = VALUES(pr_actions_channel_id),
                            control_panel_channel_id = VALUES(control_panel_channel_id),
                            control_panel_message_id = VALUES(control_panel_message_id)
                        """,
                        (
                            final_notification,
                            final_monitoring_channel,
                            final_monitoring_ids_json,
                            final_filter_gta,
                            final_pr_actions_channel,
                            final_control_panel_channel,
                            final_control_panel_message,
                        ),
                    )
                    await conn.commit()
                    self.logger.debug("✓ Guild settings saved successfully")

        except Exception as e:
            self.logger.error(f"Failed to save guild: {e}", exc_info=True)
            raise

    async def get_guild(self) -> Optional[Dict[str, Any]]:
        """Get guild settings.

        Returns:
            Guild settings dict or None if not found
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT notification_channel_id, monitoring_channel_id, monitoring_message_ids, monitoring_filter_gta, pr_actions_channel_id, control_panel_channel_id, control_panel_message_id, notification_templates, p0_rate, p1_rate, p2_rate, p3_rate, probation_rate FROM settings WHERE id = 1",
                    )
                    return await cursor.fetchone()
        except Exception as e:
            self.logger.error(f"Failed to get guild: {e}", exc_info=True)
            raise

    async def get_notification_template(self, event_type: str) -> str:
        """
        Получение шаблона уведомления для события.

        Args:
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

        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT notification_templates FROM settings WHERE id = 1"
                    )
                    result = await cursor.fetchone()
                    if result and result.get("notification_templates"):
                        templates = json.loads(result["notification_templates"])
                        return templates.get(
                            event_type, Config.template_defaults.get(event_type, "")
                        )
                    return Config.template_defaults.get(event_type, "")
        except Exception as e:
            self.logger.error(f"Failed to get template for guild: {e}", exc_info=True)
            return Config.template_defaults.get(event_type, "")

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
            True если успешно

        Raises:
            ValueError: Если занят слот или PR уже закреплен
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Check if PR already has an active session
                    await cursor.execute(
                        """
                        SELECT id FROM spec_sessions 
                        WHERE pr_id = %s AND ended_at IS NULL AND deleted_at IS NULL
                        """,
                        (pr_id,),
                    )
                    active = await cursor.fetchone()
                    if active:
                        self.logger.warning(f"PR {pr_id} already has active session {active['id']}")
                        raise ValueError(
                            "Вы уже закреплены за другим стримером или событием"
                        )

                    # Check slot availability
                    await cursor.execute(
                        """
                        SELECT ss.pr_id, ss.is_probation 
                        FROM spec_sessions ss
                        WHERE ss.target_type = 'streamer' 
                          AND ss.target_id = %s 
                          AND ss.ended_at IS NULL
                          AND ss.deleted_at IS NULL
                        """,
                        (streamer_id,),
                    )
                    existing_sessions = await cursor.fetchall()

                    if not is_probation:
                        # Main slot: enforce pr_slots limit
                        await cursor.execute(
                            "SELECT pr_slots, priority FROM streamers WHERE streamer_id = %s",
                            (streamer_id,),
                        )
                        streamer_row = await cursor.fetchone()
                        pr_slots = (
                            streamer_row.get("pr_slots", 1) if streamer_row else 1
                        )
                        streamer_priority = (
                            streamer_row.get("priority", 0) if streamer_row else 0
                        )
                        main_count = sum(
                            1 for s in existing_sessions if not s.get("is_probation")
                        )
                        if main_count >= pr_slots:
                            raise ValueError(
                                f"Все основные слоты заняты ({main_count}/{pr_slots})"
                            )
                    else:
                        # Probation slot: only 1 allowed
                        for session in existing_sessions:
                            if session.get("is_probation"):
                                raise ValueError("Слот Probation уже занят")
                        # Still need streamer priority for snapshot
                        await cursor.execute(
                            "SELECT priority FROM streamers WHERE streamer_id = %s",
                            (streamer_id,),
                        )
                        streamer_row = await cursor.fetchone()
                        streamer_priority = (
                            streamer_row.get("priority", 0) if streamer_row else 0
                        )

                    # Snapshot the rate from config
                    config = await self.get_points_config()
                    if is_probation:
                        rate_auto = await self._get_probation_rate()
                    else:
                        rate_auto = config.get(streamer_priority, 0.5)

                    # Ensure assistant exists
                    await cursor.execute(
                        """
                        INSERT INTO assistants (pr_id) VALUES (%s)
                        ON DUPLICATE KEY UPDATE pr_id = pr_id
                        """,
                        (pr_id,),
                    )

                    # Insert session with snapshot
                    try:
                        await cursor.execute(
                            """
                            INSERT INTO spec_sessions 
                                (pr_id, target_type, target_id, is_probation, started_at,
                                 priority_auto, rate_auto)
                            VALUES (%s, 'streamer', %s, %s, NOW(), %s, %s)
                            """,
                            (pr_id, streamer_id, is_probation, streamer_priority, rate_auto),
                        )
                    except Exception as e:
                        if "uq_one_active_session_per_pr" in str(e):
                            raise ValueError(
                                "Вы уже закреплены за другим стримером или событием"
                            )
                        raise

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
        self,
        streamer_id: int,
        pr_id: Optional[int] = None,
        end_reason: str = "unknown",
    ) -> List[Dict[str, Any]]:
        """
        Снятие PR-ассистента(ов) со стримера.

        Args:
            streamer_id: Twitch ID стримера
            pr_id: ID ассистента для точечного снятия. Если None - снимает всех.
            end_reason: Причина завершения

        Returns:
            Список словарей с данными сессий
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # 1. Find active sessions for this streamer
                    query = """
                        SELECT ss.id, ss.pr_id, ss.started_at, ss.is_probation, st.streamer_name
                        FROM spec_sessions ss
                        JOIN streamers st ON st.streamer_id = ss.target_id
                        WHERE ss.target_type = 'streamer' 
                          AND ss.target_id = %s 
                          AND ss.ended_at IS NULL
                          AND ss.deleted_at IS NULL
                    """
                    params = [streamer_id]

                    if pr_id is not None:
                        query += " AND ss.pr_id = %s"
                        params.append(pr_id)

                    await cursor.execute(query, tuple(params))
                    results = await cursor.fetchall()

                    if not results:
                        return []

                    unassigned_sessions = []

                    # Prepare time calculation
                    await cursor.execute("SELECT NOW() as now")
                    now_result = await cursor.fetchone()
                    now = now_result["now"]
                    if now.tzinfo is None:
                        now = now.replace(tzinfo=timezone.utc)

                    session_ids = []

                    for res in results:
                        started_at = res["started_at"]
                        if started_at and started_at.tzinfo is None:
                            started_at = started_at.replace(tzinfo=timezone.utc)

                        duration_seconds = 0
                        if started_at:
                            duration_seconds = int((now - started_at).total_seconds())

                        unassigned_sessions.append(
                            {
                                "pr_id": res["pr_id"],
                                "duration_seconds": duration_seconds,
                                "streamer_name": res["streamer_name"],
                                "is_probation": res.get("is_probation", False),
                            }
                        )
                        session_ids.append(res["id"])

                    # 2. Close Sessions (duration_seconds is auto-computed by generated column)
                    if session_ids:
                        format_strings = ",".join(["%s"] * len(session_ids))
                        await cursor.execute(
                            f"""
                            UPDATE spec_sessions 
                            SET ended_at = %s, end_reason = %s
                            WHERE id IN ({format_strings})
                            """,
                            (now, end_reason, *session_ids),
                        )

                    await conn.commit()

            return unassigned_sessions

        except Exception as e:
            self.logger.error(
                f"Failed to unassign PR(s) from streamer {streamer_id}: {e}",
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
                    # Get PR1's current active session
                    await cursor.execute(
                        """
                        SELECT ss.target_id as streamer_id, s.streamer_name, s.priority, ss.is_probation
                        FROM spec_sessions ss
                        JOIN streamers s ON s.streamer_id = ss.target_id
                        WHERE ss.pr_id = %s AND ss.target_type = 'streamer'
                          AND ss.ended_at IS NULL AND ss.deleted_at IS NULL
                        """,
                        (pr1_id,),
                    )
                    pr1_assignment = await cursor.fetchone()

                    if not pr1_assignment:
                        raise ValueError(f"PR {pr1_id} has no claimed streamer")

                    # Get PR2's current active session
                    await cursor.execute(
                        """
                        SELECT ss.target_id as streamer_id, s.streamer_name, s.priority, ss.is_probation
                        FROM spec_sessions ss
                        JOIN streamers s ON s.streamer_id = ss.target_id
                        WHERE ss.pr_id = %s AND ss.target_type = 'streamer'
                          AND ss.ended_at IS NULL AND ss.deleted_at IS NULL
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
                        WHERE pr_id IN (%s, %s) AND ended_at IS NULL AND deleted_at IS NULL
                        """,
                        (pr1_id, pr2_id),
                    )

                    # Snapshot rates for new sessions
                    config = await self.get_points_config()
                    
                    # PR1 gets streamer2
                    pr1_probation = pr1_assignment.get("is_probation", False)
                    s2_priority = pr2_assignment.get("priority", 0)
                    if pr1_probation:
                        rate1 = await self._get_probation_rate()
                    else:
                        rate1 = config.get(s2_priority, 0.5)

                    # PR2 gets streamer1
                    pr2_probation = pr2_assignment.get("is_probation", False)
                    s1_priority = pr1_assignment.get("priority", 0)
                    if pr2_probation:
                        rate2 = await self._get_probation_rate()
                    else:
                        rate2 = config.get(s1_priority, 0.5)

                    # Create new spec sessions with snapshots
                    await cursor.execute(
                        """
                        INSERT INTO spec_sessions 
                            (pr_id, target_type, target_id, is_probation, started_at, priority_auto, rate_auto)
                        VALUES 
                            (%s, 'streamer', %s, %s, NOW(), %s, %s), 
                            (%s, 'streamer', %s, %s, NOW(), %s, %s)
                        """,
                        (pr1_id, streamer2_id, pr1_probation, s2_priority, rate1,
                         pr2_id, streamer1_id, pr2_probation, s1_priority, rate2),
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
                        WHERE ended_at IS NULL AND deleted_at IS NULL
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
                        """
                        SELECT pr_id FROM spec_sessions 
                        WHERE target_type = 'streamer' AND target_id = %s 
                          AND ended_at IS NULL AND deleted_at IS NULL
                        """,
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
                        SELECT s.streamer_id, s.streamer_name, s.is_online, s.stream_title, s.stream_thumbnail_url, s.stream_game_id, s.stream_game_name, s.stream_started_at, s.priority, s.added_at, s.added_by_id, s.updated_at, ss.started_at as assigned_at
                        FROM spec_sessions ss
                        JOIN streamers s ON s.streamer_id = ss.target_id
                        WHERE ss.pr_id = %s AND ss.target_type = 'streamer'
                          AND ss.ended_at IS NULL AND ss.deleted_at IS NULL
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
        Получение общего времени спека ассистента (из spec_sessions).

        Args:
            pr_id: Discord ID ассистента

        Returns:
            Общее время в секундах
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT COALESCE(SUM(duration_seconds), 0) as total_spec_seconds 
                        FROM spec_sessions 
                        WHERE pr_id = %s AND deleted_at IS NULL AND ended_at IS NOT NULL
                        """,
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
    async def get_pr_actions_channel(self) -> Optional[int]:
        """
        Получение канала для логов действий PR.

        Returns:
            ID канала или None
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT pr_actions_channel_id FROM settings WHERE id = 1"
                    )
                    result = await cursor.fetchone()
                    return result.get("pr_actions_channel_id") if result else None
        except Exception as e:
            self.logger.error(
                f"Failed to get PR actions channel: {e}",
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
        name: str,
        description: str,
        channel_id: int,
        message_id: int,
        created_by: int,
        start_time=None,
        required_pr_count=1,
        notification_sent=False,
        pr_slots: int = 1,
        priority: int = 0,
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
                            name, description, channel_id, message_id,
                            required_pr_count, created_by, start_time, notification_sent,
                            pr_slots, priority
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                            pr_slots,
                            priority,
                        ),
                    )
                    await conn.commit()
                    return cursor.lastrowid
        except Exception as e:
            self.logger.error(f"Failed to create event: {e}", exc_info=True)
            return None

    @db_retry()
    async def get_active_events(self) -> list:
        """Получение активных событий гильдии."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        """
                        SELECT id, name, description, created_at, start_time, is_active, channel_id, message_id, created_by, notification_sent, required_pr_count, priority, pr_slots, is_pinned FROM events 
                        WHERE is_active = TRUE
                        ORDER BY is_pinned DESC, priority DESC, start_time ASC
                        """
                    )
                    events = await cursor.fetchall()
                    for event in events:
                        await cursor.execute(
                            """
                            SELECT ss.pr_id, a.nickname
                            FROM spec_sessions ss
                            LEFT JOIN assistants a ON a.pr_id = ss.pr_id
                            WHERE ss.target_type = 'event' AND ss.target_id = %s
                              AND ss.ended_at IS NULL AND ss.deleted_at IS NULL
                            """,
                            (event["id"],),
                        )
                        participants = await cursor.fetchall()
                        event["current_participants"] = len(participants)
                        event["participants"] = [
                            {"pr_id": str(p["pr_id"]), "nickname": p.get("nickname")}
                            for p in participants
                        ]

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
                        "SELECT id, name, description, created_at, start_time, is_active, channel_id, message_id, created_by, notification_sent, required_pr_count, priority, pr_slots, is_pinned FROM events WHERE id = %s",
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
                    await cursor.execute(
                        """
                        SELECT pr_id, started_at
                        FROM spec_sessions
                        WHERE target_type = 'event' AND target_id = %s AND ended_at IS NULL AND deleted_at IS NULL
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

                    await cursor.execute(
                        """
                        UPDATE events 
                        SET is_active = FALSE 
                        WHERE id = %s
                        """,
                        (event_id,),
                    )

                    await cursor.execute(
                        """
                        UPDATE spec_sessions 
                        SET ended_at = %s, end_reason = 'event_end'
                        WHERE target_type = 'event' AND target_id = %s AND ended_at IS NULL AND deleted_at IS NULL
                        """,
                        (now, event_id),
                    )

                    results = []
                    for p in participants:
                        user_id = p["pr_id"]
                        started_at = p["started_at"]
                        if started_at.tzinfo is None:
                            started_at = started_at.replace(tzinfo=timezone.utc)

                        effective_start = max(started_at, event_start_time)

                        duration = int((now - effective_start).total_seconds())
                        if duration < 0:
                            duration = 0

                        results.append({"user_id": user_id, "duration": duration})

                    await conn.commit()
                    return results
        except Exception as e:
            self.logger.error(f"Failed to end event {event_id}: {e}", exc_info=True)
            return []

    @db_retry()
    async def get_daily_stats(
        self,
        pr_id: int = None,
        date_obj: datetime.date = None,
        start_date=None,
        end_date=None,
    ) -> list:
        """Получение ежедневной статистики из VIEW daily_stats."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    query = "SELECT pr_id, date, p0_seconds, p1_seconds, p2_seconds, p3_seconds, probation_seconds, total_points FROM daily_stats WHERE 1=1"
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
    async def create_manual_spec_session(
        self,
        pr_id: int,
        target_type: str,
        target_id: Optional[int],
        duration_seconds: int,
        date_str: str,
        is_probation: bool = False,
        priority: int = 0,
    ) -> bool:
        """
        Создание ручной записи сессии спека (для админских корректировок).
        Записывается как уже завершённая сессия. daily_stats VIEW автоматически пересчитает баллы.
        """
        from datetime import datetime, timedelta

        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
            start_time = datetime.combine(date_obj, datetime.min.time())
            end_time = start_time + timedelta(seconds=duration_seconds)

            # Snapshot rate from config
            config = await self.get_points_config()
            if is_probation:
                rate_auto = await self._get_probation_rate()
            else:
                rate_auto = config.get(priority, 0.5)

            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Ensure assistant exists
                    await cursor.execute(
                        "INSERT INTO assistants (pr_id) VALUES (%s) ON DUPLICATE KEY UPDATE pr_id = pr_id",
                        (pr_id,),
                    )

                    await cursor.execute(
                        """
                        INSERT INTO spec_sessions 
                        (pr_id, target_type, target_id, started_at, ended_at, end_reason, 
                         is_probation, priority_auto, rate_auto)
                        VALUES (%s, %s, %s, %s, %s, 'manual_admin', %s, %s, %s)
                        """,
                        (
                            pr_id,
                            target_type,
                            target_id if target_type != 'manual' else None,
                            start_time,
                            end_time,
                            is_probation,
                            priority,
                            rate_auto,
                        ),
                    )
                    await conn.commit()

            self.logger.info(
                f"Manual spec session created: PR={pr_id}, duration={duration_seconds}s, date={date_str}, probation={is_probation}"
            )
            return True

        except Exception as e:
            self.logger.error(
                f"Failed to create manual spec session: {e}", exc_info=True
            )
            return False

    @db_retry()
    async def get_points_config(self) -> dict:
        """Получение конфигурации баллов для гильдии."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        "SELECT p0_rate, p1_rate, p2_rate, p3_rate FROM settings WHERE id = 1",
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
    async def set_points_config(self, rates: dict):
        """Установка конфигурации баллов."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        UPDATE settings 
                        SET p0_rate = %s, p1_rate = %s, p2_rate = %s, p3_rate = %s
                        WHERE id = 1
                        """,
                        (rates[0], rates[1], rates[2], rates[3]),
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


    async def _get_probation_rate(self) -> float:
        """Get probation rate from settings."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT probation_rate FROM settings WHERE id = 1"
                    )
                    result = await cursor.fetchone()
                    return result.get("probation_rate", 1.2) if result else 1.2
        except Exception:
            return 1.2

    @db_retry()
    async def join_event(self, event_id: int, user_id: int) -> bool:
        """Добавление пользователя в событие с проверкой лимита слотов."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    # Check if already has active session
                    await cursor.execute(
                        """
                        SELECT id FROM spec_sessions 
                        WHERE pr_id = %s AND ended_at IS NULL AND deleted_at IS NULL
                        """,
                        (user_id,),
                    )
                    active = await cursor.fetchone()
                    if active:
                        return False  # Busy

                    # Capacity check: count current participants vs pr_slots
                    await cursor.execute(
                        "SELECT pr_slots, priority FROM events WHERE id = %s AND is_active = TRUE",
                        (event_id,),
                    )
                    event = await cursor.fetchone()
                    if not event:
                        return False  # Event not found or inactive

                    pr_slots = event.get("pr_slots", 1)
                    event_priority = event.get("priority", 0)

                    await cursor.execute(
                        """
                        SELECT COUNT(*) as cnt FROM spec_sessions
                        WHERE target_type = 'event' AND target_id = %s 
                          AND ended_at IS NULL AND deleted_at IS NULL
                        """,
                        (event_id,),
                    )
                    count_row = await cursor.fetchone()
                    current_count = count_row["cnt"] if count_row else 0

                    if current_count >= pr_slots:
                        return False  # Full

                    # Snapshot rate from config
                    config = await self.get_points_config()
                    rate_auto = config.get(event_priority, 0.5)

                    # Ensure assistant exists
                    await cursor.execute(
                        "INSERT INTO assistants (pr_id) VALUES (%s) ON DUPLICATE KEY UPDATE pr_id = pr_id",
                        (user_id,),
                    )

                    # Create spec session with snapshot
                    try:
                        await cursor.execute(
                            """
                            INSERT INTO spec_sessions 
                                (pr_id, target_type, target_id, started_at, priority_auto, rate_auto)
                            VALUES (%s, 'event', %s, UTC_TIMESTAMP(), %s, %s)
                            """,
                            (user_id, event_id, event_priority, rate_auto),
                        )
                    except Exception as e:
                        if "uq_one_active_session_per_pr" in str(e):
                            return False
                        raise

                    await conn.commit()
                    return True
        except Exception as e:
            self.logger.error(f"Failed to join event: {e}", exc_info=True)
            return False

    @db_retry()
    async def leave_event(self, event_id: int, user_id: int) -> int:
        """Удаление пользователя из события и возврат длительности."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    # 1. Lock active session row for this participant
                    await cursor.execute(
                        """
                        SELECT id
                        FROM spec_sessions 
                        WHERE target_type = 'event' AND target_id = %s AND pr_id = %s 
                          AND ended_at IS NULL AND deleted_at IS NULL
                        FOR UPDATE
                        """,
                        (event_id, user_id),
                    )
                    result = await cursor.fetchone()

                    if not result:
                        return 0

                    session_id = result["id"]

                    # 2. Close session using DB time and guarantee ended_at > started_at
                    await cursor.execute(
                        """
                        UPDATE spec_sessions 
                        SET ended_at = GREATEST(
                                DATE_ADD(started_at, INTERVAL 1 SECOND),
                                UTC_TIMESTAMP()
                            ),
                            end_reason = 'manual_leave'
                        WHERE id = %s
                        """,
                        (session_id,),
                    )

                    await cursor.execute(
                        """
                        SELECT COALESCE(duration_seconds, 0) AS duration_seconds
                        FROM spec_sessions
                        WHERE id = %s
                        """,
                        (session_id,),
                    )
                    duration_row = await cursor.fetchone()

                    await conn.commit()
                    duration = int(duration_row["duration_seconds"]) if duration_row else 0
                    return max(duration, 0)
        except Exception as e:
            self.logger.error(f"Failed to leave event {event_id}: {e}", exc_info=True)
            return 0

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
            self.logger.error(
                f"Failed to mark event notification sent: {e}", exc_info=True
            )

    @db_retry()
    async def get_user_active_event_participation(self, user_id: int) -> Optional[dict]:
        """Проверка участия пользователя в активном событии."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        """
                        SELECT e.id, e.name 
                        FROM spec_sessions ss
                        JOIN events e ON ss.target_id = e.id
                        WHERE ss.pr_id = %s AND ss.target_type = 'event' 
                          AND ss.ended_at IS NULL AND ss.deleted_at IS NULL
                          AND e.is_active = TRUE
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
                        WHERE target_type = 'event' AND target_id = %s 
                          AND ended_at IS NULL AND deleted_at IS NULL
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
                        SELECT 
                            a.pr_id, 
                            COALESCE(SUM(ss.duration_seconds), 0) as total_spec_seconds,
                            COUNT(CASE WHEN ss.ended_at IS NOT NULL THEN 1 END) as session_count
                        FROM assistants a
                        LEFT JOIN spec_sessions ss ON ss.pr_id = a.pr_id AND ss.deleted_at IS NULL AND ss.ended_at IS NOT NULL
                        GROUP BY a.pr_id
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
        """Сброс статистики для конкретного ассистента (помечает все сессии как удалённые)."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        UPDATE spec_sessions 
                        SET deleted_at = NOW(), delete_reason = 'admin_reset'
                        WHERE pr_id = %s AND deleted_at IS NULL
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
        """Получение всех ассистентов с активными сессиями и статистикой."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT 
                            a.pr_id, a.nickname, a.role, 
                            DATEDIFF(NOW(), a.added_at) as experience_days,
                            CASE WHEN act.id IS NOT NULL THEN 'assigned' ELSE 'free' END as status,
                            act.target_type as assigned_to_type, act.target_id as assigned_to_id, 
                            COALESCE(stats.total_secs, 0) as total_spec_seconds, 
                            COALESCE(stats.sess_count, 0) as session_count, a.added_at,
                            COALESCE(s.streamer_name, e.name) as assigned_to_name,
                            ROUND(COALESCE(stats.total_secs, 0) / 3600, 1) as total_spec_hours
                        FROM assistants a
                        LEFT JOIN spec_sessions act ON act.pr_id = a.pr_id 
                            AND act.ended_at IS NULL AND act.deleted_at IS NULL
                        LEFT JOIN (
                            SELECT pr_id, SUM(duration_seconds) as total_secs, COUNT(*) as sess_count
                            FROM spec_sessions WHERE deleted_at IS NULL AND ended_at IS NOT NULL
                            GROUP BY pr_id
                        ) stats ON stats.pr_id = a.pr_id
                        LEFT JOIN streamers s ON act.target_type = 'streamer' AND act.target_id = s.streamer_id
                        LEFT JOIN events e ON act.target_type = 'event' AND act.target_id = e.id
                        ORDER BY total_spec_seconds DESC
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
                            CASE WHEN act.id IS NOT NULL THEN 'assigned' ELSE 'free' END as status,
                            act.target_type as assigned_to_type, act.target_id as assigned_to_id, 
                            COALESCE(stats.total_secs, 0) as total_spec_seconds, 
                            COALESCE(stats.sess_count, 0) as session_count, a.added_at,
                            COALESCE(s.streamer_name, e.name) as assigned_to_name,
                            ROUND(COALESCE(stats.total_secs, 0) / 3600, 1) as total_spec_hours
                        FROM assistants a
                        LEFT JOIN spec_sessions act ON act.pr_id = a.pr_id 
                            AND act.ended_at IS NULL AND act.deleted_at IS NULL
                        LEFT JOIN (
                            SELECT pr_id, SUM(duration_seconds) as total_secs, COUNT(*) as sess_count
                            FROM spec_sessions WHERE deleted_at IS NULL AND ended_at IS NOT NULL
                            GROUP BY pr_id
                        ) stats ON stats.pr_id = a.pr_id
                        LEFT JOIN streamers s ON act.target_type = 'streamer' AND act.target_id = s.streamer_id
                        LEFT JOIN events e ON act.target_type = 'event' AND act.target_id = e.id
                        WHERE a.pr_id = %s
                        """,
                        (user_id,),
                    )
                    return await cursor.fetchone()
        except Exception as e:
            self.logger.error(f"Failed to get assistant {user_id}: {e}", exc_info=True)
            return None

    @db_retry()
    async def get_assistant_logs(
        self, pr_id: int, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get assistant activity logs derived from spec_sessions."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    session_limit = max(int(limit), 1)
                    fetch_limit = max(session_limit * 2, session_limit)

                    await cursor.execute(
                        """
                        SELECT
                            ss.id,
                            ss.target_type,
                            ss.started_at,
                            ss.ended_at,
                            ss.duration_seconds,
                            ss.end_reason,
                            CASE
                                WHEN ss.target_type = 'streamer' THEN s.streamer_name
                                WHEN ss.target_type = 'event' THEN e.name
                                ELSE NULL
                            END AS target
                        FROM spec_sessions ss
                        LEFT JOIN streamers s
                            ON ss.target_type = 'streamer'
                            AND ss.target_id = s.streamer_id
                        LEFT JOIN events e
                            ON ss.target_type = 'event'
                            AND ss.target_id = e.id
                        WHERE ss.pr_id = %s
                          AND ss.deleted_at IS NULL
                        ORDER BY COALESCE(ss.ended_at, ss.started_at) DESC
                        LIMIT %s
                        """,
                        (pr_id, fetch_limit),
                    )
                    rows = await cursor.fetchall()

                    logs: List[Dict[str, Any]] = []

                    def format_duration(seconds: Optional[int]) -> Optional[str]:
                        if seconds is None:
                            return None
                        total = max(int(seconds), 0)
                        hours, remainder = divmod(total, 3600)
                        minutes, secs = divmod(remainder, 60)
                        if hours > 0:
                            return f"{hours}h {minutes}m"
                        if minutes > 0:
                            return f"{minutes}m {secs}s"
                        return f"{secs}s"

                    def to_epoch(value: Any) -> float:
                        if value is None:
                            return 0.0
                        if hasattr(value, "timestamp"):
                            try:
                                return float(value.timestamp())
                            except Exception:
                                return 0.0
                        return 0.0

                    for row in rows:
                        session_id = row.get("id")
                        target_type = row.get("target_type")
                        started_at = row.get("started_at")
                        ended_at = row.get("ended_at")
                        end_reason = row.get("end_reason")
                        duration_seconds = row.get("duration_seconds")
                        duration = format_duration(duration_seconds)

                        if target_type == "manual":
                            logs.append(
                                {
                                    "id": f"{session_id}:manual",
                                    "action": "Manual correction",
                                    "target": row.get("target"),
                                    "created_at": ended_at or started_at,
                                    "duration_seconds": duration_seconds,
                                    "duration": duration,
                                }
                            )
                            continue

                        # Assignment event should always remain in history
                        logs.append(
                            {
                                "id": f"{session_id}:assigned",
                                "action": "Assigned",
                                "target": row.get("target"),
                                "created_at": started_at,
                                "duration_seconds": None,
                                "duration": None,
                            }
                        )

                        # Unassignment event appears once session is closed
                        if ended_at is not None:
                            if end_reason and duration:
                                unassign_action = f"Unassigned ({end_reason}, {duration})"
                            elif end_reason:
                                unassign_action = f"Unassigned ({end_reason})"
                            elif duration:
                                unassign_action = f"Unassigned ({duration})"
                            else:
                                unassign_action = "Unassigned"

                            logs.append(
                                {
                                    "id": f"{session_id}:unassigned",
                                    "action": unassign_action,
                                    "target": row.get("target"),
                                    "created_at": ended_at,
                                    "duration_seconds": duration_seconds,
                                    "duration": duration,
                                }
                            )

                    logs.sort(key=lambda item: to_epoch(item.get("created_at")), reverse=True)
                    return logs[:session_limit]
        except Exception as e:
            self.logger.error(
                f"Failed to get assistant logs for {pr_id}: {e}", exc_info=True
            )
            return []

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
                            CASE WHEN act.id IS NOT NULL THEN 'assigned' ELSE 'free' END as status,
                            act.target_type as assigned_to_type, act.target_id as assigned_to_id, 
                            COALESCE(stats.total_secs, 0) as total_spec_seconds, 
                            COALESCE(stats.sess_count, 0) as session_count, a.added_at,
                            COALESCE(s.streamer_name, e.name) as assigned_to_name,
                            ROUND(COALESCE(stats.total_secs, 0) / 3600, 1) as total_spec_hours
                        FROM assistants a
                        LEFT JOIN spec_sessions act ON act.pr_id = a.pr_id 
                            AND act.ended_at IS NULL AND act.deleted_at IS NULL
                        LEFT JOIN (
                            SELECT pr_id, SUM(duration_seconds) as total_secs, COUNT(*) as sess_count
                            FROM spec_sessions WHERE deleted_at IS NULL AND ended_at IS NOT NULL
                            GROUP BY pr_id
                        ) stats ON stats.pr_id = a.pr_id
                        LEFT JOIN streamers s ON act.target_type = 'streamer' AND act.target_id = s.streamer_id
                        LEFT JOIN events e ON act.target_type = 'event' AND act.target_id = e.id
                        WHERE a.pr_id = %s
                        """,
                        (user_id,),
                    )
                    assistant = await cursor.fetchone()

                    if not assistant:
                        return None

                    # Get daily stats from VIEW
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
                        "INSERT INTO assistants (pr_id) VALUES (%s)",
                        (user_id,),
                    )
                    await conn.commit()

                    # Return created (use same query pattern)
                    return await self.get_assistant(user_id)
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
                        INSERT INTO assistants (pr_id, nickname, role, added_at)
                        VALUES (%s, %s, %s, DATE_SUB(NOW(), INTERVAL %s DAY))
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

    @db_retry()
    async def update_guild_templates(
        self,
        template_stream_online: Optional[str] = None,
        template_stream_offline: Optional[str] = None,
        template_category_to_gta: Optional[str] = None,
        template_category_from_gta: Optional[str] = None,
    ) -> bool:
        """Обновление шаблонов уведомлений гильдии."""
        try:
            guild = await self.get_guild()
            if not guild:  # Guild must exist
                return False

            # Get existing templates from DB
            raw_templates = guild.get("notification_templates")

            # Parse JSON string if needed, otherwise start with empty dict
            if isinstance(raw_templates, str):
                try:
                    current_templates = json.loads(raw_templates)
                except json.JSONDecodeError:
                    current_templates = {}
            elif isinstance(raw_templates, dict):
                current_templates = raw_templates.copy()
            else:
                current_templates = {}

            # Update only the provided fields
            if template_stream_online is not None:
                current_templates["stream_online"] = template_stream_online
            if template_stream_offline is not None:
                current_templates["stream_offline"] = template_stream_offline
            if template_category_to_gta is not None:
                current_templates["category_to_gta"] = template_category_to_gta
            if template_category_from_gta is not None:
                current_templates["category_from_gta"] = template_category_from_gta

            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "UPDATE settings SET notification_templates = %s",
                        (json.dumps(current_templates),),
                    )
                    await conn.commit()
                    return True
        except Exception as e:
            self.logger.error(f"Failed to update guild templates: {e}", exc_info=True)
            return False

    @db_retry()
    async def update_guild_rates(
        self,
        p0_rate: Optional[float] = None,
        p1_rate: Optional[float] = None,
        p2_rate: Optional[float] = None,
        p3_rate: Optional[float] = None,
        probation_rate: Optional[float] = None,
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
            if probation_rate is not None:
                updates.append("probation_rate = %s")
                values.append(probation_rate)

            if not updates:
                return True

            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        f"UPDATE settings SET {', '.join(updates)}",
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
                        SELECT s.streamer_id, s.streamer_name, ss.pr_id as assigned_pr_id, ss.started_at as assigned_at,
                               TIMESTAMPDIFF(SECOND, ss.started_at, NOW()) as duration_seconds
                        FROM spec_sessions ss
                        JOIN streamers s ON s.streamer_id = ss.target_id
                        WHERE ss.target_type = 'streamer'
                          AND ss.ended_at IS NULL AND ss.deleted_at IS NULL
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
                        SELECT w.id, w.discord_id, w.username, w.password_hash, w.is_active, w.require_password_change, w.failed_login_attempts, w.last_failed_login, w.last_login, w.created_at, a.role, a.nickname 
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
    async def get_user_by_discord_id(
        self, discord_id: int
    ) -> Optional[Dict[str, Any]]:
        """Get user by Discord ID (joins assistants for role)."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT w.id, w.discord_id, w.username, w.password_hash, w.is_active, w.require_password_change, w.failed_login_attempts, w.last_failed_login, w.last_login, w.created_at, a.role, a.nickname
                        FROM web_auth w
                        LEFT JOIN assistants a ON a.pr_id = w.discord_id
                        WHERE w.discord_id = %s
                        """,
                        (discord_id,),
                    )
                    return await cursor.fetchone()
        except Exception as e:
            self.logger.error(
                f"Failed to get user by discord_id {discord_id}: {e}", exc_info=True
            )
            raise

    @db_retry()
    async def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get user by ID (joins assistants for role and role_permissions for permissions)."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Assuming id is web_auth.id
                    await cursor.execute(
                        """
                        SELECT w.id, w.discord_id, w.username, w.is_active, w.require_password_change, w.failed_login_attempts, w.last_login, w.created_at, 
                        COALESCE(a.role, 'employee') as role, 
                        COALESCE(a.nickname, w.username) as nickname,
                        rp.permissions
                        FROM web_auth w
                        LEFT JOIN assistants a ON a.pr_id = w.discord_id
                        LEFT JOIN role_permissions rp ON rp.role = COALESCE(a.role, 'employee')
                        WHERE w.id = %s
                        """,
                        (user_id,),
                    )
                    user = await cursor.fetchone()
                    if user and user.get("permissions"):
                        # Parse JSON permissions
                        try:
                            if isinstance(user["permissions"], str):
                                user["permissions"] = json.loads(user["permissions"])
                        except (json.JSONDecodeError, TypeError):
                            user["permissions"] = {}
                    return user
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
                        UPDATE web_auth 
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
    async def is_session_active(self, user_id: int, session_id: int) -> bool:
        """Check whether session exists, belongs to user, is not revoked and not expired."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT id
                        FROM sessions
                        WHERE id = %s
                          AND user_id = %s
                          AND revoked = FALSE
                          AND expires_at > UTC_TIMESTAMP()
                        LIMIT 1
                        """,
                        (session_id, user_id),
                    )
                    return await cursor.fetchone() is not None
        except Exception as e:
            self.logger.error(f"Failed to validate session: {e}", exc_info=True)
            return False

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
                    # 1. Count assigned PR assistants (active sessions)
                    await cursor.execute(
                        "SELECT COUNT(*) as count FROM spec_sessions WHERE ended_at IS NULL AND deleted_at IS NULL"
                    )
                    assigned_pr_count = (await cursor.fetchone())["count"]

                    # 2. Count unassigned streamers (online but no active PR session)
                    try:
                        await cursor.execute(
                            """
                            SELECT COUNT(*) as count 
                            FROM streamers s
                            LEFT JOIN spec_sessions ss ON ss.target_type = 'streamer' AND ss.target_id = s.streamer_id
                                AND ss.ended_at IS NULL AND ss.deleted_at IS NULL
                            WHERE s.is_online = TRUE AND ss.id IS NULL
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
