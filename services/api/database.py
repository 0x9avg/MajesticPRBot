"""Модуль работы с базой данных MySQL.
Обрабатывает все операции DB, включая управление стримерами, настройками,
событиями и статистикой. Включает автоматическое создание таблиц и логику повторных попыток.
"""

import asyncio
import hashlib
import json
import time
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from typing import Any, Dict, List, Optional

import aiomysql
from config import Config  # NOTE: kept for potential future use by views migration


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
    # Schema Introspection Helpers
    # =========================================================================

    async def _table_exists(self, cursor, table_name: str) -> bool:
        await cursor.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM information_schema.tables
            WHERE table_schema = DATABASE()
              AND table_name = %s
            """,
            (table_name,),
        )
        row = await cursor.fetchone() or {}
        return int(row.get("cnt", 0)) > 0

    async def _list_columns(self, cursor, table_name: str) -> set[str]:
        await cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = %s
            """,
            (table_name,),
        )
        rows = await cursor.fetchall() or []
        return {str(row.get("column_name")) for row in rows if row.get("column_name")}

    async def _column_exists(self, cursor, table_name: str, column_name: str) -> bool:
        await cursor.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = %s
              AND column_name = %s
            """,
            (table_name, column_name),
        )
        row = await cursor.fetchone() or {}
        return int(row.get("cnt", 0)) > 0

    async def _get_primary_key_columns(self, cursor, table_name: str) -> list[str]:
        await cursor.execute(
            """
            SELECT column_name
            FROM information_schema.key_column_usage
            WHERE table_schema = DATABASE()
              AND table_name = %s
              AND constraint_name = 'PRIMARY'
            ORDER BY ordinal_position
            """,
            (table_name,),
        )
        rows = await cursor.fetchall() or []
        return [str(row.get("column_name")) for row in rows if row.get("column_name")]

    async def _index_exists(self, cursor, table_name: str, index_name: str) -> bool:
        await cursor.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM information_schema.statistics
            WHERE table_schema = DATABASE()
              AND table_name = %s
              AND index_name = %s
            """,
            (table_name, index_name),
        )
        row = await cursor.fetchone() or {}
        return int(row.get("cnt", 0)) > 0

    async def _column_is_auto_increment(
        self, cursor, table_name: str, column_name: str
    ) -> bool:
        await cursor.execute(
            """
            SELECT extra
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = %s
              AND column_name = %s
            LIMIT 1
            """,
            (table_name, column_name),
        )
        row = await cursor.fetchone() or {}
        extra = str(row.get("extra", "")).lower()
        return "auto_increment" in extra

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
                init_command="SET SESSION transaction_isolation='READ-COMMITTED', time_zone='+03:00'",  # Prevent stale reads & force MSK
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
                            allow_juniors BOOLEAN DEFAULT TRUE,
                            stream_title VARCHAR(255),
                            stream_thumbnail_url VARCHAR(512),
                            profile_image_url VARCHAR(512),
                            stream_game_id BIGINT UNSIGNED,
                            stream_game_name VARCHAR(255),
                            stream_started_at TIMESTAMP NULL,
                            priority INT DEFAULT 0,
                            pr_slots INT DEFAULT 1,
                            priority_override INT DEFAULT NULL,
                            pr_slots_override INT DEFAULT NULL,
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
                            "ALTER TABLE streamers DROP COLUMN IF EXISTS stream_points_override"
                        )
                    except Exception:
                        pass  # Column may not exist

                    try:
                        await cursor.execute(
                            "ALTER TABLE streamers ADD COLUMN pr_slots INT DEFAULT 1"
                        )
                    except Exception:
                        pass  # Column likely exists

                    try:
                        await cursor.execute(
                            "ALTER TABLE streamers ADD COLUMN allow_juniors BOOLEAN DEFAULT TRUE"
                        )
                    except Exception:
                        pass  # Column likely exists

                    try:
                        await cursor.execute(
                            "ALTER TABLE streamers ADD COLUMN priority_override INT DEFAULT NULL"
                        )
                    except Exception:
                        pass  # Column likely exists

                    try:
                        await cursor.execute(
                            "ALTER TABLE streamers ADD COLUMN pr_slots_override INT DEFAULT NULL"
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
                            monitoring_message_ids BIGINT UNSIGNED,
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
                            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            appointed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            auto_points_total FLOAT NOT NULL DEFAULT 0,
                            manual_points_adjustment FLOAT NOT NULL DEFAULT 0,
                            total_points FLOAT GENERATED ALWAYS AS (
                                ROUND(COALESCE(auto_points_total, 0) + COALESCE(manual_points_adjustment, 0), 4)
                            ) STORED,
                            penalty_points FLOAT NOT NULL DEFAULT 0,
                            penalty_percent FLOAT NOT NULL DEFAULT 0,
                            warnings_units INT UNSIGNED NOT NULL DEFAULT 0,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                        )
                        """
                    )
                    try:
                        await cursor.execute(
                            "ALTER TABLE assistants ADD COLUMN appointed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                        )
                    except Exception:
                        pass
                    try:
                        await cursor.execute(
                            "ALTER TABLE assistants ADD COLUMN auto_points_total FLOAT NOT NULL DEFAULT 0"
                        )
                    except Exception:
                        pass
                    try:
                        await cursor.execute(
                            "ALTER TABLE assistants ADD COLUMN manual_points_adjustment FLOAT NOT NULL DEFAULT 0"
                        )
                    except Exception:
                        pass
                    try:
                        await cursor.execute(
                            """
                            ALTER TABLE assistants
                            ADD COLUMN total_points FLOAT
                            GENERATED ALWAYS AS (
                                ROUND(COALESCE(auto_points_total, 0) + COALESCE(manual_points_adjustment, 0), 4)
                            ) STORED
                            """
                        )
                    except Exception:
                        pass
                    try:
                        await cursor.execute(
                            "ALTER TABLE assistants ADD COLUMN penalty_points FLOAT NOT NULL DEFAULT 0"
                        )
                    except Exception:
                        pass
                    try:
                        await cursor.execute(
                            "ALTER TABLE assistants ADD COLUMN penalty_percent FLOAT NOT NULL DEFAULT 0"
                        )
                    except Exception:
                        pass
                    try:
                        await cursor.execute(
                            "ALTER TABLE assistants ADD COLUMN warnings_units INT UNSIGNED NOT NULL DEFAULT 0"
                        )
                    except Exception:
                        pass
                    try:
                        await cursor.execute(
                            "ALTER TABLE assistants ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"
                        )
                    except Exception:
                        pass
                    await cursor.execute(
                        """
                        UPDATE assistants
                        SET appointed_at = COALESCE(appointed_at, added_at, CURRENT_TIMESTAMP)
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
                            end_reason ENUM('manual_unclaim', 'stream_end', 'category_change', 'admin_closed', 'event_end', 'event_rejected', 'unknown') NULL,
                            
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
                            session_admin_comment VARCHAR(255) NULL,

                            # Persisted contribution to assistant auto points (for deterministic delta recalculation)
                            credited_points FLOAT NOT NULL DEFAULT 0,
                            
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
                    try:
                        await cursor.execute(
                            """
                            ALTER TABLE spec_sessions
                            ADD COLUMN session_admin_comment VARCHAR(255) NULL
                            """
                        )
                    except Exception:
                        pass
                    try:
                        await cursor.execute(
                            """
                            ALTER TABLE spec_sessions
                            CHANGE COLUMN manual_comment session_admin_comment VARCHAR(255) NULL
                            """
                        )
                    except Exception:
                        pass
                    try:
                        await cursor.execute(
                            """
                            UPDATE spec_sessions
                            SET session_admin_comment = manual_comment
                            WHERE session_admin_comment IS NULL
                              AND manual_comment IS NOT NULL
                            """
                        )
                    except Exception:
                        pass
                    try:
                        await cursor.execute(
                            """
                            ALTER TABLE spec_sessions
                            DROP COLUMN manual_comment
                            """
                        )
                    except Exception:
                        pass
                    try:
                        await cursor.execute(
                            """
                            ALTER TABLE spec_sessions
                            ADD COLUMN credited_points FLOAT NOT NULL DEFAULT 0
                            """
                        )
                    except Exception:
                        pass

                    # Migration: Sanitize and alter end_reason to tight ENUM
                    try:
                        await cursor.execute(
                            """
                            UPDATE spec_sessions
                            SET end_reason = 'manual_unclaim'
                            WHERE end_reason IN ('manual', 'swap', 'transfer', 'manual_assignment_clear')
                            """
                        )
                        await cursor.execute(
                            """
                            UPDATE spec_sessions
                            SET end_reason = 'unknown'
                            WHERE end_reason IS NOT NULL
                              AND end_reason NOT IN ('manual_unclaim', 'stream_end', 'category_change', 'admin_closed', 'event_end', 'event_rejected', 'unknown')
                            """
                        )
                        await cursor.execute(
                            """
                            ALTER TABLE spec_sessions
                            MODIFY COLUMN end_reason ENUM('manual_unclaim', 'stream_end', 'category_change', 'admin_closed', 'event_end', 'event_rejected', 'unknown') NULL
                            """
                        )
                    except Exception as e:
                        self.logger.warning(f"Error migrating end_reason to ENUM: {e}")




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
                            created_by BIGINT UNSIGNED,
                            event_kind ENUM('regular','spec_request') NOT NULL DEFAULT 'regular',
                            approval_status ENUM('approved','pending','rejected') NOT NULL DEFAULT 'approved',
                            requested_by BIGINT UNSIGNED NULL,
                            approved_by BIGINT UNSIGNED NULL,
                            approved_at TIMESTAMP NULL,
                            rejected_by BIGINT UNSIGNED NULL,
                            rejected_at TIMESTAMP NULL
                        )
                        """
                    )
                    
                    try:
                        await cursor.execute(
                            "ALTER TABLE events DROP COLUMN channel_id"
                        )
                    except Exception:
                        pass
                    
                    try:
                        await cursor.execute(
                            "ALTER TABLE events DROP COLUMN message_id"
                        )
                    except Exception:
                        pass

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

                    # Spec-request feature: new columns
                    for stmt in [
                        "ALTER TABLE events ADD COLUMN event_kind ENUM('regular','spec_request') NOT NULL DEFAULT 'regular'",
                        "ALTER TABLE events ADD COLUMN approval_status ENUM('approved','pending','rejected') NOT NULL DEFAULT 'approved'",
                        "ALTER TABLE events ADD COLUMN requested_by BIGINT UNSIGNED NULL",
                        "ALTER TABLE events ADD COLUMN approved_by BIGINT UNSIGNED NULL",
                        "ALTER TABLE events ADD COLUMN approved_at TIMESTAMP NULL",
                        "ALTER TABLE events ADD COLUMN rejected_by BIGINT UNSIGNED NULL",
                        "ALTER TABLE events ADD COLUMN rejected_at TIMESTAMP NULL",
                    ]:
                        try:
                            await cursor.execute(stmt)
                        except Exception:
                            pass

                    # =========================================================
                    # 6.5. Event Participants Table (Deferred spec_sessions)
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS event_participants (
                            event_id INT UNSIGNED NOT NULL,
                            pr_id BIGINT UNSIGNED NOT NULL,
                            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            PRIMARY KEY (event_id, pr_id),
                            FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
                        )
                        """
                    )

                    # =========================================================
                    # 7. Web Auth Table (ex Users)
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS web_auth (
                            discord_id BIGINT UNSIGNED PRIMARY KEY,
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
                            user_id BIGINT UNSIGNED NOT NULL, 
                            refresh_token_hash VARCHAR(64) NOT NULL,
                            family_id VARCHAR(32) NOT NULL,
                            replaced_by_hash VARCHAR(64) NULL,
                            expires_at TIMESTAMP NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            revoked BOOLEAN DEFAULT FALSE,
                            revoked_at TIMESTAMP NULL,
                            ip_address VARCHAR(45),
                            last_ip VARCHAR(45) NULL,
                            user_agent TEXT,
                            device_label VARCHAR(128) NULL,
                            INDEX idx_user_id (user_id),
                            INDEX idx_refresh_token_hash (refresh_token_hash),
                            INDEX idx_family_id (family_id)
                        )
                        """
                    )

                    # ----------------------------------------------------------
                    # Session table migration (legacy -> new schema)
                    # ----------------------------------------------------------
                    session_migration_columns = {
                        "family_id": "ALTER TABLE sessions ADD COLUMN family_id VARCHAR(32) NOT NULL DEFAULT ''",
                        "refresh_token_hash": "ALTER TABLE sessions ADD COLUMN refresh_token_hash VARCHAR(64) NOT NULL DEFAULT ''",
                        "replaced_by_hash": "ALTER TABLE sessions ADD COLUMN replaced_by_hash VARCHAR(64) NULL",
                        "last_ip": "ALTER TABLE sessions ADD COLUMN last_ip VARCHAR(45) NULL",
                        "device_label": "ALTER TABLE sessions ADD COLUMN device_label VARCHAR(128) NULL",
                    }
                    for col_name, alter_sql in session_migration_columns.items():
                        try:
                            await cursor.execute(alter_sql)
                        except Exception:
                            pass  # Column already exists

                    # Add index on family_id if missing
                    try:
                        await cursor.execute(
                            "ALTER TABLE sessions ADD INDEX idx_family_id (family_id)"
                        )
                    except Exception:
                        pass

                    # Add index on refresh_token_hash if missing
                    try:
                        await cursor.execute(
                            "ALTER TABLE sessions ADD INDEX idx_refresh_token_hash (refresh_token_hash)"
                        )
                    except Exception:
                        pass

                    # Relax legacy columns to avoid NOT NULL errors during inserts if they still exist
                    try:
                        await cursor.execute(
                            "ALTER TABLE sessions MODIFY COLUMN refresh_token VARCHAR(512) NULL"
                        )
                    except Exception:
                        pass

                    # Auth Logs (System)
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS auth_logs (
                            id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            user_id BIGINT UNSIGNED,
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

                    # ----------------------------------------------------------
                    # web_auth PK Migration (id -> discord_id), guarded fail-fast
                    # ----------------------------------------------------------
                    await self._migrate_web_auth_pk_to_discord_id(cursor)

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
                        CREATE TABLE IF NOT EXISTS service_principals (
                            name VARCHAR(100) PRIMARY KEY,
                            token_hash VARCHAR(64) NOT NULL UNIQUE,
                            permissions JSON NOT NULL,
                            is_active BOOLEAN NOT NULL DEFAULT TRUE,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                        )
                        """
                    )

                    # service_principals hash-only migration, guarded fail-fast
                    await self._migrate_service_principals_hash_only(cursor)

                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS admin_logs (
                            id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            actor_name VARCHAR(255) NOT NULL,
                            actor_role VARCHAR(50),
                            action VARCHAR(100) NOT NULL,
                            target_type VARCHAR(50),
                            target_id VARCHAR(100),
                            details JSON NOT NULL,
                            INDEX idx_created_at (created_at),
                            INDEX idx_action_created (action, created_at),
                            INDEX idx_actor_created (actor_name, created_at),
                            INDEX idx_target_created (target_type, target_id, created_at)
                        )
                        """
                    )

                    # Admin logs migration (legacy -> compact universal schema)
                    # Keep this migration idempotent for environments with mixed schema history.
                    for statement in [
                        "ALTER TABLE admin_logs ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
                        "ALTER TABLE admin_logs ADD COLUMN actor_name VARCHAR(255) NULL",
                        "ALTER TABLE admin_logs ADD COLUMN actor_role VARCHAR(50) NULL",
                        "ALTER TABLE admin_logs ADD COLUMN details JSON NULL",
                        "ALTER TABLE admin_logs MODIFY action VARCHAR(100) NOT NULL",
                    ]:
                        try:
                            await cursor.execute(statement)
                        except Exception:
                            pass

                    # Backfill actor fields from legacy columns when present
                    try:
                        await cursor.execute(
                            """
                            UPDATE admin_logs
                            SET actor_name = COALESCE(actor_name, admin_name)
                            WHERE actor_name IS NULL
                            """
                        )
                    except Exception:
                        pass
                    try:
                        await cursor.execute(
                            """
                            UPDATE admin_logs
                            SET actor_role = COALESCE(actor_role, admin_role)
                            WHERE actor_role IS NULL
                            """
                        )
                    except Exception:
                        pass

                    # Ensure details is always present and preserve legacy ip in meta
                    await cursor.execute(
                        """
                        UPDATE admin_logs
                        SET details = COALESCE(details, JSON_OBJECT())
                        WHERE details IS NULL
                        """
                    )
                    try:
                        await cursor.execute(
                            """
                            UPDATE admin_logs
                            SET details = JSON_SET(
                                COALESCE(details, JSON_OBJECT()),
                                '$.meta.ip',
                                ip_address
                            )
                            WHERE ip_address IS NOT NULL
                              AND ip_address != ''
                            """
                        )
                    except Exception:
                        pass

                    # Finalize constraints
                    try:
                        await cursor.execute(
                            "ALTER TABLE admin_logs MODIFY actor_name VARCHAR(255) NOT NULL"
                        )
                    except Exception:
                        pass
                    try:
                        await cursor.execute(
                            "ALTER TABLE admin_logs MODIFY details JSON NOT NULL"
                        )
                    except Exception:
                        pass

                    # Drop legacy indexes/columns where they still exist
                    for statement in [
                        "ALTER TABLE admin_logs DROP INDEX idx_admin_name",
                        "ALTER TABLE admin_logs DROP INDEX idx_action",
                    ]:
                        try:
                            await cursor.execute(statement)
                        except Exception:
                            pass

                    for statement in [
                        "ALTER TABLE admin_logs DROP COLUMN admin_name",
                        "ALTER TABLE admin_logs DROP COLUMN admin_role",
                        "ALTER TABLE admin_logs DROP COLUMN ip_address",
                    ]:
                        try:
                            await cursor.execute(statement)
                        except Exception:
                            pass

                    # Create compact-schema indexes if missing
                    for statement in [
                        "ALTER TABLE admin_logs ADD INDEX idx_created_at (created_at)",
                        "ALTER TABLE admin_logs ADD INDEX idx_action_created (action, created_at)",
                        "ALTER TABLE admin_logs ADD INDEX idx_actor_created (actor_name, created_at)",
                        "ALTER TABLE admin_logs ADD INDEX idx_target_created (target_type, target_id, created_at)",
                    ]:
                        try:
                            await cursor.execute(statement)
                        except Exception:
                            pass

                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS punishment_returns (
                            id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            punishment_type ENUM('jail', 'mute') NOT NULL,
                            `static` INT UNSIGNED NOT NULL,
                            server TINYINT UNSIGNED NOT NULL,
                            duration INT UNSIGNED NOT NULL,
                            remove_reason ENUM('На стрим', 'На видео') NOT NULL,
                            discord_message_url VARCHAR(512) NULL,
                            removed_by_id BIGINT UNSIGNED NOT NULL,
                            removed_by_name VARCHAR(255) NOT NULL,
                            removed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            claimed_by_id BIGINT UNSIGNED NULL,
                            claimed_by_name VARCHAR(255) NULL,
                            claimed_at TIMESTAMP NULL,
                            completed_by_id BIGINT UNSIGNED NULL,
                            completed_by_name VARCHAR(255) NULL,
                            completed_at TIMESTAMP NULL,
                            status ENUM('pending', 'claimed', 'completed') NOT NULL DEFAULT 'pending',
                            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            INDEX idx_returns_queue (status, removed_at),
                            INDEX idx_returns_history (completed_at),
                            INDEX idx_returns_static (`static`),
                            INDEX idx_returns_server (server)
                        )
                        """
                    )

                    for statement in [
                        "ALTER TABLE punishment_returns MODIFY COLUMN discord_message_url VARCHAR(512) NULL",
                    ]:
                        try:
                            await cursor.execute(statement)
                        except Exception:
                            pass

                    # High+medium indexes
                    for statement in [
                        "ALTER TABLE spec_sessions ADD INDEX idx_target_active (target_type, target_id, ended_at, deleted_at)",
                        "ALTER TABLE spec_sessions ADD INDEX idx_pr_active (pr_id, ended_at, deleted_at)",
                        "ALTER TABLE events ADD INDEX idx_events_active_order (is_active, is_pinned, priority, start_time)",
                        "ALTER TABLE events ADD INDEX idx_events_kind_status_active (event_kind, approval_status, is_active)",
                        "ALTER TABLE events ADD INDEX idx_events_requested_by_active (requested_by, is_active)",
                        "ALTER TABLE streamers ADD INDEX idx_streamers_online_order (is_online, is_pinned, priority, streamer_name)",
                    ]:
                        try:
                            await cursor.execute(statement)
                        except Exception:
                            pass

                    # =========================================================
                    # Deterministic backfill for automatic points component
                    # (must run AFTER events table + migrations exist)
                    # =========================================================
                    # - each session stores its factual credited_points;
                    # - assistants.auto_points_total mirrors sum of credited sessions.
                    # Note: must account for spec_request events that are not yet approved.
                    await cursor.execute(
                        """
                        UPDATE spec_sessions ss
                        LEFT JOIN events e ON ss.target_type = 'event' AND ss.target_id = e.id
                        SET ss.credited_points = ROUND(
                            CASE
                                WHEN ss.ended_at IS NULL OR ss.deleted_at IS NOT NULL THEN 0
                                WHEN e.event_kind = 'spec_request' AND e.approval_status != 'approved' THEN 0
                                ELSE (COALESCE(ss.duration_seconds, 0) / 3600.0) * COALESCE(ss.applied_hourly_rate, 0)
                            END,
                            4
                        )
                        """
                    )
                    await cursor.execute(
                        """
                        UPDATE assistants a
                        LEFT JOIN (
                            SELECT pr_id, ROUND(COALESCE(SUM(credited_points), 0), 4) AS computed_auto_points
                            FROM spec_sessions
                            WHERE deleted_at IS NULL
                            GROUP BY pr_id
                        ) s ON s.pr_id = a.pr_id
                        SET a.auto_points_total = COALESCE(s.computed_auto_points, 0)
                        """
                    )

                    # =========================================================
                    # VIEWS (Requires multiple tables)
                    # =========================================================
                    # Day-Slicing View (Recursive CTE)
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
                            LEFT JOIN events e
                              ON ss.target_type = 'event' AND e.id = ss.target_id
                            WHERE ss.ended_at IS NOT NULL
                              AND ss.deleted_at IS NULL
                              AND (ss.target_type <> 'event' OR e.approval_status = 'approved')
                            
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

                    # Aggregated Daily Stats View
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

                    await cursor.execute("SET sql_notes = 1")
                    await conn.commit()

                    await self._init_default_permissions(conn)
                    await self._init_default_service_principals(conn)
                    await self._ensure_singleton_settings(conn)

                    self.logger.info("Database initialized successfully (V2 Final)")
        except Exception as e:
            self.logger.error(f"Failed to initialize database: {e}", exc_info=True)
            raise

    async def _migrate_web_auth_pk_to_discord_id(self, cursor) -> None:
        """
        Guarded migration for legacy web_auth(id PK) -> web_auth(discord_id PK).

        The sequence is intentionally fail-fast to avoid partial boot with broken auth.
        """
        if not await self._table_exists(cursor, "web_auth"):
            return

        has_id = await self._column_exists(cursor, "web_auth", "id")
        has_discord_id = await self._column_exists(cursor, "web_auth", "discord_id")
        if not has_discord_id:
            raise RuntimeError(
                "web_auth migration precondition failed: column 'discord_id' is missing. "
                "Manual intervention required."
            )

        # Always normalize dependent column types for modern IDs.
        await cursor.execute("ALTER TABLE sessions MODIFY COLUMN user_id BIGINT UNSIGNED NOT NULL")
        await cursor.execute("ALTER TABLE auth_logs MODIFY COLUMN user_id BIGINT UNSIGNED")

        if not has_id:
            return

        await cursor.execute("SELECT COUNT(*) AS cnt FROM web_auth WHERE discord_id IS NULL")
        row = await cursor.fetchone() or {}
        if int(row.get("cnt", 0)) > 0:
            raise RuntimeError(
                "web_auth migration precondition failed: NULL discord_id found. "
                "Manual intervention required."
            )

        await cursor.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM (
                SELECT discord_id
                FROM web_auth
                GROUP BY discord_id
                HAVING COUNT(*) > 1
            ) AS dup
            """
        )
        dup_row = await cursor.fetchone() or {}
        if int(dup_row.get("cnt", 0)) > 0:
            raise RuntimeError(
                "web_auth migration precondition failed: duplicate discord_id values detected. "
                "Manual intervention required."
            )

        self.logger.info("Starting guarded web_auth PK migration (id -> discord_id)...")

        # Rewrite FK-like references before dropping legacy key.
        await cursor.execute(
            "UPDATE sessions s JOIN web_auth w ON s.user_id = w.id SET s.user_id = w.discord_id"
        )
        await cursor.execute(
            "UPDATE auth_logs l JOIN web_auth w ON l.user_id = w.id SET l.user_id = w.discord_id"
        )

        pk_cols = await self._get_primary_key_columns(cursor, "web_auth")
        if pk_cols not in ([], ["id"], ["discord_id"]):
            raise RuntimeError(
                f"web_auth migration precondition failed: unexpected PK shape {pk_cols}. "
                "Manual intervention required."
            )

        if await self._column_is_auto_increment(cursor, "web_auth", "id"):
            if not await self._index_exists(cursor, "web_auth", "uq_web_auth_id_tmp"):
                await cursor.execute(
                    "ALTER TABLE web_auth ADD UNIQUE INDEX uq_web_auth_id_tmp (id)"
                )

        if pk_cols == ["id"]:
            await cursor.execute("ALTER TABLE web_auth DROP PRIMARY KEY")
            await cursor.execute("ALTER TABLE web_auth ADD PRIMARY KEY (discord_id)")
        elif pk_cols == []:
            await cursor.execute("ALTER TABLE web_auth ADD PRIMARY KEY (discord_id)")

        if await self._column_is_auto_increment(cursor, "web_auth", "id"):
            await cursor.execute("ALTER TABLE web_auth MODIFY COLUMN id INT UNSIGNED NOT NULL")

        if await self._index_exists(cursor, "web_auth", "uq_web_auth_id_tmp"):
            await cursor.execute("ALTER TABLE web_auth DROP INDEX uq_web_auth_id_tmp")

        await cursor.execute("ALTER TABLE web_auth DROP COLUMN id")
        self.logger.info("Migrated web_auth PK successfully.")

    @staticmethod
    def _plan_service_principal_token_hash_dedup(
        rows: list[Dict[str, Any]],
        configured_names: set[str],
    ) -> tuple[list[dict[str, str]], int]:
        """
        Build deterministic dedup updates for conflicting service_principals.token_hash rows.

        For each duplicate token_hash group:
        - keeper priority: configured service name, otherwise lexicographically smallest name
        - all non-keepers are moved to a unique legacy shadow hash and should be deactivated
        """
        grouped: dict[str, list[dict[str, str]]] = {}
        used_hashes: set[str] = set()

        for raw in rows or []:
            token_hash = str(raw.get("token_hash") or "").strip()
            name = str(raw.get("name") or "").strip()
            if not token_hash or not name:
                continue
            used_hashes.add(token_hash)
            grouped.setdefault(token_hash, []).append({"name": name, "token_hash": token_hash})

        updates: list[dict[str, str]] = []
        conflict_groups = 0
        for token_hash in sorted(grouped.keys()):
            group = grouped[token_hash]
            if len(group) <= 1:
                continue

            conflict_groups += 1
            configured_candidates = sorted(
                row["name"] for row in group if row["name"] in configured_names
            )
            keeper_name = (
                configured_candidates[0]
                if configured_candidates
                else min(row["name"] for row in group)
            )

            attempt = 1
            for row in sorted(group, key=lambda item: item["name"]):
                if row["name"] == keeper_name:
                    continue

                shadow_hash = hashlib.sha256(
                    f"legacy:{token_hash}:{row['name']}:{attempt}".encode("utf-8")
                ).hexdigest()
                while shadow_hash in used_hashes:
                    attempt += 1
                    shadow_hash = hashlib.sha256(
                        f"legacy:{token_hash}:{row['name']}:{attempt}".encode("utf-8")
                    ).hexdigest()

                used_hashes.add(shadow_hash)
                updates.append(
                    {
                        "name": row["name"],
                        "new_hash": shadow_hash,
                        "old_hash": token_hash,
                    }
                )
                attempt += 1

        return updates, conflict_groups

    async def _migrate_service_principals_hash_only(self, cursor) -> None:
        """
        Guarded migration for service_principals to hash-only token storage.

        Runtime contract:
        - lookup by token_hash only
        - no plaintext token column in active schema
        """
        if not await self._table_exists(cursor, "service_principals"):
            return

        has_legacy_token = await self._column_exists(
            cursor, "service_principals", "token"
        )
        has_token_hash = await self._column_exists(
            cursor, "service_principals", "token_hash"
        )

        if not has_token_hash:
            try:
                await cursor.execute(
                    "ALTER TABLE service_principals ADD COLUMN token_hash VARCHAR(64) NULL"
                )
            except Exception as exc:
                # Race/idempotency-safe behavior:
                # if DB reports duplicate column, verify actual presence and continue.
                err_code = exc.args[0] if getattr(exc, "args", None) else None
                if err_code != 1060 or not await self._column_exists(
                    cursor, "service_principals", "token_hash"
                ):
                    raise RuntimeError(
                        "service_principals migration failed: cannot add token_hash column."
                    ) from exc

            has_token_hash = await self._column_exists(
                cursor, "service_principals", "token_hash"
            )
            has_legacy_token = await self._column_exists(
                cursor, "service_principals", "token"
            )
            if not has_token_hash:
                raise RuntimeError(
                    "service_principals migration failed: token_hash column not present after ALTER."
                )

        if has_legacy_token:
            await cursor.execute(
                """
                UPDATE service_principals
                SET token_hash = SHA2(token, 256)
                WHERE (token_hash IS NULL OR token_hash = '')
                  AND token IS NOT NULL
                  AND token != ''
                """
            )

        await cursor.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM service_principals
            WHERE is_active = 1
              AND (token_hash IS NULL OR token_hash = '')
            """
        )
        active_missing_row = await cursor.fetchone() or {}
        active_missing = int(active_missing_row.get("cnt", 0))
        if active_missing > 0:
            raise RuntimeError(
                "service_principals migration failed: active principals without token_hash found. "
                "Manual intervention required."
            )

        await cursor.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM service_principals
            WHERE token_hash IS NULL OR token_hash = ''
            """
        )
        total_missing_row = await cursor.fetchone() or {}
        total_missing = int(total_missing_row.get("cnt", 0))
        if total_missing > 0:
            raise RuntimeError(
                "service_principals migration failed: rows without token_hash remain. "
                "Manual intervention required."
            )

        # Deduplicate legacy token hashes before adding/validating unique constraint.
        configured_names = set(Config.service_token_map.keys())
        await cursor.execute(
            """
            SELECT name, token_hash, is_active
            FROM service_principals
            WHERE token_hash IS NOT NULL
              AND token_hash != ''
            """
        )
        hash_rows = await cursor.fetchall() or []
        dedup_updates, conflict_groups = self._plan_service_principal_token_hash_dedup(
            hash_rows,
            configured_names,
        )
        if dedup_updates:
            for item in dedup_updates:
                await cursor.execute(
                    """
                    UPDATE service_principals
                    SET token_hash = %s, is_active = 0
                    WHERE name = %s
                    """,
                    (item["new_hash"], item["name"]),
                )
            shadowed_names = ", ".join(sorted(item["name"] for item in dedup_updates))
            self.logger.warning(
                "service_principals dedup remediated %s legacy rows across %s conflict groups; "
                "shadowed names: %s",
                len(dedup_updates),
                conflict_groups,
                shadowed_names,
            )
        else:
            self.logger.info(
                "service_principals dedup found no token_hash conflicts (groups=%s).",
                conflict_groups,
            )

        await cursor.execute(
            """
            SELECT token_hash, COUNT(*) AS cnt
            FROM service_principals
            WHERE token_hash IS NOT NULL
              AND token_hash != ''
            GROUP BY token_hash
            HAVING COUNT(*) > 1
            """
        )
        duplicates_after_dedup = await cursor.fetchall() or []
        if duplicates_after_dedup:
            self.logger.error(
                "service_principals dedup conflicts remaining: %s",
                len(duplicates_after_dedup),
            )
            raise RuntimeError(
                "service_principals migration failed: token_hash duplicates remain; "
                "manual intervention required."
            )
        self.logger.info("service_principals dedup conflicts remaining: 0")

        await cursor.execute(
            "ALTER TABLE service_principals MODIFY COLUMN token_hash VARCHAR(64) NOT NULL"
        )

        await cursor.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM information_schema.statistics
            WHERE table_schema = DATABASE()
              AND table_name = 'service_principals'
              AND column_name = 'token_hash'
              AND non_unique = 0
            """
        )
        uniq_row = await cursor.fetchone() or {}
        if int(uniq_row.get("cnt", 0)) == 0:
            await cursor.execute(
                "ALTER TABLE service_principals ADD UNIQUE INDEX uq_service_token_hash (token_hash)"
            )

        if has_legacy_token:
            await cursor.execute(
                "UPDATE service_principals SET token = NULL WHERE token IS NOT NULL"
            )
            await cursor.execute("ALTER TABLE service_principals DROP COLUMN token")

    async def _init_default_permissions(self, conn):
        """Initialize default role permissions without clobbering custom overrides."""
        async with conn.cursor() as cursor:
            catalog = {
                "dashboard.view",
                "streamers.view",
                "streamers.create",
                "streamers.update",
                "streamers.delete",
                "streamers.status.update",
                "spec.view_claimable",
                "spec.view_self_sessions",
                "spec.claim.main",
                "spec.claim.probation",
                "spec.unclaim.self",
                "spec.unclaim.any",
                "events.view",
                "events.create",
                "events.update",
                "events.manage",
                "events.spec.request",
                "events.spec.manage",
                "events.join.self",
                "events.leave.self",
                "events.leave.any",
                "assistants.view",
                "assistants.create",
                "assistants.update",
                "assistants.delete",
                "assistants.logs.view",
                "assistants.sessions.view",
                "assistants.sessions.manage",
                "assistants.points.manage",
                "assistants.sanctions.manage",
                "assistants.warnings.manage",
                "admin.users.create",
                "logs.pr_actions.view",
                "logs.admin.view",
                "returns.view",
                "returns.create",
                "returns.execute",
                "returns.history.view",
                "returns.manage.self",
                "returns.manage.any",
                "guild.view",
                "guild.settings.view",
                "guild.settings.update",
                "guild.templates.view",
                "guild.templates.update",
                "guild.rates.view",
                "guild.rates.update",
                "monitoring.view",
                "monitoring.refresh",
                "notifications.render",
            }

            # Base permissions for all staff roles
            base_staff_perms = {
                "dashboard.view": True,
                "streamers.view": True,
                "spec.view_self_sessions": True,
                "spec.view_claimable": True,
                "spec.claim.main": True,
                "spec.unclaim.self": True,
                "events.view": True,
                "events.join.self": True,
                "events.leave.self": True,
                "events.spec.request": True,
                "assistants.view": True,
                "logs.pr_actions.view": True,
                "returns.view": True,
                "returns.create": True,
                "returns.execute": True,
                "returns.history.view": True,
                "returns.manage.self": True,
            }

            # Junior Employee (base + probation claim)
            junior_employee_perms = {
                **base_staff_perms,
                "spec.claim.probation": True,
            }

            employee_perms = {**base_staff_perms}

            # Senior level (employee + event creation)
            senior_perms = {
                **employee_perms,
                "events.create": True,
            }

            # Manager level (business admin, no technical monitoring controls)
            manager_perms = {
                **senior_perms,
                "admin.users.create": True,
                "streamers.create": True,
                "streamers.update": True,
                "streamers.delete": True,
                "assistants.create": True,
                "assistants.update": True,
                "assistants.delete": True,
                "assistants.logs.view": True,
                "assistants.sessions.view": True,
                "assistants.sessions.manage": True,
                "assistants.points.manage": True,
                "assistants.sanctions.manage": True,
                "assistants.warnings.manage": True,
                "events.update": True,
                "events.manage": True,
                "events.spec.manage": True,
                "events.leave.any": True,
                "spec.unclaim.any": True,
                "logs.admin.view": True,
                "returns.manage.any": True,
                "guild.view": True,
                "guild.settings.view": True,
                "guild.settings.update": True,
                "guild.templates.view": True,
                "guild.templates.update": True,
                "guild.rates.view": True,
                "guild.rates.update": True,
            }

            # Developer (technical controls + status sync rights)
            developer_perms = {
                **manager_perms,
                "notifications.render": True,
                "monitoring.view": True,
                "monitoring.refresh": True,
                "streamers.status.update": True,
            }

            default_permissions = {
                "junior_employee": junior_employee_perms,
                "employee": employee_perms,
                "senior_employee": senior_perms,
                "manager": manager_perms,
                "developer": developer_perms,
            }

            for role, permissions in default_permissions.items():
                filtered_defaults = {
                    key: bool(value)
                    for key, value in permissions.items()
                    if key in catalog and value is True
                }

                await cursor.execute(
                    "SELECT permissions FROM role_permissions WHERE role = %s",
                    (role,),
                )
                row = await cursor.fetchone()

                existing_permissions: dict[str, bool] = {}
                if row and row.get("permissions"):
                    raw = row["permissions"]
                    if isinstance(raw, str):
                        try:
                            existing_permissions = json.loads(raw)
                        except json.JSONDecodeError:
                            existing_permissions = {}
                    elif isinstance(raw, dict):
                        existing_permissions = raw

                # Reconcile:
                # - keep custom toggles for known catalog keys,
                # - drop orphaned keys,
                # - add any missing defaults.
                reconciled: dict[str, bool] = {}
                for key, value in existing_permissions.items():
                    if key in catalog:
                        reconciled[key] = bool(value)
                for key, value in filtered_defaults.items():
                    if key not in reconciled:
                        reconciled[key] = bool(value)

                await cursor.execute(
                    """
                    INSERT INTO role_permissions (role, permissions)
                    VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE permissions = %s
                    """,
                    (
                        role,
                        json.dumps(reconciled),
                        json.dumps(reconciled),
                    ),
                )
            await conn.commit()
            self.logger.debug("  ✓ Default permissions reconciled")

    @staticmethod
    def _get_default_service_permissions(service_name: str) -> dict[str, bool]:
        """Default least-privilege permissions for built-in service principals."""
        name = service_name.lower()
        discord_scope = {
            "streamers.view": True,
            "streamers.create": True,
            "streamers.update": True,
            "streamers.delete": True,
            "spec.view_claimable": True,
            "spec.view_self_sessions": True,
            "spec.claim.main": True,
            "spec.claim.probation": True,
            "spec.unclaim.any": True,
            "assistants.view": True,
            "assistants.logs.view": True,
            "assistants.sessions.view": True,
            "assistants.sessions.manage": True,
            "events.view": True,
            "events.create": True,
            "events.manage": True,
            "events.join.self": True,
            "events.leave.any": True,
            "events.spec.manage": True,
            "guild.view": True,
            "guild.settings.update": True,
            "guild.templates.view": True,
            "guild.templates.update": True,
            "guild.rates.update": True,
            "monitoring.view": True,
            "monitoring.refresh": True,
            "notifications.render": True,
            "dashboard.view": True,
        }
        twitch_scope = {
            "streamers.view": True,
            "streamers.create": True,
            "streamers.status.update": True,
            "spec.unclaim.any": True,
            "monitoring.refresh": True,
        }
        if "discord" in name:
            return discord_scope
        if "twitch" in name:
            return twitch_scope
        # Deny by default for unknown service principals.
        return {}

    @staticmethod
    def _configured_service_tokens() -> list[tuple[str, str]]:
        """
        Parse configured service tokens into named tuples: (name, token).

        Config contract is strict and validated at startup.
        """
        return list(Config.service_token_map.items())

    @staticmethod
    def _hash_service_token(token: str) -> str:
        """Hash service bearer token for lookup/storage."""
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    async def _init_default_service_principals(self, conn):
        """Initialize or reconcile service principal scopes for configured tokens."""
        configured = self._configured_service_tokens()
        if not configured:
            return

        async with conn.cursor() as cursor:
            has_token_hash = await self._column_exists(
                cursor, "service_principals", "token_hash"
            )
            if not has_token_hash:
                # Guard against metadata/introspection false-negatives:
                # run migration path once more, then re-check deterministically.
                await self._migrate_service_principals_hash_only(cursor)
                has_token_hash = await self._column_exists(
                    cursor, "service_principals", "token_hash"
                )
            if not has_token_hash:
                raise RuntimeError(
                    "service_principals.token_hash is missing after migrations; "
                    "startup aborted to prevent broken service auth."
                )

            for service_name, token in configured:
                defaults = self._get_default_service_permissions(service_name)
                normalized_token = (token or "").strip()
                if not normalized_token:
                    continue
                token_hash = self._hash_service_token(normalized_token)

                await cursor.execute(
                    """
                    SELECT permissions, is_active
                    FROM service_principals
                    WHERE name = %s
                    LIMIT 1
                    """,
                    (service_name,),
                )
                row = await cursor.fetchone()

                existing_permissions: dict[str, bool] = {}
                # Configured service tokens are authoritative and must stay active.
                is_active = True
                if row:
                    raw_permissions = row.get("permissions")
                    if isinstance(raw_permissions, str):
                        try:
                            existing_permissions = json.loads(raw_permissions)
                        except json.JSONDecodeError:
                            existing_permissions = {}
                    elif isinstance(raw_permissions, dict):
                        existing_permissions = raw_permissions

                reconciled = dict(existing_permissions)
                for key, value in defaults.items():
                    if key not in reconciled:
                        reconciled[key] = bool(value)

                await cursor.execute(
                    """
                    INSERT INTO service_principals (name, token_hash, permissions, is_active)
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        name = %s,
                        token_hash = %s,
                        permissions = %s,
                        is_active = %s
                    """,
                    (
                        service_name,
                        token_hash,
                        json.dumps(reconciled),
                        is_active,
                        service_name,
                        token_hash,
                        json.dumps(reconciled),
                        is_active,
                    ),
                )

            await conn.commit()
            self.logger.debug("  ✓ Service principals reconciled")

    async def _ensure_singleton_settings(self, conn):
        """Ensure settings table has exactly one row."""
        async with conn.cursor() as cursor:

            await cursor.execute("SELECT COUNT(*) as count FROM settings")

            result = await cursor.fetchone()
            row_count = int(result["count"])

            if row_count == 0:
                self.logger.debug(
                    "  ℹ No settings row found, will be created on first update"
                )
            elif row_count > 1 :
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
                return {}

    async def get_service_principal_by_token(self, token: str) -> Optional[dict]:
        """Get active service principal by bearer token."""
        normalized_token = (token or "").strip()
        if not normalized_token:
            return None
        token_hash = self._hash_service_token(normalized_token)
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                try:
                    await cursor.execute(
                        """
                        SELECT name, permissions, is_active
                        FROM service_principals
                        WHERE token_hash = %s
                        LIMIT 1
                        """,
                        (token_hash,),
                    )
                    row = await cursor.fetchone()
                except Exception as e:
                    self.logger.error(
                        f"Service principal lookup failed (hash-only path): {e}",
                        exc_info=True,
                    )
                    return None
                if not row or not row.get("is_active", True):
                    return None

                raw_permissions = row.get("permissions") or {}
                permissions: dict[str, bool]
                if isinstance(raw_permissions, str):
                    try:
                        permissions = json.loads(raw_permissions)
                    except json.JSONDecodeError:
                        permissions = {}
                elif isinstance(raw_permissions, dict):
                    permissions = raw_permissions
                else:
                    permissions = {}

                return {
                    "principal_type": "service",
                    "service_name": row.get("name"),
                    "permissions": permissions,
                }

    @db_retry()
    async def log_admin_action_v2(
        self,
        actor_name: str,
        action: str,
        actor_role: Optional[str] = None,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> None:
        """Write compact universal admin log event."""
        event_details = details or {}
        if not isinstance(event_details, dict):
            event_details = {"payload": {"value": event_details}}

        if "summary" not in event_details:
            event_details["summary"] = action

        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO admin_logs
                            (actor_name, actor_role, action, target_type, target_id, details)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            actor_name,
                            actor_role,
                            action,
                            target_type,
                            target_id,
                            json.dumps(event_details, default=str),
                        ),
                    )
                    await conn.commit()
        except Exception as e:
            self.logger.error(f"Failed to log admin action: {e}", exc_info=True)

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
        """Backward-compatible wrapper to v2 admin logs."""
        payload = details.copy() if isinstance(details, dict) else {}
        meta = payload.get("meta", {})
        if ip_address:
            meta["ip"] = ip_address
        if meta:
            payload["meta"] = meta
        await self.log_admin_action_v2(
            actor_name=admin_name,
            actor_role=admin_role,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=payload,
        )

    @staticmethod
    def _action_matches_kind(action: str, kind: str) -> bool:
        if kind == "other":
            return "." not in action
        prefix = Database._kind_to_action_prefix(kind)
        if not prefix:
            return False
        return action.startswith(prefix)

    @staticmethod
    def _kind_to_action_prefix(kind: str) -> Optional[str]:
        prefix_map = {
            "user": "user.",
            "streamer": "streamer.",
            "event": "event.",
            "assistant": "assistant.",
            "system": "system.",
            "rbac": "rbac.",
            "spec": "spec.",
            "guild": "guild.",
            "return": "return.",
        }
        return prefix_map.get(kind)

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
                "created_at": "al.created_at",
                "actor_name": "al.actor_name",
                "admin_name": "al.actor_name",
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

            actor_name = filters.get("actor_name") or filters.get("admin_name")
            if actor_name:
                where_clauses.append("al.actor_name LIKE %s")
                params.append(f"%{actor_name}%")

            if filters.get("target_type") and filters["target_type"] != "all":
                where_clauses.append("al.target_type = %s")
                params.append(filters["target_type"])

            if filters.get("start_date"):
                where_clauses.append("al.created_at >= %s")
                params.append(filters["start_date"])

            if filters.get("end_date"):
                where_clauses.append("al.created_at <= %s")
                params.append(filters["end_date"])

            kind = filters.get("kind")
            if kind:
                if kind == "other":
                    where_clauses.append("al.action NOT LIKE %s")
                    params.append("%.%")
                else:
                    prefix = self._kind_to_action_prefix(kind)
                    if not prefix:
                        return []
                    where_clauses.append("al.action LIKE %s")
                    params.append(f"{prefix}%")

            where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

            params.append(limit)
            params.append(offset)

            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    sql_query = f"""
                        SELECT 
                            al.id,
                            al.actor_name,
                            al.actor_role,
                            al.action,
                            al.target_type,
                            al.target_id,
                            al.details,
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
                        log_dict["kind"] = (
                            log_dict["action"].split(".", 1)[0]
                            if "." in log_dict["action"]
                            else "other"
                        )
                        if log_dict.get("details"):
                            try:
                                if isinstance(log_dict["details"], str):
                                    log_dict["details"] = json.loads(
                                        log_dict["details"]
                                    )
                            except (json.JSONDecodeError, TypeError):
                                pass
                        log_dict["admin_name"] = log_dict.get("actor_name")
                        log_dict["admin_role"] = log_dict.get("actor_role")
                        result.append(log_dict)

                    return result
        except Exception as e:
            self.logger.error(f"Failed to fetch admin logs: {e}", exc_info=True)
            return []

    @db_retry()
    async def count_admin_logs(self, filters: dict = None) -> int:
        """Count admin logs matching the given filters."""
        try:
            filters = filters or {}
            where_clauses = []
            params = []

            if filters.get("action"):
                actions = filters["action"]
                if isinstance(actions, list) and len(actions) > 0:
                    placeholders = ", ".join(["%s"] * len(actions))
                    where_clauses.append(f"al.action IN ({placeholders})")
                    params.extend(actions)
                elif isinstance(actions, str) and actions != "all":
                    where_clauses.append("al.action = %s")
                    params.append(actions)

            actor_name = filters.get("actor_name") or filters.get("admin_name")
            if actor_name:
                where_clauses.append("al.actor_name LIKE %s")
                params.append(f"%{actor_name}%")

            if filters.get("target_type") and filters["target_type"] != "all":
                where_clauses.append("al.target_type = %s")
                params.append(filters["target_type"])

            if filters.get("start_date"):
                where_clauses.append("al.created_at >= %s")
                params.append(filters["start_date"])

            if filters.get("end_date"):
                where_clauses.append("al.created_at <= %s")
                params.append(filters["end_date"])

            kind = filters.get("kind")
            if kind:
                if kind == "other":
                    where_clauses.append("al.action NOT LIKE %s")
                    params.append("%.%")
                else:
                    prefix = self._kind_to_action_prefix(kind)
                    if not prefix:
                        return 0
                    where_clauses.append("al.action LIKE %s")
                    params.append(f"{prefix}%")

            where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        f"SELECT COUNT(*) as total FROM admin_logs al {where_sql}",
                        tuple(params),
                    )
                    row = await cursor.fetchone()
                    return row["total"] if row else 0
        except Exception as e:
            self.logger.error(f"Failed to count admin logs: {e}", exc_info=True)
            return 0

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
        allow_juniors: bool = True,
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
                            allow_juniors, added_at, added_by_id, stream_game_id, stream_game_name, stream_title, 
                            stream_thumbnail_url, profile_image_url
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, %s, %s, %s, %s, %s, %s) AS new_data
                        ON DUPLICATE KEY UPDATE 
                            streamer_name = new_data.streamer_name,
                            is_online = new_data.is_online,
                            stream_started_at = new_data.stream_started_at,
                            priority = new_data.priority,
                            pr_slots = new_data.pr_slots,
                            allow_juniors = new_data.allow_juniors,
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
                            allow_juniors,
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
                            streamer_id, streamer_name, is_online, is_pinned,
                            allow_juniors,
                            stream_title, stream_thumbnail_url,
                            profile_image_url,
                            stream_game_id as game_id, stream_game_name as game_name, stream_started_at as started_at,
                            priority, pr_slots, priority_override, pr_slots_override,
                            added_at, added_by_id, updated_at
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

                    if is_online is False:
                        set_parts.append("is_pinned = FALSE")
                        set_parts.append("priority_override = NULL")
                        set_parts.append("pr_slots_override = NULL")

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

                        # Reset overrides when streamer goes offline (same as update_streamer_status)
                        if not update.get("is_online", False):
                            set_parts.append("is_pinned = FALSE")
                            set_parts.append("priority_override = NULL")
                            set_parts.append("pr_slots_override = NULL")

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
        allow_juniors: Optional[bool] = None,
        priority_override: Optional[int] = None,
        pr_slots_override: Optional[int] = None,
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

            if allow_juniors is not None:
                set_parts.append("allow_juniors = %s")
                params.append(allow_juniors)

            if priority_override is not None:
                set_parts.append("priority_override = %s")
                params.append(priority_override)

            if pr_slots_override is not None:
                set_parts.append("pr_slots_override = %s")
                params.append(pr_slots_override)

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
    async def retroactive_update_active_sessions(
        self,
        streamer_id: int,
        new_priority_override: Optional[int],
    ) -> int:
        """Retroactively update active sessions on a streamer when priority_override changes.

        If new_priority_override is set, all active non-probation sessions get
        priority_override = new value and rate_override = matching rate from settings.
        If new_priority_override is None/cleared, session overrides are cleared too.

        Returns number of sessions updated.
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Find all active sessions on this streamer
                    await cursor.execute(
                        """
                        SELECT id, is_probation
                        FROM spec_sessions
                        WHERE target_type = 'streamer'
                          AND target_id = %s
                          AND ended_at IS NULL
                          AND deleted_at IS NULL
                        """,
                        (streamer_id,),
                    )
                    active_sessions = await cursor.fetchall()

                    if not active_sessions:
                        return 0

                    if new_priority_override is not None:
                        config = await self.get_points_config()
                        probation_rate = await self._get_probation_rate()

                        for session in active_sessions:
                            is_probation = session.get("is_probation", False)
                            if is_probation:
                                # Probation sessions keep their own rate
                                continue
                            new_rate = config.get(new_priority_override, 0.5)
                            await cursor.execute(
                                """
                                UPDATE spec_sessions
                                SET priority_override = %s, rate_override = %s
                                WHERE id = %s
                                """,
                                (new_priority_override, new_rate, session["id"]),
                            )
                    else:
                        # Clear overrides from all active sessions
                        session_ids = [s["id"] for s in active_sessions if not s.get("is_probation")]
                        if session_ids:
                            placeholders = ", ".join(["%s"] * len(session_ids))
                            await cursor.execute(
                                f"""
                                UPDATE spec_sessions
                                SET priority_override = NULL, rate_override = NULL
                                WHERE id IN ({placeholders})
                                """,
                                tuple(session_ids),
                            )

                    await conn.commit()

                    updated = sum(1 for s in active_sessions if not s.get("is_probation"))
                    self.logger.info(
                        f"Retroactive update: {updated} sessions on streamer {streamer_id} "
                        f"updated with priority_override={new_priority_override}"
                    )
                    return updated
        except Exception as e:
            self.logger.error(
                f"Failed retroactive update for streamer {streamer_id}: {e}",
                exc_info=True,
            )
            return 0

    @db_retry()
    async def recalc_target_active_sessions(
        self,
        target_type: str,
        target_id: int,
    ) -> int:
        """Recalculate priority_auto, rate_auto, priority_override, rate_override
        for ALL active sessions on a given target (streamer or event).

        Reads the current priority state from the target entity (streamers or events),
        calculates the matching rates from settings, and updates all non-probation
        active sessions.

        Returns number of sessions updated.
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    # 1. Read the current priority state of the target
                    if target_type == "streamer":
                        await cursor.execute(
                            "SELECT priority, priority_override FROM streamers WHERE streamer_id = %s",
                            (target_id,),
                        )
                    elif target_type == "event":
                        await cursor.execute(
                            "SELECT priority, NULL AS priority_override FROM events WHERE id = %s",
                            (target_id,),
                        )
                    else:
                        return 0

                    target_row = await cursor.fetchone()
                    if not target_row:
                        return 0

                    new_priority_auto = int(target_row.get("priority") or 0)
                    new_priority_override = target_row.get("priority_override")

                    # 2. Find all active sessions on this target
                    await cursor.execute(
                        """
                        SELECT id, is_probation
                        FROM spec_sessions
                        WHERE target_type = %s
                          AND target_id = %s
                          AND ended_at IS NULL
                          AND deleted_at IS NULL
                        """,
                        (target_type, target_id),
                    )
                    active_sessions = await cursor.fetchall()

                    if not active_sessions:
                        return 0

                    # 3. Read rates from settings
                    config = await self.get_points_config()
                    probation_rate = await self._get_probation_rate()

                    new_rate_auto = config.get(new_priority_auto, 0.5)

                    updated = 0
                    for session in active_sessions:
                        if session.get("is_probation"):
                            # Probation sessions keep their own rate
                            continue

                        if new_priority_override is not None:
                            new_rate_override = config.get(int(new_priority_override), 0.5)
                            await cursor.execute(
                                """
                                UPDATE spec_sessions
                                SET priority_auto = %s, rate_auto = %s,
                                    priority_override = %s, rate_override = %s
                                WHERE id = %s
                                """,
                                (
                                    new_priority_auto,
                                    new_rate_auto,
                                    int(new_priority_override),
                                    new_rate_override,
                                    session["id"],
                                ),
                            )
                        else:
                            await cursor.execute(
                                """
                                UPDATE spec_sessions
                                SET priority_auto = %s, rate_auto = %s,
                                    priority_override = NULL, rate_override = NULL
                                WHERE id = %s
                                """,
                                (new_priority_auto, new_rate_auto, session["id"]),
                            )
                        updated += 1

                    await conn.commit()

                    self.logger.info(
                        f"Recalc target sessions: {updated} sessions on "
                        f"{target_type}:{target_id} updated "
                        f"(priority_auto={new_priority_auto}, priority_override={new_priority_override})"
                    )
                    return updated
        except Exception as e:
            self.logger.error(
                f"Failed recalc_target_active_sessions for {target_type}:{target_id}: {e}",
                exc_info=True,
            )
            return 0

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
        Returns basic streamer data without assignments (for "All Media" tab).
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT 
                            s.streamer_id, s.streamer_name, s.is_online, s.stream_title, s.stream_thumbnail_url,
                            s.is_pinned, s.allow_juniors, s.profile_image_url,
                            s.stream_game_id as game_id, s.stream_game_name as game_name, s.stream_started_at as started_at,
                            s.priority, s.pr_slots, s.priority_override, s.pr_slots_override,
                            s.added_at, s.added_by_id, s.updated_at
                        FROM streamers s
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
        Получение списка всех онлайн стримеров с агрегированными назначениями.
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT 
                            s.streamer_id, s.streamer_name, s.is_online, s.stream_title, s.stream_thumbnail_url,
                            s.is_pinned, s.allow_juniors, s.profile_image_url,
                            s.stream_game_id as game_id, s.stream_game_name as game_name, s.stream_started_at as started_at,
                            s.priority, s.pr_slots, s.priority_override, s.pr_slots_override,
                            s.added_at, s.added_by_id, s.updated_at,
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
        monitoring_message_id: Optional[int] = None,
        monitoring_filter_gta: Optional[bool] = None,
        pr_actions_channel_id: Optional[int] = None,
        control_panel_channel_id: Optional[int] = None,
        control_panel_message_id: Optional[int] = None,
    ) -> None:
        """Create or update guild settings.

        Args:
            notification_channel_id: Discord channel ID for notifications (optional)
            monitoring_channel_id: Discord channel ID for monitoring (optional)
            monitoring_message_id: Discord message ID for monitoring (optional)
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
                        "SELECT notification_channel_id, monitoring_channel_id, monitoring_message_id, monitoring_filter_gta, pr_actions_channel_id, control_panel_channel_id, control_panel_message_id FROM settings",
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

                    final_monitoring_message_id = (
                        monitoring_message_id
                        if monitoring_message_id is not None
                        else (
                            existing.get("monitoring_message_id") if existing else None
                        )
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
                            monitoring_message_id, 
                            monitoring_filter_gta, 
                            pr_actions_channel_id, 
                            control_panel_channel_id, 
                            control_panel_message_id
                        )
                        VALUES (1, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            notification_channel_id = VALUES(notification_channel_id),
                            monitoring_channel_id = VALUES(monitoring_channel_id),
                            monitoring_message_id = VALUES(monitoring_message_id),
                            monitoring_filter_gta = VALUES(monitoring_filter_gta),
                            pr_actions_channel_id = VALUES(pr_actions_channel_id),
                            control_panel_channel_id = VALUES(control_panel_channel_id),
                            control_panel_message_id = VALUES(control_panel_message_id)
                        """,
                        (
                            final_notification,
                            final_monitoring_channel,
                            final_monitoring_message_id,
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
                        "SELECT notification_channel_id, monitoring_channel_id, monitoring_message_id, monitoring_filter_gta, pr_actions_channel_id, control_panel_channel_id, control_panel_message_id, notification_templates, p0_rate, p1_rate, p2_rate, p3_rate, probation_rate FROM settings WHERE id = 1",
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

    @staticmethod
    def _round_points(value: float) -> float:
        return round(float(value), 4)

    @staticmethod
    def _warnings_breakdown(units: int) -> Dict[str, Any]:
        safe_units = max(int(units or 0), 0)
        strict = safe_units // 2
        oral = safe_units % 2
        return {
            "warnings_units": safe_units,
            "strict_warnings": strict,
            "oral_warnings": oral,
            "warnings_display": f"{strict}/2 {oral}/2",
        }

    @staticmethod
    def _normalize_msk_datetime(value: Optional[datetime]) -> Optional[datetime]:
        """Normalize any datetime to naive MSK for MySQL."""
        if value is None:
            return None
        
        # Moscow timezone
        MSK = timezone(timedelta(hours=3))
        
        if value.tzinfo is None:
            # Assume it's already MSK (as our DB stores naive MSK)
            return value
            
        # If it has a timezone (e.g. UTC from Twitch), convert to MSK then strip tzinfo
        return value.astimezone(MSK).replace(tzinfo=None)

    def _compute_session_points(self, session_row: Dict[str, Any]) -> float:
        """Compute deterministic points contribution for a single session row."""
        if not session_row:
            return 0.0
        if session_row.get("ended_at") is None:
            return 0.0
        if session_row.get("deleted_at") is not None:
            return 0.0
            
        # Spec requests only yield points if they are approved
        if session_row.get("event_kind") == "spec_request" and session_row.get("approval_status") != "approved":
            return 0.0
            
        duration_seconds = float(session_row.get("duration_seconds") or 0.0)
        applied_rate = float(session_row.get("applied_hourly_rate") or 0.0)
        return self._round_points((duration_seconds / 3600.0) * applied_rate)

    async def _recalc_session_points_delta(
        self, conn, session_id: int, lock: bool = True
    ) -> float:
        """
        Recalculate one session and apply ONLY delta to assistant auto points.
        Returns applied delta.
        """
        lock_sql = "FOR UPDATE" if lock else ""
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(
                f"""
                SELECT ss.id, ss.pr_id, ss.ended_at, ss.deleted_at, ss.duration_seconds,
                       ss.applied_hourly_rate, ss.credited_points,
                       ss.target_type, ss.target_id,
                       e.event_kind, e.approval_status
                FROM spec_sessions ss
                LEFT JOIN events e ON ss.target_type = 'event' AND ss.target_id = e.id
                WHERE ss.id = %s
                {lock_sql}
                """,
                (session_id,),
            )
            row = await cursor.fetchone()
            if not row:
                return 0.0

            new_points = self._compute_session_points(row)
            old_points = float(row.get("credited_points") or 0.0)
            delta = self._round_points(new_points - old_points)

            if abs(delta) < 0.00005:
                delta = 0.0

            if new_points != old_points:
                await cursor.execute(
                    "UPDATE spec_sessions SET credited_points = %s WHERE id = %s",
                    (new_points, session_id),
                )

            if delta != 0.0:
                await cursor.execute(
                    """
                    INSERT INTO assistants (pr_id)
                    VALUES (%s)
                    ON DUPLICATE KEY UPDATE pr_id = pr_id
                    """,
                    (row["pr_id"],),
                )
                await cursor.execute(
                    """
                    UPDATE assistants
                    SET auto_points_total = ROUND(COALESCE(auto_points_total, 0) + %s, 4)
                    WHERE pr_id = %s
                    """,
                    (delta, row["pr_id"]),
                )

            return delta

    async def _recalc_points_for_sessions(
        self, conn, session_ids: List[int], lock: bool = True
    ) -> None:
        for session_id in session_ids:
            await self._recalc_session_points_delta(conn, session_id, lock=lock)

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
                        self.logger.warning(
                            f"PR {pr_id} already has active session {active['id']}"
                        )
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
                            "SELECT streamer_name, pr_slots, pr_slots_override, priority, priority_override FROM streamers WHERE streamer_id = %s",
                            (streamer_id,),
                        )
                        streamer_row = await cursor.fetchone()
                        streamer_name = streamer_row.get("streamer_name") if streamer_row else "Unknown"
                        pr_slots = (
                            streamer_row.get("pr_slots_override") or streamer_row.get("pr_slots", 1) if streamer_row else 1
                        )
                        streamer_priority = (
                            streamer_row.get("priority", 0) if streamer_row else 0
                        )
                        streamer_priority_override = (
                            streamer_row.get("priority_override") if streamer_row else None
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
                            "SELECT streamer_name, priority, priority_override FROM streamers WHERE streamer_id = %s",
                            (streamer_id,),
                        )
                        streamer_row = await cursor.fetchone()
                        streamer_name = streamer_row.get("streamer_name") if streamer_row else "Unknown"
                        streamer_priority = (
                            streamer_row.get("priority", 0) if streamer_row else 0
                        )
                        streamer_priority_override = (
                            streamer_row.get("priority_override") if streamer_row else None
                        )

                    # Snapshot the rate from config
                    config = await self.get_points_config()
                    if is_probation:
                        rate_auto = await self._get_probation_rate()
                    else:
                        rate_auto = config.get(streamer_priority, 0.5)

                    # Calculate override rate if streamer has priority_override
                    session_priority_override = None
                    session_rate_override = None
                    if streamer_priority_override is not None and not is_probation:
                        session_priority_override = streamer_priority_override
                        session_rate_override = config.get(streamer_priority_override, 0.5)

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
                                (pr_id, target_type, target_id, target_name, is_probation, started_at,
                                 priority_auto, rate_auto, priority_override, rate_override)
                            VALUES (%s, 'streamer', %s, %s, %s, CURRENT_TIMESTAMP, %s, %s, %s, %s)
                            """,
                            (
                                pr_id,
                                streamer_id,
                                streamer_name,
                                is_probation,
                                streamer_priority,
                                rate_auto,
                                session_priority_override,
                                session_rate_override,
                            ),
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
        end_reason: str = "manual_unclaim",
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
            # Fail-safe: ensure end_reason is valid for ENUM
            allowed_reasons = {
                "manual_unclaim", "stream_end", "category_change", 
                "admin_closed", "event_end", "event_rejected", "unknown"
            }
            if end_reason not in allowed_reasons:
                self.logger.warning(f"Invalid end_reason '{end_reason}' passed to unassign_pr_from_streamer. Fallback to 'unknown'.")
                end_reason = "unknown"

            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    # 1. Find active sessions for this streamer
                    query_base = """
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
                        query_base += " AND ss.pr_id = %s"
                        params.append(pr_id)

                    query = query_base + " FOR UPDATE"

                    await cursor.execute(query, tuple(params))
                    results = await cursor.fetchall()

                    if not results:
                        return []

                    unassigned_sessions = []
                    session_ids = []

                    for res in results:
                        unassigned_sessions.append(
                            {
                                "_session_id": int(res["id"]),
                                "pr_id": res["pr_id"],
                                "duration_seconds": 0,
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
                            SET ended_at = GREATEST(
                                    DATE_ADD(started_at, INTERVAL 1 SECOND),
                                    CURRENT_TIMESTAMP
                                ),
                                end_reason = %s
                            WHERE id IN ({format_strings})
                            """,
                            (end_reason, *session_ids),
                        )

                        await self._recalc_points_for_sessions(
                            conn, session_ids, lock=False
                        )

                        await cursor.execute(
                            f"""
                            SELECT id, COALESCE(duration_seconds, 0) AS duration_seconds
                            FROM spec_sessions
                            WHERE id IN ({format_strings})
                            """,
                            tuple(session_ids),
                        )
                        duration_rows = await cursor.fetchall()
                        duration_map = {
                            int(row["id"]): int(row.get("duration_seconds") or 0)
                            for row in duration_rows
                        }
                        for session in unassigned_sessions:
                            sid = session.get("_session_id")
                            session["duration_seconds"] = duration_map.get(int(sid), 0)
                            session.pop("_session_id", None)

                    await conn.commit()

            return unassigned_sessions

        except Exception as e:
            self.logger.error(
                f"Failed to unassign PR(s) from streamer {streamer_id}: {e}",
                exc_info=True,
            )
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
        Получение текущей сессии (стримера или события), назначенной PR-ассистенту.

        Args:
            pr_id: Discord ID ассистента

        Returns:
            Словарь с данными стримера/события или None
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT 
                            ss.target_type,
                            ss.target_id,
                            ss.started_at as assigned_at,
                            s.streamer_id, 
                            s.streamer_name, 
                            s.is_online, 
                            s.stream_title, 
                            s.stream_thumbnail_url, 
                            s.stream_game_id, 
                            s.stream_game_name, 
                            s.stream_started_at, 
                            s.priority, 
                            s.added_at, 
                            s.added_by_id, 
                            s.updated_at,
                            e.id as event_id,
                            e.name as event_name,
                            e.is_active as event_is_active
                        FROM spec_sessions ss
                        LEFT JOIN streamers s ON s.streamer_id = ss.target_id AND ss.target_type = 'streamer'
                        LEFT JOIN events e ON e.id = ss.target_id AND ss.target_type = 'event'
                        WHERE ss.pr_id = %s 
                          AND (ss.target_type = 'streamer' OR ss.target_type = 'event')
                          AND ss.ended_at IS NULL AND ss.deleted_at IS NULL
                        """,
                        (pr_id,),
                    )
                    result = await cursor.fetchone()
                    if result:
                        if result["target_type"] == "streamer" and result.get("streamer_id"):
                            result["streamer_id"] = str(result["streamer_id"])
                            if result.get("added_by_id"):
                                result["added_by_id"] = str(result["added_by_id"])
                            if result.get("stream_game_id"):
                                result["stream_game_id"] = str(result["stream_game_id"])
                        elif result["target_type"] == "event" and result.get("event_id"):
                            # Data stays as is, let Python handle integers
                            pass
                        return result

                    # If not currently active in a session, check if they reserved a slot for a future event
                    await cursor.execute(
                        """
                        SELECT
                            'event' as target_type,
                            e.id as target_id,
                            ep.joined_at as assigned_at,
                            e.id as event_id,
                            e.name as event_name,
                            e.is_active as event_is_active
                        FROM event_participants ep
                        JOIN events e ON e.id = ep.event_id
                        WHERE ep.pr_id = %s
                        """,
                        (pr_id,)
                    )
                    return await cursor.fetchone()
        except Exception as e:
            self.logger.error(
                f"Failed to get current session for PR {pr_id}: {e}",
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
                        SELECT s.streamer_id, s.streamer_name
                        FROM streamers s
                        LEFT JOIN spec_sessions ss
                          ON ss.target_type = 'streamer'
                         AND ss.target_id = s.streamer_id
                         AND ss.ended_at IS NULL
                         AND ss.deleted_at IS NULL
                        WHERE s.is_online = TRUE
                          AND s.stream_game_id = %s
                          AND ss.id IS NULL
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
        created_by: int,
        start_time=None,
        required_pr_count=1,
        notification_sent=False,
        pr_slots: int = 1,
        priority: int = 0,
    ) -> int:
        """Создание нового события."""
        try:
            if start_time is not None:
                # Validate that start_time is not in the past
                if isinstance(start_time, str):
                    start_time = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                if start_time.tzinfo is None:
                    start_time = start_time.replace(tzinfo=timezone(timedelta(hours=3)))
                if start_time < datetime.now(timezone(timedelta(hours=3))):
                    raise ValueError("Время начала события не может быть в прошлом")
            else:
                start_time = datetime.now(timezone(timedelta(hours=3)))

            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO events (
                            name, description,
                            required_pr_count, created_by, start_time, notification_sent,
                            pr_slots, priority
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            name,
                            description,
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
    async def get_all_events(self) -> list:
        """Получение всех событий (активных и неактивных)."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        """
                        SELECT id, name, description, created_at, start_time, is_active, created_by, notification_sent,
                               required_pr_count, priority, pr_slots, is_pinned,
                               event_kind, approval_status, requested_by, approved_by, approved_at, rejected_by, rejected_at
                        FROM events
                        ORDER BY is_active DESC, is_pinned DESC, created_at DESC
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
            self.logger.error(f"Failed to get all events: {e}", exc_info=True)
            return []

    @db_retry()
    async def get_active_events(self) -> list:
        """Получение активных событий гильдии."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        """
                        SELECT id, name, description, created_at, start_time, is_active, created_by, notification_sent,
                               required_pr_count, priority, pr_slots, is_pinned,
                               event_kind, approval_status, requested_by, approved_by, approved_at, rejected_by, rejected_at
                        FROM events
                        WHERE is_active = TRUE
                        ORDER BY is_pinned DESC, priority DESC, start_time ASC
                        """
                    )
                    events = await cursor.fetchall()
                    for event in events:
                        # Active participants (spec started)
                        await cursor.execute(
                            """
                            SELECT ss.pr_id, a.nickname, 'active' as status
                            FROM spec_sessions ss
                            LEFT JOIN assistants a ON a.pr_id = ss.pr_id
                            WHERE ss.target_type = 'event' AND ss.target_id = %s
                              AND ss.ended_at IS NULL AND ss.deleted_at IS NULL
                            """,
                            (event["id"],),
                        )
                        active_participants = await cursor.fetchall() or []

                        # Reserved participants (waiting for event start)
                        await cursor.execute(
                            """
                            SELECT ep.pr_id, a.nickname, 'reserved' as status
                            FROM event_participants ep
                            LEFT JOIN assistants a ON a.pr_id = ep.pr_id
                            WHERE ep.event_id = %s
                            """,
                            (event["id"],),
                        )
                        reserved_participants = await cursor.fetchall() or []

                        all_participants = list(active_participants) + list(reserved_participants)
                        event["current_participants"] = len(all_participants)
                        event["participants"] = [
                            {"pr_id": str(p["pr_id"]), "nickname": p.get("nickname"), "status": p.get("status", "active")}
                            for p in all_participants
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
                        "SELECT id, name, description, created_at, start_time, is_active, created_by, notification_sent, required_pr_count, priority, pr_slots, is_pinned FROM events WHERE id = %s",
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
            now = datetime.now(timezone(timedelta(hours=3)))
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    self.logger.debug(f"Attempting to end event {event_id}.")

                    await cursor.execute(
                        """
                        SELECT id, pr_id, started_at
                        FROM spec_sessions
                        WHERE target_type = 'event' AND target_id = %s AND ended_at IS NULL AND deleted_at IS NULL
                        FOR UPDATE
                        """,
                        (event_id,),
                    )
                    participants = await cursor.fetchall()
                    self.logger.debug(f"Found {len(participants)} active participants for event {event_id}.")

                    await cursor.execute(
                        "SELECT start_time FROM events WHERE id = %s", (event_id,)
                    )
                    event_data = await cursor.fetchone()
                    if not event_data:
                        self.logger.warning(f"Event {event_id} not found during end_event operation.")
                        return []

                    event_start_time = (
                        event_data["start_time"].replace(tzinfo=timezone(timedelta(hours=3)))
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
                    self.logger.debug(f"Event {event_id} marked as inactive.")

                    await cursor.execute(
                        """
                        UPDATE spec_sessions 
                        SET ended_at = GREATEST(
                                DATE_ADD(started_at, INTERVAL 1 SECOND),
                                CURRENT_TIMESTAMP
                            ),
                            end_reason = 'event_end'
                        WHERE target_type = 'event' AND target_id = %s AND ended_at IS NULL AND deleted_at IS NULL
                        """,
                        (event_id,),
                    )
                    self.logger.debug(f"Closed active spec sessions for event {event_id}.")

                    session_ids = [int(p["id"]) for p in participants]
                    if session_ids:
                        await self._recalc_points_for_sessions(
                            conn, session_ids, lock=False
                        )
                        self.logger.debug(f"Recalculated points for sessions: {session_ids}.")

                    results = []
                    for p in participants:
                        user_id = p["pr_id"]
                        started_at = p["started_at"]
                        if started_at.tzinfo is None:
                            started_at = started_at.replace(tzinfo=timezone(timedelta(hours=3)))

                        effective_start = max(started_at, event_start_time)

                        duration = int((now - effective_start).total_seconds())
                        if duration < 0:
                            duration = 0

                        results.append({"user_id": user_id, "duration": duration})

                await conn.commit()
                self.logger.debug(
                    f"Event {event_id} ended. Processed {len(results)} participant sessions. "
                    f"Participant results: {results}"
                )
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
        started_at: datetime,
        ended_at: datetime,
        is_probation: bool = False,
        priority: int = 0,
        target_name: Optional[str] = None,
    ) -> bool:
        """
        Создание ручной записи сессии спека (для админских корректировок).
        Сессия всегда создается завершенной по явным границам started_at/ended_at.
        """
        try:
            if target_type not in {"streamer", "event", "manual"}:
                self.logger.warning(
                    "Invalid target_type for manual spec session: %s", target_type
                )
                return False

            start_time = self._normalize_msk_datetime(started_at)
            end_time = self._normalize_msk_datetime(ended_at)
            if start_time is None or end_time is None or end_time <= start_time:
                self.logger.warning(
                    "Invalid manual session window for PR=%s: start=%s end=%s",
                    pr_id,
                    started_at,
                    ended_at,
                )
                return False

            if target_type == "manual":
                target_id_value: Optional[int] = None
            else:
                if target_id is None:
                    self.logger.warning(
                        "Non-manual session requires target_id (PR=%s, type=%s)",
                        pr_id,
                        target_type,
                    )
                    return False
                target_id_value = int(target_id)

            # Snapshot rate from config
            config = await self.get_points_config()
            safe_priority = max(0, min(int(priority), 3))
            if is_probation:
                rate_auto = await self._get_probation_rate()
            else:
                rate_auto = config.get(safe_priority, 0.5)

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
                        (pr_id, target_type, target_id, target_name, started_at, ended_at, end_reason, 
                         is_probation, priority_auto, rate_auto)
                        VALUES (%s, %s, %s, %s, %s, %s, 'manual_admin', %s, %s, %s)
                        """,
                        (
                            pr_id,
                            target_type,
                            target_id_value,
                            target_name,
                            start_time,
                            end_time,
                            is_probation,
                            safe_priority,
                            rate_auto,
                        ),
                    )
                    session_id = cursor.lastrowid
                    await self._recalc_session_points_delta(conn, session_id, lock=False)
                    await conn.commit()

            self.logger.info(
                "Manual spec session created: PR=%s, target_type=%s, target_id=%s, start=%s, end=%s, probation=%s",
                pr_id,
                target_type,
                target_id_value,
                start_time.isoformat(),
                end_time.isoformat(),
                is_probation,
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

            # Propagate new priority to active sessions
            await self.recalc_target_active_sessions("streamer", streamer_id)
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
    async def join_event(self, event_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        """Добавление пользователя в событие с проверкой лимита слотов."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    self.logger.debug(f"User {user_id} attempting to join event {event_id}.")

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
                        self.logger.debug(f"User {user_id} already has active session {active['id']}.")
                        return {"status": "error", "detail": "Already in an active session"}

                    # Also check if already reserved for THIS event
                    await cursor.execute(
                        "SELECT pr_id FROM event_participants WHERE event_id = %s AND pr_id = %s",
                        (event_id, user_id)
                    )
                    if await cursor.fetchone():
                        self.logger.debug(f"User {user_id} already reserved for event {event_id}.")
                        return {"status": "error", "detail": "Already reserved for this event"}

                    # Capacity check: count current participants (active + reserved) vs pr_slots
                    await cursor.execute(
                        "SELECT name, pr_slots, priority, start_time, event_kind, requested_by FROM events WHERE id = %s AND is_active = TRUE",
                        (event_id,),
                    )
                    event = await cursor.fetchone()
                    if not event:
                        self.logger.debug(f"Event {event_id} not found or inactive for user {user_id}.")
                        return {"status": "error", "detail": "Event not found or inactive"}

                    # Block non-creators from joining spec_request events
                    if event.get("event_kind") == "spec_request" and event.get("requested_by") != user_id:
                        self.logger.debug(f"User {user_id} tried to join spec_request {event_id} but is not the creator.")
                        return {"status": "error", "detail": "Cannot join another user's spec request"}

                    event_name = event.get("name", f"Событие #{event_id}")
                    pr_slots = event.get("pr_slots", 1)
                    event_priority = event.get("priority", 0)
                    start_time = event.get("start_time")
                    
                    # Count active
                    await cursor.execute(
                        """
                        SELECT COUNT(*) as cnt FROM spec_sessions
                        WHERE target_type = 'event' AND target_id = %s 
                          AND ended_at IS NULL AND deleted_at IS NULL
                        """,
                        (event_id,),
                    )
                    count_active_row = await cursor.fetchone()
                    active_count = count_active_row["cnt"] if count_active_row else 0
                    
                    # Count reserved
                    await cursor.execute(
                        "SELECT COUNT(*) as cnt FROM event_participants WHERE event_id = %s",
                        (event_id,)
                    )
                    count_reserved_row = await cursor.fetchone()
                    reserved_count = count_reserved_row["cnt"] if count_reserved_row else 0

                    self.logger.debug(f"Event {event_id} slots: {active_count} active, {reserved_count} reserved, {pr_slots} total.")
                    if (active_count + reserved_count) >= pr_slots:
                        self.logger.debug(f"Event {event_id} has no available slots for user {user_id}.")
                        return {"status": "error", "detail": "No slots available"}

                    # Snapshot rate from config
                    config = await self.get_points_config()
                    rate_auto = config.get(event_priority, 0.5)

                    # Ensure assistant exists
                    await cursor.execute(
                        "INSERT INTO assistants (pr_id) VALUES (%s) ON DUPLICATE KEY UPDATE pr_id = pr_id",
                        (user_id,),
                    )

                    # Determine if we insert into spec_sessions or event_participants
                    now = datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None) # Start time in DB is naiive UTC
                    if not start_time or start_time <= now:
                        # Event has started - join directly
                        try:
                            await cursor.execute(
                                """
                                INSERT INTO spec_sessions 
                                    (pr_id, target_type, target_id, target_name, started_at, priority_auto, rate_auto)
                                VALUES (%s, 'event', %s, %s, CURRENT_TIMESTAMP, %s, %s)
                                """,
                                (user_id, event_id, event_name, event_priority, rate_auto),
                            )
                            await conn.commit()
                            self.logger.debug(
                                f"User {user_id} joined active event {event_id} ('{event_name}'). "
                                f"State AFTER: joined spec_sessions with priority {event_priority}."
                            )
                            return {"status": "joined", "detail": "Joined active event"}
                        except Exception as e:
                            if "uq_one_active_session_per_pr" in str(e):
                                self.logger.warning(f"User {user_id} tried to join event {event_id} but already has an active session (DB constraint).")
                                return {"status": "error", "detail": "Already in an active session"}
                            raise
                    else:
                        # Event has not started - reserve slot
                        await cursor.execute(
                            "INSERT INTO event_participants (event_id, pr_id) VALUES (%s, %s)",
                            (event_id, user_id)
                        )
                        await conn.commit()
                        self.logger.debug(f"User {user_id} reserved slot for future event {event_id} ('{event_name}').")
                        return {"status": "reserved", "detail": "Reserved slot for future event"}

        except Exception as e:
            self.logger.error(f"Failed to join event: {e}", exc_info=True)
            return {"status": "error", "detail": "Internal database error"}

    @db_retry()
    async def leave_event(self, event_id: int, user_id: int, end_reason: str = "manual_unclaim") -> int:
        """Удаление пользователя из события и возврат длительности."""
        try:
            # Fail-safe: ensure end_reason is valid for ENUM
            allowed_reasons = {
                "manual_unclaim", "stream_end", "category_change", 
                "admin_closed", "event_end", "event_rejected", "unknown"
            }
            if end_reason not in allowed_reasons:
                self.logger.warning(f"Invalid end_reason '{end_reason}' passed to leave_event. Fallback to 'unknown'.")
                end_reason = "unknown"

            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    self.logger.debug(f"User {user_id} attempting to leave event {event_id}. Reason: {end_reason}.")

                    # 0. Check if user is in reserved state
                    await cursor.execute(
                        "DELETE FROM event_participants WHERE event_id = %s AND pr_id = %s",
                        (event_id, user_id)
                    )
                    if cursor.rowcount > 0:
                        await conn.commit()
                        self.logger.debug(f"User {user_id} was in reserved state for event {event_id} and removed.")
                        return 0

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
                        self.logger.debug(f"User {user_id} not found in active sessions for event {event_id}.")
                        return 0

                    session_id = result["id"]
                    self.logger.debug(f"Found active session {session_id} for user {user_id} in event {event_id}.")

                    # 2. Close session using DB time and guarantee ended_at > started_at
                    await cursor.execute(
                        """
                        UPDATE spec_sessions 
                        SET ended_at = GREATEST(
                                DATE_ADD(started_at, INTERVAL 1 SECOND),
                                CURRENT_TIMESTAMP
                            ),
                            end_reason = %s
                        WHERE id = %s
                        """,
                        (end_reason, session_id),
                    )
                    self.logger.debug(f"Session {session_id} for user {user_id} in event {event_id} marked as ended.")

                    await self._recalc_session_points_delta(conn, session_id, lock=False)
                    self.logger.debug(f"Points recalculated for session {session_id}.")

                    await cursor.execute(
                        """
                        SELECT COALESCE(duration_seconds, 0) AS duration_seconds
                        FROM spec_sessions
                        WHERE id = %s
                        """,
                        (session_id,),
                    )
                    duration_row = await cursor.fetchone()

                    # Auto-end spec_request events if 0 participants remain
                    await cursor.execute(
                        "SELECT event_kind FROM events WHERE id = %s",
                        (event_id,),
                    )
                    ev = await cursor.fetchone()
                    if ev and ev.get("event_kind") == "spec_request":
                        await cursor.execute(
                            """
                            SELECT COUNT(*) as cnt FROM spec_sessions
                            WHERE target_type = 'event' AND target_id = %s
                              AND ended_at IS NULL AND deleted_at IS NULL
                            """,
                            (event_id,),
                        )
                        cnt_row = await cursor.fetchone()
                        if cnt_row and cnt_row["cnt"] == 0:
                            await cursor.execute(
                                "UPDATE events SET is_active = FALSE WHERE id = %s",
                                (event_id,),
                            )
                            self.logger.debug(f"Spec request event {event_id} auto-marked as inactive due to 0 participants.")

                    await conn.commit()
                    duration = (
                        int(duration_row["duration_seconds"]) if duration_row else 0
                    )
                    self.logger.debug(
                        f"User {user_id} left event {event_id}. Reason: {end_reason}. "
                        f"Session ID {session_id} ended. Duration: {duration}s."
                    )
                    return max(duration, 0)
        except Exception as e:
            self.logger.error(f"Failed to leave event {event_id}: {e}", exc_info=True)
            return 0

    @db_retry()
    async def create_spec_request(
        self,
        name: str,
        description: str,
        requested_by: int,
        priority: int = 0,
    ) -> Optional[int]:
        """Create a spec_request event and auto-join the creator."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    # Check if user already has an active session
                    await cursor.execute(
                        """
                        SELECT id FROM spec_sessions
                        WHERE pr_id = %s AND ended_at IS NULL AND deleted_at IS NULL
                        """,
                        (requested_by,),
                    )
                    if await cursor.fetchone():
                        raise ValueError("У вас уже есть активная сессия")

                    # Snapshot rate from config
                    config = await self.get_points_config()
                    rate_auto = config.get(priority, 0.5)

                    # Ensure assistant exists
                    await cursor.execute(
                        "INSERT INTO assistants (pr_id) VALUES (%s) ON DUPLICATE KEY UPDATE pr_id = pr_id",
                        (requested_by,),
                    )

                    # Create event
                    await cursor.execute(
                        """
                        INSERT INTO events (
                            name, description, created_by, requested_by,
                            start_time, notification_sent,
                            pr_slots, priority, required_pr_count,
                            event_kind, approval_status, is_active
                        ) VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, TRUE, 1, %s, 1, 'spec_request', 'pending', TRUE)
                        """,
                        (name, description, requested_by, requested_by, priority),
                    )
                    event_id = cursor.lastrowid

                    # Auto-join: create spec_session immediately
                    await cursor.execute(
                        """
                        INSERT INTO spec_sessions
                            (pr_id, target_type, target_id, target_name, started_at, priority_auto, rate_auto)
                        VALUES (%s, 'event', %s, %s, CURRENT_TIMESTAMP, %s, %s)
                        """,
                        (requested_by, event_id, name, priority, rate_auto),
                    )

                    await conn.commit()
                    return event_id
        except ValueError:
            raise
        except Exception as e:
            self.logger.error(f"Failed to create spec request: {e}", exc_info=True)
            return None

    @db_retry()
    async def update_pending_spec_request(
        self,
        event_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        priority: Optional[int] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> bool:
        """Update a pending spec_request event without approving it."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        """
                        SELECT id, approval_status, event_kind FROM events
                        WHERE id = %s FOR UPDATE
                        """,
                        (event_id,),
                    )
                    event = await cursor.fetchone()
                    if not event:
                        raise ValueError("Event not found")
                    if event["event_kind"] != "spec_request":
                        raise ValueError("Event is not a spec_request")
                    if event["approval_status"] != "pending":
                        raise ValueError("Event is not pending")

                    # Build dynamic update for events table
                    set_parts = []
                    params: list = []

                    if name is not None:
                        set_parts.append("name = %s")
                        params.append(name)
                    if description is not None:
                        set_parts.append("description = %s")
                        params.append(description)
                    if priority is not None:
                        set_parts.append("priority = %s")
                        params.append(priority)

                    if set_parts:
                        params.append(event_id)
                        await cursor.execute(
                            f"UPDATE events SET {', '.join(set_parts)} WHERE id = %s",
                            tuple(params),
                        )

                    # If priority was changed, update the session rate/priority snapshot
                    if priority is not None:
                        config = await self.get_points_config()
                        new_rate = config.get(priority, 0.5)
                        await cursor.execute(
                            """
                            UPDATE spec_sessions
                            SET priority_auto = %s, rate_auto = %s
                            WHERE target_type = 'event' AND target_id = %s
                              AND deleted_at IS NULL
                            """,
                            (priority, new_rate, event_id),
                        )

                    # Update session times if provided by admin
                    if start_time is not None or end_time is not None:
                        time_set_parts = []
                        time_params: list = []
                        if start_time is not None:
                            time_set_parts.append("started_at = %s")
                            time_params.append(start_time)
                        if end_time is not None:
                            time_set_parts.append("ended_at = %s")
                            time_params.append(end_time)
                            time_set_parts.append("end_reason = 'admin_closed'")
                        time_params.append(event_id)
                        await cursor.execute(
                            f"""
                            UPDATE spec_sessions
                            SET {', '.join(time_set_parts)}
                            WHERE target_type = 'event' AND target_id = %s
                              AND deleted_at IS NULL
                            """,
                            tuple(time_params),
                        )

                    # Recalculate points for sessions of this event
                    await cursor.execute(
                        """
                        SELECT id FROM spec_sessions
                        WHERE target_type = 'event' AND target_id = %s
                          AND ended_at IS NOT NULL AND deleted_at IS NULL
                        """,
                        (event_id,),
                    )
                    closed_sessions = await cursor.fetchall()
                    if closed_sessions:
                        session_ids = [int(s["id"]) for s in closed_sessions]
                        await self._recalc_points_for_sessions(conn, session_ids, lock=False)

                    await conn.commit()
                    return True
        except ValueError:
            raise
        except Exception as e:
            self.logger.error(f"Failed to update pending spec request {event_id}: {e}", exc_info=True)
            return False

    @db_retry()
    async def approve_spec_request(
        self,
        event_id: int,
        approved_by: int,
    ) -> bool:
        """Approve a pending spec_request event."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    self.logger.debug(f"Attempting to approve spec request {event_id} by {approved_by}.")

                    await cursor.execute(
                        """
                        SELECT id, approval_status, event_kind FROM events
                        WHERE id = %s FOR UPDATE
                        """,
                        (event_id,),
                    )
                    event = await cursor.fetchone()
                    if not event:
                        self.logger.warning(f"Spec request {event_id} not found for approval.")
                        raise ValueError("Event not found")
                    if event["event_kind"] != "spec_request":
                        self.logger.warning(f"Event {event_id} is not a spec_request, cannot approve.")
                        raise ValueError("Event is not a spec_request")
                    if event["approval_status"] != "pending":
                        self.logger.warning(f"Event {event_id} is not pending, current status: {event['approval_status']}.")
                        raise ValueError("Event is not pending")

                    # Check for sessions that were closed (ended_at is NOT NULL) but still belong to this pending event
                    await cursor.execute(
                        """
                        SELECT id, pr_id, duration_seconds, ended_at
                        FROM spec_sessions
                        WHERE target_type = 'event' AND target_id = %s
                          AND ended_at IS NOT NULL AND deleted_at IS NULL
                        """,
                        (event_id,),
                    )
                    closed_sessions = await cursor.fetchall()
                    self.logger.debug(f"Found {len(closed_sessions)} closed sessions for spec request {event_id}.")

                    # If we found closed sessions, it means the spec request is already finished.
                    # We should mark the event as inactive (is_active = FALSE).
                    is_active_clause = ""
                    if closed_sessions:
                        is_active_clause = ", is_active = FALSE"

                    await cursor.execute(
                        f"""
                        UPDATE events 
                        SET approval_status = 'approved', approved_by = %s, approved_at = CURRENT_TIMESTAMP{is_active_clause}
                        WHERE id = %s
                        """,
                        (approved_by, event_id),
                    )
                    self.logger.debug(f"Spec request {event_id} status updated to 'approved'. is_active set to {not bool(closed_sessions)}.")

                    # Recalculate points for closed sessions now that status is 'approved'
                    if closed_sessions:
                        session_ids = [int(s["id"]) for s in closed_sessions]
                        await self._recalc_points_for_sessions(conn, session_ids, lock=False)
                        self.logger.debug(f"Recalculated points for closed sessions: {session_ids}.")

                    await conn.commit()
                self.logger.debug(
                    f"Spec Request {event_id} approved by {approved_by}. "
                    f"Closed {len(closed_sessions)} associated sessions. Event is_active={not bool(closed_sessions)}."
                )
                return {
                    "success": True,
                    "closed_sessions": [
                        {
                                "pr_id": s["pr_id"],
                                "duration": s.get("duration_seconds", 0),
                                "ended_at": s["ended_at"].isoformat() if s["ended_at"] else None
                            }
                            for s in closed_sessions
                        ]
                    }
        except ValueError:
            raise
        except Exception as e:
            self.logger.error(f"Failed to approve spec request {event_id}: {e}", exc_info=True)
            return False

    @db_retry()
    async def reject_spec_request(
        self,
        event_id: int,
        rejected_by: int,
    ) -> bool:
        """Reject a pending spec_request event and close active sessions."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        """
                        SELECT id, approval_status, event_kind FROM events
                        WHERE id = %s FOR UPDATE
                        """,
                        (event_id,),
                    )
                    event = await cursor.fetchone()
                    if not event:
                        raise ValueError("Event not found")
                    if event["event_kind"] != "spec_request":
                        raise ValueError("Event is not a spec_request")
                    if event["approval_status"] != "pending":
                        raise ValueError("Event is not pending")

                    # Mark event as rejected and inactive
                    await cursor.execute(
                        """
                        UPDATE events
                        SET approval_status = 'rejected',
                            rejected_by = %s,
                            rejected_at = CURRENT_TIMESTAMP,
                            is_active = FALSE
                        WHERE id = %s
                        """,
                        (rejected_by, event_id),
                    )

                    # Close active sessions with reason 'event_rejected'
                    await cursor.execute(
                        """
                        UPDATE spec_sessions
                        SET ended_at = GREATEST(
                                DATE_ADD(started_at, INTERVAL 1 SECOND),
                                CURRENT_TIMESTAMP
                            ),
                            end_reason = 'event_rejected'
                        WHERE target_type = 'event' AND target_id = %s
                          AND ended_at IS NULL AND deleted_at IS NULL
                        """,
                        (event_id,),
                    )

                    # No points recalculation needed — rejected sessions
                    # will be excluded by view filter (approval_status != 'approved')

                    await conn.commit()
                    return True
        except ValueError:
            raise
        except Exception as e:
            self.logger.error(f"Failed to reject spec request {event_id}: {e}", exc_info=True)
            return False

    @db_retry()
    async def get_pending_spec_requests(self) -> list:
        """Get all pending spec_request events with session info for admin review."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        """
                        SELECT
                            e.id, e.name, e.description, e.created_at, e.start_time,
                            e.priority, e.requested_by, e.is_active,
                            a.nickname AS requester_nickname,
                            ss.started_at AS session_started_at,
                            ss.ended_at AS session_ended_at,
                            ss.duration_seconds AS session_duration_seconds
                        FROM events e
                        LEFT JOIN assistants a ON a.pr_id = e.requested_by
                        LEFT JOIN spec_sessions ss
                            ON ss.target_type = 'event' AND ss.target_id = e.id AND ss.deleted_at IS NULL
                        WHERE e.event_kind = 'spec_request'
                          AND e.approval_status = 'pending'
                        ORDER BY e.created_at DESC
                        """
                    )
                    return await cursor.fetchall() or []
        except Exception as e:
            self.logger.error(f"Failed to get pending spec requests: {e}", exc_info=True)
            return []

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
        """Получение списка активных и зарезервированных участников события."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    # Get active
                    await cursor.execute(
                        """
                        SELECT pr_id as user_id, started_at as joined_at, 'active' as status
                        FROM spec_sessions
                        WHERE target_type = 'event' AND target_id = %s 
                          AND ended_at IS NULL AND deleted_at IS NULL
                        """,
                        (event_id,),
                    )
                    active = await cursor.fetchall() or []

                    # Get reserved
                    await cursor.execute(
                        """
                        SELECT pr_id as user_id, joined_at, 'reserved' as status
                        FROM event_participants
                        WHERE event_id = %s
                        """,
                        (event_id,)
                    )
                    reserved = await cursor.fetchall() or []

                    return list(active) + list(reserved)
        except Exception as e:
            self.logger.error(f"Failed to get participants: {e}", exc_info=True)
            return []

    @db_retry()
    async def start_event_sessions(self, event_id: int) -> list:
        """
        Migrates reserved participants from `event_participants` to `spec_sessions`.
        Called when an event officially starts.
        Returns a list of PR IDs that were migrated.
        """
        try:
            migrated_pr_ids = []
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    self.logger.debug(f"Attempting to start sessions for event {event_id}.")

                    # Lock rows
                    await cursor.execute(
                        "SELECT pr_id FROM event_participants WHERE event_id = %s FOR UPDATE",
                        (event_id,)
                    )
                    participants = await cursor.fetchall()
                    self.logger.debug(f"Found {len(participants)} reserved participants for event {event_id}.")

                    if not participants:
                        self.logger.debug(f"No reserved participants to migrate for event {event_id}.")
                        return []

                    # Get event details for config
                    await cursor.execute("SELECT name, priority FROM events WHERE id = %s", (event_id,))
                    event = await cursor.fetchone()
                    priority = event.get("priority", 0) if event else 0
                    event_name = event.get("name", f"Событие #{event_id}") if event else f"Событие #{event_id}"
                    config = await self.get_points_config()
                    rate_auto = config.get(priority, 0.5)

                    for p in participants:
                        pr_id = p["pr_id"]
                        
                        # Verify they don't already have an active session
                        await cursor.execute(
                            """
                            SELECT id FROM spec_sessions 
                            WHERE pr_id = %s AND ended_at IS NULL AND deleted_at IS NULL
                            """,
                            (pr_id,)
                        )
                        if not await cursor.fetchone():
                            # Insert into spec
                            await cursor.execute(
                                """
                                INSERT INTO spec_sessions 
                                    (pr_id, target_type, target_id, target_name, started_at, priority_auto, rate_auto)
                                VALUES (%s, 'event', %s, %s, CURRENT_TIMESTAMP, %s, %s)
                                """,
                                (pr_id, event_id, event_name, priority, rate_auto)
                            )
                            migrated_pr_ids.append(pr_id)
                            self.logger.debug(f"Migrated PR {pr_id} to active session for event {event_id}.")
                        else:
                            self.logger.debug(f"PR {pr_id} already has an active session, skipping migration for event {event_id}.")

                    # Delete reserved since they are now migrated or rejected
                    await cursor.execute(
                        "DELETE FROM event_participants WHERE event_id = %s",
                        (event_id,)
                    )
                    await conn.commit()
            self.logger.debug(
                f"Event {event_id} started. Migrated {len(migrated_pr_ids)} reserved participants "
                f"to active spec_sessions. IDs: {migrated_pr_ids}"
            )
            return migrated_pr_ids
        except Exception as e:
            self.logger.error(f"Failed to start sessions for event {event_id}: {e}", exc_info=True)
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
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        """
                        SELECT id
                        FROM spec_sessions
                        WHERE pr_id = %s AND deleted_at IS NULL
                        FOR UPDATE
                        """,
                        (pr_id,),
                    )
                    rows = await cursor.fetchall()
                    session_ids = [int(row["id"]) for row in rows]
                    if not session_ids:
                        return False

                    await cursor.execute(
                        """
                        UPDATE spec_sessions 
                        SET deleted_at = CURRENT_TIMESTAMP, delete_reason = 'admin_reset'
                        WHERE pr_id = %s AND deleted_at IS NULL
                        """,
                        (pr_id,),
                    )
                    await self._recalc_points_for_sessions(conn, session_ids, lock=False)
                    await conn.commit()
                    return True
        except Exception as e:
            self.logger.error(f"Failed to reset assistant stats: {e}", exc_info=True)
            return False

    async def _get_assistant_points_snapshot(
        self, cursor, pr_id: int, for_update: bool = False
    ) -> Optional[Dict[str, Any]]:
        lock_sql = " FOR UPDATE" if for_update else ""
        await cursor.execute(
            f"""
            SELECT
                pr_id,
                ROUND(COALESCE(auto_points_total, 0), 4) AS auto_points_total,
                ROUND(COALESCE(manual_points_adjustment, 0), 4) AS manual_points_adjustment,
                ROUND(
                    COALESCE(total_points, COALESCE(auto_points_total, 0) + COALESCE(manual_points_adjustment, 0)),
                    4
                ) AS total_points,
                ROUND(COALESCE(penalty_points, 0), 4) AS penalty_points,
                ROUND(COALESCE(penalty_percent, 0), 4) AS penalty_percent,
                COALESCE(warnings_units, 0) AS warnings_units,
                ROUND(
                    COALESCE(total_points, COALESCE(auto_points_total, 0) + COALESCE(manual_points_adjustment, 0))
                    - COALESCE(penalty_points, 0),
                    4
                ) AS display_points
            FROM assistants
            WHERE pr_id = %s{lock_sql}
            """,
            (pr_id,),
        )
        row = await cursor.fetchone()
        if row:
            row.update(self._warnings_breakdown(row.get("warnings_units", 0)))
        return row

    @db_retry()
    async def adjust_assistant_points(
        self,
        pr_id: int,
        delta: float,
        source: str = "manual_adjust",
    ) -> Optional[Dict[str, Any]]:
        """Adjust manual assistant points component (persistent across auto recalculation)."""
        try:
            rounded_delta = self._round_points(delta)
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO assistants (pr_id)
                        VALUES (%s)
                        ON DUPLICATE KEY UPDATE pr_id = pr_id
                        """,
                        (pr_id,),
                    )
                    before = await self._get_assistant_points_snapshot(
                        cursor, pr_id, for_update=True
                    )
                    if not before:
                        return None
                    await cursor.execute(
                        """
                        UPDATE assistants
                        SET manual_points_adjustment = ROUND(
                                COALESCE(manual_points_adjustment, 0) + %s,
                                4
                            )
                        WHERE pr_id = %s
                        """,
                        (rounded_delta, pr_id),
                    )
                    after = await self._get_assistant_points_snapshot(cursor, pr_id)
                    await conn.commit()
                    return {
                        "pr_id": pr_id,
                        "delta": rounded_delta,
                        "source": source,
                        "before": before,
                        "after": after,
                    }
        except Exception as e:
            self.logger.error(
                f"Failed to adjust assistant points for {pr_id}: {e}", exc_info=True
            )
            return None

    @db_retry()
    async def update_assistant_sanctions(
        self,
        pr_id: int,
        penalty_points: Optional[float] = None,
        penalty_percent: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update assistant sanctions (penalty points/percent)."""
        if penalty_points is None and penalty_percent is None:
            return None
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    self.logger.debug(f"Updating sanctions for pr_id={pr_id}. Penalty points: {penalty_points}, percent: {penalty_percent}.")

                    await cursor.execute(
                        """
                        INSERT INTO assistants (pr_id)
                        VALUES (%s)
                        ON DUPLICATE KEY UPDATE pr_id = pr_id
                        """,
                        (pr_id,),
                    )
                    before = await self._get_assistant_points_snapshot(
                        cursor, pr_id, for_update=True
                    )
                    if not before:
                        self.logger.warning(f"Assistant {pr_id} not found for sanction update.")
                        return None

                    clauses: List[str] = []
                    params: List[Any] = []
                    if penalty_points is not None:
                        clauses.append("penalty_points = GREATEST(0, ROUND(COALESCE(penalty_points, 0) + %s, 4))")
                        params.append(penalty_points)
                    if penalty_percent is not None:
                        clauses.append("penalty_percent = GREATEST(0, ROUND(COALESCE(penalty_percent, 0) + %s, 4))")
                        params.append(penalty_percent)
                    params.append(pr_id)
                    await cursor.execute(
                        f"UPDATE assistants SET {', '.join(clauses)} WHERE pr_id = %s",
                        tuple(params),
                    )
                    after = await self._get_assistant_points_snapshot(cursor, pr_id)
                await conn.commit()
                self.logger.debug(
                    f"Assistant sanctions updated for pr_id={pr_id}.\n"
                    f"BEFORE: {before}\nAFTER: {after}"
                )
                return {
                    "pr_id": pr_id,
                    "before": before,
                    "after": after,
                }
        except Exception as e:
            self.logger.error(
                f"Failed to update assistant sanctions for {pr_id}: {e}",
                exc_info=True,
            )
            return None

    @db_retry()
    async def update_assistant_warnings(
        self,
        pr_id: int,
        oral_delta: int = 0,
        strict_delta: int = 0,
    ) -> Optional[Dict[str, Any]]:
        """Update warnings units (oral=1 unit, strict=2 units)."""
        units_delta = int(oral_delta or 0) + int(strict_delta or 0) * 2
        if units_delta == 0:
            return None
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO assistants (pr_id)
                        VALUES (%s)
                        ON DUPLICATE KEY UPDATE pr_id = pr_id
                        """,
                        (pr_id,),
                    )
                    before = await self._get_assistant_points_snapshot(
                        cursor, pr_id, for_update=True
                    )
                    if not before:
                        return None
                    await cursor.execute(
                        """
                        UPDATE assistants
                        SET warnings_units = GREATEST(0, COALESCE(warnings_units, 0) + %s)
                        WHERE pr_id = %s
                        """,
                        (units_delta, pr_id),
                    )
                    after = await self._get_assistant_points_snapshot(cursor, pr_id)
                    await conn.commit()
                    return {
                        "pr_id": pr_id,
                        "units_delta": units_delta,
                        "oral_delta": int(oral_delta or 0),
                        "strict_delta": int(strict_delta or 0),
                        "before": before,
                        "after": after,
                    }
        except Exception as e:
            self.logger.error(
                f"Failed to update warnings for assistant {pr_id}: {e}", exc_info=True
            )
            return None

    @db_retry()
    async def update_assistant_session(
        self, pr_id: int, session_id: int, patch: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Admin patch of one spec session with deterministic points delta recalculation."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        """
                        SELECT
                            id, pr_id, target_type, target_id, target_name, started_at, ended_at,
                            is_probation, priority_override, rate_override,
                            deleted_at, credited_points
                        FROM spec_sessions
                        WHERE id = %s AND pr_id = %s AND deleted_at IS NULL
                        FOR UPDATE
                        """,
                        (session_id, pr_id),
                    )
                    before = await cursor.fetchone()
                    if not before:
                        return None

                    updates: List[str] = []
                    params: List[Any] = []

                    current_target_type = before.get("target_type")
                    current_target_id = before.get("target_id")
                    current_started = self._normalize_msk_datetime(
                        before.get("started_at")
                    )
                    current_ended = self._normalize_msk_datetime(before.get("ended_at"))

                    next_target_type = (
                        patch.get("target_type")
                        if patch.get("target_type") is not None
                        else current_target_type
                    )
                    next_target_id = (
                        patch.get("target_id")
                        if "target_id" in patch
                        else current_target_id
                    )

                    next_started = current_started
                    next_ended = current_ended

                    started_in_patch = (
                        "started_at" in patch and patch.get("started_at") is not None
                    )
                    ended_in_patch = (
                        "ended_at" in patch and patch.get("ended_at") is not None
                    )
                    if started_in_patch != ended_in_patch:
                        raise ValueError(
                            "started_at and ended_at must be provided together"
                        )

                    if started_in_patch and ended_in_patch:
                        next_started = self._normalize_msk_datetime(patch["started_at"])
                        next_ended = self._normalize_msk_datetime(patch["ended_at"])
                        if not next_started or not next_ended or next_ended <= next_started:
                            raise ValueError("ended_at must be greater than started_at")
                        updates.append("started_at = %s")
                        params.append(next_started)
                        updates.append("ended_at = %s")
                        params.append(next_ended)
                        # If session was open and admin is closing it, set end_reason
                        if current_ended is None:
                            updates.append("end_reason = %s")
                            params.append("admin_closed")

                    if next_target_type == "manual":
                        next_target_id = None
                    elif next_target_type in ("streamer", "event"):
                        if next_target_id is None:
                            raise ValueError(
                                "target_id is required for streamer/event sessions"
                            )
                    else:
                        raise ValueError("Unsupported target_type")

                    if next_target_type != current_target_type:
                        updates.append("target_type = %s")
                        params.append(next_target_type)

                    if next_target_id != current_target_id:
                        updates.append("target_id = %s")
                        params.append(next_target_id)

                    if "target_name" in patch:
                        updates.append("target_name = %s")
                        params.append(patch.get("target_name"))

                    if "is_probation" in patch:
                        updates.append("is_probation = %s")
                        params.append(patch.get("is_probation"))

                    if "priority_override" in patch:
                        updates.append("priority_override = %s")
                        params.append(patch.get("priority_override"))

                    # If is_probation OR priority_override changed, we might need a new rate_override
                    probation_changed = "is_probation" in patch
                    priority_changed = "priority_override" in patch

                    if probation_changed or priority_changed:
                        # Get latest values (considering patch or existing)
                        next_is_probation = patch.get("is_probation") if probation_changed else before.get("is_probation", False)
                        next_priority = patch.get("priority_override") if priority_changed else before.get("priority_override")

                        if next_priority is not None:
                            config = await self.get_points_config()
                            if next_is_probation:
                                auto_rate = await self._get_probation_rate()
                            else:
                                auto_rate = config.get(next_priority, 0.5)
                            updates.append("rate_override = %s")
                            params.append(auto_rate)
                        elif priority_changed:
                            # Specifically clearing priority_override
                            updates.append("rate_override = NULL")
                        # Else: priority stayed None, rate stays as is (likely NULL or auto)

                    # Healing logic: if target_name is NULL but we have target_id, try to fetch it
                    if (
                        "target_name" not in patch
                        and before.get("target_name") is None
                        and next_target_type in ("streamer", "event")
                        and next_target_id is not None
                    ):
                        heal_name = None
                        if next_target_type == "streamer":
                            await cursor.execute("SELECT streamer_name FROM streamers WHERE streamer_id = %s", (next_target_id,))
                            row = await cursor.fetchone()
                            if row:
                                heal_name = row["streamer_name"]
                        else:  # event
                            await cursor.execute("SELECT name FROM events WHERE id = %s", (next_target_id,))
                            row = await cursor.fetchone()
                            if row:
                                heal_name = row["name"]

                        if heal_name:
                            updates.append("target_name = %s")
                            params.append(heal_name)


                    if updates:
                        params.append(session_id)
                        await cursor.execute(
                            f"UPDATE spec_sessions SET {', '.join(updates)} WHERE id = %s",
                            tuple(params),
                        )

                        # Auto-close spec_request events if 0 participants remain after update
                        if next_target_type == "event" and next_target_id is not None:
                            await cursor.execute(
                                "SELECT event_kind FROM events WHERE id = %s",
                                (next_target_id,),
                            )
                            ev = await cursor.fetchone()
                            if ev and ev.get("event_kind") == "spec_request":
                                await cursor.execute(
                                    """
                                    SELECT COUNT(*) as cnt FROM spec_sessions
                                    WHERE target_type = 'event' AND target_id = %s
                                      AND ended_at IS NULL AND deleted_at IS NULL
                                    """,
                                    (next_target_id,),
                                )
                                cnt_row = await cursor.fetchone()
                                if cnt_row and cnt_row["cnt"] == 0:
                                    await cursor.execute(
                                        "UPDATE events SET is_active = FALSE WHERE id = %s",
                                        (next_target_id,),
                                    )
                                    self.logger.debug(f"Spec request event {next_target_id} auto-marked as inactive via admin update.")

                    await self._recalc_session_points_delta(conn, session_id, lock=False)

                    await cursor.execute(
                        """
                        SELECT
                            ss.id, ss.pr_id, ss.target_type, ss.target_id,
                            CASE
                                WHEN ss.target_name IS NOT NULL THEN ss.target_name
                                WHEN ss.target_type = 'streamer' THEN s.streamer_name
                                WHEN ss.target_type = 'event' THEN e.name
                                ELSE NULL
                            END AS target_name,
                            ss.started_at, ss.ended_at,
                            ss.is_probation, ss.priority_override, ss.rate_override,
                            ss.credited_points, ss.duration_seconds
                        FROM spec_sessions ss
                        LEFT JOIN streamers s ON ss.target_type = 'streamer' AND ss.target_id = s.streamer_id
                        LEFT JOIN events e ON ss.target_type = 'event' AND ss.target_id = e.id
                        WHERE ss.id = %s
                        """,
                        (session_id,),
                    )
                    after = await cursor.fetchone()
                    await conn.commit()
                    return {"session_id": session_id, "before": before, "after": after}
        except ValueError:
            raise
        except Exception as e:
            self.logger.error(
                f"Failed to update assistant session {session_id}: {e}", exc_info=True
            )
            return None

    @db_retry()
    async def soft_delete_assistant_session(
        self,
        pr_id: int,
        session_id: int,
        deleted_by_id: Optional[int] = None,
        reason: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Soft-delete one session and apply delta recalculation."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        """
                        SELECT
                            id, pr_id, target_type, target_id, started_at, ended_at,
                            credited_points, deleted_at
                        FROM spec_sessions
                        WHERE id = %s AND pr_id = %s AND deleted_at IS NULL
                        FOR UPDATE
                        """,
                        (session_id, pr_id),
                    )
                    before = await cursor.fetchone()
                    if not before:
                        return None

                    await cursor.execute(
                        """
                        UPDATE spec_sessions
                        SET deleted_at = CURRENT_TIMESTAMP,
                            deleted_by_id = %s,
                            delete_reason = %s
                        WHERE id = %s
                        """,
                        (deleted_by_id, reason or "admin_delete", session_id),
                    )

                    # Auto-close spec_request events if 0 participants remain after deletion
                    target_type = before.get("target_type")
                    target_id = before.get("target_id")
                    if target_type == "event" and target_id is not None:
                        await cursor.execute(
                            "SELECT event_kind FROM events WHERE id = %s",
                            (target_id,),
                        )
                        ev = await cursor.fetchone()
                        if ev and ev.get("event_kind") == "spec_request":
                            await cursor.execute(
                                """
                                SELECT COUNT(*) as cnt FROM spec_sessions
                                WHERE target_type = 'event' AND target_id = %s
                                  AND ended_at IS NULL AND deleted_at IS NULL
                                """,
                                (target_id,),
                            )
                            cnt_row = await cursor.fetchone()
                            if cnt_row and cnt_row["cnt"] == 0:
                                await cursor.execute(
                                    "UPDATE events SET is_active = FALSE WHERE id = %s",
                                    (target_id,),
                                )
                                self.logger.debug(f"Spec request event {target_id} auto-marked as inactive via admin soft-delete.")

                    await self._recalc_session_points_delta(conn, session_id, lock=False)

                    await cursor.execute(
                        """
                        SELECT 
                            ss.id, ss.pr_id, ss.target_type, ss.target_id,
                            CASE
                                WHEN ss.target_name IS NOT NULL THEN ss.target_name
                                WHEN ss.target_type = 'streamer' THEN s.streamer_name
                                WHEN ss.target_type = 'event' THEN e.name
                                ELSE NULL
                            END AS target_name,
                            ss.started_at, ss.ended_at,
                            ss.deleted_at, ss.deleted_by_id, ss.delete_reason, ss.credited_points
                        FROM spec_sessions ss
                        LEFT JOIN streamers s ON ss.target_type = 'streamer' AND ss.target_id = s.streamer_id
                        LEFT JOIN events e ON ss.target_type = 'event' AND ss.target_id = e.id
                        WHERE ss.id = %s
                        """,
                        (session_id,),
                    )
                    after = await cursor.fetchone()
                    await conn.commit()
                    return {"session_id": session_id, "before": before, "after": after}
        except Exception as e:
            self.logger.error(
                f"Failed to soft-delete session {session_id}: {e}", exc_info=True
            )
            return None

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
                            GREATEST(
                                DATEDIFF(CURRENT_TIMESTAMP, COALESCE(a.appointed_at, a.added_at, CURRENT_TIMESTAMP)),
                                0
                            ) as experience_days,
                            CASE WHEN act.id IS NOT NULL THEN 'assigned' ELSE 'free' END as status,
                            act.target_type as assigned_to_type, act.target_id as assigned_to_id, 
                            COALESCE(stats.total_secs, 0) as total_spec_seconds, 
                            COALESCE(stats.sess_count, 0) as session_count, a.added_at, a.appointed_at, a.updated_at,
                            ROUND(COALESCE(a.auto_points_total, 0), 4) as auto_points_total,
                            ROUND(COALESCE(a.manual_points_adjustment, 0), 4) as manual_points_adjustment,
                            ROUND(
                                COALESCE(
                                    a.total_points,
                                    COALESCE(a.auto_points_total, 0) + COALESCE(a.manual_points_adjustment, 0)
                                ),
                                4
                            ) as total_points,
                            ROUND(COALESCE(a.penalty_points, 0), 4) as penalty_points,
                            ROUND(COALESCE(a.penalty_percent, 0), 4) as penalty_percent,
                            COALESCE(a.warnings_units, 0) as warnings_units,
                            ROUND(
                                COALESCE(
                                    a.total_points,
                                    COALESCE(a.auto_points_total, 0) + COALESCE(a.manual_points_adjustment, 0)
                                ) - COALESCE(a.penalty_points, 0),
                                4
                            ) as display_points,
                            FLOOR(COALESCE(a.warnings_units, 0) / 2) as strict_warnings,
                            MOD(COALESCE(a.warnings_units, 0), 2) as oral_warnings,
                            CONCAT(
                                FLOOR(COALESCE(a.warnings_units, 0) / 2),
                                '/2 ',
                                MOD(COALESCE(a.warnings_units, 0), 2),
                                '/2'
                            ) as warnings_display,
                            COALESCE(s.streamer_name, e.name) as assigned_to_name,
                            ROUND(COALESCE(stats.total_secs, 0) / 3600, 1) as total_spec_hours,
                            ROUND(COALESCE(recent.total_secs_30d, 0) / 3600, 4) as total_spec_hours_30d,
                            ROUND((COALESCE(recent.total_secs_30d, 0) / 3600) / 30.0, 4) as avg_spec_hours_per_day_30d
                        FROM assistants a
                        LEFT JOIN spec_sessions act ON act.pr_id = a.pr_id 
                            AND act.ended_at IS NULL AND act.deleted_at IS NULL
                        LEFT JOIN (
                            SELECT pr_id, SUM(duration_seconds) as total_secs, COUNT(*) as sess_count
                            FROM spec_sessions WHERE deleted_at IS NULL AND ended_at IS NOT NULL
                            GROUP BY pr_id
                        ) stats ON stats.pr_id = a.pr_id
                        LEFT JOIN (
                            SELECT pr_id, SUM(seconds_in_day) as total_secs_30d
                            FROM spec_session_day_slices
                            WHERE work_date >= DATE_SUB(UTC_DATE(), INTERVAL 29 DAY)
                            GROUP BY pr_id
                        ) recent ON recent.pr_id = a.pr_id
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
                            GREATEST(
                                DATEDIFF(CURRENT_TIMESTAMP, COALESCE(a.appointed_at, a.added_at, CURRENT_TIMESTAMP)),
                                0
                            ) as experience_days,
                            CASE WHEN act.id IS NOT NULL THEN 'assigned' ELSE 'free' END as status,
                            act.target_type as assigned_to_type, act.target_id as assigned_to_id, 
                            COALESCE(stats.total_secs, 0) as total_spec_seconds, 
                            COALESCE(stats.sess_count, 0) as session_count, a.added_at, a.appointed_at, a.updated_at,
                            ROUND(COALESCE(a.auto_points_total, 0), 4) as auto_points_total,
                            ROUND(COALESCE(a.manual_points_adjustment, 0), 4) as manual_points_adjustment,
                            ROUND(
                                COALESCE(
                                    a.total_points,
                                    COALESCE(a.auto_points_total, 0) + COALESCE(a.manual_points_adjustment, 0)
                                ),
                                4
                            ) as total_points,
                            ROUND(COALESCE(a.penalty_points, 0), 4) as penalty_points,
                            ROUND(COALESCE(a.penalty_percent, 0), 4) as penalty_percent,
                            COALESCE(a.warnings_units, 0) as warnings_units,
                            ROUND(
                                COALESCE(
                                    a.total_points,
                                    COALESCE(a.auto_points_total, 0) + COALESCE(a.manual_points_adjustment, 0)
                                ) - COALESCE(a.penalty_points, 0),
                                4
                            ) as display_points,
                            FLOOR(COALESCE(a.warnings_units, 0) / 2) as strict_warnings,
                            MOD(COALESCE(a.warnings_units, 0), 2) as oral_warnings,
                            CONCAT(
                                FLOOR(COALESCE(a.warnings_units, 0) / 2),
                                '/2 ',
                                MOD(COALESCE(a.warnings_units, 0), 2),
                                '/2'
                            ) as warnings_display,
                            COALESCE(s.streamer_name, e.name) as assigned_to_name,
                            ROUND(COALESCE(stats.total_secs, 0) / 3600, 1) as total_spec_hours,
                            ROUND(COALESCE(recent.total_secs_30d, 0) / 3600, 4) as total_spec_hours_30d,
                            ROUND((COALESCE(recent.total_secs_30d, 0) / 3600) / 30.0, 4) as avg_spec_hours_per_day_30d
                        FROM assistants a
                        LEFT JOIN spec_sessions act ON act.pr_id = a.pr_id 
                            AND act.ended_at IS NULL AND act.deleted_at IS NULL
                        LEFT JOIN (
                            SELECT pr_id, SUM(duration_seconds) as total_secs, COUNT(*) as sess_count
                            FROM spec_sessions WHERE deleted_at IS NULL AND ended_at IS NOT NULL
                            GROUP BY pr_id
                        ) stats ON stats.pr_id = a.pr_id
                        LEFT JOIN (
                            SELECT pr_id, SUM(seconds_in_day) as total_secs_30d
                            FROM spec_session_day_slices
                            WHERE work_date >= DATE_SUB(UTC_DATE(), INTERVAL 29 DAY)
                            GROUP BY pr_id
                        ) recent ON recent.pr_id = a.pr_id
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
                          AND (ss.target_type != 'event' OR e.approval_status IS NULL OR e.approval_status != 'rejected')
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
                                unassign_action = (
                                    f"Unassigned ({end_reason}, {duration})"
                                )
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

                    logs.sort(
                        key=lambda item: to_epoch(item.get("created_at")), reverse=True
                    )
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
                            GREATEST(
                                DATEDIFF(CURRENT_TIMESTAMP, COALESCE(a.appointed_at, a.added_at, CURRENT_TIMESTAMP)),
                                0
                            ) as experience_days,
                            CASE WHEN act.id IS NOT NULL THEN 'assigned' ELSE 'free' END as status,
                            act.target_type as assigned_to_type, act.target_id as assigned_to_id, 
                            COALESCE(stats.total_secs, 0) as total_spec_seconds, 
                            COALESCE(stats.sess_count, 0) as session_count, a.added_at, a.appointed_at, a.updated_at,
                            ROUND(COALESCE(a.auto_points_total, 0), 4) as auto_points_total,
                            ROUND(COALESCE(a.manual_points_adjustment, 0), 4) as manual_points_adjustment,
                            ROUND(
                                COALESCE(
                                    a.total_points,
                                    COALESCE(a.auto_points_total, 0) + COALESCE(a.manual_points_adjustment, 0)
                                ),
                                4
                            ) as total_points,
                            ROUND(COALESCE(a.penalty_points, 0), 4) as penalty_points,
                            ROUND(COALESCE(a.penalty_percent, 0), 4) as penalty_percent,
                            COALESCE(a.warnings_units, 0) as warnings_units,
                            ROUND(
                                COALESCE(
                                    a.total_points,
                                    COALESCE(a.auto_points_total, 0) + COALESCE(a.manual_points_adjustment, 0)
                                ) - COALESCE(a.penalty_points, 0),
                                4
                            ) as display_points,
                            FLOOR(COALESCE(a.warnings_units, 0) / 2) as strict_warnings,
                            MOD(COALESCE(a.warnings_units, 0), 2) as oral_warnings,
                            CONCAT(
                                FLOOR(COALESCE(a.warnings_units, 0) / 2),
                                '/2 ',
                                MOD(COALESCE(a.warnings_units, 0), 2),
                                '/2'
                            ) as warnings_display,
                            COALESCE(s.streamer_name, e.name) as assigned_to_name,
                            ROUND(COALESCE(stats.total_secs, 0) / 3600, 1) as total_spec_hours,
                            ROUND(COALESCE(recent.total_secs_30d, 0) / 3600, 4) as total_spec_hours_30d,
                            ROUND((COALESCE(recent.total_secs_30d, 0) / 3600) / 30.0, 4) as avg_spec_hours_per_day_30d
                        FROM assistants a
                        LEFT JOIN spec_sessions act ON act.pr_id = a.pr_id 
                            AND act.ended_at IS NULL AND act.deleted_at IS NULL
                        LEFT JOIN (
                            SELECT pr_id, SUM(duration_seconds) as total_secs, COUNT(*) as sess_count
                            FROM spec_sessions WHERE deleted_at IS NULL AND ended_at IS NOT NULL
                            GROUP BY pr_id
                        ) stats ON stats.pr_id = a.pr_id
                        LEFT JOIN (
                            SELECT pr_id, SUM(seconds_in_day) as total_secs_30d
                            FROM spec_session_day_slices
                            WHERE work_date >= DATE_SUB(UTC_DATE(), INTERVAL 29 DAY)
                            GROUP BY pr_id
                        ) recent ON recent.pr_id = a.pr_id
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
        self,
        pr_id: int,
        nickname: str,
        role: str,
        experience_days: int = 0,
        appointed_at: Optional[date] = None,
    ) -> bool:
        """Create or update assistant profile."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    if appointed_at is not None:
                        appointed_at_dt = datetime.combine(
                            appointed_at, datetime.min.time(), tzinfo=timezone(timedelta(hours=3))
                        )
                        await cursor.execute(
                            """
                            INSERT INTO assistants (pr_id, nickname, role, appointed_at)
                            VALUES (%s, %s, %s, %s)
                            ON DUPLICATE KEY UPDATE
                                nickname = VALUES(nickname),
                                role = VALUES(role),
                                appointed_at = VALUES(appointed_at)
                            """,
                            (pr_id, nickname, role, appointed_at_dt),
                        )
                    else:
                        await cursor.execute(
                            """
                            INSERT INTO assistants (pr_id, nickname, role, appointed_at)
                            VALUES (%s, %s, %s, DATE_SUB(CURRENT_TIMESTAMP, INTERVAL %s DAY))
                            ON DUPLICATE KEY UPDATE
                                nickname = VALUES(nickname),
                                role = VALUES(role),
                                appointed_at = DATE_SUB(CURRENT_TIMESTAMP, INTERVAL %s DAY)
                            """,
                            (pr_id, nickname, role, experience_days, experience_days),
                        )
                    await conn.commit()
                    return True
        except Exception as e:
            self.logger.error(f"Failed to save assistant {pr_id}: {e}", exc_info=True)
            raise

    @db_retry()
    async def update_assistant_assignment(
        self,
        pr_id: int,
        assigned_to_type: Optional[str],
        assigned_to_id: Optional[int],
        assigned_to_name: Optional[str] = None,
    ) -> bool:
        """Compatibility helper: map assistant assignment updates to spec sessions."""
        try:
            if assigned_to_type is None:
                async with self.pool.acquire() as conn:
                    async with conn.cursor(aiomysql.DictCursor) as cursor:
                        await cursor.execute(
                            """
                            SELECT id
                            FROM spec_sessions
                            WHERE pr_id = %s
                              AND ended_at IS NULL
                              AND deleted_at IS NULL
                            FOR UPDATE
                            """,
                            (pr_id,),
                        )
                        row = await cursor.fetchone()
                        if not row:
                            return True
                        session_id = int(row["id"])
                        await cursor.execute(
                            """
                            UPDATE spec_sessions
                            SET ended_at = GREATEST(
                                    DATE_ADD(started_at, INTERVAL 1 SECOND),
                                    CURRENT_TIMESTAMP
                                ),
                                end_reason = 'manual_unclaim'
                            WHERE id = %s
                            """,
                            (session_id,),
                        )
                        await self._recalc_session_points_delta(
                            conn, session_id, lock=False
                        )
                        await conn.commit()
                        return True

            if assigned_to_id is None:
                return False
            if assigned_to_type == "streamer":
                return await self.assign_pr_to_streamer(assigned_to_id, pr_id)
            if assigned_to_type == "event":
                return await self.join_event(assigned_to_id, pr_id)
            return False
        except Exception as e:
            self.logger.error(
                f"Failed to update assignment for assistant {pr_id}: {e}",
                exc_info=True,
            )
            return False

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
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(
                        """
                        SELECT id, name
                        FROM events 
                        WHERE is_active = TRUE 
                          AND start_time <= CURRENT_TIMESTAMP 
                          AND (notification_sent IS FALSE OR notification_sent IS NULL)
                        """
                    )
                    events = await cursor.fetchall()

            # Add participants to each event
            results = []
            for e in events:
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
                               TIMESTAMPDIFF(SECOND, ss.started_at, CURRENT_TIMESTAMP) as duration_seconds
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
                               TIMESTAMPDIFF(SECOND, started_at, COALESCE(ended_at, CURRENT_TIMESTAMP)) as duration_seconds
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
    async def get_assistant_sessions_detailed(
        self,
        pr_id: int,
        limit: int = 50,
        include_deleted: bool = False,
    ) -> List[Dict[str, Any]]:
        """Get assistant sessions with full admin-editable fields."""
        try:
            limit = max(1, min(int(limit or 50), 200))
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    deleted_clause = "" if include_deleted else "AND ss.deleted_at IS NULL"
                    await cursor.execute(
                        f"""
                        SELECT
                            ss.id,
                            ss.pr_id,
                            ss.target_type,
                            ss.target_id,
                            CASE
                                WHEN ss.target_name IS NOT NULL THEN ss.target_name
                                WHEN ss.target_type = 'streamer' THEN s.streamer_name
                                WHEN ss.target_type = 'event' THEN e.name
                                ELSE NULL
                            END AS target_name,
                            ss.started_at,
                            ss.ended_at,
                            ss.duration_seconds,
                            ss.end_reason,
                            ss.is_probation,
                            ss.priority_auto,
                            ss.priority_override,
                            ss.rate_auto,
                            ss.rate_override,
                            ss.credited_points,
                            ss.deleted_at,
                            ss.delete_reason
                        FROM spec_sessions ss
                        LEFT JOIN streamers s
                            ON ss.target_type = 'streamer' AND ss.target_id = s.streamer_id
                        LEFT JOIN events e
                            ON ss.target_type = 'event' AND ss.target_id = e.id
                        WHERE ss.pr_id = %s
                          AND (ss.target_type <> 'event' OR e.approval_status = 'approved')
                          {deleted_clause}
                        ORDER BY ss.started_at DESC
                        LIMIT %s
                        """,
                        (pr_id, limit),
                    )
                    rows = await cursor.fetchall()
                    for row in rows:
                        row["pr_id"] = str(row["pr_id"])
                        if row.get("target_id") is not None:
                            row["target_id"] = str(row["target_id"])
                    return rows
        except Exception as e:
            self.logger.error(
                f"Failed to get detailed assistant sessions for {pr_id}: {e}",
                exc_info=True,
            )
            return []



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
        """Create a new web user (web_auth) and return its PK (discord_id)."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO web_auth (discord_id, username, password_hash, created_at) 
                        VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                        """,
                        (discord_id, username, password_hash),
                    )
                    await conn.commit()
                    return discord_id
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
                        SELECT w.discord_id, w.username, w.password_hash, w.is_active, w.require_password_change, w.failed_login_attempts, w.last_failed_login, w.last_login, w.created_at, a.role, a.nickname 
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
    async def get_user_by_discord_id(self, discord_id: int) -> Optional[Dict[str, Any]]:
        """Get user by Discord ID (joins assistants for role)."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT w.discord_id, w.username, w.password_hash, w.is_active, w.require_password_change, w.failed_login_attempts, w.last_failed_login, w.last_login, w.created_at, a.role, a.nickname
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
                        SELECT w.discord_id as id, w.discord_id, w.username, w.is_active, w.require_password_change, w.failed_login_attempts, w.last_login, w.created_at, 
                        COALESCE(a.role, 'employee') as role, 
                        COALESCE(a.nickname, w.username) as nickname,
                        rp.permissions
                        FROM web_auth w
                        LEFT JOIN assistants a ON a.pr_id = w.discord_id
                        LEFT JOIN role_permissions rp ON rp.role = COALESCE(a.role, 'employee')
                        WHERE w.discord_id = %s
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
                        WHERE discord_id = %s
                        """,
                        (user_id,),
                    )
                    await conn.commit()
        except Exception as e:
            self.logger.error(f"Failed to reset login stats: {e}", exc_info=True)

    @db_retry()
    async def create_session(
        self,
        user_id: int,
        refresh_token_hash: str,
        family_id: str,
        expires_at,
        ip: str,
        user_agent: str,
    ) -> int:
        """Create a new session with hashed refresh token and family chain."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO sessions 
                            (user_id, refresh_token_hash, family_id, expires_at, ip_address, last_ip, user_agent) 
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (user_id, refresh_token_hash, family_id, expires_at, ip, ip, user_agent),
                    )
                    await conn.commit()
                    return cursor.lastrowid
        except Exception as e:
            self.logger.error(f"Failed to create session: {e}", exc_info=True)
            raise

    @db_retry()
    async def find_session_by_refresh_hash(self, token_hash: str) -> Optional[Dict[str, Any]]:
        """Find a session by its refresh token hash (active or replaced)."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT id, user_id, refresh_token_hash, family_id, 
                               replaced_by_hash, expires_at, created_at,
                               revoked, revoked_at, ip_address, last_ip, user_agent
                        FROM sessions
                        WHERE refresh_token_hash = %s
                        LIMIT 1
                        """,
                        (token_hash,),
                    )
                    return await cursor.fetchone()
        except Exception as e:
            self.logger.error(f"Failed to find session by hash: {e}", exc_info=True)
            return None

    @db_retry()
    async def rotate_session(
        self,
        old_session_id: int,
        old_token_hash: str,
        new_token_hash: str,
        new_expires_at,
        new_ip: str,
        new_user_agent: str,
    ) -> Optional[int]:
        """
        Atomically rotate a refresh token: mark old as replaced, create new session in same family.

        Returns new session_id or None if the old session was already rotated/revoked (reuse detection).
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Lock the old session to prevent race conditions
                    await cursor.execute(
                        """
                        SELECT id, user_id, family_id, refresh_token_hash, 
                               revoked, replaced_by_hash, expires_at
                        FROM sessions
                        WHERE id = %s
                        FOR UPDATE
                        """,
                        (old_session_id,),
                    )
                    old_session = await cursor.fetchone()

                    if not old_session:
                        return None

                    # Reuse detection: if already replaced or revoked, it's a replay/theft
                    replaced_by_hash = old_session.get("replaced_by_hash")
                    if (
                        (replaced_by_hash is not None and str(replaced_by_hash).strip() != "")
                        or old_session["revoked"]
                    ):
                        return None  # Caller must handle reuse detection

                    # Mark old session as replaced
                    await cursor.execute(
                        """
                        UPDATE sessions 
                        SET replaced_by_hash = %s, revoked = TRUE, revoked_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                        """,
                        (new_token_hash, old_session_id),
                    )

                    # Create new session in the same family
                    await cursor.execute(
                        """
                        INSERT INTO sessions 
                            (user_id, refresh_token_hash, family_id, expires_at, ip_address, last_ip, user_agent) 
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            old_session["user_id"],
                            new_token_hash,
                            old_session["family_id"],
                            new_expires_at,
                            old_session.get("ip_address"),
                            new_ip,
                            new_user_agent,
                        ),
                    )
                    new_session_id = cursor.lastrowid

                    await conn.commit()
                    return new_session_id
        except Exception as e:
            self.logger.error(f"Failed to rotate session: {e}", exc_info=True)
            return None

    @db_retry()
    async def revoke_session_family(self, family_id: str) -> int:
        """Revoke ALL sessions in a token family (reuse detection response). Returns count."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        UPDATE sessions 
                        SET revoked = TRUE, revoked_at = CURRENT_TIMESTAMP 
                        WHERE family_id = %s AND revoked = FALSE
                        """,
                        (family_id,),
                    )
                    await conn.commit()
                    return cursor.rowcount
        except Exception as e:
            self.logger.error(f"Failed to revoke session family {family_id}: {e}", exc_info=True)
            return 0

    @db_retry()
    async def revoke_session(self, session_id: int) -> bool:
        """Revoke a single session by its ID."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        UPDATE sessions 
                        SET revoked = TRUE, revoked_at = CURRENT_TIMESTAMP 
                        WHERE id = %s AND revoked = FALSE
                        """,
                        (session_id,),
                    )
                    await conn.commit()
                    return cursor.rowcount > 0
        except Exception as e:
            self.logger.error(f"Failed to revoke session {session_id}: {e}", exc_info=True)
            return False

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
                          AND (replaced_by_hash IS NULL OR replaced_by_hash = '')
                          AND expires_at > CURRENT_TIMESTAMP
                        LIMIT 1
                        """,
                        (session_id, user_id),
                    )
                    return await cursor.fetchone() is not None
        except Exception as e:
            self.logger.error(f"Failed to validate session: {e}", exc_info=True)
            return False

    @db_retry()
    async def get_user_sessions(self, user_id: int) -> List[Dict[str, Any]]:
        """Get all active (non-revoked, non-expired) sessions for a user."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT id, ip_address, last_ip, user_agent, device_label,
                               created_at, expires_at
                        FROM sessions
                        WHERE user_id = %s
                          AND revoked = FALSE
                          AND (replaced_by_hash IS NULL OR replaced_by_hash = '')
                          AND expires_at > CURRENT_TIMESTAMP
                        ORDER BY created_at DESC
                        """,
                        (user_id,),
                    )
                    return await cursor.fetchall()
        except Exception as e:
            self.logger.error(f"Failed to get user sessions: {e}", exc_info=True)
            return []

    @db_retry()
    async def get_session_owner(self, session_id: int) -> Optional[int]:
        """Get the user_id that owns a given session."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT user_id FROM sessions WHERE id = %s",
                        (session_id,),
                    )
                    row = await cursor.fetchone()
                    return row["user_id"] if row else None
        except Exception as e:
            self.logger.error(f"Failed to get session owner: {e}", exc_info=True)
            return None

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

                    # 2. Count online GTA streamers
                    try:
                        await cursor.execute(
                            """
                            SELECT COUNT(*) as count 
                            FROM streamers s
                            WHERE s.is_online = TRUE
                              AND s.stream_game_id = %s
                            """,
                            (Config.gta5_game_id,),
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

    # =========================================================================
    # PR Action Logs (хронологическая лента закреплений/откреплений)
    # =========================================================================

    def _build_pr_action_filters(self, filters: dict):
        """Build WHERE clauses and params from filters dict for PR action logs."""
        where_parts = []
        params = []

        if filters.get("pr_id"):
            where_parts.append("ss.pr_id = %s")
            params.append(int(filters["pr_id"]))

        if filters.get("priority") is not None:
            where_parts.append("ss.applied_priority_level = %s")
            params.append(int(filters["priority"]))

        if filters.get("target_type") and filters["target_type"] != "all":
            where_parts.append("ss.target_type = %s")
            params.append(filters["target_type"])

        return where_parts, params

    def _build_date_filter_join(self, filters: dict, time_col: str):
        """Build date range filter for a specific time column."""
        parts = []
        params = []
        if filters.get("date_from"):
            parts.append(f"{time_col} >= %s")
            params.append(filters["date_from"])
        if filters.get("date_to"):
            parts.append(f"{time_col} <= %s")
            params.append(filters["date_to"])
        return parts, params

    @db_retry()
    async def get_pr_action_logs(
        self,
        limit: int = 20,
        offset: int = 0,
        filters: dict = None,
    ) -> dict:
        """
        Get PR action logs (joins/leaves) with pagination and filtering.

        Uses UNION ALL to split spec_sessions into individual join/leave events.
        Returns dict with 'items' and 'total'.
        """
        try:
            filters = filters or {}

            # Build shared WHERE clauses (applied to both halves of UNION)
            base_where, base_params = self._build_pr_action_filters(filters)

            # Date filters applied specifically to each half's time column
            join_date_parts, join_date_params = self._build_date_filter_join(filters, "ss.started_at")
            leave_date_parts, leave_date_params = self._build_date_filter_join(filters, "ss.ended_at")

            # Action type filter
            action_type_filter = filters.get("action_type")  # 'join' | 'leave' | None

            # === Build JOIN half ===
            join_where_parts = list(base_where) + join_date_parts
            join_where_parts.append("ss.deleted_at IS NULL")
            join_params = list(base_params) + join_date_params
            join_where_sql = "WHERE " + " AND ".join(join_where_parts) if join_where_parts else ""

            join_sql = f"""
                SELECT
                    ss.id as session_id,
                    ss.pr_id,
                    ss.target_type,
                    ss.target_id,
                    ss.started_at as action_time,
                    'join' as action_type,
                    NULL as duration_seconds,
                    ss.applied_priority_level as priority,
                    ss.is_probation,
                    ss.end_reason
                FROM spec_sessions ss
                {join_where_sql}
            """

            # === Build LEAVE half ===
            leave_where_parts = list(base_where) + leave_date_parts
            leave_where_parts.append("ss.ended_at IS NOT NULL")
            leave_where_parts.append("ss.deleted_at IS NULL")
            leave_params = list(base_params) + leave_date_params
            leave_where_sql = "WHERE " + " AND ".join(leave_where_parts) if leave_where_parts else ""

            leave_sql = f"""
                SELECT
                    ss.id as session_id,
                    ss.pr_id,
                    ss.target_type,
                    ss.target_id,
                    ss.ended_at as action_time,
                    'leave' as action_type,
                    ss.duration_seconds,
                    ss.applied_priority_level as priority,
                    ss.is_probation,
                    ss.end_reason
                FROM spec_sessions ss
                {leave_where_sql}
            """

            # Combine based on action_type filter
            if action_type_filter == "join":
                union_sql = join_sql
                union_params = join_params
            elif action_type_filter == "leave":
                union_sql = leave_sql
                union_params = leave_params
            else:
                union_sql = f"({join_sql}) UNION ALL ({leave_sql})"
                union_params = join_params + leave_params

            # Wrap in subquery for ordering and pagination, join names
            full_sql = f"""
                SELECT
                    u.session_id,
                    u.pr_id,
                    a.nickname as pr_nickname,
                    a.role as pr_role,
                    u.target_type,
                    u.target_id,
                    CASE
                        WHEN u.target_type = 'streamer' THEN s.streamer_name
                        WHEN u.target_type = 'event' THEN e.name
                        ELSE CAST(u.target_id AS CHAR)
                    END as target_name,
                    s.profile_image_url as target_avatar,
                    s.is_online as target_is_online,
                    u.action_time,
                    u.action_type,
                    u.duration_seconds,
                    u.priority,
                    u.is_probation,
                    u.end_reason
                FROM ({union_sql}) u
                LEFT JOIN assistants a ON u.pr_id = a.pr_id
                LEFT JOIN streamers s ON u.target_type = 'streamer' AND u.target_id = s.streamer_id
                LEFT JOIN events e ON u.target_type = 'event' AND u.target_id = e.id
                ORDER BY u.action_time DESC
                LIMIT %s OFFSET %s
            """
            full_params = tuple(union_params) + (limit, offset)

            # Count query
            count_sql = f"""
                SELECT COUNT(*) as total FROM ({union_sql}) u
            """
            count_params = tuple(union_params)

            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Get total count
                    await cursor.execute(count_sql, count_params)
                    count_result = await cursor.fetchone()
                    total = count_result["total"] if count_result else 0

                    # Get items
                    await cursor.execute(full_sql, full_params)
                    rows = await cursor.fetchall()

                    items = []
                    for row in rows:
                        item = dict(row)
                        item["pr_id"] = str(item["pr_id"]) if item.get("pr_id") else None
                        item["target_id"] = str(item["target_id"]) if item.get("target_id") else None
                        items.append(item)

                    return {
                        "items": items,
                        "total": total,
                    }
        except Exception as e:
            self.logger.error(f"Failed to get PR action logs: {e}", exc_info=True)
            return {"items": [], "total": 0}

    # ------------------------------------------------------------------
    # Punishment Returns
    # ------------------------------------------------------------------

    @db_retry()
    async def create_punishment_return(
        self,
        *,
        punishment_type: str,
        static: int,
        server: int,
        duration: int,
        remove_reason: str,
        discord_message_url: Optional[str],
        removed_by_id: int,
        removed_by_name: str,
    ) -> Optional[dict]:
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO punishment_returns (
                            punishment_type,
                            `static`,
                            server,
                            duration,
                            remove_reason,
                            discord_message_url,
                            removed_by_id,
                            removed_by_name
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            punishment_type,
                            int(static),
                            int(server),
                            int(duration),
                            remove_reason,
                            discord_message_url,
                            int(removed_by_id),
                            removed_by_name,
                        ),
                    )
                    return_id = cursor.lastrowid
                    await conn.commit()

            return await self.get_punishment_return(return_id)
        except Exception as e:
            self.logger.error(f"Failed to create punishment return: {e}", exc_info=True)
            return None

    @db_retry()
    async def get_punishment_return(self, return_id: int) -> Optional[dict]:
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT
                            id,
                            punishment_type,
                            `static`,
                            server,
                            duration,
                            remove_reason,
                            discord_message_url,
                            removed_by_id,
                            removed_by_name,
                            removed_at,
                            claimed_by_id,
                            claimed_by_name,
                            claimed_at,
                            completed_by_id,
                            completed_by_name,
                            completed_at,
                            status,
                            created_at,
                            updated_at
                        FROM punishment_returns
                        WHERE id = %s
                        LIMIT 1
                        """,
                        (int(return_id),),
                    )
                    row = await cursor.fetchone()
                    return dict(row) if row else None
        except Exception as e:
            self.logger.error(f"Failed to get punishment return: {e}", exc_info=True)
            return None

    @db_retry()
    async def list_punishment_returns_queue(self) -> list[dict]:
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT
                            id,
                            punishment_type,
                            `static`,
                            server,
                            duration,
                            remove_reason,
                            discord_message_url,
                            removed_by_id,
                            removed_by_name,
                            removed_at,
                            claimed_by_id,
                            claimed_by_name,
                            claimed_at,
                            completed_by_id,
                            completed_by_name,
                            completed_at,
                            status,
                            created_at,
                            updated_at
                        FROM punishment_returns
                        WHERE status IN ('pending', 'claimed')
                        ORDER BY
                            CASE
                                WHEN status = 'pending'
                                  AND TIMESTAMPADD(HOUR, 12, removed_at) <= CURRENT_TIMESTAMP THEN 0
                                WHEN status = 'claimed' THEN 1
                                ELSE 2
                            END ASC,
                            removed_at ASC,
                            id ASC
                        """
                    )
                    rows = await cursor.fetchall() or []
                    return [dict(row) for row in rows]
        except Exception as e:
            self.logger.error(
                f"Failed to list punishment returns queue: {e}",
                exc_info=True,
            )
            return []

    @db_retry()
    async def claim_punishment_return(
        self,
        return_id: int,
        *,
        claimed_by_id: int,
        claimed_by_name: str,
    ) -> Optional[dict]:
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        UPDATE punishment_returns
                        SET
                            status = 'claimed',
                            claimed_by_id = %s,
                            claimed_by_name = %s,
                            claimed_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                          AND status = 'pending'
                          AND TIMESTAMPADD(HOUR, 12, removed_at) <= CURRENT_TIMESTAMP
                        """,
                        (int(claimed_by_id), claimed_by_name, int(return_id)),
                    )
                    updated = cursor.rowcount > 0
                    await conn.commit()

            if not updated:
                return None
            return await self.get_punishment_return(return_id)
        except Exception as e:
            self.logger.error(f"Failed to claim punishment return: {e}", exc_info=True)
            return None

    @db_retry()
    async def complete_punishment_return(
        self,
        return_id: int,
        *,
        completed_by_id: int,
        completed_by_name: str,
        claimer_only: bool = True,
    ) -> Optional[dict]:
        try:
            params: list[Any] = [int(completed_by_id), completed_by_name, int(return_id)]
            where_sql = "status = 'claimed'"
            if claimer_only:
                where_sql += " AND claimed_by_id = %s"
                params.append(int(completed_by_id))

            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        f"""
                        UPDATE punishment_returns
                        SET
                            status = 'completed',
                            completed_by_id = %s,
                            completed_by_name = %s,
                            completed_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                          AND {where_sql}
                        """,
                        tuple(params),
                    )
                    updated = cursor.rowcount > 0
                    await conn.commit()

            if not updated:
                return None
            return await self.get_punishment_return(return_id)
        except Exception as e:
            self.logger.error(
                f"Failed to complete punishment return: {e}",
                exc_info=True,
            )
            return None

    @db_retry()
    async def release_punishment_return(
        self,
        return_id: int,
        *,
        claimed_by_id: int,
        claimer_only: bool = True,
    ) -> Optional[dict]:
        try:
            params: list[Any] = [int(return_id)]
            where_sql = "status = 'claimed'"
            if claimer_only:
                where_sql += " AND claimed_by_id = %s"
                params.append(int(claimed_by_id))

            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        f"""
                        UPDATE punishment_returns
                        SET
                            status = 'pending',
                            claimed_by_id = NULL,
                            claimed_by_name = NULL,
                            claimed_at = NULL
                        WHERE id = %s
                          AND {where_sql}
                        """,
                        tuple(params),
                    )
                    updated = cursor.rowcount > 0
                    await conn.commit()

            if not updated:
                return None
            return await self.get_punishment_return(return_id)
        except Exception as e:
            self.logger.error(
                f"Failed to release punishment return: {e}",
                exc_info=True,
            )
            return None

    @db_retry()
    async def update_punishment_return(
        self,
        return_id: int,
        updates: dict[str, Any],
    ) -> Optional[dict]:
        filtered_updates = {
            key: value
            for key, value in updates.items()
            if key
            in {
                "punishment_type",
                "static",
                "server",
                "duration",
                "remove_reason",
                "discord_message_url",
            }
        }
        if not filtered_updates:
            return await self.get_punishment_return(return_id)

        column_map = {
            "punishment_type": "punishment_type",
            "static": "`static`",
            "server": "server",
            "duration": "duration",
            "remove_reason": "remove_reason",
            "discord_message_url": "discord_message_url",
        }

        set_parts: list[str] = []
        params: list[Any] = []
        for key, value in filtered_updates.items():
            set_parts.append(f"{column_map[key]} = %s")
            params.append(value)
        params.append(int(return_id))

        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        f"""
                        UPDATE punishment_returns
                        SET {", ".join(set_parts)}
                        WHERE id = %s
                        """,
                        tuple(params),
                    )
                    updated = cursor.rowcount > 0
                    await conn.commit()

            if not updated:
                return None
            return await self.get_punishment_return(return_id)
        except Exception as e:
            self.logger.error(f"Failed to update punishment return: {e}", exc_info=True)
            return None

    @db_retry()
    async def delete_punishment_return(self, return_id: int) -> bool:
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "DELETE FROM punishment_returns WHERE id = %s",
                        (int(return_id),),
                    )
                    deleted = cursor.rowcount > 0
                    await conn.commit()
                    return deleted
        except Exception as e:
            self.logger.error(f"Failed to delete punishment return: {e}", exc_info=True)
            return False

    @db_retry()
    async def get_punishment_return_history(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        filters: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        filters = filters or {}
        where_clauses = ["status = 'completed'"]
        params: list[Any] = []

        if filters.get("static") is not None:
            where_clauses.append("`static` = %s")
            params.append(int(filters["static"]))

        if filters.get("server") is not None:
            where_clauses.append("server = %s")
            params.append(int(filters["server"]))

        if filters.get("punishment_type"):
            where_clauses.append("punishment_type = %s")
            params.append(filters["punishment_type"])

        if filters.get("removed_by_name"):
            where_clauses.append("removed_by_name LIKE %s")
            params.append(f"%{filters['removed_by_name']}%")

        if filters.get("completed_by_name"):
            where_clauses.append("completed_by_name LIKE %s")
            params.append(f"%{filters['completed_by_name']}%")

        if filters.get("date_from"):
            where_clauses.append("completed_at >= %s")
            params.append(filters["date_from"])

        if filters.get("date_to"):
            where_clauses.append("completed_at <= %s")
            params.append(filters["date_to"])

        where_sql = "WHERE " + " AND ".join(where_clauses)

        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        f"""
                        SELECT COUNT(*) AS total
                        FROM punishment_returns
                        {where_sql}
                        """,
                        tuple(params),
                    )
                    total_row = await cursor.fetchone() or {}
                    total = int(total_row.get("total", 0))

                    await cursor.execute(
                        f"""
                        SELECT
                            id,
                            punishment_type,
                            `static`,
                            server,
                            duration,
                            remove_reason,
                            discord_message_url,
                            removed_by_id,
                            removed_by_name,
                            removed_at,
                            claimed_by_id,
                            claimed_by_name,
                            claimed_at,
                            completed_by_id,
                            completed_by_name,
                            completed_at,
                            status,
                            created_at,
                            updated_at
                        FROM punishment_returns
                        {where_sql}
                        ORDER BY completed_at DESC, id DESC
                        LIMIT %s OFFSET %s
                        """,
                        tuple(params) + (int(limit), int(offset)),
                    )
                    rows = await cursor.fetchall() or []
                    return {
                        "items": [dict(row) for row in rows],
                        "total": total,
                    }
        except Exception as e:
            self.logger.error(
                f"Failed to get punishment return history: {e}",
                exc_info=True,
            )
            return {"items": [], "total": 0}
