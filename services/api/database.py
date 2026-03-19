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
from typing import Any, Dict, List, Optional, Set

import aiomysql
from config import Config  # NOTE: kept for potential future use by views migration

SPEC_SESSION_END_REASONS = (
    "manual_unclaim",
    "stream_end",
    "category_change",
    "admin_closed",
    "event_end",
    "event_rejected",
    "unknown",
)
SPEC_SESSION_END_REASON_VALUES_SQL = ", ".join(
    f"'{reason}'" for reason in SPEC_SESSION_END_REASONS
)
SPEC_SESSION_END_REASON_UNKNOWN = "unknown"
SPEC_SESSION_END_REASON_ADMIN_CLOSED = "admin_closed"
BROKER_OUTBOX_STATUS_PENDING = "pending"
BROKER_OUTBOX_STATUS_PROCESSING = "processing"
BROKER_OUTBOX_STATUS_SENT = "sent"
SANCTIONS_GLOBAL_LOCK_NAME = "prmajesticbot:sanctions:global"
SANCTIONS_NIGHTLY_STALE_SECONDS = 3600
CURRENT_SANCTION_POLICY_MONTH = date(2000, 1, 1)
FIXED_SIZE_SANCTION_KINDS = {"check", "oral", "strict"}
WARNING_SANCTION_KINDS = {"oral", "strict"}
MSK = timezone(timedelta(hours=3))
WEEKLY_DAY_STATUS_VALUES = ("P", "U", "O")
WEEKLY_MANUAL_STATUSES = set(WEEKLY_DAY_STATUS_VALUES)
LEAVE_MANUAL_STATUSES = {"U", "O"}
WEEKLY_MANUAL_STATUS_NONE = "NONE"
WEEKLY_SUGGESTED_RESULT_ULTRA = "Ультра-Актив"
WEEKLY_SUGGESTED_RESULT_ACTIVE = "Актив"
WEEKLY_SUGGESTED_RESULT_MIXED = "Инактив/Актив"
WEEKLY_SUGGESTED_RESULT_INACTIVE = "Инактив"
WEEKLY_SUGGESTED_RESULT_OPTIONS = (
    WEEKLY_SUGGESTED_RESULT_ULTRA,
    WEEKLY_SUGGESTED_RESULT_ACTIVE,
    WEEKLY_SUGGESTED_RESULT_MIXED,
    WEEKLY_SUGGESTED_RESULT_INACTIVE,
)
WEEKLY_SUGGESTED_RESULTS = set(WEEKLY_SUGGESTED_RESULT_OPTIONS)
WEEKLY_SELECTED_RESULT_OPTIONS = (
    WEEKLY_SUGGESTED_RESULT_ULTRA,
    WEEKLY_SUGGESTED_RESULT_ACTIVE,
    "Актив/Отпуск",
    WEEKLY_SUGGESTED_RESULT_INACTIVE,
    "Инактив/Отпуск",
    "Отпуск",
    WEEKLY_SUGGESTED_RESULT_MIXED,
)
WEEKLY_SELECTED_RESULTS = set(WEEKLY_SELECTED_RESULT_OPTIONS)
WEEKLY_RESULT_ALIASES = {
    "Ультра-актив": WEEKLY_SUGGESTED_RESULT_ULTRA,
    WEEKLY_SUGGESTED_RESULT_ULTRA: WEEKLY_SUGGESTED_RESULT_ULTRA,
}
WEEKLY_PAYOUT_TYPES = ("EXP", "Premium", "MC", "MONEY")
WEEKLY_PAYOUT_ISSUE_STATUS_PENDING = "pending"
WEEKLY_PAYOUT_ISSUE_STATUS_ISSUED = "issued"
WEEKLY_PAYOUT_ISSUE_STATUS_OPTIONS = (
    WEEKLY_PAYOUT_ISSUE_STATUS_PENDING,
    WEEKLY_PAYOUT_ISSUE_STATUS_ISSUED,
)
WEEKLY_PAYOUT_ISSUE_STATUSES = set(WEEKLY_PAYOUT_ISSUE_STATUS_OPTIONS)
WEEKLY_PAYOUT_TYPE_COMMANDS = {
    "EXP": "giveexp",
    "Premium": "setvip",
    "MC": "givedonate",
    "MONEY": "givemoney",
}
WEEKLY_PAYOUT_ROLE_GROUPS = {
    "junior_employee": "junior",
    "employee": "default",
    "senior_employee": "Senior",
    "manager": "default",
    "developer": "default",
}
WEEKLY_PAYOUT_AMOUNT_RULES = {
    ("junior", "EXP", WEEKLY_SUGGESTED_RESULT_ACTIVE): "20000",
    ("junior", "EXP", WEEKLY_SUGGESTED_RESULT_ULTRA): "35000",
    ("junior", "Premium", WEEKLY_SUGGESTED_RESULT_ACTIVE): "4",
    ("junior", "Premium", WEEKLY_SUGGESTED_RESULT_ULTRA): "7",
    ("junior", "MC", WEEKLY_SUGGESTED_RESULT_ACTIVE): "1000",
    ("junior", "MC", WEEKLY_SUGGESTED_RESULT_ULTRA): "1200",
    ("junior", "MONEY", WEEKLY_SUGGESTED_RESULT_ACTIVE): "150000",
    ("junior", "MONEY", WEEKLY_SUGGESTED_RESULT_ULTRA): "200000",
    ("default", "EXP", WEEKLY_SUGGESTED_RESULT_ACTIVE): "35000",
    ("default", "EXP", WEEKLY_SUGGESTED_RESULT_ULTRA): "50000",
    ("default", "Premium", WEEKLY_SUGGESTED_RESULT_ACTIVE): "7",
    ("default", "Premium", WEEKLY_SUGGESTED_RESULT_ULTRA): "14",
    ("default", "MC", WEEKLY_SUGGESTED_RESULT_ACTIVE): "1200",
    ("default", "MC", WEEKLY_SUGGESTED_RESULT_ULTRA): "2000",
    ("default", "MONEY", WEEKLY_SUGGESTED_RESULT_ACTIVE): "200000",
    ("default", "MONEY", WEEKLY_SUGGESTED_RESULT_ULTRA): "250000",
    ("Senior", "EXP", WEEKLY_SUGGESTED_RESULT_ACTIVE): "35000",
    ("Senior", "EXP", WEEKLY_SUGGESTED_RESULT_ULTRA): "50000",
    ("Senior", "Premium", WEEKLY_SUGGESTED_RESULT_ACTIVE): "7",
    ("Senior", "Premium", WEEKLY_SUGGESTED_RESULT_ULTRA): "14",
    ("Senior", "MC", WEEKLY_SUGGESTED_RESULT_ACTIVE): "1200",
    ("Senior", "MC", WEEKLY_SUGGESTED_RESULT_ULTRA): "2000",
    ("Senior", "MONEY", WEEKLY_SUGGESTED_RESULT_ACTIVE): "200000",
    ("Senior", "MONEY", WEEKLY_SUGGESTED_RESULT_ULTRA): "250000",
}
WEEKLY_PAYOUT_SERVERS = tuple(f"RU{i}" for i in range(1, 19))
WEEKLY_PAYOUT_SUFFIX = "pr-assist_byStynee"


def _msk_now() -> datetime:
    return datetime.now(MSK)


def _msk_today() -> date:
    return _msk_now().date()


def _week_start_msk(value: Optional[date] = None) -> date:
    target = value or _msk_today()
    return target - timedelta(days=target.weekday())


def _week_dates(week_start: date) -> List[date]:
    return [week_start + timedelta(days=index) for index in range(7)]


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _date_only(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _canonical_weekly_result(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = WEEKLY_RESULT_ALIASES.get(str(value).strip(), str(value).strip())
    return normalized or None


def _canonical_weekly_payout_issue_status(value: Optional[str]) -> str:
    normalized = str(value or WEEKLY_PAYOUT_ISSUE_STATUS_PENDING).strip().lower()
    if normalized not in WEEKLY_PAYOUT_ISSUE_STATUSES:
        return WEEKLY_PAYOUT_ISSUE_STATUS_PENDING
    return normalized


def _weekly_role_group(role: Optional[str]) -> str:
    if role == "junior_employee":
        return "junior"
    if role == "senior_employee":
        return "Senior"
    return "default"


def _sum_numeric(values: List[float]) -> float:
    return round(sum(float(value or 0) for value in values), 4)


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
        self,
        db_host: str,
        db_port: int,
        db_user: str,
        db_password: str,
        db_name: str,
        logger,
    ) -> None:
        """Initialize database configuration.

        Args:
            db_host: MySQL server hostname
            db_port: MySQL server port
            db_user: Database username
            db_password: Database password
            db_name: Database name
            logger: Logger instance for this module
        """
        self.pool: Optional[aiomysql.Pool] = None
        self.db_host = db_host
        self.db_port = db_port
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
                port=self.db_port,
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
                            stream_title VARCHAR(255),
                            stream_thumbnail_url VARCHAR(512),
                            profile_image_url VARCHAR(512),
                            stream_game_id BIGINT UNSIGNED,
                            stream_game_name VARCHAR(255),
                            stream_started_at DATETIME NULL,
                            priority INT DEFAULT 0,
                            pr_slots INT DEFAULT 1,
                            added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            added_by_id BIGINT UNSIGNED,
                            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            allow_juniors BOOLEAN DEFAULT TRUE,
                            priority_override INT DEFAULT NULL,
                            pr_slots_override INT DEFAULT NULL,
                            UNIQUE(streamer_name),
                            INDEX idx_streamers_online_order (is_online, is_pinned, priority, streamer_name)
                        )
                        """
                    )

                    # =========================================================
                    # 2. Settings Table
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS settings (
                            id INT PRIMARY KEY DEFAULT 1,
                            notification_channel_id BIGINT UNSIGNED,
                            monitoring_channel_id BIGINT UNSIGNED,
                            monitoring_message_id BIGINT,
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
                            added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            appointed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            dismissed_at DATETIME NULL
                        )
                        """
                    )

                    # =========================================================
                    # 4. Spec Sessions Table
                    # =========================================================
                    await cursor.execute(
                        f"""
                        CREATE TABLE IF NOT EXISTS spec_sessions (
                            id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            pr_id BIGINT UNSIGNED NOT NULL,
                            
                            target_type ENUM('streamer', 'event', 'manual') NOT NULL DEFAULT 'streamer',
                            target_id BIGINT UNSIGNED NULL,
                            target_name VARCHAR(255) NULL,
                            is_probation BOOLEAN DEFAULT FALSE,
                            
                            started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            ended_at DATETIME NULL,
                            end_reason ENUM({SPEC_SESSION_END_REASON_VALUES_SQL}) NULL,
                            
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
                            deleted_at DATETIME NULL,
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
                            INDEX idx_target_started (target_type, target_id, started_at),
                            INDEX idx_target_active (target_type, target_id, ended_at, deleted_at),
                            INDEX idx_pr_active (pr_id, ended_at, deleted_at)
                        )
                        """
                    )

                    # =========================================================
                    # 5. Events Table
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS events (
                            id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            name VARCHAR(255) NOT NULL,
                            description TEXT,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            start_time DATETIME NULL,
                            is_active BOOLEAN DEFAULT TRUE,
                            notification_sent BOOLEAN DEFAULT FALSE,
                            required_pr_count INT DEFAULT 1,
                            priority INT DEFAULT 0,
                            pr_slots INT DEFAULT 1,
                            created_by BIGINT UNSIGNED,
                            is_pinned BOOLEAN DEFAULT FALSE,
                            event_kind ENUM('regular','spec_request') NOT NULL DEFAULT 'regular',
                            approval_status ENUM('approved','pending','rejected') NOT NULL DEFAULT 'approved',
                            requested_by BIGINT UNSIGNED NULL,
                            approved_by BIGINT UNSIGNED NULL,
                            approved_at DATETIME NULL,
                            rejected_by BIGINT UNSIGNED NULL,
                            rejected_at DATETIME NULL,
                            points FLOAT NULL,
                            INDEX idx_events_active_order (is_active, is_pinned, priority, start_time),
                            INDEX idx_events_kind_status_active (event_kind, approval_status, is_active),
                            INDEX idx_events_requested_by_active (requested_by, is_active)
                        )
                        """
                    )
                    
                    # =========================================================
                    # 5.5. Event Participants Table
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS event_participants (
                            event_id INT UNSIGNED NOT NULL,
                            pr_id BIGINT UNSIGNED NOT NULL,
                            joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            PRIMARY KEY (event_id, pr_id),
                            FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
                        )
                        """
                    )

                    # =========================================================
                    # 6. Web Auth Table
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
                            last_login TIMESTAMP NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            last_failed_login TIMESTAMP NULL
                        )
                        """
                    )

                    # =========================================================
                    # 7. Sessions Table
                    # =========================================================
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

                    # =========================================================
                    # 8. Auth Logs Table
                    # =========================================================
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

                    # =========================================================
                    # 9. Role Permissions Table
                    # =========================================================
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
                    # 10. Service Principals Table
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS service_principals (
                            name VARCHAR(100) PRIMARY KEY,
                            token_hash VARCHAR(64) NOT NULL UNIQUE,
                            permissions JSON NOT NULL,
                            is_active BOOLEAN NOT NULL DEFAULT TRUE,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            INDEX idx_service_token_hash (token_hash)
                        )
                        """
                    )

                    # service_principals hash-only migration, guarded fail-fast
                    await self._migrate_service_principals_hash_only(cursor)

                    # =========================================================
                    # 11. Admin Logs Table
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS admin_logs (
                            id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            action VARCHAR(100) NOT NULL,
                            target_type VARCHAR(50),
                            target_id VARCHAR(100),
                            details JSON NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            actor_name VARCHAR(255) NOT NULL,
                            actor_role VARCHAR(50),
                            INDEX idx_created_at (created_at),
                            INDEX idx_action_created (action, created_at),
                            INDEX idx_actor_created (actor_name, created_at),
                            INDEX idx_target_created (target_type, target_id, created_at)
                        )
                        """
                    )

                    # =========================================================
                    # 12. Punishment Returns Table
                    # =========================================================
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

                    # =========================================================
                    # 13. Day-Based Manual Adjustments
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS assistant_day_point_adjustments (
                            assistant_id BIGINT UNSIGNED NOT NULL,
                            work_date DATE NOT NULL,
                            delta_points FLOAT NOT NULL DEFAULT 0,
                            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            PRIMARY KEY (assistant_id, work_date),
                            INDEX idx_day_point_adjustments_work_date (work_date)
                        )
                        """
                    )

                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS assistant_day_mchat (
                            assistant_id BIGINT UNSIGNED NOT NULL,
                            work_date DATE NOT NULL,
                            mchat_count INT UNSIGNED NOT NULL DEFAULT 0,
                            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            PRIMARY KEY (assistant_id, work_date),
                            INDEX idx_day_mchat_work_date (work_date)
                        )
                        """
                    )

                    # =========================================================
                    # 14. Weekly Assistant Statistics
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS assistant_day_status_overrides (
                            assistant_id BIGINT UNSIGNED NOT NULL,
                            work_date DATE NOT NULL,
                            manual_status ENUM('P', 'U', 'O', 'NONE') NOT NULL,
                            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            updated_by_id BIGINT UNSIGNED NULL,
                            PRIMARY KEY (assistant_id, work_date),
                            INDEX idx_day_status_overrides_work_date (work_date),
                            INDEX idx_day_status_overrides_updated_by (updated_by_id)
                        )
                        """
                    )
                    await cursor.execute(
                        """
                        ALTER TABLE assistant_day_status_overrides
                        MODIFY COLUMN manual_status ENUM('P', 'U', 'O', 'NONE') NOT NULL
                        """
                    )

                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS assistant_weekly_reviews (
                            assistant_id BIGINT UNSIGNED NOT NULL,
                            week_start DATE NOT NULL,
                            selected_result ENUM(
                                'Ультра-Актив',
                                'Актив',
                                'Актив/Отпуск',
                                'Инактив',
                                'Инактив/Отпуск',
                                'Отпуск',
                                'Инактив/Актив'
                            ) NULL,
                            payout_type ENUM('EXP', 'Premium', 'MC', 'MONEY') NULL,
                            payout_server VARCHAR(16) NULL,
                            payout_static VARCHAR(64) NULL,
                            payout_issue_status ENUM('pending', 'issued') NOT NULL DEFAULT 'pending',
                            payout_issued_at DATETIME NULL,
                            payout_issued_by_id BIGINT UNSIGNED NULL,
                            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            updated_by_id BIGINT UNSIGNED NULL,
                            PRIMARY KEY (assistant_id, week_start),
                            INDEX idx_weekly_reviews_week_start (week_start),
                            INDEX idx_weekly_reviews_updated_by (updated_by_id)
                        )
                        """
                    )

                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS assistant_weekly_payout_type_rules (
                            payout_type ENUM('EXP', 'Premium', 'MC', 'MONEY') PRIMARY KEY,
                            command_name VARCHAR(64) NOT NULL,
                            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                        )
                        """
                    )

                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS assistant_weekly_payout_amount_rules (
                            role_group ENUM('junior', 'default', 'Senior') NOT NULL,
                            payout_type ENUM('EXP', 'Premium', 'MC', 'MONEY') NOT NULL,
                            result_code ENUM('Актив', 'Ультра-Актив') NOT NULL,
                            amount VARCHAR(64) NOT NULL,
                            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            PRIMARY KEY (role_group, payout_type, result_code)
                        )
                        """
                    )

                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS assistant_weekly_payout_servers (
                            server_code VARCHAR(16) PRIMARY KEY,
                            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                        )
                        """
                    )

                    # =========================================================
                    # 15. Complaints
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS complaints (
                            id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            assistant_id BIGINT UNSIGNED NULL,
                            status ENUM('pending', 'claimed', 'completed', 'cancelled') NOT NULL DEFAULT 'pending',
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            claimed_at DATETIME NULL,
                            completed_at DATETIME NULL,
                            cancelled_at DATETIME NULL,
                            INDEX idx_complaints_assistant_status (assistant_id, status),
                            INDEX idx_complaints_completed (completed_at)
                        )
                        """
                    )

                    # =========================================================
                    # 16. Monthly Sanction Policies
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS monthly_sanction_settings (
                            month_start DATE PRIMARY KEY,
                            check_cycle_size INT UNSIGNED NOT NULL DEFAULT 5,
                            check_immunity_hours_per_day FLOAT NOT NULL DEFAULT 4,
                            point_immunity_hours_per_day FLOAT NOT NULL DEFAULT 5,
                            percent_immunity_hours_per_day FLOAT NOT NULL DEFAULT 6,
                            check_relief_hours_per_day FLOAT NOT NULL DEFAULT 4,
                            point_relief_hours_per_day FLOAT NOT NULL DEFAULT 5,
                            percent_relief_hours_per_day FLOAT NOT NULL DEFAULT 6,
                            check_relief_min_streak_days INT UNSIGNED NOT NULL DEFAULT 2,
                            point_relief_min_streak_days INT UNSIGNED NOT NULL DEFAULT 2,
                            percent_relief_min_streak_days INT UNSIGNED NOT NULL DEFAULT 2,
                            percent_relief_step_amount FLOAT NOT NULL DEFAULT 3,
                            daily_norm_spec FLOAT NOT NULL DEFAULT 4,
                            daily_norm_complaints INT UNSIGNED NOT NULL DEFAULT 0,
                            daily_norm_mchat INT UNSIGNED NOT NULL DEFAULT 0,
                            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                        )
                        """
                    )

                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS monthly_check_rules (
                            id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            month_start DATE NOT NULL,
                            range_start INT UNSIGNED NOT NULL,
                            range_end INT UNSIGNED NULL,
                            penalty_kind ENUM('point', 'percent', 'oral', 'strict') NOT NULL,
                            penalty_amount FLOAT NOT NULL,
                            INDEX idx_check_rules_month (month_start, range_start, range_end)
                        )
                        """
                    )

                    # =========================================================
                    # 17. Sanction Operations
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS sanction_operations (
                            id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            operation_date DATE NOT NULL,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            created_by_id BIGINT UNSIGNED NULL,
                            penalty_kind ENUM('check', 'point', 'percent', 'oral', 'strict') NOT NULL,
                            penalty_amount FLOAT NOT NULL,
                            auto_relief_date DATE NULL,
                            recipient_mode ENUM('all_active', 'live_without_active_session', 'selected_only') NOT NULL,
                            status ENUM('queued', 'processing', 'completed', 'cancelled', 'failed') NOT NULL DEFAULT 'queued',
                            processing_mode ENUM('manual_now', 'nightly_auto') NULL,
                            processed_by_id BIGINT UNSIGNED NULL,
                            queued_at DATETIME NULL,
                            processed_at DATETIME NULL,
                            cancelled_at DATETIME NULL,
                            failure_reason TEXT NULL,
                            INDEX idx_sanction_operations_date_status (operation_date, status),
                            INDEX idx_sanction_operations_creator (created_by_id, created_at),
                            INDEX idx_sanction_operations_processed_by (processed_by_id, processed_at)
                        )
                        """
                    )

                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS sanction_operation_members (
                            operation_id BIGINT UNSIGNED NOT NULL,
                            assistant_id BIGINT UNSIGNED NOT NULL,
                            issue_status ENUM('pending', 'issued', 'skipped_immunity', 'skipped_leave', 'failed') NOT NULL DEFAULT 'pending',
                            issue_reason VARCHAR(255) NULL,
                            issued_sanction_id BIGINT UNSIGNED NULL,
                            PRIMARY KEY (operation_id, assistant_id),
                            INDEX idx_operation_members_status (operation_id, issue_status),
                            INDEX idx_operation_members_sanction (issued_sanction_id)
                        )
                        """
                    )

                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS sanction_operation_workoffs (
                            id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            operation_id BIGINT UNSIGNED NOT NULL,
                            metric ENUM('spec', 'complaints', 'mchat') NOT NULL,
                            multiplier FLOAT NOT NULL,
                            period_start DATE NOT NULL,
                            period_end DATE NOT NULL,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE KEY uq_operation_workoff_metric (operation_id, metric),
                            INDEX idx_operation_workoffs_period (period_start, period_end)
                        )
                        """
                    )

                    # =========================================================
                    # 18. Sanction Ledger
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS assistant_sanctions (
                            id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            assistant_id BIGINT UNSIGNED NOT NULL,
                            kind ENUM('check', 'point', 'percent', 'oral', 'strict') NOT NULL,
                            amount_total FLOAT NOT NULL,
                            auto_relief_date DATE NULL,
                            issued_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            source_type ENUM('manual', 'queued_batch', 'check_cycle', 'legacy_migration') NOT NULL,
                            operation_id BIGINT UNSIGNED NULL,
                            basis_date DATE NULL,
                            settings_month DATE NULL,
                            check_rule_hit_no INT UNSIGNED NULL,
                            replaced_by_sanction_id BIGINT UNSIGNED NULL,
                            INDEX idx_assistant_sanctions_assistant_kind (assistant_id, kind, issued_at),
                            INDEX idx_assistant_sanctions_basis_date (basis_date),
                            INDEX idx_assistant_sanctions_settings_month (settings_month),
                            INDEX idx_assistant_sanctions_operation (operation_id)
                        )
                        """
                    )

                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS assistant_sanction_workoffs (
                            id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            sanction_id BIGINT UNSIGNED NOT NULL,
                            metric ENUM('spec', 'complaints', 'mchat') NOT NULL,
                            multiplier FLOAT NOT NULL,
                            period_start DATE NOT NULL,
                            period_end DATE NOT NULL,
                            target_amount FLOAT NOT NULL,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE KEY uq_assistant_sanction_workoff_metric (sanction_id, metric),
                            INDEX idx_assistant_sanction_workoffs_period (period_start, period_end)
                        )
                        """
                    )

                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS assistant_sanction_reliefs (
                            id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            sanction_id BIGINT UNSIGNED NOT NULL,
                            amount FLOAT NOT NULL,
                            relieved_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            basis_date DATE NULL,
                            relief_type ENUM('default', 'custom_workoff', 'cycle_reset', 'month_reset', 'manual', 'replacement', 'auto_expire') NOT NULL,
                            INDEX idx_assistant_sanction_reliefs_sanction (sanction_id, relieved_at),
                            INDEX idx_assistant_sanction_reliefs_basis (basis_date, relief_type)
                        )
                        """
                    )

                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS sanction_nightly_runs (
                            basis_date DATE PRIMARY KEY,
                            status ENUM('processing', 'completed', 'failed') NOT NULL,
                            started_at DATETIME NOT NULL,
                            finished_at DATETIME NULL,
                            failure_reason TEXT NULL,
                            INDEX idx_sanction_nightly_runs_status (status, started_at)
                        )
                        """
                    )

                    # =========================================================
                    # 19. Integration Delivery Outbox
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS broker_outbox (
                            id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            routing_key VARCHAR(255) NOT NULL,
                            payload JSON NOT NULL,
                            status ENUM('pending', 'processing', 'sent') NOT NULL DEFAULT 'pending',
                            attempts INT UNSIGNED NOT NULL DEFAULT 0,
                            available_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            processing_started_at DATETIME NULL,
                            sent_at DATETIME NULL,
                            last_error TEXT NULL,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            INDEX idx_broker_outbox_delivery (status, available_at, id),
                            INDEX idx_broker_outbox_created (created_at)
                        )
                        """
                    )

                    # =========================================================
                    # VIEWS (Requires multiple tables)
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE OR REPLACE VIEW active_assignments_v AS
                        SELECT
                            ss.id AS session_id,
                            ss.pr_id,
                            ss.target_type,
                            ss.target_id,
                            CASE
                                WHEN ss.target_name IS NOT NULL THEN ss.target_name
                                WHEN ss.target_type = 'streamer' THEN s.streamer_name
                                WHEN ss.target_type = 'event' THEN e.name
                                ELSE NULL
                            END AS target_name,
                            ss.is_probation,
                            ss.started_at,
                            e.event_kind,
                            e.approval_status
                        FROM spec_sessions ss
                        LEFT JOIN streamers s
                            ON ss.target_type = 'streamer'
                            AND ss.target_id = s.streamer_id
                        LEFT JOIN events e
                            ON ss.target_type = 'event'
                            AND ss.target_id = e.id
                        WHERE ss.ended_at IS NULL
                          AND ss.deleted_at IS NULL
                        """
                    )

                    # Day-Slicing View (Recursive CTE)
                    await cursor.execute(
                        """
                        CREATE OR REPLACE VIEW spec_session_day_slices AS
                        WITH RECURSIVE eligible_sessions AS (
                            SELECT
                                ss.id AS session_id,
                                ss.pr_id,
                                ss.target_type,
                                ss.target_id,
                                ss.is_probation,
                                ss.applied_priority_level,
                                ss.applied_hourly_rate,
                                CASE
                                    WHEN ss.target_type = 'event'
                                         AND e.event_kind = 'spec_request'
                                         AND e.approval_status = 'approved'
                                    THEN GREATEST(
                                        ss.started_at,
                                        COALESCE(e.approved_at, ss.started_at)
                                    )
                                    ELSE ss.started_at
                                END AS effective_started_at,
                                ss.ended_at
                            FROM spec_sessions ss
                            LEFT JOIN events e
                              ON ss.target_type = 'event'
                             AND e.id = ss.target_id
                            WHERE ss.ended_at IS NOT NULL
                              AND ss.deleted_at IS NULL
                              AND (
                                  ss.target_type <> 'event'
                                  OR e.event_kind <> 'spec_request'
                                  OR e.approval_status = 'approved'
                              )
                        ),
                        day_slices AS (
                            # Anchor: start of each completed, non-deleted session
                            SELECT
                                es.session_id,
                                es.pr_id,
                                es.target_type,
                                es.target_id,
                                es.is_probation,
                                es.applied_priority_level,
                                es.applied_hourly_rate,
                                es.effective_started_at AS started_at,
                                es.ended_at,
                                # slice_start = effective_started_at for the first day
                                es.effective_started_at AS slice_start,
                                # slice_end = midnight of the next day, or ended_at (whichever is earlier)
                                LEAST(
                                    DATE_ADD(DATE(es.effective_started_at), INTERVAL 1 DAY),
                                    es.ended_at
                                ) AS slice_end
                            FROM eligible_sessions es
                            WHERE es.effective_started_at < es.ended_at
                            
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
                            SUM(CASE WHEN applied_priority_level = 0 AND 0 = is_probation THEN seconds_in_day ELSE 0 END) AS p0_seconds,
                            SUM(CASE WHEN applied_priority_level = 1 AND 0 = is_probation THEN seconds_in_day ELSE 0 END) AS p1_seconds,
                            SUM(CASE WHEN applied_priority_level = 2 AND 0 = is_probation THEN seconds_in_day ELSE 0 END) AS p2_seconds,
                            SUM(CASE WHEN applied_priority_level = 3 AND 0 = is_probation THEN seconds_in_day ELSE 0 END) AS p3_seconds,
                            SUM(CASE WHEN is_probation THEN seconds_in_day ELSE 0 END) AS probation_seconds,
                            SUM(points_in_day) AS total_points
                        FROM spec_session_day_slices
                        GROUP BY pr_id, work_date
                        """
                    )

                    await cursor.execute(
                        """
                        CREATE OR REPLACE VIEW assistant_day_spec_totals AS
                        SELECT
                            pr_id AS assistant_id,
                            work_date,
                            SUM(seconds_in_day) AS spec_seconds_on_day,
                            ROUND(SUM(seconds_in_day) / 3600.0, 4) AS spec_hours_on_day,
                            ROUND(SUM(points_in_day), 4) AS spec_points_auto
                        FROM spec_session_day_slices
                        GROUP BY pr_id, work_date
                        """
                    )

                    await cursor.execute(
                        """
                        CREATE OR REPLACE VIEW sanction_balances AS
                        SELECT
                            s.id AS sanction_id,
                            s.assistant_id,
                            s.kind,
                            s.amount_total,
                            s.auto_relief_date,
                            s.issued_at,
                            s.source_type,
                            s.operation_id AS source_batch_id,
                            s.basis_date,
                            s.settings_month AS policy_month,
                            s.check_rule_hit_no AS cycle_no,
                            ROUND(COALESCE(SUM(sr.amount), 0), 4) AS relieved_amount,
                            GREATEST(ROUND(s.amount_total - COALESCE(SUM(sr.amount), 0), 4), 0) AS active_amount
                        FROM assistant_sanctions s
                        LEFT JOIN assistant_sanction_reliefs sr ON sr.sanction_id = s.id
                        GROUP BY
                            s.id,
                            s.assistant_id,
                            s.kind,
                            s.amount_total,
                            s.auto_relief_date,
                            s.issued_at,
                            s.source_type,
                            s.operation_id,
                            s.basis_date,
                            s.settings_month,
                            s.check_rule_hit_no
                        """
                    )

                    await cursor.execute("SET sql_notes = 1")
                    await conn.commit()

                    await self._init_default_permissions(conn)
                    await self._init_weekly_payout_config(conn)
                    await self._init_default_service_principals(conn)
                    await self._ensure_singleton_settings(conn)
                    await self._init_cutover_schema(conn)

                    self.logger.info("Database schema initialized successfully")
        except Exception as e:
            self.logger.error(f"Failed to initialize database: {e}", exc_info=True)
            raise

    @staticmethod
    def _month_start_for(value: date) -> date:
        return value.replace(day=1)

    @staticmethod
    def _normalize_db_datetime(value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is not None:
            return value.replace(tzinfo=None)
        return value

    @classmethod
    def _approved_session_start(
        cls,
        started_at: Optional[datetime],
        approved_at: Optional[datetime],
    ) -> Optional[datetime]:
        normalized_started = cls._normalize_db_datetime(started_at)
        normalized_approved = cls._normalize_db_datetime(approved_at)
        if normalized_started is None:
            return None
        if normalized_approved is None:
            return normalized_started
        return max(normalized_started, normalized_approved)

    async def _acquire_named_lock(
        self,
        cursor,
        *,
        lock_name: str,
        timeout_seconds: int = 30,
    ) -> bool:
        await cursor.execute(
            "SELECT GET_LOCK(%s, %s) AS acquired",
            (lock_name, int(timeout_seconds)),
        )
        row = await cursor.fetchone()
        if isinstance(row, dict):
            return bool(row.get("acquired"))
        return bool(row[0]) if row else False

    async def _release_named_lock(self, cursor, *, lock_name: str) -> None:
        try:
            await cursor.execute("SELECT RELEASE_LOCK(%s)", (lock_name,))
            await cursor.fetchone()
        except Exception:
            self.logger.debug("Failed to release named lock %s", lock_name, exc_info=True)

    async def _enqueue_outbox_message_with_cursor(
        self,
        cursor,
        *,
        routing_key: str,
        payload: Dict[str, Any],
    ) -> int:
        await cursor.execute(
            """
            INSERT INTO broker_outbox (routing_key, payload)
            VALUES (%s, %s)
            """,
            (str(routing_key), json.dumps(payload, default=str)),
        )
        return int(cursor.lastrowid)

    async def _enqueue_outbox_messages_with_cursor(
        self,
        cursor,
        outbox_events: Optional[List[Dict[str, Any]]],
    ) -> List[int]:
        message_ids: List[int] = []
        for event in outbox_events or []:
            routing_key = str(event.get("routing_key") or "").strip()
            payload = event.get("payload")
            if not routing_key or not isinstance(payload, dict):
                continue
            message_id = await self._enqueue_outbox_message_with_cursor(
                cursor,
                routing_key=routing_key,
                payload=payload,
            )
            message_ids.append(message_id)
        return message_ids

    @db_retry()
    async def enqueue_outbox_message(self, routing_key: str, payload: Dict[str, Any]) -> int:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                message_id = await self._enqueue_outbox_message_with_cursor(
                    cursor,
                    routing_key=routing_key,
                    payload=payload,
                )
                await conn.commit()
                return message_id

    @db_retry()
    async def requeue_stuck_outbox_messages(self, *, max_age_seconds: int = 300) -> int:
        cutoff = datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None) - timedelta(
            seconds=max(1, int(max_age_seconds))
        )
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    UPDATE broker_outbox
                    SET status = 'pending',
                        available_at = CURRENT_TIMESTAMP,
                        processing_started_at = NULL
                    WHERE status = 'processing'
                      AND processing_started_at IS NOT NULL
                      AND processing_started_at <= %s
                    """,
                    (cutoff,),
                )
                await conn.commit()
                return int(cursor.rowcount or 0)

    @db_retry()
    async def list_pending_outbox_messages(self, limit: int = 100) -> List[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(
                    """
                    SELECT id, routing_key, payload, attempts, created_at
                    FROM broker_outbox
                    WHERE status = 'pending'
                      AND available_at <= CURRENT_TIMESTAMP
                    ORDER BY id ASC
                    LIMIT %s
                    """,
                    (max(1, int(limit)),),
                )
                rows = await cursor.fetchall() or []
                for row in rows:
                    payload = row.get("payload")
                    if isinstance(payload, str):
                        row["payload"] = json.loads(payload)
                return rows

    @db_retry()
    async def claim_outbox_message(self, message_id: int) -> bool:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    UPDATE broker_outbox
                    SET status = 'processing',
                        attempts = attempts + 1,
                        processing_started_at = CURRENT_TIMESTAMP,
                        last_error = NULL
                    WHERE id = %s
                      AND status = 'pending'
                      AND available_at <= CURRENT_TIMESTAMP
                    """,
                    (int(message_id),),
                )
                await conn.commit()
                return cursor.rowcount > 0

    @db_retry()
    async def mark_outbox_message_sent(self, message_id: int) -> bool:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    UPDATE broker_outbox
                    SET status = 'sent',
                        sent_at = CURRENT_TIMESTAMP,
                        processing_started_at = NULL,
                        last_error = NULL
                    WHERE id = %s
                    """,
                    (int(message_id),),
                )
                await conn.commit()
                return cursor.rowcount > 0

    @db_retry()
    async def mark_outbox_message_failed(
        self,
        message_id: int,
        *,
        error: str,
        retry_delay_seconds: int = 5,
    ) -> bool:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    UPDATE broker_outbox
                    SET status = 'pending',
                        available_at = DATE_ADD(CURRENT_TIMESTAMP, INTERVAL %s SECOND),
                        processing_started_at = NULL,
                        last_error = %s
                    WHERE id = %s
                    """,
                    (max(1, int(retry_delay_seconds)), str(error)[:65535], int(message_id)),
                )
                await conn.commit()
                return cursor.rowcount > 0

    async def _init_cutover_schema(self, conn) -> None:
        """Idempotent additive migration path for the assistant_sanctions/workoff cutover."""
        async with conn.cursor() as cursor:
            try:
                await cursor.execute(
                    "ALTER TABLE settings MODIFY COLUMN monitoring_message_id BIGINT UNSIGNED"
                )
            except Exception:
                pass

            table_renames = [
                ("monthly_sanction_settings", "monthly_sanction_settings"),
                ("monthly_check_rules", "monthly_check_rules"),
                ("sanction_operations", "sanction_operations"),
                ("sanction_operation_members", "sanction_operation_members"),
                ("sanction_operation_workoffs", "sanction_operation_workoffs"),
                ("assistant_sanctions", "assistant_sanctions"),
                ("assistant_sanction_workoffs", "assistant_sanction_workoffs"),
                ("assistant_sanction_reliefs", "assistant_sanction_reliefs"),
                ("sanction_nightly_runs", "sanction_nightly_runs"),
            ]
            for old_name, new_name in table_renames:
                if await self._table_exists(cursor, old_name) and not await self._table_exists(cursor, new_name):
                    await cursor.execute(f"RENAME TABLE {old_name} TO {new_name}")

            column_renames = [
                ("monthly_check_rules", "cycle_from", "range_start", "INT UNSIGNED NOT NULL"),
                ("monthly_check_rules", "cycle_to", "range_end", "INT UNSIGNED NULL"),
                ("monthly_check_rules", "sanction_kind", "penalty_kind", "ENUM('point', 'percent', 'oral', 'strict') NOT NULL"),
                ("monthly_check_rules", "sanction_amount", "penalty_amount", "FLOAT NOT NULL"),
                ("sanction_operations", "basis_date", "operation_date", "DATE NOT NULL"),
                ("sanction_operations", "sanction_kind", "penalty_kind", "ENUM('check', 'point', 'percent', 'oral', 'strict') NOT NULL"),
                ("sanction_operations", "sanction_amount", "penalty_amount", "FLOAT NOT NULL"),
                ("sanction_operations", "audience_mode", "recipient_mode", "ENUM('all_active', 'live_without_active_session', 'selected_only') NOT NULL"),
                ("sanction_operation_members", "batch_id", "operation_id", "BIGINT UNSIGNED NOT NULL"),
                ("sanction_operation_members", "execution_status", "issue_status", "ENUM('pending', 'issued', 'skipped_immunity', 'skipped_leave', 'failed') NOT NULL DEFAULT 'pending'"),
                ("sanction_operation_members", "execution_reason", "issue_reason", "VARCHAR(255) NULL"),
                ("sanction_operation_workoffs", "batch_id", "operation_id", "BIGINT UNSIGNED NOT NULL"),
                ("assistant_sanctions", "source_batch_id", "operation_id", "BIGINT UNSIGNED NULL"),
                ("assistant_sanctions", "policy_month", "settings_month", "DATE NULL"),
                ("assistant_sanctions", "cycle_no", "check_rule_hit_no", "INT UNSIGNED NULL"),
            ]
            for table_name, old_column, new_column, column_def in column_renames:
                if await self._table_exists(cursor, table_name) and await self._column_exists(cursor, table_name, old_column) and not await self._column_exists(cursor, table_name, new_column):
                    await cursor.execute(
                        f"ALTER TABLE {table_name} CHANGE COLUMN {old_column} {new_column} {column_def}"
                    )

            if await self._table_exists(cursor, "monthly_check_rules") and await self._column_exists(cursor, "monthly_check_rules", "range_end"):
                await cursor.execute(
                    "ALTER TABLE monthly_check_rules MODIFY COLUMN range_end INT UNSIGNED NULL"
                )
                await cursor.execute(
                    """
                    UPDATE monthly_check_rules current_rule
                    LEFT JOIN monthly_check_rules other_rule
                      ON other_rule.month_start = current_rule.month_start
                     AND other_rule.id <> current_rule.id
                     AND (
                         other_rule.range_start > current_rule.range_end
                         OR other_rule.range_end IS NULL
                     )
                    SET current_rule.range_end = NULL
                    WHERE current_rule.range_start = 8
                      AND current_rule.range_end = 8
                      AND current_rule.penalty_kind = 'strict'
                      AND other_rule.id IS NULL
                    """
                )

            if await self._table_exists(cursor, "sanction_operations"):
                if not await self._column_exists(cursor, "sanction_operations", "auto_relief_date"):
                    await cursor.execute(
                        """
                        ALTER TABLE sanction_operations
                        ADD COLUMN auto_relief_date DATE NULL
                        AFTER penalty_amount
                        """
                    )
                if not await self._column_exists(cursor, "sanction_operations", "processing_mode"):
                    await cursor.execute(
                        """
                        ALTER TABLE sanction_operations
                        ADD COLUMN processing_mode ENUM('manual_now', 'nightly_auto') NULL
                        AFTER status
                        """
                    )

            if not await self._table_exists(cursor, "broker_outbox"):
                await cursor.execute(
                    """
                    CREATE TABLE broker_outbox (
                        id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                        routing_key VARCHAR(255) NOT NULL,
                        payload JSON NOT NULL,
                        status ENUM('pending', 'processing', 'sent') NOT NULL DEFAULT 'pending',
                        attempts INT UNSIGNED NOT NULL DEFAULT 0,
                        available_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        processing_started_at DATETIME NULL,
                        sent_at DATETIME NULL,
                        last_error TEXT NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        INDEX idx_broker_outbox_delivery (status, available_at, id),
                        INDEX idx_broker_outbox_created (created_at)
                    )
                    """
                )

            if not await self._table_exists(cursor, "sanction_nightly_runs"):
                await cursor.execute(
                    """
                    CREATE TABLE sanction_nightly_runs (
                        basis_date DATE PRIMARY KEY,
                        status ENUM('processing', 'completed', 'failed') NOT NULL,
                        started_at DATETIME NOT NULL,
                        finished_at DATETIME NULL,
                        failure_reason TEXT NULL,
                        INDEX idx_sanction_nightly_runs_status (status, started_at)
                    )
                    """
                )

            if await self._table_exists(cursor, "sanction_operations"):
                if not await self._column_exists(cursor, "sanction_operations", "processed_by_id"):
                    await cursor.execute(
                        """
                        ALTER TABLE sanction_operations
                        ADD COLUMN processed_by_id BIGINT UNSIGNED NULL
                        AFTER processing_mode
                        """
                    )
                if not await self._index_exists(cursor, "sanction_operations", "idx_sanction_operations_processed_by"):
                    await cursor.execute(
                        """
                        ALTER TABLE sanction_operations
                        ADD INDEX idx_sanction_operations_processed_by (processed_by_id, processed_at)
                        """
                    )
                if await self._column_exists(cursor, "sanction_operations", "audience_mode"):
                    await cursor.execute(
                        """
                        UPDATE sanction_operations
                        SET audience_mode = 'selected_only'
                        WHERE audience_mode = 'all_except'
                        """
                    )
                elif await self._column_exists(cursor, "sanction_operations", "recipient_mode"):
                    try:
                        await cursor.execute(
                            """
                            UPDATE sanction_operations
                            SET recipient_mode = 'selected_only'
                            WHERE recipient_mode = 'all_except'
                            """
                        )
                    except Exception:
                        pass
                try:
                    await cursor.execute(
                        """
                        UPDATE sanction_operations
                        SET status = 'queued',
                            queued_at = COALESCE(queued_at, created_at, CURRENT_TIMESTAMP)
                        WHERE status = 'draft'
                        """
                    )
                except Exception:
                    pass
                try:
                    await cursor.execute(
                        """
                        ALTER TABLE sanction_operations
                        MODIFY COLUMN status ENUM('queued', 'processing', 'completed', 'cancelled', 'failed') NOT NULL DEFAULT 'queued'
                        """
                    )
                except Exception:
                    pass

            if not await self._column_exists(cursor, "assistants", "dismissed_at"):
                await cursor.execute(
                    "ALTER TABLE assistants ADD COLUMN dismissed_at DATETIME NULL AFTER updated_at"
                )

            if await self._table_exists(cursor, "assistant_sanctions"):
                if not await self._column_exists(cursor, "assistant_sanctions", "auto_relief_date"):
                    await cursor.execute(
                        """
                        ALTER TABLE assistant_sanctions
                        ADD COLUMN auto_relief_date DATE NULL
                        AFTER amount_total
                        """
                    )

            if await self._table_exists(cursor, "assistant_sanction_reliefs"):
                try:
                    await cursor.execute(
                        """
                        ALTER TABLE assistant_sanction_reliefs
                        MODIFY COLUMN relief_type ENUM(
                            'default',
                            'custom_workoff',
                            'cycle_reset',
                            'month_reset',
                            'manual',
                            'replacement',
                            'auto_expire'
                        ) NOT NULL
                        """
                    )
                except Exception:
                    pass

            if await self._table_exists(cursor, "sanction_operation_members"):
                try:
                    await cursor.execute(
                        """
                        ALTER TABLE sanction_operation_members
                        MODIFY COLUMN issue_status ENUM(
                            'pending',
                            'issued',
                            'skipped_immunity',
                            'skipped_leave',
                            'failed'
                        ) NOT NULL DEFAULT 'pending'
                        """
                    )
                except Exception:
                    pass

            if await self._table_exists(cursor, "spec_sessions") and await self._column_exists(
                cursor, "spec_sessions", "end_reason"
            ):
                await cursor.execute(
                    f"""
                    ALTER TABLE spec_sessions
                    MODIFY COLUMN end_reason ENUM({SPEC_SESSION_END_REASON_VALUES_SQL}) NULL
                    """
                )

            if not await self._column_exists(cursor, "admin_logs", "actor_id"):
                await cursor.execute(
                    "ALTER TABLE admin_logs ADD COLUMN actor_id BIGINT UNSIGNED NULL AFTER actor_role"
                )
            if not await self._column_exists(cursor, "admin_logs", "actor_type"):
                await cursor.execute(
                    "ALTER TABLE admin_logs ADD COLUMN actor_type VARCHAR(32) NULL AFTER actor_id"
                )
            if not await self._column_exists(cursor, "admin_logs", "trace_id"):
                await cursor.execute(
                    "ALTER TABLE admin_logs ADD COLUMN trace_id VARCHAR(64) NULL AFTER actor_type"
                )
            if await self._table_exists(cursor, "assistant_weekly_reviews"):
                if not await self._column_exists(cursor, "assistant_weekly_reviews", "payout_issue_status"):
                    await cursor.execute(
                        """
                        ALTER TABLE assistant_weekly_reviews
                        ADD COLUMN payout_issue_status ENUM('pending', 'issued') NOT NULL DEFAULT 'pending'
                        AFTER payout_static
                        """
                    )
                if not await self._column_exists(cursor, "assistant_weekly_reviews", "payout_issued_at"):
                    await cursor.execute(
                        """
                        ALTER TABLE assistant_weekly_reviews
                        ADD COLUMN payout_issued_at DATETIME NULL
                        AFTER payout_issue_status
                        """
                    )
                if not await self._column_exists(cursor, "assistant_weekly_reviews", "payout_issued_by_id"):
                    await cursor.execute(
                        """
                        ALTER TABLE assistant_weekly_reviews
                        ADD COLUMN payout_issued_by_id BIGINT UNSIGNED NULL
                        AFTER payout_issued_at
                        """
                    )
                await cursor.execute(
                    """
                    ALTER TABLE assistant_weekly_reviews
                    MODIFY COLUMN payout_issue_status ENUM('pending', 'issued') NOT NULL DEFAULT 'pending'
                    """
                )
            await self._seed_default_monthly_policies(cursor)
            await self._backfill_legacy_balances(cursor)
            await self._drop_legacy_assistant_balance_columns(cursor)
            await conn.commit()

    async def _seed_default_monthly_policies(self, cursor) -> None:
        """Ensure previous/current/next month policy defaults exist."""
        current_msk = datetime.now(timezone(timedelta(hours=3))).date()
        month_starts = {
            self._month_start_for(current_msk),
            self._month_start_for((current_msk.replace(day=1) - timedelta(days=1))),
            self._month_start_for((current_msk.replace(day=28) + timedelta(days=4)).replace(day=1)),
        }
        default_rules = [
            (1, 2, "point", 1.0),
            (3, 3, "point", 2.0),
            (4, 5, "percent", 3.0),
            (6, 6, "percent", 5.0),
            (7, 7, "oral", 1.0),
            (8, None, "strict", 1.0),
        ]

        for month_start in sorted(month_starts):
            await cursor.execute(
                """
                INSERT INTO monthly_sanction_settings (
                    month_start,
                    check_cycle_size,
                    check_immunity_hours_per_day,
                    point_immunity_hours_per_day,
                    percent_immunity_hours_per_day,
                    check_relief_hours_per_day,
                    point_relief_hours_per_day,
                    percent_relief_hours_per_day,
                    check_relief_min_streak_days,
                    point_relief_min_streak_days,
                    percent_relief_min_streak_days,
                    percent_relief_step_amount,
                    daily_norm_spec,
                    daily_norm_complaints,
                    daily_norm_mchat
                )
                VALUES (%s, 5, 4, 5, 6, 4, 5, 6, 2, 2, 2, 3, 4, 0, 0)
                ON DUPLICATE KEY UPDATE month_start = month_start
                """,
                (month_start,),
            )

            await cursor.execute(
                "SELECT COUNT(*) AS cnt FROM monthly_check_rules WHERE month_start = %s",
                (month_start,),
            )
            row = await cursor.fetchone() or {}
            if int(row.get("cnt", 0)) == 0:
                for range_start, range_end, penalty_kind, penalty_amount in default_rules:
                    await cursor.execute(
                        """
                        INSERT INTO monthly_check_rules (
                            month_start, range_start, range_end, penalty_kind, penalty_amount
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (month_start, range_start, range_end, penalty_kind, penalty_amount),
                    )

    async def _backfill_legacy_balances(self, cursor) -> None:
        """One-time cutover of legacy stored balances into the new ledger/day tables."""
        if not await self._table_exists(cursor, "assistants"):
            return

        has_manual_adjustment = await self._column_exists(
            cursor, "assistants", "manual_points_adjustment"
        )
        has_penalty_points = await self._column_exists(
            cursor, "assistants", "penalty_points"
        )
        has_penalty_percent = await self._column_exists(
            cursor, "assistants", "penalty_percent"
        )
        has_warnings_units = await self._column_exists(
            cursor, "assistants", "warnings_units"
        )

        # Manual points -> opening day adjustments on appointed/added date.
        if has_manual_adjustment:
            await cursor.execute(
                """
                INSERT INTO assistant_day_point_adjustments (assistant_id, work_date, delta_points)
                SELECT
                    a.pr_id,
                    COALESCE(DATE(a.appointed_at), DATE(a.added_at), CURDATE()) AS work_date,
                    ROUND(a.manual_points_adjustment, 4)
                FROM assistants a
                WHERE COALESCE(a.manual_points_adjustment, 0) <> 0
                  AND NOT EXISTS (
                      SELECT 1
                      FROM assistant_day_point_adjustments ad
                      WHERE ad.assistant_id = a.pr_id
                        AND ad.work_date = COALESCE(DATE(a.appointed_at), DATE(a.added_at), CURDATE())
                  )
                """
            )
            await cursor.execute(
                """
                UPDATE assistants
                SET manual_points_adjustment = 0
                WHERE COALESCE(manual_points_adjustment, 0) <> 0
                """
            )

        # Stored assistant_sanctions -> opening ledger rows.
        if has_penalty_points:
            await cursor.execute(
                """
                INSERT INTO assistant_sanctions (assistant_id, kind, amount_total, issued_at, source_type, basis_date, settings_month)
                SELECT
                    a.pr_id,
                    'point',
                    ROUND(a.penalty_points, 4),
                    CURRENT_TIMESTAMP,
                    'legacy_migration',
                    CURDATE(),
                    DATE_SUB(CURDATE(), INTERVAL DAYOFMONTH(CURDATE()) - 1 DAY)
                FROM assistants a
                WHERE COALESCE(a.penalty_points, 0) > 0
                  AND NOT EXISTS (
                      SELECT 1
                      FROM assistant_sanctions s
                      WHERE s.assistant_id = a.pr_id
                        AND s.kind = 'point'
                        AND s.source_type = 'legacy_migration'
                  )
                """
            )

        if has_penalty_percent:
            await cursor.execute(
                """
                INSERT INTO assistant_sanctions (assistant_id, kind, amount_total, issued_at, source_type, basis_date, settings_month)
                SELECT
                    a.pr_id,
                    'percent',
                    ROUND(a.penalty_percent, 4),
                    CURRENT_TIMESTAMP,
                    'legacy_migration',
                    CURDATE(),
                    DATE_SUB(CURDATE(), INTERVAL DAYOFMONTH(CURDATE()) - 1 DAY)
                FROM assistants a
                WHERE COALESCE(a.penalty_percent, 0) > 0
                  AND NOT EXISTS (
                      SELECT 1
                      FROM assistant_sanctions s
                      WHERE s.assistant_id = a.pr_id
                        AND s.kind = 'percent'
                        AND s.source_type = 'legacy_migration'
                  )
                """
            )

        if has_warnings_units:
            await cursor.execute(
                """
                INSERT INTO assistant_sanctions (assistant_id, kind, amount_total, issued_at, source_type, basis_date, settings_month)
                SELECT
                    a.pr_id,
                    'strict',
                    FLOOR(COALESCE(a.warnings_units, 0) / 2),
                    CURRENT_TIMESTAMP,
                    'legacy_migration',
                    CURDATE(),
                    DATE_SUB(CURDATE(), INTERVAL DAYOFMONTH(CURDATE()) - 1 DAY)
                FROM assistants a
                WHERE FLOOR(COALESCE(a.warnings_units, 0) / 2) > 0
                  AND NOT EXISTS (
                      SELECT 1
                      FROM assistant_sanctions s
                      WHERE s.assistant_id = a.pr_id
                        AND s.kind = 'strict'
                        AND s.source_type = 'legacy_migration'
                  )
                """
            )
            await cursor.execute(
                """
                INSERT INTO assistant_sanctions (assistant_id, kind, amount_total, issued_at, source_type, basis_date, settings_month)
                SELECT
                    a.pr_id,
                    'oral',
                    MOD(COALESCE(a.warnings_units, 0), 2),
                    CURRENT_TIMESTAMP,
                    'legacy_migration',
                    CURDATE(),
                    DATE_SUB(CURDATE(), INTERVAL DAYOFMONTH(CURDATE()) - 1 DAY)
                FROM assistants a
                WHERE MOD(COALESCE(a.warnings_units, 0), 2) > 0
                  AND NOT EXISTS (
                      SELECT 1
                      FROM assistant_sanctions s
                      WHERE s.assistant_id = a.pr_id
                        AND s.kind = 'oral'
                        AND s.source_type = 'legacy_migration'
                  )
                """
            )

        if has_penalty_points or has_penalty_percent or has_warnings_units:
            set_parts: list[str] = []
            where_parts: list[str] = []
            if has_penalty_points:
                set_parts.append("penalty_points = 0")
                where_parts.append("COALESCE(penalty_points, 0) <> 0")
            if has_penalty_percent:
                set_parts.append("penalty_percent = 0")
                where_parts.append("COALESCE(penalty_percent, 0) <> 0")
            if has_warnings_units:
                set_parts.append("warnings_units = 0")
                where_parts.append("COALESCE(warnings_units, 0) <> 0")
            if set_parts and where_parts:
                await cursor.execute(
                    f"""
                    UPDATE assistants
                    SET {", ".join(set_parts)}
                    WHERE {" OR ".join(where_parts)}
                    """
                )

    async def _drop_legacy_assistant_balance_columns(self, cursor) -> None:
        """Drop legacy mutable balance cache columns after cutover backfill."""
        if not await self._table_exists(cursor, "assistants"):
            return

        legacy_columns = [
            "total_points",
            "auto_points_total",
            "manual_points_adjustment",
            "penalty_points",
            "penalty_percent",
            "warnings_units",
        ]
        for column_name in legacy_columns:
            if not await self._column_exists(cursor, "assistants", column_name):
                continue
            try:
                await cursor.execute(f"ALTER TABLE assistants DROP COLUMN {column_name}")
                self.logger.info("Dropped legacy assistants.%s column", column_name)
            except Exception as exc:
                # Keep startup idempotent for mixed MariaDB/MySQL deployments.
                self.logger.warning(
                    "Could not drop legacy assistants.%s column: %s",
                    column_name,
                    exc,
                )

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
                "assistants.weekly.view",
                "assistants.weekly.manage",
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
                "assistants.weekly.view": True,
                "assistants.weekly.manage": True,
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

    async def _init_weekly_payout_config(self, conn):
        """Seed config-driven payout metadata for weekly assistant reviews."""
        type_rules = {
            "EXP": "giveexp",
            "Premium": "setvip",
            "MC": "givedonate",
            "MONEY": "givemoney",
        }
        amount_rules = {
            ("junior", "EXP", "Актив"): "20000",
            ("junior", "EXP", "Ультра-Актив"): "35000",
            ("junior", "Premium", "Актив"): "4",
            ("junior", "Premium", "Ультра-Актив"): "7",
            ("junior", "MC", "Актив"): "1000",
            ("junior", "MC", "Ультра-Актив"): "1200",
            ("junior", "MONEY", "Актив"): "150000",
            ("junior", "MONEY", "Ультра-Актив"): "200000",
            ("default", "EXP", "Актив"): "35000",
            ("default", "EXP", "Ультра-Актив"): "50000",
            ("default", "Premium", "Актив"): "7",
            ("default", "Premium", "Ультра-Актив"): "14",
            ("default", "MC", "Актив"): "1200",
            ("default", "MC", "Ультра-Актив"): "2000",
            ("default", "MONEY", "Актив"): "200000",
            ("default", "MONEY", "Ультра-Актив"): "250000",
            ("Senior", "EXP", "Актив"): "35000",
            ("Senior", "EXP", "Ультра-Актив"): "50000",
            ("Senior", "Premium", "Актив"): "7",
            ("Senior", "Premium", "Ультра-Актив"): "14",
            ("Senior", "MC", "Актив"): "1200",
            ("Senior", "MC", "Ультра-Актив"): "2000",
            ("Senior", "MONEY", "Актив"): "200000",
            ("Senior", "MONEY", "Ультра-Актив"): "250000",
        }
        server_codes = [f"RU{index}" for index in range(1, 19)]

        async with conn.cursor() as cursor:
            for payout_type, command_name in type_rules.items():
                await cursor.execute(
                    """
                    INSERT INTO assistant_weekly_payout_type_rules (payout_type, command_name)
                    VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE command_name = command_name
                    """,
                    (payout_type, command_name),
                )
            for (role_group, payout_type, result_code), amount in amount_rules.items():
                await cursor.execute(
                    """
                    INSERT INTO assistant_weekly_payout_amount_rules (
                        role_group, payout_type, result_code, amount
                    )
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE amount = amount
                    """,
                    (role_group, payout_type, result_code, amount),
                )
            for server_code in server_codes:
                await cursor.execute(
                    """
                    INSERT INTO assistant_weekly_payout_servers (server_code)
                    VALUES (%s)
                    ON DUPLICATE KEY UPDATE server_code = server_code
                    """,
                    (server_code,),
                )
        await conn.commit()
        self.logger.debug("  ✓ Weekly payout config seeded")

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
            "notifications.render": True,
            "dashboard.view": True,
            "streamers.status.update": True,
        }
        twitch_scope = {
            "streamers.view": True,
            "streamers.create": True,
            "streamers.status.update": True,
            "spec.unclaim.any": True,
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
        actor_id: Optional[int] = None,
        actor_type: Optional[str] = None,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        details: Optional[dict] = None,
        trace_id: Optional[str] = None,
    ) -> None:
        """Write compact universal admin log event."""
        event_details = details or {}
        if not isinstance(event_details, dict):
            event_details = {"payload": {"value": event_details}}

        if "summary" not in event_details:
            event_details["summary"] = action

        meta = event_details.get("meta") or {}
        if actor_id is None:
            try:
                actor_id = int(meta.get("actor_id")) if meta.get("actor_id") is not None else None
            except (TypeError, ValueError):
                actor_id = None
        if actor_type is None:
            actor_type = str(meta.get("actor_type") or "user")
        if trace_id is None:
            trace_id = meta.get("trace_id")

        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO admin_logs
                            (actor_name, actor_role, actor_id, actor_type, trace_id, action, target_type, target_id, details)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            actor_name,
                            actor_role,
                            actor_id,
                            actor_type,
                            trace_id,
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
        outbox_events: Optional[List[Dict[str, Any]]] = None,
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
                    await self._enqueue_outbox_messages_with_cursor(cursor, outbox_events)
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
                            priority, pr_slots,
                            priority_override AS current_stream_priority_override,
                            pr_slots_override AS current_stream_pr_slots_override,
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
                            act.pr_id,
                            a.nickname,
                            act.is_probation,
                            act.started_at as assigned_at
                        FROM active_assignments_v act
                        LEFT JOIN assistants a ON a.pr_id = act.pr_id
                        WHERE act.target_type = 'streamer' AND act.target_id = %s
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
        outbox_trace_id: Optional[str] = None,
        outbox_events: Optional[List[Dict[str, Any]]] = None,
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

                    staged_outbox_events: List[Dict[str, Any]] = list(outbox_events or [])
                    if outbox_trace_id:
                        if is_online and not bool(old_state.get("is_online")):
                            staged_outbox_events.append(
                                {
                                    "routing_key": "stream.state.online",
                                    "payload": {
                                        "event": "online",
                                        "streamer_id": streamer_id,
                                        "streamer_name": old_state.get("streamer_name"),
                                        "is_online": True,
                                        "game_id": game_id,
                                        "game_name": game_name,
                                        "stream_title": stream_title,
                                        "thumbnail_url": stream_thumbnail_url,
                                        "trace_id": outbox_trace_id,
                                    },
                                }
                            )
                        elif not is_online and bool(old_state.get("is_online")):
                            staged_outbox_events.append(
                                {
                                    "routing_key": "stream.state.offline",
                                    "payload": {
                                        "event": "offline",
                                        "streamer_id": streamer_id,
                                        "streamer_name": old_state.get("streamer_name"),
                                        "is_online": False,
                                        "trace_id": outbox_trace_id,
                                    },
                                }
                            )
                        elif (
                            is_online
                            and bool(old_state.get("is_online"))
                            and old_state.get("game_id") != (str(game_id) if game_id else None)
                        ):
                            staged_outbox_events.append(
                                {
                                    "routing_key": "stream.state.category",
                                    "payload": {
                                        "event": "category_change",
                                        "streamer_id": streamer_id,
                                        "streamer_name": old_state.get("streamer_name"),
                                        "old_game_id": old_state.get("game_id"),
                                        "new_game_id": str(game_id) if game_id else None,
                                        "new_game_name": game_name,
                                        "stream_title": stream_title,
                                        "thumbnail_url": stream_thumbnail_url,
                                        "trace_id": outbox_trace_id,
                                    },
                                }
                            )
                    await self._enqueue_outbox_messages_with_cursor(
                        cursor,
                        staged_outbox_events,
                    )
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
        outbox_events: Optional[List[Dict[str, Any]]] = None,
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
                    await self._enqueue_outbox_messages_with_cursor(cursor, outbox_events)
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
        outbox_trace_id: Optional[str] = None,
        outbox_events: Optional[List[Dict[str, Any]]] = None,
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

            if points is not None:
                set_parts.append("points = %s")
                params.append(points)

            if not set_parts:
                return False

            params.append(event_id)

            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        f"UPDATE events SET {', '.join(set_parts)} WHERE id = %s",
                        tuple(params),
                    )
                    staged_outbox_events: List[Dict[str, Any]] = list(outbox_events or [])
                    if outbox_trace_id:
                        await cursor.execute(
                            "SELECT name FROM events WHERE id = %s",
                            (event_id,),
                        )
                        event_row = await cursor.fetchone() or {}
                        staged_outbox_events.append(
                            {
                                "routing_key": "event.updated",
                                "payload": {
                                    "event": "event.updated",
                                    "event_id": event_id,
                                    "event_name": event_row.get("name", "Unknown"),
                                    "trace_id": outbox_trace_id,
                                },
                            }
                        )
                    await self._enqueue_outbox_messages_with_cursor(
                        cursor,
                        staged_outbox_events,
                    )
                    await conn.commit()
                    return cursor.rowcount > 0
        except Exception as e:
            self.logger.error(f"Failed to update event {event_id}: {e}", exc_info=True)
            return False

    @db_retry()
    async def remove_streamer(
        self,
        streamer_id: int,
        outbox_events: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
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
                    await self._enqueue_outbox_messages_with_cursor(cursor, outbox_events)
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
    async def list_all_streamers(
        self,
        include_assignments: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Получение всех стримеров из базы данных.
        By default returns basic streamer data without assignments.
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    if not include_assignments:
                        await cursor.execute(
                            """
                            SELECT 
                                s.streamer_id, s.streamer_name, s.is_online, s.stream_title, s.stream_thumbnail_url,
                                s.is_pinned, s.allow_juniors, s.profile_image_url,
                                s.stream_game_id as game_id, s.stream_game_name as game_name, s.stream_started_at as started_at,
                                s.priority, s.pr_slots,
                                s.priority_override AS current_stream_priority_override,
                                s.pr_slots_override AS current_stream_pr_slots_override,
                                s.added_at, s.added_by_id, s.updated_at
                            FROM streamers s
                            ORDER BY s.priority DESC, s.streamer_name ASC
                            """
                        )
                        return await cursor.fetchall()

                    await cursor.execute(
                        """
                        SELECT 
                            s.streamer_id, s.streamer_name, s.is_online, s.stream_title, s.stream_thumbnail_url,
                            s.is_pinned, s.allow_juniors, s.profile_image_url,
                            s.stream_game_id as game_id, s.stream_game_name as game_name, s.stream_started_at as started_at,
                            s.priority, s.pr_slots,
                            s.priority_override AS current_stream_priority_override,
                            s.pr_slots_override AS current_stream_pr_slots_override,
                            s.added_at, s.added_by_id, s.updated_at,
                            MIN(act.pr_id) as assigned_pr_id,
                            COALESCE(
                                JSON_ARRAYAGG(
                                    CASE WHEN a.pr_id IS NOT NULL THEN
                                        JSON_OBJECT(
                                            'pr_id', CAST(a.pr_id AS CHAR),
                                            'nickname', a.nickname,
                                            'is_probation', COALESCE(act.is_probation, FALSE),
                                            'assigned_at', act.started_at
                                        )
                                    ELSE NULL END
                                ),
                                JSON_ARRAY()
                            ) as assignments
                        FROM streamers s
                        LEFT JOIN active_assignments_v act ON act.target_type = 'streamer'
                             AND act.target_id = s.streamer_id
                        LEFT JOIN assistants a ON a.pr_id = act.pr_id
                        GROUP BY s.streamer_id
                        ORDER BY s.is_pinned DESC, s.priority DESC, s.streamer_name ASC
                        """
                    )
                    results = await cursor.fetchall()
                    for row in results:
                        if isinstance(row.get("assignments"), str):
                            row["assignments"] = json.loads(row["assignments"])
                        if row.get("assignments"):
                            row["assignments"] = [
                                assignment
                                for assignment in row["assignments"]
                                if assignment is not None
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
                            s.is_pinned, s.allow_juniors, s.profile_image_url,
                            s.stream_game_id as game_id, s.stream_game_name as game_name, s.stream_started_at as started_at,
                            s.priority, s.pr_slots,
                            s.priority_override AS current_stream_priority_override,
                            s.pr_slots_override AS current_stream_pr_slots_override,
                            s.added_at, s.added_by_id, s.updated_at,
                            MIN(act.pr_id) as assigned_pr_id,
                            COALESCE(
                                JSON_ARRAYAGG(
                                    CASE WHEN a.pr_id IS NOT NULL THEN
                                        JSON_OBJECT(
                                            'pr_id', CAST(a.pr_id AS CHAR),
                                            'nickname', a.nickname,
                                            'is_probation', COALESCE(act.is_probation, FALSE),
                                            'assigned_at', act.started_at
                                        )
                                    ELSE NULL END
                                ),
                                JSON_ARRAY()
                            ) as assignments
                        FROM streamers s
                        LEFT JOIN active_assignments_v act ON act.target_type = 'streamer' 
                             AND act.target_id = s.streamer_id 
                        LEFT JOIN assistants a ON a.pr_id = act.pr_id
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
        outbox_events: Optional[List[Dict[str, Any]]] = None,
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
                    await self._enqueue_outbox_messages_with_cursor(cursor, outbox_events)
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

    @staticmethod
    def _current_msk_date() -> date:
        return datetime.now(timezone(timedelta(hours=3))).date()

    @classmethod
    def _iter_interval_dates(
        cls,
        started_at: Optional[datetime],
        ended_at: Optional[datetime],
    ) -> Set[date]:
        start = cls._normalize_msk_datetime(started_at)
        end = cls._normalize_msk_datetime(ended_at)
        if start is None:
            return set()
        effective_end = end or datetime.combine(cls._current_msk_date() + timedelta(days=1), datetime.min.time())
        if effective_end <= start:
            return set()

        dates: Set[date] = set()
        cursor = start
        while cursor < effective_end:
            dates.add(cursor.date())
            cursor = datetime.combine(cursor.date() + timedelta(days=1), datetime.min.time())
        return dates

    def _compute_session_points(self, session_row: Dict[str, Any]) -> float:
        """Compute deterministic points contribution for a single session row."""
        if not session_row:
            return 0.0
        ended_at = self._normalize_db_datetime(session_row.get("ended_at"))
        if ended_at is None:
            return 0.0
        if session_row.get("deleted_at") is not None:
            return 0.0

        duration_seconds = float(session_row.get("duration_seconds") or 0.0)

        # User-requested pending time must never count retroactively.
        if session_row.get("event_kind") == "spec_request":
            if session_row.get("approval_status") != "approved":
                return 0.0

            effective_start = self._approved_session_start(
                session_row.get("started_at"),
                session_row.get("approved_at"),
            )
            if effective_start is None or effective_start >= ended_at:
                return 0.0
            duration_seconds = max(
                int((ended_at - effective_start).total_seconds()),
                0,
            )

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
                       ss.started_at, ss.applied_hourly_rate, ss.credited_points,
                       ss.target_type, ss.target_id,
                       e.event_kind, e.approval_status, e.approved_at
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

            return delta

    async def _recalc_points_for_sessions(
        self, conn, session_ids: List[int], lock: bool = True
    ) -> None:
        for session_id in session_ids:
            await self._recalc_session_points_delta(conn, session_id, lock=lock)

    @db_retry()
    async def assign_pr_to_streamer(
        self,
        streamer_id: int,
        pr_id: int,
        is_probation: bool = False,
        outbox_events: Optional[List[Dict[str, Any]]] = None,
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

                    await self._enqueue_outbox_messages_with_cursor(cursor, outbox_events)
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
        outbox_trace_id: Optional[str] = None,
        outbox_events: Optional[List[Dict[str, Any]]] = None,
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
            allowed_reasons = set(SPEC_SESSION_END_REASONS)
            if end_reason not in allowed_reasons:
                self.logger.warning(f"Invalid end_reason '{end_reason}' passed to unassign_pr_from_streamer. Fallback to 'unknown'.")
                end_reason = SPEC_SESSION_END_REASON_UNKNOWN

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

                    staged_outbox_events: List[Dict[str, Any]] = list(outbox_events or [])
                    if outbox_trace_id:
                        for session in unassigned_sessions:
                            staged_outbox_events.append(
                                {
                                    "routing_key": "spec.unclaimed",
                                    "payload": {
                                        "event": "spec.unclaimed",
                                        "streamer_id": streamer_id,
                                        "streamer_name": session.get("streamer_name", "Unknown"),
                                        "pr_id": session.get("pr_id"),
                                        "duration_seconds": session.get("duration_seconds", 0),
                                        "reason": end_reason,
                                        "trace_id": outbox_trace_id,
                                    },
                                }
                            )
                    await self._enqueue_outbox_messages_with_cursor(
                        cursor,
                        staged_outbox_events,
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
                        LEFT JOIN active_assignments_v act
                          ON act.target_type = 'streamer'
                         AND act.target_id = s.streamer_id
                        WHERE s.is_online = TRUE
                          AND s.stream_game_id = %s
                          AND act.session_id IS NULL
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
        is_pinned: bool = False,
        points: Optional[float] = None,
        outbox_trace_id: Optional[str] = None,
        outbox_events: Optional[List[Dict[str, Any]]] = None,
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
                            pr_slots, priority, is_pinned, points
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                            is_pinned,
                            points,
                        ),
                    )
                    event_id = int(cursor.lastrowid)
                    staged_outbox_events: List[Dict[str, Any]] = list(outbox_events or [])
                    if outbox_trace_id:
                        staged_outbox_events.append(
                            {
                                "routing_key": "event.added",
                                "payload": {
                                    "event": "event.added",
                                    "event_id": event_id,
                                    "event_name": name,
                                    "trace_id": outbox_trace_id,
                                },
                            }
                        )
                    await self._enqueue_outbox_messages_with_cursor(
                        cursor,
                        staged_outbox_events,
                    )
                    await conn.commit()
                    return event_id
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
                               required_pr_count, priority, pr_slots, is_pinned, points,
                               event_kind, approval_status, requested_by, approved_by, approved_at, rejected_by, rejected_at
                        FROM events
                        ORDER BY is_active DESC, is_pinned DESC, created_at DESC
                        """
                    )
                    events = await cursor.fetchall()
                    for event in events:
                        await cursor.execute(
                            """
                            SELECT act.pr_id, a.nickname
                            FROM active_assignments_v act
                            LEFT JOIN assistants a ON a.pr_id = act.pr_id
                            WHERE act.target_type = 'event' AND act.target_id = %s
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
                               required_pr_count, priority, pr_slots, is_pinned, points,
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
                            SELECT act.pr_id, a.nickname, 'active' as status
                            FROM active_assignments_v act
                            LEFT JOIN assistants a ON a.pr_id = act.pr_id
                            WHERE act.target_type = 'event' AND act.target_id = %s
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
                        """
                        SELECT
                            id, name, description, created_at, start_time, is_active, created_by,
                            notification_sent, required_pr_count, priority, pr_slots, is_pinned,
                            points, event_kind, approval_status, requested_by,
                            approved_by, approved_at, rejected_by, rejected_at
                        FROM events
                        WHERE id = %s
                        """,
                        (event_id,),
                    )
                    event = await cursor.fetchone()
                    if not event:
                        return None

                    await cursor.execute(
                        """
                        SELECT act.pr_id, a.nickname, 'active' AS status
                        FROM active_assignments_v act
                        LEFT JOIN assistants a ON a.pr_id = act.pr_id
                        WHERE act.target_type = 'event' AND act.target_id = %s
                        """,
                        (event_id,),
                    )
                    active_participants = await cursor.fetchall() or []

                    await cursor.execute(
                        """
                        SELECT ep.pr_id, a.nickname, 'reserved' AS status
                        FROM event_participants ep
                        LEFT JOIN assistants a ON a.pr_id = ep.pr_id
                        WHERE ep.event_id = %s
                        """,
                        (event_id,),
                    )
                    reserved_participants = await cursor.fetchall() or []

                    participants = list(active_participants) + list(reserved_participants)
                    event["current_participants"] = len(participants)
                    event["participants"] = [
                        {
                            "pr_id": str(p["pr_id"]),
                            "nickname": p.get("nickname"),
                            "status": p.get("status", "active"),
                        }
                        for p in participants
                    ]
                    return event
        except Exception as e:
            self.logger.error(f"Failed to get event {event_id}: {e}", exc_info=True)
            return None

    @db_retry()
    async def end_event(
        self,
        event_id: int,
        outbox_trace_id: Optional[str] = None,
        outbox_events: Optional[List[Dict[str, Any]]] = None,
    ) -> list:
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
                        "SELECT start_time, name FROM events WHERE id = %s",
                        (event_id,),
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
                    event_name = event_data.get("name") or "Unknown"

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

                        results.append({"pr_id": user_id, "duration": duration})

                    staged_outbox_events: List[Dict[str, Any]] = list(outbox_events or [])
                    if outbox_trace_id:
                        for participant in results:
                            staged_outbox_events.append(
                                {
                                    "routing_key": "event.left",
                                    "payload": {
                                        "event": "event.left",
                                        "event_id": event_id,
                                        "event_name": event_name,
                                        "pr_id": participant.get("pr_id"),
                                        "duration_seconds": participant.get("duration", 0),
                                        "ended_at": None,
                                        "trace_id": outbox_trace_id,
                                    },
                                }
                            )
                        staged_outbox_events.append(
                            {
                                "routing_key": "event.ended",
                                "payload": {
                                    "event": "event.ended",
                                    "event_id": event_id,
                                    "event_name": event_name,
                                    "trace_id": outbox_trace_id,
                                },
                            }
                        )
                    await self._enqueue_outbox_messages_with_cursor(
                        cursor,
                        staged_outbox_events,
                    )
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

            affected_dates = sorted(
                day
                for day in self._iter_interval_dates(start_time, end_time)
                if day < self._current_msk_date()
            )

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
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            pr_id,
                            target_type,
                            target_id_value,
                            target_name,
                            start_time,
                            end_time,
                            SPEC_SESSION_END_REASON_ADMIN_CLOSED,
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
            if affected_dates:
                try:
                    await self.recalculate_assistant_sanction_derivations(
                        assistant_id=pr_id,
                        start_date=affected_dates[0],
                        end_date=affected_dates[-1],
                    )
                except Exception as recalc_exc:
                    self.logger.error(
                        "Failed to auto-recalculate assistant_sanctions after manual spec session create: pr_id=%s, dates=%s, error=%s",
                        pr_id,
                        affected_dates,
                        recalc_exc,
                        exc_info=True,
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
    async def join_event(
        self,
        event_id: int,
        user_id: int,
        outbox_trace_id: Optional[str] = None,
        outbox_events: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
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
                            staged_outbox_events: List[Dict[str, Any]] = list(outbox_events or [])
                            if outbox_trace_id:
                                staged_outbox_events.append(
                                    {
                                        "routing_key": "event.joined",
                                        "payload": {
                                            "event": "event.joined",
                                            "event_id": event_id,
                                            "event_name": event_name,
                                            "pr_id": user_id,
                                            "trace_id": outbox_trace_id,
                                        },
                                    }
                                )
                            await self._enqueue_outbox_messages_with_cursor(
                                cursor,
                                staged_outbox_events,
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
                        staged_outbox_events = list(outbox_events or [])
                        if outbox_trace_id:
                            staged_outbox_events.append(
                                {
                                    "routing_key": "event.updated",
                                    "payload": {
                                        "event": "event.updated",
                                        "event_id": event_id,
                                        "event_name": event_name,
                                        "trace_id": outbox_trace_id,
                                    },
                                }
                            )
                        await self._enqueue_outbox_messages_with_cursor(
                            cursor,
                            staged_outbox_events,
                        )
                        await conn.commit()
                        self.logger.debug(f"User {user_id} reserved slot for future event {event_id} ('{event_name}').")
                        return {"status": "reserved", "detail": "Reserved slot for future event"}

        except Exception as e:
            self.logger.error(f"Failed to join event: {e}", exc_info=True)
            return {"status": "error", "detail": "Internal database error"}

    @db_retry()
    async def leave_event(
        self,
        event_id: int,
        user_id: int,
        end_reason: str = "manual_unclaim",
        outbox_trace_id: Optional[str] = None,
        outbox_events: Optional[List[Dict[str, Any]]] = None,
    ) -> int:
        """Удаление пользователя из события и возврат длительности."""
        try:
            # Fail-safe: ensure end_reason is valid for ENUM
            allowed_reasons = set(SPEC_SESSION_END_REASONS)
            if end_reason not in allowed_reasons:
                self.logger.warning(f"Invalid end_reason '{end_reason}' passed to leave_event. Fallback to 'unknown'.")
                end_reason = SPEC_SESSION_END_REASON_UNKNOWN

            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    self.logger.debug(f"User {user_id} attempting to leave event {event_id}. Reason: {end_reason}.")

                    # 0. Check if user is in reserved state
                    await cursor.execute(
                        "SELECT name FROM events WHERE id = %s",
                        (event_id,),
                    )
                    event_row = await cursor.fetchone() or {}
                    event_name = event_row.get("name", "Unknown")

                    await cursor.execute(
                        "DELETE FROM event_participants WHERE event_id = %s AND pr_id = %s",
                        (event_id, user_id)
                    )
                    if cursor.rowcount > 0:
                        staged_outbox_events: List[Dict[str, Any]] = list(outbox_events or [])
                        if outbox_trace_id:
                            staged_outbox_events.append(
                                {
                                    "routing_key": "event.updated",
                                    "payload": {
                                        "event": "event.updated",
                                        "event_id": event_id,
                                        "event_name": event_name,
                                        "trace_id": outbox_trace_id,
                                    },
                                }
                            )
                        await self._enqueue_outbox_messages_with_cursor(
                            cursor,
                            staged_outbox_events,
                        )
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

                    staged_outbox_events = list(outbox_events or [])
                    if outbox_trace_id:
                        if duration_row and int(duration_row.get("duration_seconds") or 0) > 0:
                            staged_outbox_events.append(
                                {
                                    "routing_key": "event.left",
                                    "payload": {
                                        "event": "event.left",
                                        "event_id": event_id,
                                        "event_name": event_name,
                                        "pr_id": user_id,
                                        "duration_seconds": int(duration_row.get("duration_seconds") or 0),
                                        "ended_at": None,
                                        "trace_id": outbox_trace_id,
                                    },
                                }
                            )
                        else:
                            staged_outbox_events.append(
                                {
                                    "routing_key": "event.updated",
                                    "payload": {
                                        "event": "event.updated",
                                        "event_id": event_id,
                                        "event_name": event_name,
                                        "trace_id": outbox_trace_id,
                                    },
                                }
                            )
                    await self._enqueue_outbox_messages_with_cursor(
                        cursor,
                        staged_outbox_events,
                    )
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
        outbox_trace_id: Optional[str] = None,
        outbox_events: Optional[List[Dict[str, Any]]] = None,
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

                    staged_outbox_events: List[Dict[str, Any]] = list(outbox_events or [])
                    if outbox_trace_id:
                        staged_outbox_events.append(
                            {
                                "routing_key": "event.joined",
                                "payload": {
                                    "event": "event.joined",
                                    "event_id": event_id,
                                    "event_name": name,
                                    "pr_id": requested_by,
                                    "trace_id": outbox_trace_id,
                                },
                            }
                        )
                    await self._enqueue_outbox_messages_with_cursor(
                        cursor,
                        staged_outbox_events,
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
                        SELECT id, name, approval_status, event_kind FROM events
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
        outbox_trace_id: Optional[str] = None,
        outbox_events: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """Approve a pending spec_request event."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    self.logger.debug(f"Attempting to approve spec request {event_id} by {approved_by}.")

                    await cursor.execute(
                        """
                        SELECT id, name, approval_status, event_kind FROM events
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
                    event_name = event.get("name", "Unknown")

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

                    staged_outbox_events: List[Dict[str, Any]] = list(outbox_events or [])
                    if outbox_trace_id and closed_sessions:
                        for session in closed_sessions:
                            staged_outbox_events.append(
                                {
                                    "routing_key": "event.left",
                                    "payload": {
                                        "event": "event.left",
                                        "event_id": event_id,
                                        "event_name": event_name,
                                        "pr_id": session["pr_id"],
                                        "duration_seconds": session.get("duration_seconds", 0),
                                        "ended_at": (
                                            session["ended_at"].isoformat()
                                            if session.get("ended_at")
                                            else None
                                        ),
                                        "trace_id": outbox_trace_id,
                                    },
                                }
                            )
                        staged_outbox_events.append(
                            {
                                "routing_key": "event.ended",
                                "payload": {
                                    "event": "event.ended",
                                    "event_id": event_id,
                                    "event_name": event_name,
                                    "trace_id": outbox_trace_id,
                                },
                            }
                        )
                    await self._enqueue_outbox_messages_with_cursor(
                        cursor,
                        staged_outbox_events,
                    )
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
                        SELECT pr_id, started_at as joined_at, 'active' as status
                        FROM active_assignments_v
                        WHERE target_type = 'event' AND target_id = %s
                        """,
                        (event_id,),
                    )
                    active = await cursor.fetchall() or []

                    # Get reserved
                    await cursor.execute(
                        """
                        SELECT pr_id, joined_at, 'reserved' as status
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
    async def start_event_sessions(
        self,
        event_id: int,
        outbox_trace_id: Optional[str] = None,
        outbox_events: Optional[List[Dict[str, Any]]] = None,
    ) -> list:
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
                    staged_outbox_events: List[Dict[str, Any]] = list(outbox_events or [])
                    if outbox_trace_id:
                        for migrated_pr_id in migrated_pr_ids:
                            staged_outbox_events.append(
                                {
                                    "routing_key": "event.joined",
                                    "payload": {
                                        "event": "event.joined",
                                        "event_id": event_id,
                                        "event_name": event_name,
                                        "pr_id": migrated_pr_id,
                                        "trace_id": outbox_trace_id,
                                    },
                                }
                            )
                    await self._enqueue_outbox_messages_with_cursor(
                        cursor,
                        staged_outbox_events,
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

    @db_retry()
    async def update_assistant_session(
        self,
        pr_id: int,
        session_id: int,
        patch: Dict[str, Any],
        outbox_trace_id: Optional[str] = None,
        outbox_events: Optional[List[Dict[str, Any]]] = None,
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
                    affected_dates = set(
                        day
                        for day in self._iter_interval_dates(current_started, current_ended)
                        if day < self._current_msk_date()
                    )

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
                            params.append(SPEC_SESSION_END_REASON_ADMIN_CLOSED)

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
                    affected_dates.update(
                        day
                        for day in self._iter_interval_dates(next_started, next_ended)
                        if day < self._current_msk_date()
                    )

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
                    staged_outbox_events: List[Dict[str, Any]] = list(outbox_events or [])
                    if (
                        outbox_trace_id
                        and before.get("ended_at") is None
                        and after
                        and after.get("ended_at") is not None
                    ):
                        target_type = after.get("target_type")
                        target_id = after.get("target_id")
                        target_name = after.get("target_name") or "Unknown"
                        duration = int(after.get("duration_seconds") or 0)
                        if target_type == "streamer" and target_id is not None:
                            staged_outbox_events.append(
                                {
                                    "routing_key": "spec.unclaimed",
                                    "payload": {
                                        "event": "spec.unclaimed",
                                        "streamer_id": int(target_id),
                                        "streamer_name": target_name,
                                        "pr_id": pr_id,
                                        "duration_seconds": duration,
                                        "reason": "admin_closed",
                                        "trace_id": outbox_trace_id,
                                    },
                                }
                            )
                        elif target_type == "event" and target_id is not None:
                            ended_dt = after.get("ended_at")
                            staged_outbox_events.append(
                                {
                                    "routing_key": "event.left",
                                    "payload": {
                                        "event": "event.left",
                                        "event_id": int(target_id),
                                        "event_name": target_name,
                                        "pr_id": pr_id,
                                        "duration_seconds": duration,
                                        "ended_at": (
                                            ended_dt.isoformat()
                                            if hasattr(ended_dt, "isoformat")
                                            else str(ended_dt)
                                        ),
                                        "trace_id": outbox_trace_id,
                                    },
                                }
                            )
                    await self._enqueue_outbox_messages_with_cursor(
                        cursor,
                        staged_outbox_events,
                    )
                    await conn.commit()
                    if affected_dates:
                        try:
                            await self.recalculate_assistant_sanction_derivations(
                                assistant_id=pr_id,
                                start_date=min(affected_dates),
                                end_date=max(affected_dates),
                            )
                        except Exception as recalc_exc:
                            self.logger.error(
                                "Failed to auto-recalculate assistant_sanctions after session patch: pr_id=%s session_id=%s dates=%s error=%s",
                                pr_id,
                                session_id,
                                sorted(affected_dates),
                                recalc_exc,
                                exc_info=True,
                            )
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
                    affected_dates = sorted(
                        day
                        for day in self._iter_interval_dates(
                            before.get("started_at"),
                            before.get("ended_at"),
                        )
                        if day < self._current_msk_date()
                    )

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
                    if affected_dates:
                        try:
                            await self.recalculate_assistant_sanction_derivations(
                                assistant_id=pr_id,
                                start_date=affected_dates[0],
                                end_date=affected_dates[-1],
                            )
                        except Exception as recalc_exc:
                            self.logger.error(
                                "Failed to auto-recalculate assistant_sanctions after session delete: pr_id=%s session_id=%s dates=%s error=%s",
                                pr_id,
                                session_id,
                                affected_dates,
                                recalc_exc,
                                exc_info=True,
                            )
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
                            CASE WHEN act.session_id IS NOT NULL THEN 'assigned' ELSE 'free' END as status,
                            act.target_type as assigned_to_type, act.target_id as assigned_to_id, 
                            COALESCE(stats.total_secs, 0) as total_spec_seconds, 
                            COALESCE(stats.sess_count, 0) as session_count, a.added_at, a.appointed_at, a.updated_at,
                            ROUND(COALESCE(points.auto_points_total, 0) + COALESCE(adj.manual_points_adjustment, 0), 4) as gross_points,
                            ROUND(COALESCE(sb.penalty_points, 0), 4) as active_point_penalty,
                            ROUND(COALESCE(sb.penalty_percent, 0), 4) as active_percent_penalty,
                            COALESCE(sb.strict_warnings, 0) * 2 + COALESCE(sb.oral_warnings, 0) as active_warning_units,
                            ROUND(
                                COALESCE(points.auto_points_total, 0) + COALESCE(adj.manual_points_adjustment, 0) - COALESCE(sb.penalty_points, 0),
                                4
                            ) as net_points,
                            COALESCE(sb.strict_warnings, 0) as active_strict_warnings,
                            COALESCE(sb.oral_warnings, 0) as active_oral_warnings,
                            CONCAT(
                                COALESCE(sb.strict_warnings, 0),
                                '/2 ',
                                COALESCE(sb.oral_warnings, 0),
                                '/2'
                            ) as active_warnings_display,
                            ROUND(COALESCE(sb.check_marks, 0), 4) as active_checks,
                            COALESCE(s.streamer_name, e.name) as assigned_to_name,
                            ROUND(COALESCE(stats.total_secs, 0) / 3600, 1) as total_spec_hours,
                            ROUND(COALESCE(recent.total_secs_30d, 0) / 3600, 4) as total_spec_hours_30d,
                            ROUND((COALESCE(recent.total_secs_30d, 0) / 3600) / 30.0, 4) as avg_spec_hours_per_day_30d
                        FROM assistants a
                        LEFT JOIN active_assignments_v act ON act.pr_id = a.pr_id
                        LEFT JOIN (
                            SELECT pr_id, SUM(duration_seconds) as total_secs, COUNT(*) as sess_count
                            FROM spec_sessions WHERE deleted_at IS NULL AND ended_at IS NOT NULL
                            GROUP BY pr_id
                        ) stats ON stats.pr_id = a.pr_id
                        LEFT JOIN (
                            SELECT assistant_id, ROUND(SUM(spec_points_auto), 4) AS auto_points_total
                            FROM assistant_day_spec_totals
                            GROUP BY assistant_id
                        ) points ON points.assistant_id = a.pr_id
                        LEFT JOIN (
                            SELECT assistant_id, ROUND(SUM(delta_points), 4) AS manual_points_adjustment
                            FROM assistant_day_point_adjustments
                            GROUP BY assistant_id
                        ) adj ON adj.assistant_id = a.pr_id
                        LEFT JOIN (
                            SELECT
                                assistant_id,
                                ROUND(SUM(CASE WHEN kind = 'point' THEN active_amount ELSE 0 END), 4) AS penalty_points,
                                ROUND(SUM(CASE WHEN kind = 'percent' THEN active_amount ELSE 0 END), 4) AS penalty_percent,
                                ROUND(SUM(CASE WHEN kind = 'check' THEN active_amount ELSE 0 END), 4) AS check_marks,
                                ROUND(SUM(CASE WHEN kind = 'oral' THEN active_amount ELSE 0 END), 4) AS oral_warnings,
                                ROUND(SUM(CASE WHEN kind = 'strict' THEN active_amount ELSE 0 END), 4) AS strict_warnings
                            FROM sanction_balances
                            GROUP BY assistant_id
                        ) sb ON sb.assistant_id = a.pr_id
                        LEFT JOIN (
                            SELECT pr_id, SUM(seconds_in_day) as total_secs_30d
                            FROM spec_session_day_slices
                            WHERE work_date >= DATE_SUB(CURDATE(), INTERVAL 29 DAY)
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
                            CASE WHEN act.session_id IS NOT NULL THEN 'assigned' ELSE 'free' END as status,
                            act.target_type as assigned_to_type, act.target_id as assigned_to_id, 
                            COALESCE(stats.total_secs, 0) as total_spec_seconds, 
                            COALESCE(stats.sess_count, 0) as session_count, a.added_at, a.appointed_at, a.updated_at,
                            ROUND(COALESCE(points.auto_points_total, 0) + COALESCE(adj.manual_points_adjustment, 0), 4) as gross_points,
                            ROUND(COALESCE(sb.penalty_points, 0), 4) as active_point_penalty,
                            ROUND(COALESCE(sb.penalty_percent, 0), 4) as active_percent_penalty,
                            COALESCE(sb.strict_warnings, 0) * 2 + COALESCE(sb.oral_warnings, 0) as active_warning_units,
                            ROUND(
                                COALESCE(points.auto_points_total, 0) + COALESCE(adj.manual_points_adjustment, 0) - COALESCE(sb.penalty_points, 0),
                                4
                            ) as net_points,
                            COALESCE(sb.strict_warnings, 0) as active_strict_warnings,
                            COALESCE(sb.oral_warnings, 0) as active_oral_warnings,
                            CONCAT(
                                COALESCE(sb.strict_warnings, 0),
                                '/2 ',
                                COALESCE(sb.oral_warnings, 0),
                                '/2'
                            ) as active_warnings_display,
                            ROUND(COALESCE(sb.check_marks, 0), 4) as active_checks,
                            COALESCE(s.streamer_name, e.name) as assigned_to_name,
                            ROUND(COALESCE(stats.total_secs, 0) / 3600, 1) as total_spec_hours,
                            ROUND(COALESCE(recent.total_secs_30d, 0) / 3600, 4) as total_spec_hours_30d,
                            ROUND((COALESCE(recent.total_secs_30d, 0) / 3600) / 30.0, 4) as avg_spec_hours_per_day_30d
                        FROM assistants a
                        LEFT JOIN active_assignments_v act ON act.pr_id = a.pr_id
                        LEFT JOIN (
                            SELECT pr_id, SUM(duration_seconds) as total_secs, COUNT(*) as sess_count
                            FROM spec_sessions WHERE deleted_at IS NULL AND ended_at IS NOT NULL
                            GROUP BY pr_id
                        ) stats ON stats.pr_id = a.pr_id
                        LEFT JOIN (
                            SELECT assistant_id, ROUND(SUM(spec_points_auto), 4) AS auto_points_total
                            FROM assistant_day_spec_totals
                            GROUP BY assistant_id
                        ) points ON points.assistant_id = a.pr_id
                        LEFT JOIN (
                            SELECT assistant_id, ROUND(SUM(delta_points), 4) AS manual_points_adjustment
                            FROM assistant_day_point_adjustments
                            GROUP BY assistant_id
                        ) adj ON adj.assistant_id = a.pr_id
                        LEFT JOIN (
                            SELECT
                                assistant_id,
                                ROUND(SUM(CASE WHEN kind = 'point' THEN active_amount ELSE 0 END), 4) AS penalty_points,
                                ROUND(SUM(CASE WHEN kind = 'percent' THEN active_amount ELSE 0 END), 4) AS penalty_percent,
                                ROUND(SUM(CASE WHEN kind = 'check' THEN active_amount ELSE 0 END), 4) AS check_marks,
                                ROUND(SUM(CASE WHEN kind = 'oral' THEN active_amount ELSE 0 END), 4) AS oral_warnings,
                                ROUND(SUM(CASE WHEN kind = 'strict' THEN active_amount ELSE 0 END), 4) AS strict_warnings
                            FROM sanction_balances
                            GROUP BY assistant_id
                        ) sb ON sb.assistant_id = a.pr_id
                        LEFT JOIN (
                            SELECT pr_id, SUM(seconds_in_day) as total_secs_30d
                            FROM spec_session_day_slices
                            WHERE work_date >= DATE_SUB(CURDATE(), INTERVAL 29 DAY)
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
                            CASE WHEN act.session_id IS NOT NULL THEN 'assigned' ELSE 'free' END as status,
                            act.target_type as assigned_to_type, act.target_id as assigned_to_id, 
                            COALESCE(stats.total_secs, 0) as total_spec_seconds, 
                            COALESCE(stats.sess_count, 0) as session_count, a.added_at, a.appointed_at, a.updated_at,
                            ROUND(COALESCE(points.auto_points_total, 0) + COALESCE(adj.manual_points_adjustment, 0), 4) as gross_points,
                            ROUND(COALESCE(sb.penalty_points, 0), 4) as active_point_penalty,
                            ROUND(COALESCE(sb.penalty_percent, 0), 4) as active_percent_penalty,
                            COALESCE(sb.strict_warnings, 0) * 2 + COALESCE(sb.oral_warnings, 0) as active_warning_units,
                            ROUND(
                                COALESCE(points.auto_points_total, 0) + COALESCE(adj.manual_points_adjustment, 0) - COALESCE(sb.penalty_points, 0),
                                4
                            ) as net_points,
                            COALESCE(sb.strict_warnings, 0) as active_strict_warnings,
                            COALESCE(sb.oral_warnings, 0) as active_oral_warnings,
                            CONCAT(
                                COALESCE(sb.strict_warnings, 0),
                                '/2 ',
                                COALESCE(sb.oral_warnings, 0),
                                '/2'
                            ) as active_warnings_display,
                            ROUND(COALESCE(sb.check_marks, 0), 4) as active_checks,
                            COALESCE(s.streamer_name, e.name) as assigned_to_name,
                            ROUND(COALESCE(stats.total_secs, 0) / 3600, 1) as total_spec_hours,
                            ROUND(COALESCE(recent.total_secs_30d, 0) / 3600, 4) as total_spec_hours_30d,
                            ROUND((COALESCE(recent.total_secs_30d, 0) / 3600) / 30.0, 4) as avg_spec_hours_per_day_30d
                        FROM assistants a
                        LEFT JOIN active_assignments_v act ON act.pr_id = a.pr_id
                        LEFT JOIN (
                            SELECT pr_id, SUM(duration_seconds) as total_secs, COUNT(*) as sess_count
                            FROM spec_sessions WHERE deleted_at IS NULL AND ended_at IS NOT NULL
                            GROUP BY pr_id
                        ) stats ON stats.pr_id = a.pr_id
                        LEFT JOIN (
                            SELECT assistant_id, ROUND(SUM(spec_points_auto), 4) AS auto_points_total
                            FROM assistant_day_spec_totals
                            GROUP BY assistant_id
                        ) points ON points.assistant_id = a.pr_id
                        LEFT JOIN (
                            SELECT assistant_id, ROUND(SUM(delta_points), 4) AS manual_points_adjustment
                            FROM assistant_day_point_adjustments
                            GROUP BY assistant_id
                        ) adj ON adj.assistant_id = a.pr_id
                        LEFT JOIN (
                            SELECT
                                assistant_id,
                                ROUND(SUM(CASE WHEN kind = 'point' THEN active_amount ELSE 0 END), 4) AS penalty_points,
                                ROUND(SUM(CASE WHEN kind = 'percent' THEN active_amount ELSE 0 END), 4) AS penalty_percent,
                                ROUND(SUM(CASE WHEN kind = 'check' THEN active_amount ELSE 0 END), 4) AS check_marks,
                                ROUND(SUM(CASE WHEN kind = 'oral' THEN active_amount ELSE 0 END), 4) AS oral_warnings,
                                ROUND(SUM(CASE WHEN kind = 'strict' THEN active_amount ELSE 0 END), 4) AS strict_warnings
                            FROM sanction_balances
                            GROUP BY assistant_id
                        ) sb ON sb.assistant_id = a.pr_id
                        LEFT JOIN (
                            SELECT pr_id, SUM(seconds_in_day) as total_secs_30d
                            FROM spec_session_day_slices
                            WHERE work_date >= DATE_SUB(CURDATE(), INTERVAL 29 DAY)
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
                        SELECT
                            base.work_date AS date,
                            COALESCE(ds.p0_seconds, 0) AS p0_seconds,
                            COALESCE(ds.p1_seconds, 0) AS p1_seconds,
                            COALESCE(ds.p2_seconds, 0) AS p2_seconds,
                            COALESCE(ds.p3_seconds, 0) AS p3_seconds,
                            ROUND(COALESCE(ds.total_points, 0) + COALESCE(ad.delta_points, 0), 4) AS total_points
                        FROM (
                            SELECT date AS work_date
                            FROM daily_stats
                            WHERE pr_id = %s
                            UNION
                            SELECT work_date
                            FROM assistant_day_point_adjustments
                            WHERE assistant_id = %s
                        ) base
                        LEFT JOIN daily_stats ds
                            ON ds.pr_id = %s
                           AND ds.date = base.work_date
                        LEFT JOIN assistant_day_point_adjustments ad
                            ON ad.assistant_id = %s
                           AND ad.work_date = base.work_date
                        ORDER BY base.work_date DESC
                        LIMIT 30
                        """,
                        (user_id, user_id, user_id, user_id),
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
        template_stream_online_gta: Optional[str] = None,
        template_stream_online_other: Optional[str] = None,
        template_stream_offline: Optional[str] = None,
        template_category_to_gta: Optional[str] = None,
        template_category_from_gta: Optional[str] = None,
        outbox_events: Optional[List[Dict[str, Any]]] = None,
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
            if template_stream_online_gta is not None:
                current_templates["stream_online_gta"] = template_stream_online_gta
            if template_stream_online_other is not None:
                current_templates["stream_online_other"] = template_stream_online_other
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
                    await self._enqueue_outbox_messages_with_cursor(cursor, outbox_events)
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
        outbox_events: Optional[List[Dict[str, Any]]] = None,
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
                    await self._enqueue_outbox_messages_with_cursor(cursor, outbox_events)
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
        """Legacy no-op.

        Discord-specific message linkage no longer belongs to core events.
        """
        self.logger.warning(
            "update_event_message_id(%s, %s) called on legacy path; ignoring",
            event_id,
            message_id,
        )
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
                        SELECT
                            s.streamer_id,
                            s.streamer_name,
                            act.pr_id as assigned_pr_id,
                            act.started_at as assigned_at,
                            TIMESTAMPDIFF(SECOND, act.started_at, CURRENT_TIMESTAMP) as duration_seconds
                        FROM active_assignments_v act
                        JOIN streamers s
                          ON act.target_type = 'streamer'
                         AND s.streamer_id = act.target_id
                        ORDER BY act.started_at DESC
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
    async def create_user_with_assistant(
        self,
        discord_id: int,
        username: str,
        password_hash: str,
        nickname: str,
        role: str,
        appointed_at: Optional[date] = None,
        experience_days: int = 0,
        created_by: Optional[int] = None,
    ) -> int:
        """Create web_auth and assistant records in a single transaction."""
        try:
            async with self.pool.acquire() as conn:
                try:
                    async with conn.cursor() as cursor:
                        await cursor.execute(
                            """
                            INSERT INTO web_auth (discord_id, username, password_hash, created_at)
                            VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                            """,
                            (discord_id, username, password_hash),
                        )

                        if appointed_at is not None:
                            appointed_at_dt = datetime.combine(
                                appointed_at,
                                datetime.min.time(),
                                tzinfo=timezone(timedelta(hours=3)),
                            )
                            await cursor.execute(
                                """
                                INSERT INTO assistants (pr_id, nickname, role, appointed_at)
                                VALUES (%s, %s, %s, %s)
                                """,
                                (discord_id, nickname, role, appointed_at_dt),
                            )
                        else:
                            await cursor.execute(
                                """
                                INSERT INTO assistants (pr_id, nickname, role, appointed_at)
                                VALUES (%s, %s, %s, DATE_SUB(CURRENT_TIMESTAMP, INTERVAL %s DAY))
                                """,
                                (discord_id, nickname, role, experience_days),
                            )

                        await conn.commit()
                        return discord_id
                except Exception:
                    await conn.rollback()
                    raise
        except Exception as e:
            self.logger.error(
                f"Failed to create user+assistant {username}: {e}",
                exc_info=True,
            )
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
                        "SELECT COUNT(*) as count FROM active_assignments_v"
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

    @db_retry()
    async def get_service_overview_stats(self) -> Dict[str, int]:
        """Get service-facing domain counters for the service overview panel."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT
                            COUNT(*) AS streamers_total,
                            COALESCE(SUM(CASE WHEN is_online = TRUE THEN 1 ELSE 0 END), 0) AS streamers_online,
                            COALESCE(SUM(CASE WHEN is_online = TRUE AND stream_game_id = %s THEN 1 ELSE 0 END), 0) AS gta_online
                        FROM streamers
                        """,
                        (Config.gta5_game_id,),
                    )
                    streamer_stats = await cursor.fetchone() or {}

                    await cursor.execute(
                        """
                        SELECT
                            COUNT(*) AS active_spec_sessions,
                            COALESCE(SUM(CASE WHEN is_probation = TRUE THEN 1 ELSE 0 END), 0) AS probation_sessions
                        FROM active_assignments_v
                        """
                    )
                    spec_stats = await cursor.fetchone() or {}

                    await cursor.execute(
                        "SELECT COUNT(*) AS active_events FROM events WHERE is_active = TRUE"
                    )
                    event_stats = await cursor.fetchone() or {}

                    await cursor.execute(
                        "SELECT COUNT(*) AS assistants_total FROM assistants"
                    )
                    assistant_stats = await cursor.fetchone() or {}

                    await cursor.execute(
                        "SELECT COUNT(*) AS web_users_total FROM web_auth"
                    )
                    user_stats = await cursor.fetchone() or {}

                    await cursor.execute(
                        """
                        SELECT COUNT(*) AS admin_actions_24h
                        FROM admin_logs
                        WHERE created_at >= (UTC_TIMESTAMP() - INTERVAL 1 DAY)
                        """
                    )
                    log_stats = await cursor.fetchone() or {}

                    return {
                        "streamers_total": int(streamer_stats.get("streamers_total", 0)),
                        "streamers_online": int(streamer_stats.get("streamers_online", 0)),
                        "gta_online": int(streamer_stats.get("gta_online", 0)),
                        "active_spec_sessions": int(spec_stats.get("active_spec_sessions", 0)),
                        "probation_sessions": int(spec_stats.get("probation_sessions", 0)),
                        "active_events": int(event_stats.get("active_events", 0)),
                        "assistants_total": int(assistant_stats.get("assistants_total", 0)),
                        "web_users_total": int(user_stats.get("web_users_total", 0)),
                        "admin_actions_24h": int(log_stats.get("admin_actions_24h", 0)),
                    }
        except Exception as e:
            self.logger.error(
                f"Failed to get service overview stats: {e}",
                exc_info=True,
            )
            return {
                "streamers_total": 0,
                "streamers_online": 0,
                "gta_online": 0,
                "active_spec_sessions": 0,
                "probation_sessions": 0,
                "active_events": 0,
                "assistants_total": 0,
                "web_users_total": 0,
                "admin_actions_24h": 0,
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

    # =========================================================================
    # Cutover Day Metrics / Sanctions / Batch Queue
    # =========================================================================

    @staticmethod
    def _default_sanction_policy_values() -> Dict[str, Any]:
        return {
            "check_cycle_size": 5,
            "check_immunity_hours_per_day": 4,
            "point_immunity_hours_per_day": 5,
            "percent_immunity_hours_per_day": 6,
            "check_relief_hours_per_day": 4,
            "point_relief_hours_per_day": 5,
            "percent_relief_hours_per_day": 6,
            "check_relief_min_streak_days": 2,
            "point_relief_min_streak_days": 2,
            "percent_relief_min_streak_days": 2,
            "percent_relief_step_amount": 3,
            "daily_norm_spec": 4,
            "daily_norm_complaints": 0,
            "daily_norm_mchat": 0,
        }

    @staticmethod
    def _default_check_cycle_rules() -> List[tuple[int, Optional[int], str, float]]:
        return [
            (1, 2, "point", 1.0),
            (3, 3, "point", 2.0),
            (4, 5, "percent", 3.0),
            (6, 6, "percent", 5.0),
            (7, 7, "oral", 1.0),
            (8, None, "strict", 1.0),
        ]

    @staticmethod
    def _normalize_runtime_sanction(
        *,
        kind: str,
        amount: Optional[float],
        auto_relief_date: Optional[date],
    ) -> tuple[float, Optional[date]]:
        safe_kind = str(kind)
        if safe_kind in FIXED_SIZE_SANCTION_KINDS:
            normalized_amount = 1.0
        else:
            if amount is None or float(amount) <= 0:
                raise ValueError("Для выбранной санкции требуется положительный размер")
            normalized_amount = round(float(amount), 4)

        normalized_auto_relief_date = (
            auto_relief_date if safe_kind in WARNING_SANCTION_KINDS else None
        )
        if safe_kind in WARNING_SANCTION_KINDS and normalized_auto_relief_date is None:
            raise ValueError("Для устного и строгого требуется дата автоматического снятия")
        return normalized_amount, normalized_auto_relief_date

    async def _ensure_monthly_policy_row(
        self, cursor, month_start: date
    ) -> Dict[str, Any]:
        await cursor.execute(
            """
            INSERT INTO monthly_sanction_settings (
                month_start,
                check_cycle_size,
                check_immunity_hours_per_day,
                point_immunity_hours_per_day,
                percent_immunity_hours_per_day,
                check_relief_hours_per_day,
                point_relief_hours_per_day,
                percent_relief_hours_per_day,
                check_relief_min_streak_days,
                point_relief_min_streak_days,
                percent_relief_min_streak_days,
                percent_relief_step_amount,
                daily_norm_spec,
                daily_norm_complaints,
                daily_norm_mchat
            )
            VALUES (%s, 5, 4, 5, 6, 4, 5, 6, 2, 2, 2, 3, 4, 0, 0)
            ON DUPLICATE KEY UPDATE month_start = month_start
            """,
            (month_start,),
        )
        await cursor.execute(
            "SELECT * FROM monthly_sanction_settings WHERE month_start = %s",
            (month_start,),
        )
        row = await cursor.fetchone() or {}
        await cursor.execute(
            "SELECT COUNT(*) AS cnt FROM monthly_check_rules WHERE month_start = %s",
            (month_start,),
        )
        count_row = await cursor.fetchone() or {}
        if int(count_row.get("cnt", 0)) == 0:
            for range_start, range_end, penalty_kind, penalty_amount in [
                (1, 2, "point", 1.0),
                (3, 3, "point", 2.0),
                (4, 5, "percent", 3.0),
                (6, 6, "percent", 5.0),
                (7, 7, "oral", 1.0),
                (8, None, "strict", 1.0),
            ]:
                await cursor.execute(
                    """
                    INSERT INTO monthly_check_rules (
                        month_start, range_start, range_end, penalty_kind, penalty_amount
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (month_start, range_start, range_end, penalty_kind, penalty_amount),
                )
        return row

    async def _ensure_current_policy_row(self, cursor) -> Dict[str, Any]:
        current_month = CURRENT_SANCTION_POLICY_MONTH
        await cursor.execute(
            "SELECT * FROM monthly_sanction_settings WHERE month_start = %s",
            (current_month,),
        )
        row = await cursor.fetchone() or {}

        if not row:
            template = self._default_sanction_policy_values()
            await cursor.execute(
                """
                SELECT *
                FROM monthly_sanction_settings
                WHERE month_start <> %s
                ORDER BY month_start DESC
                LIMIT 1
                """,
                (current_month,),
            )
            existing = await cursor.fetchone() or {}
            for key in template:
                if existing.get(key) is not None:
                    template[key] = existing[key]

            await cursor.execute(
                """
                INSERT INTO monthly_sanction_settings (
                    month_start,
                    check_cycle_size,
                    check_immunity_hours_per_day,
                    point_immunity_hours_per_day,
                    percent_immunity_hours_per_day,
                    check_relief_hours_per_day,
                    point_relief_hours_per_day,
                    percent_relief_hours_per_day,
                    check_relief_min_streak_days,
                    point_relief_min_streak_days,
                    percent_relief_min_streak_days,
                    percent_relief_step_amount,
                    daily_norm_spec,
                    daily_norm_complaints,
                    daily_norm_mchat
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    current_month,
                    int(template["check_cycle_size"]),
                    float(template["check_immunity_hours_per_day"]),
                    float(template["point_immunity_hours_per_day"]),
                    float(template["percent_immunity_hours_per_day"]),
                    float(template["check_relief_hours_per_day"]),
                    float(template["point_relief_hours_per_day"]),
                    float(template["percent_relief_hours_per_day"]),
                    int(template["check_relief_min_streak_days"]),
                    int(template["point_relief_min_streak_days"]),
                    int(template["percent_relief_min_streak_days"]),
                    float(template["percent_relief_step_amount"]),
                    float(template["daily_norm_spec"]),
                    int(template["daily_norm_complaints"]),
                    int(template["daily_norm_mchat"]),
                ),
            )
            await cursor.execute(
                "SELECT * FROM monthly_sanction_settings WHERE month_start = %s",
                (current_month,),
            )
            row = await cursor.fetchone() or {}

        await cursor.execute(
            "SELECT COUNT(*) AS cnt FROM monthly_check_rules WHERE month_start = %s",
            (current_month,),
        )
        count_row = await cursor.fetchone() or {}
        if int(count_row.get("cnt", 0)) == 0:
            await cursor.execute(
                """
                SELECT month_start
                FROM monthly_check_rules
                WHERE month_start <> %s
                GROUP BY month_start
                ORDER BY month_start DESC
                LIMIT 1
                """,
                (current_month,),
            )
            source_month_row = await cursor.fetchone() or {}
            source_month = source_month_row.get("month_start")
            if source_month is not None:
                await cursor.execute(
                    """
                    SELECT range_start, range_end, penalty_kind, penalty_amount
                    FROM monthly_check_rules
                    WHERE month_start = %s
                    ORDER BY range_start ASC, COALESCE(range_end, 4294967295) ASC, id ASC
                    """,
                    (source_month,),
                )
                source_rules = await cursor.fetchall() or []
            else:
                source_rules = []

            rules_to_insert = source_rules or [
                {
                    "range_start": range_start,
                    "range_end": range_end,
                    "penalty_kind": penalty_kind,
                    "penalty_amount": penalty_amount,
                }
                for range_start, range_end, penalty_kind, penalty_amount in self._default_check_cycle_rules()
            ]
            for rule in rules_to_insert:
                await cursor.execute(
                    """
                    INSERT INTO monthly_check_rules (
                        month_start, range_start, range_end, penalty_kind, penalty_amount
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        current_month,
                        int(rule["range_start"]),
                        int(rule["range_end"]) if rule.get("range_end") is not None else None,
                        str(rule["penalty_kind"]),
                        float(rule["penalty_amount"]),
                    ),
                )

        return row

    @staticmethod
    def _nightly_run_context_for_basis_date(
        basis_date: date,
    ) -> Dict[str, Any]:
        processing_date = basis_date + timedelta(days=1)
        run_started_at = datetime.combine(processing_date, datetime.min.time())
        return {
            "basis_date": basis_date,
            "processing_date": processing_date,
            "run_started_at": run_started_at,
        }

    @staticmethod
    def _normalize_manual_status(
        value: Any,
    ) -> Optional[str]:
        if value is None:
            return None
        normalized = str(value).strip().upper()
        if normalized == WEEKLY_MANUAL_STATUS_NONE:
            return None
        if normalized not in WEEKLY_MANUAL_STATUSES:
            return None
        return normalized

    async def _get_day_manual_status_locked(
        self,
        cursor,
        *,
        assistant_id: int,
        work_date: date,
    ) -> Dict[str, Any]:
        await cursor.execute(
            """
            SELECT manual_status, updated_at, updated_by_id
            FROM assistant_day_status_overrides
            WHERE assistant_id = %s
              AND work_date = %s
            LIMIT 1
            """,
            (assistant_id, work_date),
        )
        row = await cursor.fetchone() or {}
        manual_status = self._normalize_manual_status(row.get("manual_status"))
        return {
            "manual_status": manual_status,
            "is_leave_day": manual_status in LEAVE_MANUAL_STATUSES,
            "updated_at": row.get("updated_at"),
            "updated_by_id": row.get("updated_by_id"),
        }

    async def _claim_sanction_nightly_run_locked(
        self,
        cursor,
        *,
        basis_date: date,
    ) -> Dict[str, Any]:
        claimed_at = _msk_now().replace(tzinfo=None)
        stale_before = claimed_at - timedelta(seconds=SANCTIONS_NIGHTLY_STALE_SECONDS)
        await cursor.execute(
            """
            SELECT basis_date, status, started_at, finished_at, failure_reason
            FROM sanction_nightly_runs
            WHERE basis_date = %s
            LIMIT 1
            """,
            (basis_date,),
        )
        existing = await cursor.fetchone() or {}
        status = str(existing.get("status") or "")
        started_at = existing.get("started_at")

        if not existing:
            await cursor.execute(
                """
                INSERT INTO sanction_nightly_runs (
                    basis_date,
                    status,
                    started_at,
                    finished_at,
                    failure_reason
                )
                VALUES (%s, 'processing', %s, NULL, NULL)
                """,
                (basis_date, claimed_at),
            )
            return {
                "claimed": True,
                "status": "processing",
                "stale_recovered": False,
            }

        if status == "processing" and started_at is not None and started_at < stale_before:
            await cursor.execute(
                """
                UPDATE sanction_nightly_runs
                SET status = 'processing',
                    started_at = %s,
                    finished_at = NULL,
                    failure_reason = NULL
                WHERE basis_date = %s
                """,
                (claimed_at, basis_date),
            )
            return {
                "claimed": True,
                "status": "processing",
                "stale_recovered": True,
            }

        if status == "failed":
            await cursor.execute(
                """
                UPDATE sanction_nightly_runs
                SET status = 'processing',
                    started_at = %s,
                    finished_at = NULL,
                    failure_reason = NULL
                WHERE basis_date = %s
                """,
                (claimed_at, basis_date),
            )
            return {
                "claimed": True,
                "status": "processing",
                "stale_recovered": False,
                "replayed_failed_run": True,
            }

        return {
            "claimed": False,
            "status": status or None,
            "stale_recovered": False,
            "finished_at": existing.get("finished_at"),
            "failure_reason": existing.get("failure_reason"),
        }

    async def _complete_sanction_nightly_run_locked(
        self,
        cursor,
        *,
        basis_date: date,
    ) -> None:
        await cursor.execute(
            """
            UPDATE sanction_nightly_runs
            SET status = 'completed',
                finished_at = %s,
                failure_reason = NULL
            WHERE basis_date = %s
            """,
            (_msk_now().replace(tzinfo=None), basis_date),
        )

    async def _fail_sanction_nightly_run_locked(
        self,
        cursor,
        *,
        basis_date: date,
        failure_reason: str,
    ) -> None:
        await cursor.execute(
            """
            UPDATE sanction_nightly_runs
            SET status = 'failed',
                finished_at = %s,
                failure_reason = %s
            WHERE basis_date = %s
            """,
            (
                _msk_now().replace(tzinfo=None),
                str(failure_reason or "")[:65535],
                basis_date,
            ),
        )

    async def _compute_workoff_targets(
        self,
        cursor,
        *,
        month_start: date,
        period_days: Optional[int],
        multiplier: Optional[float],
        use_spec: bool,
        use_complaints: bool,
        use_mchat: bool,
        ) -> Dict[str, Any]:
        if not period_days or not multiplier or multiplier <= 0:
            return {
                "workoff_period_days": None,
                "workoff_multiplier": None,
                "workoff_target_spec": None,
                "workoff_target_complaints": None,
                "workoff_target_mchat": None,
            }

        policy = await self._ensure_current_policy_row(cursor)
        days = int(period_days)
        factor = float(multiplier)

        return {
            "workoff_period_days": days,
            "workoff_multiplier": factor,
            "workoff_target_spec": round(float(policy.get("daily_norm_spec") or 0) * days * factor, 4)
            if use_spec
            else None,
            "workoff_target_complaints": int(round(float(policy.get("daily_norm_complaints") or 0) * days * factor))
            if use_complaints
            else None,
            "workoff_target_mchat": int(round(float(policy.get("daily_norm_mchat") or 0) * days * factor))
            if use_mchat
            else None,
        }

    @staticmethod
    def _normalize_workoff_items(
        workoff_items: Optional[List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for raw_item in workoff_items or []:
            metric = str(raw_item.get("metric") or "").strip()
            if metric not in {"spec", "complaints", "mchat"}:
                raise ValueError("Unsupported workoff metric")
            multiplier = float(raw_item.get("multiplier") or 0)
            if multiplier <= 0:
                raise ValueError("Workoff multiplier must be greater than 0")
            period_start = raw_item.get("period_start")
            period_end = raw_item.get("period_end")
            if not isinstance(period_start, date) or not isinstance(period_end, date):
                raise ValueError("Workoff period must include valid start and end dates")
            if period_end < period_start:
                raise ValueError("Workoff period_end must be greater than or equal to period_start")
            normalized.append(
                {
                    "metric": metric,
                    "multiplier": multiplier,
                    "period_start": period_start,
                    "period_end": period_end,
                }
            )
        return normalized

    async def _compute_workoff_item_target_amount_locked(
        self,
        cursor,
        *,
        metric: str,
        multiplier: float,
        period_start: date,
        period_end: date,
    ) -> float:
        target = 0.0
        cursor_day = period_start
        while cursor_day <= period_end:
            target += await self._daily_norm_amount_locked(
                cursor,
                metric=metric,
                work_date=cursor_day,
                multiplier=multiplier,
            )
            cursor_day += timedelta(days=1)
        if metric == "spec":
            return round(target, 4)
        return float(int(round(target)))

    async def _daily_norm_amount_locked(
        self,
        cursor,
        *,
        metric: str,
        work_date: date,
        multiplier: float,
    ) -> float:
        policy = await self._ensure_monthly_policy_row(
            cursor,
            self._month_start_for(work_date),
        )
        field_name = {
            "spec": "daily_norm_spec",
            "complaints": "daily_norm_complaints",
            "mchat": "daily_norm_mchat",
        }[metric]
        amount = float(policy.get(field_name) or 0) * float(multiplier)
        if metric == "spec":
            return round(amount, 4)
        return float(int(round(amount)))

    async def _day_metric_amount_locked(
        self,
        cursor,
        *,
        assistant_id: int,
        metric: str,
        work_date: date,
    ) -> float:
        if metric == "spec":
            metrics = await self._get_day_spec_metrics_locked(
                cursor,
                assistant_id=assistant_id,
                work_date=work_date,
            )
            return round(float(metrics.get("spec_hours_on_day") or 0), 4)

        if metric == "complaints":
            await cursor.execute(
                """
                SELECT COUNT(*) AS amount_done
                FROM complaints
                WHERE assistant_id = %s
                  AND status = 'completed'
                  AND DATE(completed_at) = %s
                """,
                (assistant_id, work_date),
            )
            row = await cursor.fetchone() or {}
            return float(int(row.get("amount_done") or 0))

        await cursor.execute(
            """
            SELECT mchat_count
            FROM assistant_day_mchat
            WHERE assistant_id = %s
              AND work_date = %s
            LIMIT 1
            """,
            (assistant_id, work_date),
        )
        row = await cursor.fetchone() or {}
        return float(int(row.get("mchat_count") or 0))

    async def _replace_batch_workoff_items_locked(
        self,
        cursor,
        *,
        batch_id: int,
        workoff_items: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        normalized = self._normalize_workoff_items(workoff_items)
        await cursor.execute(
            "DELETE FROM sanction_operation_workoffs WHERE operation_id = %s",
            (batch_id,),
        )
        for item in normalized:
            await cursor.execute(
                """
                INSERT INTO sanction_operation_workoffs (
                    operation_id, metric, multiplier, period_start, period_end
                )
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    batch_id,
                    item["metric"],
                    item["multiplier"],
                    item["period_start"],
                    item["period_end"],
                ),
            )
        return normalized

    async def _get_batch_workoff_items_locked(
        self,
        cursor,
        *,
        batch_id: int,
    ) -> List[Dict[str, Any]]:
        await cursor.execute(
            """
            SELECT id, operation_id AS batch_id, metric, multiplier, period_start, period_end, created_at
            FROM sanction_operation_workoffs
            WHERE operation_id = %s
            ORDER BY id ASC
            """,
            (batch_id,),
        )
        return await cursor.fetchall() or []

    async def _create_sanction_workoff_items_locked(
        self,
        cursor,
        *,
        sanction_id: int,
        workoff_items: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        normalized = self._normalize_workoff_items(workoff_items)
        created: List[Dict[str, Any]] = []
        for item in normalized:
            target_amount = await self._compute_workoff_item_target_amount_locked(
                cursor,
                metric=item["metric"],
                multiplier=float(item["multiplier"]),
                period_start=item["period_start"],
                period_end=item["period_end"],
            )
            await cursor.execute(
                """
                INSERT INTO assistant_sanction_workoffs (
                    sanction_id, metric, multiplier, period_start, period_end, target_amount
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    sanction_id,
                    item["metric"],
                    item["multiplier"],
                    item["period_start"],
                    item["period_end"],
                    target_amount,
                ),
            )
            created.append(
                {
                    "id": int(cursor.lastrowid),
                    "sanction_id": sanction_id,
                    "metric": item["metric"],
                    "multiplier": float(item["multiplier"]),
                    "period_start": item["period_start"],
                    "period_end": item["period_end"],
                    "target_amount": target_amount,
                }
            )
        return created

    async def _sync_sanction_workoff_summary_locked(
        self,
        cursor,
        *,
        sanction_id: int,
        workoff_items: List[Dict[str, Any]],
    ) -> None:
        return None

    async def _get_sanction_workoff_items_locked(
        self,
        cursor,
        *,
        sanction_id: int,
    ) -> List[Dict[str, Any]]:
        await cursor.execute(
            """
            SELECT id, sanction_id, metric, multiplier, period_start, period_end, target_amount, created_at
            FROM assistant_sanction_workoffs
            WHERE sanction_id = %s
            ORDER BY id ASC
            """,
            (sanction_id,),
        )
        return await cursor.fetchall() or []

    @staticmethod
    def _build_sanction_workoff_summary(
        workoff_items: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not workoff_items:
            return {
                "workoff_period_start": None,
                "workoff_period_end": None,
                "workoff_target_spec": None,
                "workoff_target_complaints": None,
                "workoff_target_mchat": None,
            }
        period_start = min(item["period_start"] for item in workoff_items)
        period_end = max(item["period_end"] for item in workoff_items)
        total_spec = sum(float(item.get("target_amount") or 0) for item in workoff_items if item.get("metric") == "spec")
        total_complaints = sum(float(item.get("target_amount") or 0) for item in workoff_items if item.get("metric") == "complaints")
        total_mchat = sum(float(item.get("target_amount") or 0) for item in workoff_items if item.get("metric") == "mchat")
        return {
            "workoff_period_start": period_start,
            "workoff_period_end": period_end,
            "workoff_target_spec": round(total_spec, 4) if total_spec else None,
            "workoff_target_complaints": int(round(total_complaints)) if total_complaints else None,
            "workoff_target_mchat": int(round(total_mchat)) if total_mchat else None,
        }

    async def _get_workoff_progress_items_locked(
        self,
        cursor,
        *,
        assistant_id: int,
        workoff_items: List[Dict[str, Any]],
        evaluation_cutoff: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        progress_items: List[Dict[str, Any]] = []
        for item in workoff_items:
            progress_items.append(
                await self._evaluate_workoff_item_progress_locked(
                    cursor,
                    assistant_id=assistant_id,
                    item=item,
                    evaluation_cutoff=evaluation_cutoff,
                )
            )
        return progress_items

    async def _evaluate_workoff_item_progress_locked(
        self,
        cursor,
        *,
        assistant_id: int,
        item: Dict[str, Any],
        evaluation_cutoff: Optional[date] = None,
    ) -> Dict[str, Any]:
        metric = str(item["metric"])
        period_start = item["period_start"]
        period_end = item["period_end"]
        cutoff = evaluation_cutoff or self._current_msk_date()
        required_work_days = (period_end - period_start).days + 1
        counted_projected_days = 0
        counted_work_days = 0
        uo_days_count = 0
        amount_done = 0.0
        target_amount = 0.0
        failed = False
        days: List[Dict[str, Any]] = []
        cursor_day = period_start
        effective_period_end = period_end

        while counted_projected_days < required_work_days:
            manual_status_row = await self._get_day_manual_status_locked(
                cursor,
                assistant_id=assistant_id,
                work_date=cursor_day,
            )
            manual_status = manual_status_row.get("manual_status")
            is_leave_day = bool(manual_status_row.get("is_leave_day"))
            actual_amount: Optional[float] = None
            required_amount: Optional[float] = None

            if is_leave_day:
                uo_days_count += 1
                day_status = "leave_skipped"
                counts_for_workoff = False
            else:
                counts_for_workoff = True
                required_amount = await self._daily_norm_amount_locked(
                    cursor,
                    metric=metric,
                    work_date=cursor_day,
                    multiplier=float(item.get("multiplier") or 0),
                )
                target_amount += float(required_amount or 0)
                counted_projected_days += 1
                if cursor_day > cutoff:
                    day_status = "pending"
                else:
                    actual_amount = await self._day_metric_amount_locked(
                        cursor,
                        assistant_id=assistant_id,
                        metric=metric,
                        work_date=cursor_day,
                    )
                    counted_work_days += 1
                    amount_done += float(actual_amount or 0)
                    if float(actual_amount or 0) + 1e-9 >= float(required_amount or 0):
                        day_status = "completed"
                    else:
                        day_status = "failed"
                        failed = True

            days.append(
                {
                    "date": cursor_day,
                    "manual_status": manual_status,
                    "counts_for_workoff": counts_for_workoff,
                    "required_amount": round(float(required_amount), 4)
                    if required_amount is not None and metric == "spec"
                    else (int(round(required_amount)) if required_amount is not None else None),
                    "actual_amount": round(float(actual_amount), 4)
                    if actual_amount is not None and metric == "spec"
                    else (int(round(actual_amount)) if actual_amount is not None else None),
                    "day_status": day_status,
                }
            )
            effective_period_end = cursor_day
            cursor_day += timedelta(days=1)

        if failed:
            status = "failed"
        elif cutoff < effective_period_end:
            status = "pending"
        else:
            status = "completed"

        normalized_target_amount = round(target_amount, 4) if metric == "spec" else int(round(target_amount))
        normalized_amount_done = round(amount_done, 4) if metric == "spec" else int(round(amount_done))
        remaining_amount = max(float(normalized_target_amount) - float(normalized_amount_done), 0.0)
        normalized_remaining_amount = (
            round(remaining_amount, 4)
            if metric == "spec"
            else int(round(remaining_amount))
        )

        return {
            **item,
            "required_work_days": required_work_days,
            "counted_work_days": counted_work_days,
            "effective_period_end": effective_period_end,
            "uo_days_count": uo_days_count,
            "status": status,
            "days": days,
            "target_amount": normalized_target_amount,
            "amount_done": normalized_amount_done,
            "remaining_amount": normalized_remaining_amount,
            "is_completed": status == "completed",
        }

    @staticmethod
    def _build_workoff_progress_summary(
        progress_items: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return {
            "has_workoff": bool(progress_items),
            "total_items": len(progress_items),
            "completed_items": sum(
                1 for item in progress_items if str(item.get("status") or "") == "completed"
            ),
            "items": progress_items,
        }

    async def _get_day_spec_metrics_locked(
        self,
        cursor,
        *,
        assistant_id: int,
        work_date: date,
    ) -> Dict[str, Any]:
        day_start = datetime.combine(work_date, datetime.min.time())
        day_end = day_start + timedelta(days=1)
        await cursor.execute(
            """
            SELECT
                COALESCE(
                    SUM(
                        GREATEST(
                            0,
                            TIMESTAMPDIFF(
                                SECOND,
                                GREATEST(ss.started_at, %s),
                                LEAST(COALESCE(ss.ended_at, %s), %s)
                            )
                        )
                    ),
                    0
                ) AS spec_seconds_on_day,
                ROUND(
                    COALESCE(
                        SUM(
                            (GREATEST(
                                0,
                                TIMESTAMPDIFF(
                                    SECOND,
                                    GREATEST(ss.started_at, %s),
                                    LEAST(COALESCE(ss.ended_at, %s), %s)
                                )
                            ) / 3600.0) * ss.applied_hourly_rate
                        ),
                        0
                    ),
                    4
                ) AS spec_points_auto
            FROM spec_sessions ss
            LEFT JOIN events e
              ON ss.target_type = 'event'
             AND e.id = ss.target_id
            WHERE ss.pr_id = %s
              AND ss.deleted_at IS NULL
              AND ss.started_at < %s
              AND COALESCE(ss.ended_at, %s) > %s
              AND (ss.target_type <> 'event' OR e.approval_status = 'approved')
            """,
            (
                day_start,
                day_end,
                day_end,
                day_start,
                day_end,
                day_end,
                assistant_id,
                day_end,
                day_end,
                day_start,
            ),
        )
        row = await cursor.fetchone() or {}
        seconds = int(row.get("spec_seconds_on_day") or 0)
        return {
            "spec_seconds_on_day": seconds,
            "spec_hours_on_day": round(seconds / 3600.0, 4),
            "spec_points_auto": round(float(row.get("spec_points_auto") or 0), 4),
        }

    async def _get_day_spec_metrics_map_locked(
        self,
        cursor,
        *,
        assistant_ids: List[int],
        work_date: date,
    ) -> Dict[int, Dict[str, Any]]:
        if not assistant_ids:
            return {}

        day_start = datetime.combine(work_date, datetime.min.time())
        day_end = day_start + timedelta(days=1)
        placeholders = ", ".join(["%s"] * len(assistant_ids))
        await cursor.execute(
            f"""
            SELECT
                ss.pr_id AS assistant_id,
                COALESCE(
                    SUM(
                        GREATEST(
                            0,
                            TIMESTAMPDIFF(
                                SECOND,
                                GREATEST(ss.started_at, %s),
                                LEAST(COALESCE(ss.ended_at, %s), %s)
                            )
                        )
                    ),
                    0
                ) AS spec_seconds_on_day,
                ROUND(
                    COALESCE(
                        SUM(
                            (GREATEST(
                                0,
                                TIMESTAMPDIFF(
                                    SECOND,
                                    GREATEST(ss.started_at, %s),
                                    LEAST(COALESCE(ss.ended_at, %s), %s)
                                )
                            ) / 3600.0) * ss.applied_hourly_rate
                        ),
                        0
                    ),
                    4
                ) AS spec_points_auto
            FROM spec_sessions ss
            LEFT JOIN events e
              ON ss.target_type = 'event'
             AND e.id = ss.target_id
            WHERE ss.pr_id IN ({placeholders})
              AND ss.deleted_at IS NULL
              AND ss.started_at < %s
              AND COALESCE(ss.ended_at, %s) > %s
              AND (ss.target_type <> 'event' OR e.approval_status = 'approved')
            GROUP BY ss.pr_id
            """,
            (
                day_start,
                day_end,
                day_end,
                day_start,
                day_end,
                day_end,
                *assistant_ids,
                day_end,
                day_end,
                day_start,
            ),
        )
        rows = await cursor.fetchall() or []
        result: Dict[int, Dict[str, Any]] = {}
        for row in rows:
            assistant_id_value = int(row.get("assistant_id") or 0)
            seconds = int(row.get("spec_seconds_on_day") or 0)
            result[assistant_id_value] = {
                "spec_seconds_on_day": seconds,
                "spec_hours_on_day": round(seconds / 3600.0, 4),
                "spec_points_auto": round(float(row.get("spec_points_auto") or 0), 4),
            }
        return result

    async def _get_streak_days_locked(
        self,
        cursor,
        *,
        assistant_id: int,
        work_date: date,
        min_hours: float,
        limit_days: int = 60,
    ) -> int:
        streak = 0
        cursor_date = work_date
        for _ in range(limit_days):
            manual_status_row = await self._get_day_manual_status_locked(
                cursor,
                assistant_id=assistant_id,
                work_date=cursor_date,
            )
            if manual_status_row.get("is_leave_day"):
                break
            metrics = await self._get_day_spec_metrics_locked(
                cursor,
                assistant_id=assistant_id,
                work_date=cursor_date,
            )
            if float(metrics.get("spec_hours_on_day") or 0) + 1e-9 < float(min_hours):
                break
            streak += 1
            cursor_date = cursor_date - timedelta(days=1)
        return streak

    async def _get_assistant_day_status_locked(
        self,
        cursor,
        *,
        assistant_id: int,
        work_date: date,
    ) -> Dict[str, Any]:
        policy = await self._ensure_monthly_policy_row(
            cursor,
            self._month_start_for(work_date),
        )
        metrics = await self._get_day_spec_metrics_locked(
            cursor,
            assistant_id=assistant_id,
            work_date=work_date,
        )
        manual_status_row = await self._get_day_manual_status_locked(
            cursor,
            assistant_id=assistant_id,
            work_date=work_date,
        )
        manual_status = manual_status_row.get("manual_status")
        is_leave_day = bool(manual_status_row.get("is_leave_day"))

        await cursor.execute(
            """
            SELECT delta_points
            FROM assistant_day_point_adjustments
            WHERE assistant_id = %s AND work_date = %s
            """,
            (assistant_id, work_date),
        )
        adjustment_row = await cursor.fetchone() or {}

        await cursor.execute(
            """
            SELECT mchat_count
            FROM assistant_day_mchat
            WHERE assistant_id = %s AND work_date = %s
            """,
            (assistant_id, work_date),
        )
        mchat_row = await cursor.fetchone() or {}

        await cursor.execute(
            """
            SELECT COUNT(*) AS complaints_count
            FROM complaints
            WHERE assistant_id = %s
              AND status = 'completed'
              AND DATE(completed_at) = %s
            """,
            (assistant_id, work_date),
        )
        complaints_row = await cursor.fetchone() or {}

        streak_check = await self._get_streak_days_locked(
            cursor,
            assistant_id=assistant_id,
            work_date=work_date,
            min_hours=float(policy.get("check_relief_hours_per_day") or 4),
        )
        streak_point = await self._get_streak_days_locked(
            cursor,
            assistant_id=assistant_id,
            work_date=work_date,
            min_hours=float(policy.get("point_relief_hours_per_day") or 5),
        )
        streak_percent = await self._get_streak_days_locked(
            cursor,
            assistant_id=assistant_id,
            work_date=work_date,
            min_hours=float(policy.get("percent_relief_hours_per_day") or 6),
        )

        spec_hours = float(metrics.get("spec_hours_on_day") or 0)
        return {
            "assistant_id": assistant_id,
            "work_date": work_date,
            "manual_status": manual_status,
            "is_leave_day": is_leave_day,
            "spec_seconds_on_day": int(metrics.get("spec_seconds_on_day") or 0),
            "spec_hours_on_day": round(spec_hours, 4),
            "spec_points_auto": round(float(metrics.get("spec_points_auto") or 0), 4),
            "manual_points_delta": round(float(adjustment_row.get("delta_points") or 0), 4),
            "mchat_count": int(mchat_row.get("mchat_count") or 0),
            "complaints_count": int(complaints_row.get("complaints_count") or 0),
            "check_immunity": spec_hours + 1e-9 >= float(policy.get("check_immunity_hours_per_day") or 4),
            "point_immunity": spec_hours + 1e-9 >= float(policy.get("point_immunity_hours_per_day") or 5),
            "percent_immunity": spec_hours + 1e-9 >= float(policy.get("percent_immunity_hours_per_day") or 6),
            "streak_check_days": streak_check,
            "streak_point_days": streak_point,
            "streak_percent_days": streak_percent,
        }

    async def _insert_sanction_locked(
        self,
        cursor,
        *,
        assistant_id: int,
        kind: str,
        amount_total: float,
        auto_relief_date: Optional[date] = None,
        source_type: str,
        issued_at: Optional[datetime] = None,
        basis_date: Optional[date] = None,
        source_batch_id: Optional[int] = None,
        policy_month: Optional[date] = None,
        cycle_no: Optional[int] = None,
    ) -> int:
        normalized_amount, normalized_auto_relief_date = self._normalize_runtime_sanction(
            kind=kind,
            amount=amount_total,
            auto_relief_date=auto_relief_date,
        )
        if issued_at is None:
            await cursor.execute(
                """
                INSERT INTO assistant_sanctions (
                    assistant_id,
                    kind,
                    amount_total,
                    auto_relief_date,
                    issued_at,
                    source_type,
                    operation_id,
                    basis_date,
                    settings_month,
                    check_rule_hit_no
                )
                VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, %s, %s, %s, %s, %s)
                """,
                (
                    assistant_id,
                    kind,
                    normalized_amount,
                    normalized_auto_relief_date,
                    source_type,
                    source_batch_id,
                    basis_date,
                    policy_month,
                    cycle_no,
                ),
            )
        else:
            await cursor.execute(
                """
                INSERT INTO assistant_sanctions (
                    assistant_id,
                    kind,
                    amount_total,
                    auto_relief_date,
                    issued_at,
                    source_type,
                    operation_id,
                    basis_date,
                    settings_month,
                    check_rule_hit_no
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    assistant_id,
                    kind,
                    normalized_amount,
                    normalized_auto_relief_date,
                    issued_at,
                    source_type,
                    source_batch_id,
                    basis_date,
                    policy_month,
                    cycle_no,
                ),
            )
        return int(cursor.lastrowid)

    async def _apply_check_cycle_locked(
        self,
        cursor,
        *,
        assistant_id: int,
        basis_date: date,
        source_batch_id: Optional[int] = None,
        run_timestamp: Optional[datetime] = None,
    ) -> Optional[Dict[str, Any]]:
        month_start = self._month_start_for(basis_date)
        policy = await self._ensure_monthly_policy_row(cursor, month_start)
        cycle_size = int(policy.get("check_cycle_size") or 5)

        await cursor.execute(
            """
            SELECT
                sb.sanction_id,
                sb.active_amount
            FROM sanction_balances sb
            JOIN assistant_sanctions s ON s.id = sb.sanction_id
            WHERE s.assistant_id = %s
              AND s.kind = 'check'
              AND sb.active_amount > 0
              AND s.basis_date >= %s
              AND s.basis_date < DATE_ADD(%s, INTERVAL 1 MONTH)
            ORDER BY s.basis_date ASC, s.issued_at ASC, s.id ASC
            """,
            (assistant_id, month_start, month_start),
        )
        open_checks = await cursor.fetchall() or []
        total_open_checks = sum(float(row.get("active_amount") or 0) for row in open_checks)
        if total_open_checks + 1e-9 < cycle_size:
            return None

        await cursor.execute(
            """
            SELECT COALESCE(MAX(check_rule_hit_no), 0) AS max_cycle
            FROM assistant_sanctions
            WHERE assistant_id = %s
              AND source_type = 'check_cycle'
              AND settings_month = %s
            """,
            (assistant_id, month_start),
        )
        cycle_row = await cursor.fetchone() or {}
        cycle_no = int(cycle_row.get("max_cycle") or 0) + 1

        await cursor.execute(
            """
            SELECT penalty_kind AS sanction_kind, penalty_amount AS sanction_amount
            FROM monthly_check_rules
            WHERE month_start = %s
              AND %s >= range_start
              AND (range_end IS NULL OR %s <= range_end)
            ORDER BY range_start DESC, COALESCE(range_end, 4294967295) DESC, id DESC
            LIMIT 1
            """,
            (month_start, cycle_no, cycle_no),
        )
        rule = await cursor.fetchone()
        if not rule:
            return None

        derived_sanction_id = await self._insert_sanction_locked(
            cursor,
            assistant_id=assistant_id,
            kind=str(rule.get("sanction_kind")),
            amount_total=float(rule.get("sanction_amount") or 0),
            source_type="check_cycle",
            issued_at=run_timestamp,
            basis_date=basis_date,
            source_batch_id=source_batch_id,
            policy_month=month_start,
            cycle_no=cycle_no,
        )

        remaining_to_consume = float(cycle_size)
        consumed_check_ids: List[int] = []
        for row in open_checks:
            if remaining_to_consume <= 0:
                break
            available = float(row.get("active_amount") or 0)
            if available <= 0:
                continue
            relief_amount = min(available, remaining_to_consume)
            if run_timestamp is None:
                await cursor.execute(
                    """
                    INSERT INTO assistant_sanction_reliefs (
                        sanction_id, amount, relieved_at, basis_date, relief_type
                    )
                    VALUES (%s, %s, CURRENT_TIMESTAMP, %s, 'cycle_reset')
                    """,
                    (row["sanction_id"], relief_amount, basis_date),
                )
            else:
                await cursor.execute(
                    """
                    INSERT INTO assistant_sanction_reliefs (
                        sanction_id, amount, relieved_at, basis_date, relief_type
                    )
                    VALUES (%s, %s, %s, %s, 'cycle_reset')
                    """,
                    (row["sanction_id"], relief_amount, run_timestamp, basis_date),
                )
            remaining_to_consume -= relief_amount
            consumed_check_ids.append(int(row["sanction_id"]))

        return {
            "derived_sanction_id": derived_sanction_id,
            "cycle_no": cycle_no,
            "rule": dict(rule),
            "consumed_check_ids": consumed_check_ids,
        }

    async def _active_sanction_candidate_locked(
        self,
        cursor,
        *,
        assistant_id: int,
        kind: str,
        run_started_at: datetime,
        basis_date: date,
    ) -> Optional[Dict[str, Any]]:
        await cursor.execute(
            """
            SELECT sb.sanction_id, sb.active_amount
            FROM sanction_balances sb
            JOIN assistant_sanctions s ON s.id = sb.sanction_id
            WHERE s.assistant_id = %s
              AND s.kind = %s
              AND s.issued_at < %s
              AND sb.active_amount > 0
              AND NOT EXISTS (
                  SELECT 1
                  FROM assistant_sanction_reliefs sr
                  WHERE sr.sanction_id = s.id
                    AND sr.relief_type = 'default'
                    AND sr.basis_date = %s
              )
            ORDER BY s.issued_at ASC, s.id ASC
            """,
            (assistant_id, kind, run_started_at, basis_date),
        )
        candidates = await cursor.fetchall() or []
        for candidate in candidates:
            workoff_state = await self._get_sanction_workoff_state_locked(
                cursor,
                sanction_id=int(candidate["sanction_id"]),
                assistant_id=assistant_id,
                evaluation_cutoff=basis_date,
            )
            effective_period_end = workoff_state.get("effective_period_end")
            if workoff_state.get("has_workoff") and effective_period_end is not None and effective_period_end > basis_date:
                continue
            return candidate
        return None

    async def _get_sanction_workoff_state_locked(
        self,
        cursor,
        *,
        sanction_id: int,
        assistant_id: int,
        evaluation_cutoff: Optional[date],
    ) -> Dict[str, Any]:
        workoff_items = await self._get_sanction_workoff_items_locked(
            cursor,
            sanction_id=sanction_id,
        )
        if not workoff_items:
            return {
                "has_workoff": False,
                "items": [],
                "effective_period_end": None,
                "all_completed": False,
                "any_failed": False,
            }

        progress_items = await self._get_workoff_progress_items_locked(
            cursor,
            assistant_id=assistant_id,
            workoff_items=workoff_items,
            evaluation_cutoff=evaluation_cutoff,
        )
        effective_period_end = max(
            (
                item.get("effective_period_end")
                for item in progress_items
                if item.get("effective_period_end") is not None
            ),
            default=None,
        )
        return {
            "has_workoff": True,
            "items": progress_items,
            "effective_period_end": effective_period_end,
            "all_completed": bool(progress_items)
            and all(str(item.get("status") or "") == "completed" for item in progress_items),
            "any_failed": any(str(item.get("status") or "") == "failed" for item in progress_items),
        }

    async def _apply_custom_workoff_relief_locked(
        self,
        cursor,
        *,
        basis_date: date,
        run_started_at: datetime,
        assistant_filter: Optional[Set[int]] = None,
    ) -> Dict[str, Any]:
        await cursor.execute(
            """
            SELECT
                sb.sanction_id,
                sb.assistant_id,
                sb.kind,
                sb.active_amount
            FROM sanction_balances sb
            JOIN assistant_sanctions s ON s.id = sb.sanction_id
            WHERE s.issued_at < %s
              AND sb.active_amount > 0
              AND EXISTS (
                  SELECT 1
                  FROM assistant_sanction_workoffs sw
                  WHERE sw.sanction_id = s.id
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM assistant_sanction_reliefs sr
                  WHERE sr.sanction_id = s.id
                    AND sr.relief_type = 'custom_workoff'
              )
            ORDER BY s.issued_at ASC, s.id ASC
            """,
            (run_started_at,),
        )
        rows = await cursor.fetchall() or []
        relieved: List[Dict[str, Any]] = []
        for row in rows:
            assistant_id = int(row["assistant_id"])
            if assistant_filter is not None and assistant_id not in assistant_filter:
                continue
            workoff_state = await self._get_sanction_workoff_state_locked(
                cursor,
                sanction_id=int(row["sanction_id"]),
                assistant_id=assistant_id,
                evaluation_cutoff=basis_date,
            )
            effective_period_end = workoff_state.get("effective_period_end")
            if effective_period_end is None or effective_period_end > basis_date:
                continue
            if not workoff_state.get("all_completed"):
                continue
            amount = round(float(row.get("active_amount") or 0), 4)
            if amount <= 0:
                continue
            await cursor.execute(
                """
                INSERT INTO assistant_sanction_reliefs (
                    sanction_id, amount, relieved_at, basis_date, relief_type
                )
                VALUES (%s, %s, %s, %s, 'custom_workoff')
                """,
                (row["sanction_id"], amount, run_started_at, basis_date),
            )
            relieved.append(
                {
                    "assistant_id": assistant_id,
                    "sanction_id": int(row["sanction_id"]),
                    "kind": str(row["kind"]),
                    "amount": amount,
                    "effective_period_end": effective_period_end,
                }
            )
        return {"relieved": relieved}

    async def _apply_warning_auto_expiry_locked(
        self,
        cursor,
        *,
        current_date: date,
        run_started_at: datetime,
        assistant_filter: Optional[Set[int]] = None,
    ) -> Dict[str, Any]:
        await cursor.execute(
            """
            SELECT
                sb.sanction_id,
                sb.assistant_id,
                sb.kind,
                sb.active_amount
            FROM sanction_balances sb
            JOIN assistant_sanctions s ON s.id = sb.sanction_id
            WHERE s.kind IN ('oral', 'strict')
              AND s.auto_relief_date IS NOT NULL
              AND s.auto_relief_date <= %s
              AND sb.active_amount > 0
              AND NOT EXISTS (
                  SELECT 1
                  FROM assistant_sanction_reliefs sr
                  WHERE sr.sanction_id = s.id
                    AND sr.relief_type = 'auto_expire'
              )
            ORDER BY s.auto_relief_date ASC, s.issued_at ASC, s.id ASC
            """,
            (current_date,),
        )
        rows = await cursor.fetchall() or []
        expired: List[Dict[str, Any]] = []
        for row in rows:
            assistant_id = int(row["assistant_id"])
            if assistant_filter is not None and assistant_id not in assistant_filter:
                continue
            amount = round(float(row.get("active_amount") or 0), 4)
            if amount <= 0:
                continue
            await cursor.execute(
                """
                INSERT INTO assistant_sanction_reliefs (
                    sanction_id, amount, relieved_at, basis_date, relief_type
                )
                VALUES (%s, %s, %s, %s, 'auto_expire')
                """,
                (row["sanction_id"], amount, run_started_at, current_date),
            )
            expired.append(
                {
                    "assistant_id": assistant_id,
                    "sanction_id": int(row["sanction_id"]),
                    "kind": str(row["kind"]),
                    "amount": amount,
                }
            )
        return {"relieved": expired}

    async def _apply_default_auto_relief_locked(
        self,
        cursor,
        *,
        basis_date: date,
        run_started_at: datetime,
        assistant_filter: Optional[Set[int]] = None,
    ) -> Dict[str, Any]:
        month_start = self._month_start_for(basis_date)
        policy = await self._ensure_monthly_policy_row(cursor, month_start)

        await cursor.execute(
            """
            SELECT DISTINCT s.assistant_id
            FROM assistant_sanctions s
            JOIN sanction_balances sb ON sb.sanction_id = s.id
            WHERE s.issued_at < %s
              AND sb.active_amount > 0
            """,
            (run_started_at,),
        )
        assistant_rows = await cursor.fetchall() or []

        relieved: List[Dict[str, Any]] = []
        for row in assistant_rows:
            assistant_id = int(row["assistant_id"])
            if assistant_filter is not None and assistant_id not in assistant_filter:
                continue
            day_status = await self._get_assistant_day_status_locked(
                cursor,
                assistant_id=assistant_id,
                work_date=basis_date,
            )

            # Check-line relief: independent from financial line.
            if int(day_status.get("streak_check_days") or 0) >= int(policy.get("check_relief_min_streak_days") or 2):
                candidate = await self._active_sanction_candidate_locked(
                    cursor,
                    assistant_id=assistant_id,
                    kind="check",
                    run_started_at=run_started_at,
                    basis_date=basis_date,
                )
                if candidate and float(candidate.get("active_amount") or 0) > 0:
                    amount = min(1.0, float(candidate.get("active_amount") or 0))
                    await cursor.execute(
                        """
                        INSERT INTO assistant_sanction_reliefs (
                            sanction_id, amount, relieved_at, basis_date, relief_type
                        )
                        VALUES (%s, %s, %s, %s, 'default')
                        """,
                        (candidate["sanction_id"], amount, run_started_at, basis_date),
                    )
                    relieved.append(
                        {
                            "assistant_id": assistant_id,
                            "kind": "check",
                            "sanction_id": int(candidate["sanction_id"]),
                            "amount": amount,
                        }
                    )

            # Financial line: point first, percent only if point unavailable.
            point_candidate = None
            if int(day_status.get("streak_point_days") or 0) >= int(policy.get("point_relief_min_streak_days") or 2):
                point_candidate = await self._active_sanction_candidate_locked(
                    cursor,
                    assistant_id=assistant_id,
                    kind="point",
                    run_started_at=run_started_at,
                    basis_date=basis_date,
                )
                if point_candidate and float(point_candidate.get("active_amount") or 0) > 0:
                    amount = min(1.0, float(point_candidate.get("active_amount") or 0))
                    await cursor.execute(
                        """
                        INSERT INTO assistant_sanction_reliefs (
                            sanction_id, amount, relieved_at, basis_date, relief_type
                        )
                        VALUES (%s, %s, %s, %s, 'default')
                        """,
                        (point_candidate["sanction_id"], amount, run_started_at, basis_date),
                    )
                    relieved.append(
                        {
                            "assistant_id": assistant_id,
                            "kind": "point",
                            "sanction_id": int(point_candidate["sanction_id"]),
                            "amount": amount,
                        }
                    )
                    continue

            if int(day_status.get("streak_percent_days") or 0) >= int(policy.get("percent_relief_min_streak_days") or 2):
                percent_candidate = await self._active_sanction_candidate_locked(
                    cursor,
                    assistant_id=assistant_id,
                    kind="percent",
                    run_started_at=run_started_at,
                    basis_date=basis_date,
                )
                if percent_candidate and float(percent_candidate.get("active_amount") or 0) > 0:
                    amount = min(
                        float(policy.get("percent_relief_step_amount") or 3),
                        float(percent_candidate.get("active_amount") or 0),
                    )
                    await cursor.execute(
                        """
                        INSERT INTO assistant_sanction_reliefs (
                            sanction_id, amount, relieved_at, basis_date, relief_type
                        )
                        VALUES (%s, %s, %s, %s, 'default')
                        """,
                        (percent_candidate["sanction_id"], amount, run_started_at, basis_date),
                    )
                    relieved.append(
                        {
                            "assistant_id": assistant_id,
                            "kind": "percent",
                            "sanction_id": int(percent_candidate["sanction_id"]),
                            "amount": amount,
                        }
                    )

        return {"relieved": relieved}

    async def _apply_month_end_check_reset_locked(
        self,
        cursor,
        *,
        basis_date: date,
        run_started_at: datetime,
        assistant_filter: Optional[Set[int]] = None,
    ) -> Dict[str, Any]:
        next_day = basis_date + timedelta(days=1)
        if next_day.month == basis_date.month:
            return {"reset_count": 0}

        month_start = self._month_start_for(basis_date)
        await cursor.execute(
            """
            SELECT sb.sanction_id, sb.active_amount, s.assistant_id
            FROM sanction_balances sb
            JOIN assistant_sanctions s ON s.id = sb.sanction_id
            WHERE s.kind = 'check'
              AND s.issued_at < %s
              AND s.basis_date >= %s
              AND s.basis_date < DATE_ADD(%s, INTERVAL 1 MONTH)
              AND sb.active_amount > 0
            """,
            (run_started_at, month_start, month_start),
        )
        rows = await cursor.fetchall() or []
        if assistant_filter is not None:
            rows = [
                row
                for row in rows
                if int(row.get("assistant_id") or 0) in assistant_filter
            ]
        for row in rows:
            await cursor.execute(
                """
                INSERT INTO assistant_sanction_reliefs (
                    sanction_id, amount, relieved_at, basis_date, relief_type
                )
                VALUES (%s, %s, %s, %s, 'month_reset')
                """,
                (row["sanction_id"], float(row["active_amount"] or 0), run_started_at, basis_date),
            )
        return {"reset_count": len(rows)}

    @db_retry()
    async def get_monthly_sanction_policy(self, month_start: date) -> Dict[str, Any]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                row = await self._ensure_monthly_policy_row(cursor, month_start)
                await conn.commit()
                return row

    @db_retry()
    async def get_current_sanction_policy(self) -> Dict[str, Any]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                row = dict(await self._ensure_current_policy_row(cursor))
                await conn.commit()
                row.pop("month_start", None)
                return row

    @db_retry()
    async def upsert_monthly_sanction_policy(self, month_start: date, payload: Dict[str, Any]) -> Dict[str, Any]:
        allowed_fields = {
            "check_cycle_size",
            "check_immunity_hours_per_day",
            "point_immunity_hours_per_day",
            "percent_immunity_hours_per_day",
            "check_relief_hours_per_day",
            "point_relief_hours_per_day",
            "percent_relief_hours_per_day",
            "check_relief_min_streak_days",
            "point_relief_min_streak_days",
            "percent_relief_min_streak_days",
            "percent_relief_step_amount",
            "daily_norm_spec",
            "daily_norm_complaints",
            "daily_norm_mchat",
        }
        data = {key: value for key, value in payload.items() if key in allowed_fields}
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await self._ensure_monthly_policy_row(cursor, month_start)
                if data:
                    set_sql = ", ".join(f"{field} = %s" for field in data.keys())
                    await cursor.execute(
                        f"UPDATE monthly_sanction_settings SET {set_sql} WHERE month_start = %s",
                        tuple(data.values()) + (month_start,),
                    )
                await conn.commit()
                return await self.get_monthly_sanction_policy(month_start)

    @db_retry()
    async def upsert_current_sanction_policy(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        allowed_fields = {
            "check_cycle_size",
            "check_immunity_hours_per_day",
            "point_immunity_hours_per_day",
            "percent_immunity_hours_per_day",
            "check_relief_hours_per_day",
            "point_relief_hours_per_day",
            "percent_relief_hours_per_day",
            "check_relief_min_streak_days",
            "point_relief_min_streak_days",
            "percent_relief_min_streak_days",
            "percent_relief_step_amount",
            "daily_norm_spec",
            "daily_norm_complaints",
            "daily_norm_mchat",
        }
        data = {key: value for key, value in payload.items() if key in allowed_fields}
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await self._ensure_current_policy_row(cursor)
                if data:
                    set_sql = ", ".join(f"{field} = %s" for field in data.keys())
                    await cursor.execute(
                        f"UPDATE monthly_sanction_settings SET {set_sql} WHERE month_start = %s",
                        tuple(data.values()) + (CURRENT_SANCTION_POLICY_MONTH,),
                    )
                await conn.commit()
        return await self.get_current_sanction_policy()

    @db_retry()
    async def get_monthly_check_cycle_rules(self, month_start: date) -> List[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await self._ensure_monthly_policy_row(cursor, month_start)
                await cursor.execute(
                    """
                    SELECT
                        id,
                        month_start,
                        range_start AS cycle_from,
                        range_end AS cycle_to,
                        penalty_kind AS sanction_kind,
                        penalty_amount AS sanction_amount
                    FROM monthly_check_rules
                    WHERE month_start = %s
                    ORDER BY range_start ASC, COALESCE(range_end, 4294967295) ASC, id ASC
                    """,
                    (month_start,),
                )
                rows = await cursor.fetchall() or []
                await conn.commit()
                return rows

    @db_retry()
    async def replace_monthly_check_cycle_rules(
        self,
        month_start: date,
        rules: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not rules:
            raise ValueError("Нужно задать хотя бы одно правило галок")
        normalized_rules: List[Dict[str, Any]] = []
        for rule in rules:
            cycle_from = int(rule["cycle_from"])
            raw_cycle_to = rule.get("cycle_to")
            cycle_to = int(raw_cycle_to) if raw_cycle_to is not None else None
            if cycle_to is not None and cycle_to < cycle_from:
                raise ValueError("Диапазон правила галок задан некорректно")
            normalized_rules.append(
                {
                    "cycle_from": cycle_from,
                    "cycle_to": cycle_to,
                    "sanction_kind": str(rule["sanction_kind"]),
                    "sanction_amount": float(rule["sanction_amount"]),
                }
            )
        sorted_rules = sorted(
            normalized_rules,
            key=lambda item: (
                item["cycle_from"],
                item["cycle_to"] if item["cycle_to"] is not None else 4294967295,
            ),
        )
        for index, current in enumerate(sorted_rules):
            current_end = (
                int(current["cycle_to"])
                if current["cycle_to"] is not None
                else 4294967295
            )
            for other in sorted_rules[index + 1:]:
                if other["cycle_from"] <= current_end:
                    raise ValueError("Диапазоны правил галок не должны пересекаться")
                break

        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await self._ensure_monthly_policy_row(cursor, month_start)
                await cursor.execute(
                    "DELETE FROM monthly_check_rules WHERE month_start = %s",
                    (month_start,),
                )
                for rule in normalized_rules:
                    await cursor.execute(
                        """
                        INSERT INTO monthly_check_rules (
                            month_start, range_start, range_end, penalty_kind, penalty_amount
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            month_start,
                            int(rule["cycle_from"]),
                            int(rule["cycle_to"]) if rule["cycle_to"] is not None else None,
                            str(rule["sanction_kind"]),
                            float(rule["sanction_amount"]),
                        ),
                    )
                await conn.commit()
        return await self.get_monthly_check_cycle_rules(month_start)

    @db_retry()
    async def get_current_check_cycle_rules(self) -> List[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await self._ensure_current_policy_row(cursor)
                await cursor.execute(
                    """
                    SELECT
                        id,
                        range_start AS cycle_from,
                        range_end AS cycle_to,
                        penalty_kind AS sanction_kind,
                        penalty_amount AS sanction_amount
                    FROM monthly_check_rules
                    WHERE month_start = %s
                    ORDER BY range_start ASC, COALESCE(range_end, 4294967295) ASC, id ASC
                    """,
                    (CURRENT_SANCTION_POLICY_MONTH,),
                )
                rows = await cursor.fetchall() or []
                await conn.commit()
                return rows

    @db_retry()
    async def replace_current_check_cycle_rules(
        self,
        rules: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not rules:
            raise ValueError("Нужно задать хотя бы одно правило галок")
        normalized_rules: List[Dict[str, Any]] = []
        for rule in rules:
            cycle_from = int(rule["cycle_from"])
            raw_cycle_to = rule.get("cycle_to")
            cycle_to = int(raw_cycle_to) if raw_cycle_to is not None else None
            if cycle_to is not None and cycle_to < cycle_from:
                raise ValueError("Диапазон правила галок задан некорректно")
            normalized_rules.append(
                {
                    "cycle_from": cycle_from,
                    "cycle_to": cycle_to,
                    "sanction_kind": str(rule["sanction_kind"]),
                    "sanction_amount": float(rule["sanction_amount"]),
                }
            )
        sorted_rules = sorted(
            normalized_rules,
            key=lambda item: (
                item["cycle_from"],
                item["cycle_to"] if item["cycle_to"] is not None else 4294967295,
            ),
        )
        for index, current in enumerate(sorted_rules):
            current_end = (
                int(current["cycle_to"])
                if current["cycle_to"] is not None
                else 4294967295
            )
            for other in sorted_rules[index + 1:]:
                if other["cycle_from"] <= current_end:
                    raise ValueError("Диапазоны правил галок не должны пересекаться")
                break

        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await self._ensure_current_policy_row(cursor)
                await cursor.execute(
                    "DELETE FROM monthly_check_rules WHERE month_start = %s",
                    (CURRENT_SANCTION_POLICY_MONTH,),
                )
                for rule in normalized_rules:
                    await cursor.execute(
                        """
                        INSERT INTO monthly_check_rules (
                            month_start, range_start, range_end, penalty_kind, penalty_amount
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            CURRENT_SANCTION_POLICY_MONTH,
                            int(rule["cycle_from"]),
                            int(rule["cycle_to"]) if rule["cycle_to"] is not None else None,
                            str(rule["sanction_kind"]),
                            float(rule["sanction_amount"]),
                        ),
                    )
                await conn.commit()
        return await self.get_current_check_cycle_rules()

    @db_retry()
    async def upsert_assistant_day_point_adjustment(
        self,
        *,
        assistant_id: int,
        work_date: date,
        delta_points: float,
    ) -> Dict[str, Any]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO assistant_day_point_adjustments (assistant_id, work_date, delta_points)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        delta_points = VALUES(delta_points),
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (assistant_id, work_date, round(float(delta_points), 4)),
                )
                await cursor.execute(
                    """
                    SELECT assistant_id, work_date, delta_points, updated_at
                    FROM assistant_day_point_adjustments
                    WHERE assistant_id = %s AND work_date = %s
                    """,
                    (assistant_id, work_date),
                )
                row = await cursor.fetchone() or {}
                await conn.commit()
                return row

    @db_retry()
    async def upsert_assistant_day_mchat(
        self,
        *,
        assistant_id: int,
        work_date: date,
        mchat_count: int,
    ) -> Dict[str, Any]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO assistant_day_mchat (assistant_id, work_date, mchat_count)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        mchat_count = VALUES(mchat_count),
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (assistant_id, work_date, max(int(mchat_count), 0)),
                )
                await cursor.execute(
                    """
                    SELECT assistant_id, work_date, mchat_count, updated_at
                    FROM assistant_day_mchat
                    WHERE assistant_id = %s AND work_date = %s
                    """,
                    (assistant_id, work_date),
                )
                row = await cursor.fetchone() or {}
                await conn.commit()
                return row

    @db_retry()
    async def get_assistant_day_status(
        self,
        *,
        assistant_id: int,
        work_date: date,
    ) -> Dict[str, Any]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                status = await self._get_assistant_day_status_locked(
                    cursor,
                    assistant_id=assistant_id,
                    work_date=work_date,
                )
                await conn.commit()
                return status

    async def _get_weekly_payout_config_locked(self, cursor) -> Dict[str, Any]:
        await cursor.execute(
            """
            SELECT payout_type, command_name
            FROM assistant_weekly_payout_type_rules
            ORDER BY payout_type ASC
            """
        )
        type_rows = await cursor.fetchall() or []

        await cursor.execute(
            """
            SELECT role_group, payout_type, result_code, amount
            FROM assistant_weekly_payout_amount_rules
            """
        )
        amount_rows = await cursor.fetchall() or []

        await cursor.execute(
            """
            SELECT server_code
            FROM assistant_weekly_payout_servers
            ORDER BY server_code ASC
            """
        )
        server_rows = await cursor.fetchall() or []

        return {
            "types": [
                {
                    "value": str(row.get("payout_type")),
                    "command_name": str(row.get("command_name") or ""),
                }
                for row in type_rows
            ],
            "type_command_map": {
                str(row.get("payout_type")): str(row.get("command_name") or "")
                for row in type_rows
                if row.get("payout_type")
            },
            "amount_map": {
                (
                    str(row.get("role_group")),
                    str(row.get("payout_type")),
                    str(row.get("result_code")),
                ): str(row.get("amount") or "")
                for row in amount_rows
                if row.get("role_group") and row.get("payout_type") and row.get("result_code")
            },
            "servers": [
                str(row.get("server_code"))
                for row in server_rows
                if row.get("server_code")
            ],
            "selected_results": list(WEEKLY_SELECTED_RESULT_OPTIONS),
            "manual_statuses": list(WEEKLY_DAY_STATUS_VALUES),
        }

    def _build_weekly_payout_preview(
        self,
        *,
        assistant_role: Optional[str],
        selected_result: Optional[str],
        payout_type: Optional[str],
        payout_server: Optional[str],
        payout_static: Optional[str],
        payout_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        normalized_result = _canonical_weekly_result(selected_result)
        normalized_static = str(payout_static or "").strip() or None
        command_name = (
            payout_config.get("type_command_map", {}).get(str(payout_type))
            if payout_type
            else None
        )
        preview = {
            "type": payout_type,
            "server": payout_server,
            "static": normalized_static,
            "command_name": command_name,
            "amount": None,
            "command": None,
            "command_available": False,
            "command_unavailable_reason": None,
            "role_group": _weekly_role_group(assistant_role),
        }

        if normalized_result not in {"Актив", "Ультра-Актив"}:
            preview["command_unavailable_reason"] = "selected_result_not_payout_eligible"
            return preview
        if not payout_type or not payout_server or not normalized_static:
            preview["command_unavailable_reason"] = "incomplete_payout_data"
            return preview
        if not command_name:
            preview["command_unavailable_reason"] = "payout_type_rule_missing"
            return preview

        amount = payout_config.get("amount_map", {}).get(
            (_weekly_role_group(assistant_role), str(payout_type), normalized_result)
        )
        if not amount:
            preview["command_unavailable_reason"] = "amount_rule_missing"
            return preview

        preview["amount"] = amount
        preview["command"] = (
            f"{payout_server}:{command_name} {normalized_static} {amount} {WEEKLY_PAYOUT_SUFFIX}"
        )
        preview["command_available"] = True
        return preview

    def _calculate_weekly_suggested_result(
        self,
        *,
        active_day_records: List[Dict[str, Any]],
        total_spec_hours: float,
        total_mchat: int,
        total_complaints: int,
        count_p: int,
        count_o: int,
    ) -> Dict[str, Any]:
        if not active_day_records:
            return {
                "suggested_result": None,
                "suggested_reason": "unconfigured",
                "metric_hits": 0,
                "weekly_norm_spec": 0.0,
                "weekly_norm_mchat": 0,
                "weekly_norm_complaints": 0,
            }

        if any(
            float(day.get("daily_norm_spec") or 0) <= 0
            or int(day.get("daily_norm_mchat") or 0) <= 0
            or int(day.get("daily_norm_complaints") or 0) <= 0
            for day in active_day_records
        ):
            return {
                "suggested_result": None,
                "suggested_reason": "unconfigured",
                "metric_hits": 0,
                "weekly_norm_spec": 0.0,
                "weekly_norm_mchat": 0,
                "weekly_norm_complaints": 0,
            }

        weekly_norm_spec = round(
            sum(float(day.get("daily_norm_spec") or 0) for day in active_day_records),
            4,
        )
        weekly_norm_mchat = int(
            sum(int(day.get("daily_norm_mchat") or 0) for day in active_day_records)
        )
        weekly_norm_complaints = int(
            sum(int(day.get("daily_norm_complaints") or 0) for day in active_day_records)
        )

        metric_hits = 0
        if total_spec_hours + 1e-9 >= weekly_norm_spec:
            metric_hits += 1
        if total_mchat >= weekly_norm_mchat:
            metric_hits += 1
        if total_complaints >= weekly_norm_complaints:
            metric_hits += 1

        ultra_daily_ok = all(
            (
                day.get("resolved_status") == "O"
                or (
                    float(day.get("spec_hours") or 0) + 1e-9 >= float(day.get("daily_norm_spec") or 0)
                    and int(day.get("mchat_count") or 0) >= int(day.get("daily_norm_mchat") or 0)
                    and int(day.get("complaints_count") or 0) >= int(day.get("daily_norm_complaints") or 0)
                )
            )
            for day in active_day_records
        )
        ultra_boosted = (
            total_spec_hours + 1e-9 >= round(weekly_norm_spec * 1.5, 4)
            or total_mchat >= weekly_norm_mchat * 2
            or total_complaints >= weekly_norm_complaints * 2
        )

        if count_p == 0 and count_o <= 1 and ultra_daily_ok and ultra_boosted:
            suggested_result = "Ультра-Актив"
        elif metric_hits == 3 and count_p <= 1:
            suggested_result = "Актив"
        elif metric_hits == 2 and count_p <= 2:
            suggested_result = "Инактив/Актив"
        else:
            suggested_result = "Инактив"

        return {
            "suggested_result": suggested_result,
            "suggested_reason": None,
            "metric_hits": metric_hits,
            "weekly_norm_spec": weekly_norm_spec,
            "weekly_norm_mchat": weekly_norm_mchat,
            "weekly_norm_complaints": weekly_norm_complaints,
        }

    async def _build_assistant_weekly_read_model_locked(
        self,
        cursor,
        *,
        week_start: date,
        assistant_id: Optional[int] = None,
        include_day_matrix: bool,
        include_payout_options: bool,
    ) -> Dict[str, Any]:
        normalized_week_start = _week_start_msk(week_start)
        week_end = normalized_week_start + timedelta(days=6)
        week_days = _week_dates(normalized_week_start)
        current_msk_date = _msk_today()
        roster_start_dt = datetime.combine(normalized_week_start, datetime.min.time())
        roster_end_exclusive = datetime.combine(
            week_end + timedelta(days=1),
            datetime.min.time(),
        )
        assistant_where = ""
        assistant_params: List[Any] = [roster_end_exclusive, roster_start_dt]
        if assistant_id is not None:
            assistant_where = " AND a.pr_id = %s"
            assistant_params.append(assistant_id)

        await cursor.execute(
            f"""
            SELECT
                a.pr_id,
                a.nickname,
                a.role,
                a.added_at,
                a.appointed_at,
                a.dismissed_at
            FROM assistants a
            WHERE COALESCE(a.appointed_at, a.added_at, CURRENT_TIMESTAMP) < %s
              AND (a.dismissed_at IS NULL OR a.dismissed_at >= %s)
              {assistant_where}
            ORDER BY a.nickname ASC, a.pr_id ASC
            """,
            tuple(assistant_params),
        )
        assistants = await cursor.fetchall() or []
        assistant_ids = [int(row.get("pr_id")) for row in assistants if row.get("pr_id") is not None]

        payout_config = (
            await self._get_weekly_payout_config_locked(cursor)
            if include_payout_options
            else {"types": [], "type_command_map": {}, "amount_map": {}, "servers": []}
        )

        policy_by_month: Dict[date, Dict[str, Any]] = {}
        for month_start in sorted({_month_start(work_date) for work_date in week_days}):
            policy_by_month[month_start] = await self._ensure_monthly_policy_row(cursor, month_start)

        spec_map: Dict[tuple[int, date], Dict[str, Any]] = {}
        mchat_map: Dict[tuple[int, date], int] = {}
        complaints_map: Dict[tuple[int, date], int] = {}
        override_map: Dict[tuple[int, date], Dict[str, Any]] = {}
        review_map: Dict[int, Dict[str, Any]] = {}

        if assistant_ids:
            placeholders = ", ".join(["%s"] * len(assistant_ids))

            await cursor.execute(
                f"""
                SELECT assistant_id, work_date, spec_seconds_on_day, spec_hours_on_day, spec_points_auto
                FROM assistant_day_spec_totals
                WHERE assistant_id IN ({placeholders})
                  AND work_date BETWEEN %s AND %s
                """,
                (*assistant_ids, normalized_week_start, week_end),
            )
            for row in await cursor.fetchall() or []:
                work_date = row.get("work_date")
                if isinstance(work_date, datetime):
                    work_date = work_date.date()
                spec_map[(int(row.get("assistant_id") or 0), work_date)] = {
                    "spec_seconds_on_day": int(row.get("spec_seconds_on_day") or 0),
                    "spec_hours_on_day": round(float(row.get("spec_hours_on_day") or 0), 4),
                    "spec_points_auto": round(float(row.get("spec_points_auto") or 0), 4),
                }

            if normalized_week_start <= current_msk_date <= week_end:
                live_spec_map = await self._get_day_spec_metrics_map_locked(
                    cursor,
                    assistant_ids=assistant_ids,
                    work_date=current_msk_date,
                )
                for current_assistant_id, metrics in live_spec_map.items():
                    spec_map[(current_assistant_id, current_msk_date)] = metrics

            await cursor.execute(
                f"""
                SELECT assistant_id, work_date, mchat_count
                FROM assistant_day_mchat
                WHERE assistant_id IN ({placeholders})
                  AND work_date BETWEEN %s AND %s
                """,
                (*assistant_ids, normalized_week_start, week_end),
            )
            for row in await cursor.fetchall() or []:
                work_date = row.get("work_date")
                if isinstance(work_date, datetime):
                    work_date = work_date.date()
                mchat_map[(int(row.get("assistant_id") or 0), work_date)] = int(row.get("mchat_count") or 0)

            await cursor.execute(
                f"""
                SELECT assistant_id, DATE(completed_at) AS work_date, COUNT(*) AS complaints_count
                FROM complaints
                WHERE assistant_id IN ({placeholders})
                  AND status = 'completed'
                  AND DATE(completed_at) BETWEEN %s AND %s
                GROUP BY assistant_id, DATE(completed_at)
                """,
                (*assistant_ids, normalized_week_start, week_end),
            )
            for row in await cursor.fetchall() or []:
                work_date = row.get("work_date")
                if isinstance(work_date, datetime):
                    work_date = work_date.date()
                if isinstance(work_date, str):
                    work_date = date.fromisoformat(work_date)
                complaints_map[(int(row.get("assistant_id") or 0), work_date)] = int(
                    row.get("complaints_count") or 0
                )

            await cursor.execute(
                f"""
                SELECT assistant_id, work_date, manual_status, updated_at, updated_by_id
                FROM assistant_day_status_overrides
                WHERE assistant_id IN ({placeholders})
                  AND work_date BETWEEN %s AND %s
                """,
                (*assistant_ids, normalized_week_start, week_end),
            )
            for row in await cursor.fetchall() or []:
                work_date = row.get("work_date")
                if isinstance(work_date, datetime):
                    work_date = work_date.date()
                override_map[(int(row.get("assistant_id") or 0), work_date)] = {
                    "manual_status": row.get("manual_status"),
                    "updated_at": row.get("updated_at"),
                    "updated_by_id": row.get("updated_by_id"),
                }

            await cursor.execute(
                f"""
                SELECT
                    assistant_id,
                    selected_result,
                    payout_type,
                    payout_server,
                    payout_static,
                    payout_issue_status,
                    payout_issued_at,
                    payout_issued_by_id,
                    updated_at,
                    updated_by_id
                FROM assistant_weekly_reviews
                WHERE assistant_id IN ({placeholders})
                  AND week_start = %s
                """,
                (*assistant_ids, normalized_week_start),
            )
            for row in await cursor.fetchall() or []:
                review_map[int(row.get("assistant_id") or 0)] = dict(row)

        day_headers = [
            {
                "work_date": work_date,
                "weekday_index": index,
                "weekday_short": ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")[index],
                "label_short": work_date.strftime("%d.%m"),
            }
            for index, work_date in enumerate(week_days)
        ]

        items: List[Dict[str, Any]] = []
        for assistant in assistants:
            current_assistant_id = int(assistant.get("pr_id") or 0)
            appointed_date = _date_only(
                assistant.get("appointed_at") or assistant.get("added_at")
            ) or normalized_week_start
            dismissed_date = _date_only(assistant.get("dismissed_at"))

            day_payloads: List[Dict[str, Any]] = []
            active_day_records: List[Dict[str, Any]] = []
            total_spec_hours = 0.0
            total_mchat = 0
            total_complaints = 0
            count_p = 0
            count_u = 0
            count_o = 0

            for index, work_date in enumerate(week_days):
                policy = policy_by_month[_month_start(work_date)]
                daily_norm_spec = round(float(policy.get("daily_norm_spec") or 0), 4)
                daily_norm_mchat = int(policy.get("daily_norm_mchat") or 0)
                daily_norm_complaints = int(policy.get("daily_norm_complaints") or 0)
                is_roster_day = work_date >= appointed_date and (
                    dismissed_date is None or work_date <= dismissed_date
                )
                spec_metrics = spec_map.get(
                    (current_assistant_id, work_date),
                    {
                        "spec_seconds_on_day": 0,
                        "spec_hours_on_day": 0.0,
                        "spec_points_auto": 0.0,
                    },
                )
                spec_hours = round(float(spec_metrics.get("spec_hours_on_day") or 0), 4)
                mchat_count = int(mchat_map.get((current_assistant_id, work_date), 0))
                complaints_count = int(complaints_map.get((current_assistant_id, work_date), 0))
                override = override_map.get((current_assistant_id, work_date), {})
                has_manual_override = (current_assistant_id, work_date) in override_map
                raw_manual_status = override.get("manual_status")
                manual_status = (
                    None
                    if raw_manual_status in (None, WEEKLY_MANUAL_STATUS_NONE)
                    else raw_manual_status
                )
                auto_status = None
                if (
                    is_roster_day
                    and work_date < current_msk_date
                    and daily_norm_spec > 0
                    and spec_hours + 1e-9 < daily_norm_spec
                ):
                    auto_status = "P"
                resolved_status = manual_status if has_manual_override else auto_status
                status_source = "manual" if has_manual_override else ("auto" if auto_status else "none")

                if is_roster_day and resolved_status == "P":
                    count_p += 1
                elif is_roster_day and resolved_status == "U":
                    count_u += 1
                elif is_roster_day and resolved_status == "O":
                    count_o += 1

                total_spec_hours = round(total_spec_hours + spec_hours, 4)
                total_mchat += mchat_count
                total_complaints += complaints_count

                day_payload = {
                    "work_date": work_date,
                    "weekday_index": index,
                    "is_roster_day": is_roster_day,
                    "spec_seconds": int(spec_metrics.get("spec_seconds_on_day") or 0),
                    "spec_hours": spec_hours,
                    "mchat_count": mchat_count,
                    "complaints_count": complaints_count,
                    "daily_norm_spec": daily_norm_spec,
                    "daily_norm_mchat": daily_norm_mchat,
                    "daily_norm_complaints": daily_norm_complaints,
                    "manual_status": manual_status,
                    "auto_status": auto_status,
                    "resolved_status": resolved_status,
                    "status_source": status_source,
                    "manual_status_updated_at": override.get("updated_at"),
                    "manual_status_updated_by_id": override.get("updated_by_id"),
                }
                day_payloads.append(day_payload)
                if is_roster_day:
                    active_day_records.append(day_payload)

            suggestion = self._calculate_weekly_suggested_result(
                active_day_records=active_day_records,
                total_spec_hours=total_spec_hours,
                total_mchat=total_mchat,
                total_complaints=total_complaints,
                count_p=count_p,
                count_o=count_o,
            )
            review = review_map.get(current_assistant_id, {})
            selected_result = _canonical_weekly_result(review.get("selected_result"))
            payout = self._build_weekly_payout_preview(
                assistant_role=assistant.get("role"),
                selected_result=selected_result,
                payout_type=review.get("payout_type"),
                payout_server=review.get("payout_server"),
                payout_static=review.get("payout_static"),
                payout_config=payout_config,
            )
            payout_issue_status = _canonical_weekly_payout_issue_status(
                review.get("payout_issue_status")
            )

            item = {
                "assistant_id": current_assistant_id,
                "nickname": assistant.get("nickname"),
                "role": assistant.get("role"),
                "week_start": normalized_week_start,
                "week_end": week_end,
                "totals": {
                    "spec_hours": round(total_spec_hours, 4),
                    "mchat_count": total_mchat,
                    "complaints_count": total_complaints,
                },
                "counts": {
                    "P": count_p,
                    "U": count_u,
                    "O": count_o,
                },
                "suggested_result": suggestion.get("suggested_result"),
                "suggested_reason": suggestion.get("suggested_reason"),
                "suggestion_metrics": {
                    "metric_hits": suggestion.get("metric_hits"),
                    "weekly_norm_spec": suggestion.get("weekly_norm_spec"),
                    "weekly_norm_mchat": suggestion.get("weekly_norm_mchat"),
                    "weekly_norm_complaints": suggestion.get("weekly_norm_complaints"),
                },
                "selected_result": selected_result,
                "result_display": selected_result or suggestion.get("suggested_result"),
                "payout": payout,
                "payout_type": review.get("payout_type"),
                "payout_server": review.get("payout_server"),
                "payout_static": review.get("payout_static"),
                "payout_issue_status": payout_issue_status,
                "payout_issued_at": review.get("payout_issued_at"),
                "payout_issued_by_id": review.get("payout_issued_by_id"),
                "review_updated_at": review.get("updated_at"),
                "review_updated_by_id": review.get("updated_by_id"),
            }
            if include_day_matrix:
                item["days"] = day_payloads
            items.append(item)

        payload = {
            "week_start": normalized_week_start,
            "week_end": week_end,
            "day_headers": day_headers,
            "items": items,
        }
        if include_payout_options:
            payload["payout_options"] = {
                "types": payout_config.get("types", []),
                "servers": payout_config.get("servers", []),
                "selected_results": payout_config.get("selected_results", []),
                "manual_statuses": payout_config.get("manual_statuses", []),
            }
        return payload

    @db_retry()
    async def get_current_assistant_weekly_overview(self) -> Dict[str, Any]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                payload = await self._build_assistant_weekly_read_model_locked(
                    cursor,
                    week_start=_week_start_msk(),
                    include_day_matrix=True,
                    include_payout_options=False,
                )
                await conn.commit()
                return payload

    @db_retry()
    async def get_assistant_weekly_admin_overview(
        self,
        *,
        week_start: Optional[date] = None,
    ) -> Dict[str, Any]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                payload = await self._build_assistant_weekly_read_model_locked(
                    cursor,
                    week_start=week_start or _week_start_msk(),
                    include_day_matrix=True,
                    include_payout_options=True,
                )
                await conn.commit()
                return payload

    @db_retry()
    async def get_assistant_weekly_admin_detail(
        self,
        *,
        assistant_id: int,
        week_start: Optional[date] = None,
    ) -> Optional[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                payload = await self._build_assistant_weekly_read_model_locked(
                    cursor,
                    week_start=week_start or _week_start_msk(),
                    assistant_id=assistant_id,
                    include_day_matrix=True,
                    include_payout_options=True,
                )
                await conn.commit()
                if not payload.get("items"):
                    return None
                return {
                    "week_start": payload.get("week_start"),
                    "week_end": payload.get("week_end"),
                    "day_headers": payload.get("day_headers", []),
                    "payout_options": payload.get("payout_options", {}),
                    "detail": payload["items"][0],
                }

    @db_retry()
    async def save_assistant_weekly_admin_review(
        self,
        *,
        assistant_id: int,
        week_start: date,
        actor_id: Optional[int],
        day_overrides: List[Dict[str, Any]],
        selected_result: Optional[str],
        payout_type: Optional[str],
        payout_server: Optional[str],
        payout_static: Optional[str],
    ) -> Dict[str, Any]:
        normalized_week_start = _week_start_msk(week_start)
        week_end = normalized_week_start + timedelta(days=6)
        normalized_result = _canonical_weekly_result(selected_result)
        if normalized_result is not None and normalized_result not in WEEKLY_SELECTED_RESULTS:
            raise ValueError("Невалидный weekly result")
        if payout_type is not None and payout_type not in WEEKLY_PAYOUT_TYPES:
            raise ValueError("Невалидный payout type")
        normalized_static = str(payout_static or "").strip() or None
        payout_issue_transition = None

        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT pr_id, role
                    FROM assistants
                    WHERE pr_id = %s
                      AND COALESCE(appointed_at, added_at, CURRENT_TIMESTAMP) < %s
                      AND (dismissed_at IS NULL OR dismissed_at >= %s)
                    LIMIT 1
                    """,
                    (
                        assistant_id,
                        datetime.combine(week_end + timedelta(days=1), datetime.min.time()),
                        datetime.combine(normalized_week_start, datetime.min.time()),
                    ),
                )
                assistant = await cursor.fetchone()
                if not assistant:
                    raise ValueError("Ассистент не найден")
                assistant_role = assistant.get("role")

                payout_config = await self._get_weekly_payout_config_locked(cursor)
                allowed_servers = set(payout_config.get("servers", []))
                if payout_server is not None and payout_server not in allowed_servers:
                    raise ValueError("Невалидный payout server")

                await cursor.execute(
                    """
                    SELECT
                        selected_result,
                        payout_type,
                        payout_server,
                        payout_static,
                        payout_issue_status,
                        payout_issued_at,
                        payout_issued_by_id
                    FROM assistant_weekly_reviews
                    WHERE assistant_id = %s
                      AND week_start = %s
                    LIMIT 1
                    """,
                    (assistant_id, normalized_week_start),
                )
                previous_review = await cursor.fetchone() or {}
                previous_result = _canonical_weekly_result(previous_review.get("selected_result"))
                previous_static = str(previous_review.get("payout_static") or "").strip() or None
                previous_issue_status = _canonical_weekly_payout_issue_status(
                    previous_review.get("payout_issue_status")
                )
                payout_fields_changed = (
                    previous_result != normalized_result
                    or previous_review.get("payout_type") != payout_type
                    or previous_review.get("payout_server") != payout_server
                    or previous_static != normalized_static
                )
                payout_issue_reset = (
                    bool(previous_review)
                    and previous_issue_status == WEEKLY_PAYOUT_ISSUE_STATUS_ISSUED
                    and payout_fields_changed
                )
                if payout_issue_reset:
                    previous_payout_preview = self._build_weekly_payout_preview(
                        assistant_role=assistant_role,
                        selected_result=previous_result,
                        payout_type=previous_review.get("payout_type"),
                        payout_server=previous_review.get("payout_server"),
                        payout_static=previous_static,
                        payout_config=payout_config,
                    )
                    payout_issue_transition = {
                        "from_status": previous_issue_status,
                        "to_status": WEEKLY_PAYOUT_ISSUE_STATUS_PENDING,
                        "issued_at": previous_review.get("payout_issued_at"),
                        "issued_by_id": previous_review.get("payout_issued_by_id"),
                        "generated_payout_command": previous_payout_preview.get("command"),
                        "auto_reset": True,
                    }

                seen_dates: Set[date] = set()
                for override in day_overrides:
                    work_date = override.get("work_date")
                    manual_status = override.get("manual_status")
                    is_manual_override = bool(override.get("is_manual_override"))
                    if work_date is None:
                        raise ValueError("work_date is required")
                    if work_date in seen_dates:
                        raise ValueError("Повторяющиеся daily overrides недопустимы")
                    seen_dates.add(work_date)
                    if work_date < normalized_week_start or work_date > week_end:
                        raise ValueError("work_date должен находиться внутри выбранной недели")
                    if manual_status is not None and manual_status not in WEEKLY_MANUAL_STATUSES:
                        raise ValueError("Невалидный day status")

                    if not is_manual_override:
                        await cursor.execute(
                            """
                            DELETE FROM assistant_day_status_overrides
                            WHERE assistant_id = %s AND work_date = %s
                            """,
                            (assistant_id, work_date),
                        )
                    else:
                        stored_manual_status = manual_status or WEEKLY_MANUAL_STATUS_NONE
                        await cursor.execute(
                            """
                            INSERT INTO assistant_day_status_overrides (
                                assistant_id,
                                work_date,
                                manual_status,
                                updated_by_id
                            )
                            VALUES (%s, %s, %s, %s)
                            ON DUPLICATE KEY UPDATE
                                manual_status = VALUES(manual_status),
                                updated_by_id = VALUES(updated_by_id),
                                updated_at = CURRENT_TIMESTAMP
                            """,
                            (assistant_id, work_date, stored_manual_status, actor_id),
                        )

                if (
                    normalized_result is None
                    and payout_type is None
                    and payout_server is None
                    and normalized_static is None
                ):
                    await cursor.execute(
                        """
                        DELETE FROM assistant_weekly_reviews
                        WHERE assistant_id = %s AND week_start = %s
                        """,
                        (assistant_id, normalized_week_start),
                    )
                else:
                    await cursor.execute(
                        """
                        INSERT INTO assistant_weekly_reviews (
                            assistant_id,
                            week_start,
                            selected_result,
                            payout_type,
                            payout_server,
                            payout_static,
                            payout_issue_status,
                            payout_issued_at,
                            payout_issued_by_id,
                            updated_by_id
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            selected_result = VALUES(selected_result),
                            payout_type = VALUES(payout_type),
                            payout_server = VALUES(payout_server),
                            payout_static = VALUES(payout_static),
                            payout_issue_status = VALUES(payout_issue_status),
                            payout_issued_at = VALUES(payout_issued_at),
                            payout_issued_by_id = VALUES(payout_issued_by_id),
                            updated_by_id = VALUES(updated_by_id),
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        (
                            assistant_id,
                            normalized_week_start,
                            normalized_result,
                            payout_type,
                            payout_server,
                            normalized_static,
                            WEEKLY_PAYOUT_ISSUE_STATUS_PENDING
                            if payout_issue_reset
                            else _canonical_weekly_payout_issue_status(
                                previous_review.get("payout_issue_status")
                            ),
                            None
                            if payout_issue_reset
                            else previous_review.get("payout_issued_at"),
                            None
                            if payout_issue_reset
                            else previous_review.get("payout_issued_by_id"),
                            actor_id,
                        ),
                    )
                await conn.commit()

        detail = await self.get_assistant_weekly_admin_detail(
            assistant_id=assistant_id,
            week_start=normalized_week_start,
        )
        if detail is None:
            raise ValueError("Не удалось получить weekly detail после сохранения")
        if payout_issue_transition:
            detail["payout_issue_transition"] = payout_issue_transition
        return detail

    @db_retry()
    async def save_assistant_weekly_payout_issue_status(
        self,
        *,
        assistant_id: int,
        week_start: date,
        actor_id: Optional[int],
        payout_issue_status: str,
    ) -> Dict[str, Any]:
        normalized_week_start = _week_start_msk(week_start)
        week_end = normalized_week_start + timedelta(days=6)
        normalized_status = _canonical_weekly_payout_issue_status(payout_issue_status)
        payout_issue_transition = None

        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT pr_id, role
                    FROM assistants
                    WHERE pr_id = %s
                      AND COALESCE(appointed_at, added_at, CURRENT_TIMESTAMP) < %s
                      AND (dismissed_at IS NULL OR dismissed_at >= %s)
                    LIMIT 1
                    """,
                    (
                        assistant_id,
                        datetime.combine(week_end + timedelta(days=1), datetime.min.time()),
                        datetime.combine(normalized_week_start, datetime.min.time()),
                    ),
                )
                assistant = await cursor.fetchone()
                if not assistant:
                    raise ValueError("Ассистент не найден")

                payout_config = await self._get_weekly_payout_config_locked(cursor)
                await cursor.execute(
                    """
                    SELECT
                        selected_result,
                        payout_type,
                        payout_server,
                        payout_static,
                        payout_issue_status,
                        payout_issued_at,
                        payout_issued_by_id
                    FROM assistant_weekly_reviews
                    WHERE assistant_id = %s
                      AND week_start = %s
                    LIMIT 1
                    """,
                    (assistant_id, normalized_week_start),
                )
                review = await cursor.fetchone() or {}
                current_status = _canonical_weekly_payout_issue_status(
                    review.get("payout_issue_status")
                )

                if not review:
                    if normalized_status == WEEKLY_PAYOUT_ISSUE_STATUS_ISSUED:
                        raise ValueError("Нельзя отметить выдачу без сохранённой weekly review")
                    detail = await self.get_assistant_weekly_admin_detail(
                        assistant_id=assistant_id,
                        week_start=normalized_week_start,
                    )
                    if detail is None:
                        raise ValueError("Не удалось получить weekly detail")
                    return detail

                selected_result = _canonical_weekly_result(review.get("selected_result"))
                normalized_static = str(review.get("payout_static") or "").strip() or None
                payout_preview = self._build_weekly_payout_preview(
                    assistant_role=assistant.get("role"),
                    selected_result=selected_result,
                    payout_type=review.get("payout_type"),
                    payout_server=review.get("payout_server"),
                    payout_static=normalized_static,
                    payout_config=payout_config,
                )

                if normalized_status == current_status:
                    detail = await self.get_assistant_weekly_admin_detail(
                        assistant_id=assistant_id,
                        week_start=normalized_week_start,
                    )
                    if detail is None:
                        raise ValueError("Не удалось получить weekly detail")
                    return detail

                if (
                    normalized_status == WEEKLY_PAYOUT_ISSUE_STATUS_ISSUED
                    and not payout_preview.get("command_available")
                ):
                    raise ValueError("Команда недоступна для выдачи")

                await cursor.execute(
                    """
                    UPDATE assistant_weekly_reviews
                    SET payout_issue_status = %s,
                        payout_issued_at = CASE
                            WHEN %s = 'issued' THEN CURRENT_TIMESTAMP
                            ELSE NULL
                        END,
                        payout_issued_by_id = CASE
                            WHEN %s = 'issued' THEN %s
                            ELSE NULL
                        END,
                        updated_by_id = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE assistant_id = %s
                      AND week_start = %s
                    """,
                    (
                        normalized_status,
                        normalized_status,
                        normalized_status,
                        actor_id,
                        actor_id,
                        assistant_id,
                        normalized_week_start,
                    ),
                )
                await conn.commit()
                payout_issue_transition = {
                    "from_status": current_status,
                    "to_status": normalized_status,
                    "issued_at": review.get("payout_issued_at"),
                    "issued_by_id": review.get("payout_issued_by_id"),
                    "generated_payout_command": payout_preview.get("command"),
                    "auto_reset": False,
                }

        detail = await self.get_assistant_weekly_admin_detail(
            assistant_id=assistant_id,
            week_start=normalized_week_start,
        )
        if detail is None:
            raise ValueError("Не удалось получить weekly detail")
        detail["payout_issue_transition"] = payout_issue_transition
        return detail

    @db_retry()
    async def get_assistant_sanctions_summary(
        self,
        *,
        assistant_id: int,
        as_of_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        target_date = as_of_date or datetime.now(timezone(timedelta(hours=3))).date()
        next_day = datetime.combine(target_date + timedelta(days=1), datetime.min.time())
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT
                        kind,
                        ROUND(SUM(active_amount), 4) AS amount
                    FROM (
                        SELECT
                            s.id,
                            s.kind,
                            GREATEST(
                                ROUND(
                                    s.amount_total - COALESCE(SUM(sr.amount), 0),
                                    4
                                ),
                                0
                            ) AS active_amount
                        FROM assistant_sanctions s
                        LEFT JOIN assistant_sanction_reliefs sr
                          ON sr.sanction_id = s.id
                         AND sr.relieved_at < %s
                        WHERE s.assistant_id = %s
                          AND s.issued_at < %s
                        GROUP BY s.id, s.kind, s.amount_total
                    ) x
                    GROUP BY kind
                    """,
                    (next_day, assistant_id, next_day),
                )
                rows = await cursor.fetchall() or []
                summary = {
                    "assistant_id": assistant_id,
                    "as_of_date": target_date,
                    "check": 0.0,
                    "point": 0.0,
                    "percent": 0.0,
                    "oral": 0.0,
                    "strict": 0.0,
                }
                for row in rows:
                    kind = str(row.get("kind"))
                    summary[kind] = round(float(row.get("amount") or 0), 4)
                summary["warnings_units"] = int(summary["strict"] * 2 + summary["oral"])
                summary.update(self._warnings_breakdown(summary["warnings_units"]))
                return summary

    @db_retry()
    async def get_assistant_active_sanctions(
        self,
        assistant_id: int,
    ) -> List[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT
                        sb.sanction_id,
                        sb.assistant_id,
                        sb.kind,
                        sb.amount_total,
                        sb.relieved_amount,
                        sb.active_amount,
                        sb.auto_relief_date,
                        sb.issued_at,
                        CASE
                            WHEN sb.source_type = 'queued_batch' AND op.queued_at IS NOT NULL
                                THEN op.queued_at
                            ELSE sb.issued_at
                        END AS display_issued_at,
                        sb.source_type,
                        sb.source_batch_id,
                        sb.basis_date,
                        sb.policy_month,
                        sb.cycle_no
                    FROM sanction_balances sb
                    LEFT JOIN sanction_operations op
                      ON op.id = sb.source_batch_id
                    WHERE sb.assistant_id = %s
                      AND sb.active_amount > 0
                    ORDER BY sb.issued_at DESC, sb.sanction_id DESC
                    """,
                    (assistant_id,),
                )
                assistant_sanctions = await cursor.fetchall() or []
                result: List[Dict[str, Any]] = []
                for sanction in assistant_sanctions:
                    sanction_id = int(sanction["sanction_id"])
                    workoff_items = await self._get_sanction_workoff_items_locked(
                        cursor,
                        sanction_id=sanction_id,
                    )
                    progress_items = await self._get_workoff_progress_items_locked(
                        cursor,
                        assistant_id=assistant_id,
                        workoff_items=workoff_items,
                    ) if workoff_items else []
                    result.append(
                        {
                            **{
                                **dict(sanction),
                                "operation_id": sanction.get("source_batch_id"),
                                "settings_month": sanction.get("policy_month"),
                                "check_rule_hit_no": sanction.get("cycle_no"),
                            },
                            "workoff_items": workoff_items,
                            "workoff_progress_summary": self._build_workoff_progress_summary(progress_items),
                        }
                    )
                return result

    @db_retry()
    async def get_sanction_workoff_progress(self, sanction_id: int) -> Optional[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT *
                    FROM assistant_sanctions
                    WHERE id = %s
                    """,
                    (int(sanction_id),),
                )
                sanction = await cursor.fetchone()
                if not sanction:
                    return None

                workoff_items = await self._get_sanction_workoff_items_locked(
                    cursor,
                    sanction_id=int(sanction_id),
                )
                if not workoff_items:
                    return {
                        "sanction_id": sanction_id,
                        "has_workoff": False,
                    }

                assistant_id = int(sanction["assistant_id"])
                progress_items = await self._get_workoff_progress_items_locked(
                    cursor,
                    assistant_id=assistant_id,
                    workoff_items=workoff_items,
                )

                return {
                    "sanction_id": sanction_id,
                    "has_workoff": True,
                    "items": progress_items,
                    "completed_items": sum(
                        1 for item in progress_items if str(item.get("status") or "") == "completed"
                    ),
                    "total_items": len(progress_items),
                }

    @db_retry()
    async def preview_workoff_for_assistants(
        self,
        *,
        assistant_ids: List[int],
        workoff_items: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        normalized_assistant_ids = sorted({int(value) for value in assistant_ids})
        normalized_items = self._normalize_workoff_items(workoff_items)
        if not normalized_assistant_ids or not normalized_items:
            return []

        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                placeholders = ", ".join(["%s"] * len(normalized_assistant_ids))
                await cursor.execute(
                    f"""
                    SELECT pr_id AS assistant_id, nickname
                    FROM assistants
                    WHERE pr_id IN ({placeholders})
                    ORDER BY nickname ASC, pr_id ASC
                    """,
                    tuple(normalized_assistant_ids),
                )
                assistant_rows = await cursor.fetchall() or []
                results: List[Dict[str, Any]] = []
                for assistant in assistant_rows:
                    assistant_id = int(assistant["assistant_id"])
                    progress_items = await self._get_workoff_progress_items_locked(
                        cursor,
                        assistant_id=assistant_id,
                        workoff_items=normalized_items,
                    )
                    results.append(
                        {
                            "assistant_id": assistant_id,
                            "nickname": assistant.get("nickname"),
                            "items": progress_items,
                        }
                    )
                return results

    @db_retry()
    async def create_manual_sanction(
        self,
        *,
        assistant_id: int,
        kind: str,
        amount: float,
        auto_relief_date: Optional[date],
        basis_date: Optional[date],
        workoff_items: Optional[List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        basis = basis_date or datetime.now(timezone(timedelta(hours=3))).date()
        month_start = self._month_start_for(basis)
        normalized_amount, normalized_auto_relief_date = self._normalize_runtime_sanction(
            kind=kind,
            amount=amount,
            auto_relief_date=auto_relief_date,
        )
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                sanction_id = await self._insert_sanction_locked(
                    cursor,
                    assistant_id=assistant_id,
                    kind=kind,
                    amount_total=normalized_amount,
                    auto_relief_date=normalized_auto_relief_date,
                    source_type="manual",
                    basis_date=basis,
                    policy_month=month_start,
                )
                created_workoff_items = await self._create_sanction_workoff_items_locked(
                    cursor,
                    sanction_id=sanction_id,
                    workoff_items=workoff_items or [],
                )
                if created_workoff_items:
                    await self._sync_sanction_workoff_summary_locked(
                        cursor,
                        sanction_id=sanction_id,
                        workoff_items=created_workoff_items,
                    )
                cycle_result = None
                if kind == "check":
                    cycle_result = await self._apply_check_cycle_locked(
                        cursor,
                        assistant_id=assistant_id,
                        basis_date=basis,
                    )
                await conn.commit()
                return {
                    "sanction_id": sanction_id,
                    "cycle_result": cycle_result,
                }

    @db_retry()
    async def add_sanction_relief(
        self,
        *,
        sanction_id: int,
        amount: float,
        relief_type: str,
        basis_date: Optional[date],
    ) -> Optional[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT sb.active_amount, s.kind
                    FROM sanction_balances sb
                    JOIN assistant_sanctions s ON s.id = sb.sanction_id
                    WHERE sb.sanction_id = %s
                    """,
                    (int(sanction_id),),
                )
                balance = await cursor.fetchone()
                if not balance:
                    return None
                active_amount = float(balance.get("active_amount") or 0)
                if active_amount <= 0:
                    return None
                kind = str(balance.get("kind") or "")
                relief_amount = round(float(amount), 4)
                if kind in {"oral", "strict"} and abs(relief_amount - 1.0) > 1e-9:
                    raise ValueError("Для устного и строгого допускается только полное снятие на 1")
                if relief_amount <= 0 or relief_amount - active_amount > 1e-9:
                    raise ValueError("Нельзя снять больше активного остатка санкции")
                await cursor.execute(
                    """
                    INSERT INTO assistant_sanction_reliefs (
                        sanction_id, amount, relieved_at, basis_date, relief_type
                    )
                    VALUES (%s, %s, CURRENT_TIMESTAMP, %s, %s)
                    """,
                    (int(sanction_id), relief_amount, basis_date, relief_type),
                )
                relief_id = int(cursor.lastrowid)
                await conn.commit()
                return {
                    "relief_id": relief_id,
                    "sanction_id": sanction_id,
                    "amount": relief_amount,
                    "relief_type": relief_type,
                    "basis_date": basis_date,
                }

    @db_retry()
    async def replace_sanction(
        self,
        *,
        sanction_id: int,
        new_kind: str,
        new_amount: float,
        new_auto_relief_date: Optional[date],
        basis_date: Optional[date],
        workoff_items: Optional[List[Dict[str, Any]]],
    ) -> Optional[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT * FROM assistant_sanctions WHERE id = %s",
                    (int(sanction_id),),
                )
                existing = await cursor.fetchone()
                if not existing:
                    return None
                await self.add_sanction_relief(
                    sanction_id=sanction_id,
                    amount=float(existing.get("amount_total") or 0),
                    relief_type="replacement",
                    basis_date=basis_date,
                )
                created = await self.create_manual_sanction(
                    assistant_id=int(existing["assistant_id"]),
                    kind=new_kind,
                    amount=new_amount,
                    auto_relief_date=new_auto_relief_date,
                    basis_date=basis_date or existing.get("basis_date"),
                    workoff_items=workoff_items or [],
                )
                await cursor.execute(
                    "UPDATE assistant_sanctions SET replaced_by_sanction_id = %s WHERE id = %s",
                    (created["sanction_id"], int(sanction_id)),
                )
                await conn.commit()
                return {
                    "replaced_sanction_id": sanction_id,
                    "new_sanction_id": created["sanction_id"],
                    "cycle_result": created.get("cycle_result"),
                }

    async def _list_active_assistants_with_live_status_locked(self, cursor) -> List[Dict[str, Any]]:
        await cursor.execute(
            """
            SELECT
                a.pr_id AS assistant_id,
                CASE WHEN ss.id IS NULL THEN FALSE ELSE TRUE END AS live_in_spec
            FROM assistants a
            LEFT JOIN spec_sessions ss
              ON ss.pr_id = a.pr_id
             AND ss.ended_at IS NULL
             AND ss.deleted_at IS NULL
            WHERE a.dismissed_at IS NULL
            ORDER BY a.pr_id ASC
            """
        )
        return await cursor.fetchall() or []

    async def _rebuild_batch_snapshot_locked(
        self,
        cursor,
        *,
        batch_id: int,
        explicit_assistant_ids: Optional[List[int]] = None,
    ) -> None:
        await cursor.execute(
            """
            SELECT
                id,
                operation_date AS basis_date,
                penalty_kind AS sanction_kind,
                penalty_amount AS sanction_amount,
                recipient_mode AS audience_mode,
                status
            FROM sanction_operations
            WHERE id = %s
            """,
            (batch_id,),
        )
        batch = await cursor.fetchone()
        if not batch:
            raise ValueError("Operation not found")

        audience_mode = str(batch.get("audience_mode"))
        assistants = await self._list_active_assistants_with_live_status_locked(cursor)
        assistant_status_map = {
            int(row["assistant_id"]): bool(row.get("live_in_spec"))
            for row in assistants
        }

        if explicit_assistant_ids is not None:
            selected_ids = list(dict.fromkeys(int(value) for value in explicit_assistant_ids))
        else:
            selected_ids: List[int] = []
            for assistant_id, live_in_spec in assistant_status_map.items():
                if audience_mode == "all_active":
                    selected_ids.append(assistant_id)
                elif audience_mode == "live_without_active_session" and not live_in_spec:
                    selected_ids.append(assistant_id)

        await cursor.execute(
            "DELETE FROM sanction_operation_members WHERE operation_id = %s",
            (batch_id,),
        )

        for assistant_id in selected_ids:
            await cursor.execute(
                """
                INSERT INTO sanction_operation_members (
                    operation_id,
                    assistant_id,
                    issue_status,
                    issue_reason,
                    issued_sanction_id
                )
                VALUES (%s, %s, 'pending', NULL, NULL)
                """,
                (batch_id, assistant_id),
            )

    @db_retry()
    async def create_queued_sanction_batch(
        self,
        *,
        basis_date: date,
        created_by_id: Optional[int],
        sanction_kind: str,
        sanction_amount: float,
        auto_relief_date: Optional[date],
        audience_mode: str,
        assistant_ids: Optional[List[int]],
        workoff_items: Optional[List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        assistant_ids = [int(v) for v in (assistant_ids or [])]
        normalized_amount, normalized_auto_relief_date = self._normalize_runtime_sanction(
            kind=sanction_kind,
            amount=sanction_amount,
            auto_relief_date=auto_relief_date,
        )
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO sanction_operations (
                        operation_date,
                        created_at,
                        created_by_id,
                        penalty_kind,
                        penalty_amount,
                        auto_relief_date,
                        recipient_mode,
                        status,
                        queued_at
                    )
                    VALUES (%s, CURRENT_TIMESTAMP, %s, %s, %s, %s, %s, 'queued', CURRENT_TIMESTAMP)
                    """,
                    (
                        basis_date,
                        created_by_id,
                        sanction_kind,
                        normalized_amount,
                        normalized_auto_relief_date,
                        audience_mode,
                    ),
                )
                batch_id = int(cursor.lastrowid)
                await self._rebuild_batch_snapshot_locked(
                    cursor,
                    batch_id=batch_id,
                    explicit_assistant_ids=assistant_ids if assistant_ids else None,
                )
                await self._replace_batch_workoff_items_locked(
                    cursor,
                    batch_id=batch_id,
                    workoff_items=workoff_items or [],
                )

                await conn.commit()
        return await self.get_queued_sanction_batch(batch_id)

    @db_retry()
    async def update_queued_sanction_batch(
        self,
        *,
        batch_id: int,
        payload: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        allowed_fields = {
            "sanction_kind",
            "sanction_amount",
            "auto_relief_date",
            "audience_mode",
        }
        data = {key: value for key, value in payload.items() if key in allowed_fields}
        workoff_items = payload.get("workoff_items")
        assistant_ids = payload.get("assistant_ids")
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT status, penalty_kind, penalty_amount, auto_relief_date
                    FROM sanction_operations
                    WHERE id = %s
                    """,
                    (batch_id,),
                )
                existing = await cursor.fetchone()
                if not existing:
                    return None
                if existing.get("status") != "queued":
                    raise ValueError("Operation cannot be edited in current status")
                if any(
                    field in data
                    for field in ("sanction_kind", "sanction_amount", "auto_relief_date")
                ):
                    effective_kind = str(
                        data.get("sanction_kind") or existing.get("penalty_kind")
                    )
                    normalized_amount, normalized_auto_relief_date = self._normalize_runtime_sanction(
                        kind=effective_kind,
                        amount=float(
                            data.get("sanction_amount")
                            if data.get("sanction_amount") is not None
                            else existing.get("penalty_amount") or 0
                        ),
                        auto_relief_date=data.get(
                            "auto_relief_date",
                            existing.get("auto_relief_date"),
                        ),
                    )
                    data["sanction_kind"] = effective_kind
                    data["sanction_amount"] = normalized_amount
                    data["auto_relief_date"] = normalized_auto_relief_date
                column_map = {
                    "sanction_kind": "penalty_kind",
                    "sanction_amount": "penalty_amount",
                    "auto_relief_date": "auto_relief_date",
                    "audience_mode": "recipient_mode",
                }
                if data:
                    set_sql = ", ".join(f"{column_map[field]} = %s" for field in data.keys())
                    await cursor.execute(
                        f"UPDATE sanction_operations SET {set_sql} WHERE id = %s",
                        tuple(data.values()) + (batch_id,),
                    )
                if workoff_items is not None:
                    await self._replace_batch_workoff_items_locked(
                        cursor,
                        batch_id=batch_id,
                        workoff_items=workoff_items,
                    )
                if assistant_ids is not None:
                    await self._rebuild_batch_snapshot_locked(
                        cursor,
                        batch_id=batch_id,
                        explicit_assistant_ids=[int(v) for v in assistant_ids],
                    )
                await conn.commit()
        return await self.get_queued_sanction_batch(batch_id)

    @db_retry()
    async def add_queued_batch_member(
        self,
        *,
        batch_id: int,
        assistant_id: int,
    ) -> Optional[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT status FROM sanction_operations WHERE id = %s",
                    (batch_id,),
                )
                batch = await cursor.fetchone()
                if not batch:
                    return None
                if batch.get("status") != "queued":
                    raise ValueError("Operation cannot be edited in current status")
                await cursor.execute(
                    """
                    SELECT 1
                    FROM sanction_operation_members
                    WHERE operation_id = %s AND assistant_id = %s
                    """,
                    (batch_id, assistant_id),
                )
                if await cursor.fetchone():
                    raise ValueError("Ассистент уже добавлен в эту выдачу")
                await cursor.execute(
                    """
                    INSERT INTO sanction_operation_members (
                        operation_id,
                        assistant_id,
                        issue_status,
                        issue_reason,
                        issued_sanction_id
                    )
                    VALUES (%s, %s, 'pending', NULL, NULL)
                    """,
                    (batch_id, assistant_id),
                )
                await conn.commit()
        return await self.get_queued_sanction_batch(batch_id)

    @db_retry()
    async def remove_queued_batch_member(
        self,
        *,
        batch_id: int,
        assistant_id: int,
    ) -> Optional[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT status FROM sanction_operations WHERE id = %s",
                    (batch_id,),
                )
                batch = await cursor.fetchone()
                if not batch:
                    return None
                if batch.get("status") != "queued":
                    raise ValueError("Operation cannot be edited in current status")
                await cursor.execute(
                    """
                    DELETE FROM sanction_operation_members
                    WHERE operation_id = %s AND assistant_id = %s
                    """,
                    (batch_id, assistant_id),
                )
                await conn.commit()
        return await self.get_queued_sanction_batch(batch_id)

    @db_retry()
    async def queue_queued_sanction_batch(self, batch_id: int) -> Optional[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    UPDATE sanction_operations
                    SET status = 'queued', queued_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                      AND status = 'queued'
                    """,
                    (batch_id,),
                )
                if cursor.rowcount <= 0:
                    await cursor.execute(
                        "SELECT id FROM sanction_operations WHERE id = %s",
                        (batch_id,),
                    )
                    if not await cursor.fetchone():
                        return None
                await conn.commit()
        return await self.get_queued_sanction_batch(batch_id)

    @db_retry()
    async def cancel_queued_sanction_batch(self, batch_id: int) -> Optional[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT status FROM sanction_operations WHERE id = %s",
                    (batch_id,),
                )
                batch = await cursor.fetchone()
                if not batch:
                    return None
                if batch.get("status") != "queued":
                    raise ValueError("Operation cannot be cancelled in current status")
                await cursor.execute(
                    """
                    UPDATE sanction_operations
                    SET status = 'cancelled', cancelled_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                      AND status = 'queued'
                    """,
                    (batch_id,),
                )
                await conn.commit()
        return await self.get_queued_sanction_batch(batch_id)

    @db_retry()
    async def list_queued_sanction_batches(self, *, status: Optional[str] = None) -> List[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                where_sql = ""
                params: List[Any] = []
                if status:
                    where_sql = "WHERE b.status = %s"
                    params.append(status)
                else:
                    where_sql = "WHERE b.status <> 'cancelled'"
                await cursor.execute(
                    f"""
                    SELECT
                        b.id,
                        b.operation_date AS basis_date,
                        b.created_at,
                        b.created_by_id,
                        COALESCE(created_assistant.nickname, created_user.username) AS created_by_name,
                        b.penalty_kind AS sanction_kind,
                        b.penalty_amount AS sanction_amount,
                        b.auto_relief_date,
                        b.recipient_mode AS audience_mode,
                        b.status,
                        b.processing_mode,
                        b.processed_by_id,
                        COALESCE(processed_assistant.nickname, processed_user.username) AS processed_by_name,
                        b.queued_at,
                        b.processed_at,
                        b.cancelled_at,
                        b.failure_reason,
                        COUNT(m.assistant_id) AS members_total,
                        COUNT(m.assistant_id) AS effective_members,
                        SUM(CASE WHEN m.issue_status = 'issued' THEN 1 ELSE 0 END) AS issued_members,
                        SUM(CASE WHEN m.issue_status = 'skipped_immunity' THEN 1 ELSE 0 END) AS skipped_immunity_members,
                        SUM(CASE WHEN m.issue_status = 'skipped_leave' THEN 1 ELSE 0 END) AS skipped_leave_members
                    FROM sanction_operations b
                    LEFT JOIN sanction_operation_members m ON m.operation_id = b.id
                    LEFT JOIN web_auth created_user ON created_user.discord_id = b.created_by_id
                    LEFT JOIN assistants created_assistant ON created_assistant.pr_id = b.created_by_id
                    LEFT JOIN web_auth processed_user ON processed_user.discord_id = b.processed_by_id
                    LEFT JOIN assistants processed_assistant ON processed_assistant.pr_id = b.processed_by_id
                    {where_sql}
                    GROUP BY b.id
                    ORDER BY b.created_at DESC, b.id DESC
                    """,
                    tuple(params),
                )
                return await cursor.fetchall() or []

    @db_retry()
    async def get_queued_sanction_batch(self, batch_id: int) -> Optional[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT
                        b.id,
                        b.operation_date AS basis_date,
                        b.created_at,
                        b.created_by_id,
                        COALESCE(created_assistant.nickname, created_user.username) AS created_by_name,
                        b.penalty_kind AS sanction_kind,
                        b.penalty_amount AS sanction_amount,
                        b.auto_relief_date,
                        b.recipient_mode AS audience_mode,
                        b.status,
                        b.processing_mode,
                        b.processed_by_id,
                        COALESCE(processed_assistant.nickname, processed_user.username) AS processed_by_name,
                        b.queued_at,
                        b.processed_at,
                        b.cancelled_at,
                        b.failure_reason,
                        COUNT(m.assistant_id) AS members_total,
                        COUNT(m.assistant_id) AS effective_members,
                        SUM(CASE WHEN m.issue_status = 'issued' THEN 1 ELSE 0 END) AS issued_members,
                        SUM(CASE WHEN m.issue_status = 'skipped_immunity' THEN 1 ELSE 0 END) AS skipped_immunity_members,
                        SUM(CASE WHEN m.issue_status = 'skipped_leave' THEN 1 ELSE 0 END) AS skipped_leave_members
                    FROM sanction_operations b
                    LEFT JOIN sanction_operation_members m ON m.operation_id = b.id
                    LEFT JOIN web_auth created_user ON created_user.discord_id = b.created_by_id
                    LEFT JOIN assistants created_assistant ON created_assistant.pr_id = b.created_by_id
                    LEFT JOIN web_auth processed_user ON processed_user.discord_id = b.processed_by_id
                    LEFT JOIN assistants processed_assistant ON processed_assistant.pr_id = b.processed_by_id
                    WHERE b.id = %s
                    GROUP BY b.id
                    """,
                    (batch_id,),
                )
                batch = await cursor.fetchone()
                if not batch:
                    return None
                await cursor.execute(
                    """
                    SELECT
                        m.operation_id AS batch_id,
                        m.assistant_id,
                        m.issue_status AS execution_status,
                        m.issue_reason AS execution_reason,
                        m.issued_sanction_id,
                        a.nickname
                    FROM sanction_operation_members m
                    LEFT JOIN assistants a ON a.pr_id = m.assistant_id
                    WHERE m.operation_id = %s
                    ORDER BY a.nickname ASC, m.assistant_id ASC
                    """,
                    (batch_id,),
                )
                batch["members"] = await cursor.fetchall() or []
                batch["workoff_items"] = await self._get_batch_workoff_items_locked(
                    cursor,
                    batch_id=batch_id,
                )
                return batch

    async def _get_effective_batch_members_locked(
        self,
        cursor,
        *,
        batch_id: int,
        assistant_filter: Optional[Set[int]] = None,
    ) -> List[Dict[str, Any]]:
        query = """
            SELECT *
            FROM sanction_operation_members
            WHERE operation_id = %s
        """
        params: List[Any] = [batch_id]
        if assistant_filter:
            placeholders = ", ".join(["%s"] * len(assistant_filter))
            query += f" AND assistant_id IN ({placeholders})"
            params.extend(sorted(assistant_filter))
        query += " ORDER BY assistant_id ASC"
        await cursor.execute(query, tuple(params))
        return await cursor.fetchall() or []

    async def _refresh_queued_batch_status_locked(self, cursor, *, batch_id: int) -> Optional[str]:
        await cursor.execute(
            "SELECT status FROM sanction_operations WHERE id = %s",
            (batch_id,),
        )
        batch = await cursor.fetchone()
        if not batch:
            return None
        current_status = str(batch.get("status") or "")
        if current_status == "cancelled":
            return current_status

        await cursor.execute(
            """
            SELECT
                COUNT(*) AS effective_members,
                SUM(CASE WHEN issue_status = 'pending' THEN 1 ELSE 0 END) AS pending_members,
                SUM(CASE WHEN issue_status = 'failed' THEN 1 ELSE 0 END) AS failed_members
            FROM sanction_operation_members
            WHERE operation_id = %s
            """,
            (batch_id,),
        )
        counts = await cursor.fetchone() or {}
        pending_members = int(counts.get("pending_members") or 0)
        failed_members = int(counts.get("failed_members") or 0)

        if failed_members > 0:
            next_status = "failed"
        elif pending_members > 0:
            next_status = current_status if current_status in {"queued", "processing"} else "processing"
        else:
            next_status = "completed"

        await cursor.execute(
            """
            UPDATE sanction_operations
            SET status = %s,
                processed_at = CASE
                    WHEN %s IN ('completed', 'failed') THEN CURRENT_TIMESTAMP
                    ELSE processed_at
                END
            WHERE id = %s
            """,
            (next_status, next_status, batch_id),
        )
        return next_status

    async def _execute_queued_batch_locked(
        self,
        cursor,
        *,
        batch: Dict[str, Any],
        run_started_at: datetime,
        ignore_immunity: bool = False,
        assistant_filter: Optional[Set[int]] = None,
        apply_check_cycle: bool = True,
    ) -> Dict[str, Any]:
        batch_id = int(batch["id"])
        members = await self._get_effective_batch_members_locked(
            cursor,
            batch_id=batch_id,
            assistant_filter=assistant_filter,
        )
        batch_workoff_items = await self._get_batch_workoff_items_locked(
            cursor,
            batch_id=batch_id,
        )

        batch_result = {
            "batch_id": batch_id,
            "issued": [],
            "skipped_immunity": [],
            "skipped_leave": [],
            "failed": [],
            "derived": [],
        }

        for member in members:
            assistant_id = int(member["assistant_id"])
            try:
                day_status = await self._get_assistant_day_status_locked(
                    cursor,
                    assistant_id=assistant_id,
                    work_date=batch["basis_date"],
                )
                kind = str(batch["sanction_kind"])
                if not ignore_immunity and bool(day_status.get("is_leave_day")):
                    await cursor.execute(
                        """
                        UPDATE sanction_operation_members
                        SET issue_status = 'skipped_leave',
                            issue_reason = %s,
                            issued_sanction_id = NULL
                        WHERE operation_id = %s AND assistant_id = %s
                        """,
                        ("Skipped by U/O day override", batch_id, assistant_id),
                    )
                    batch_result["skipped_leave"].append(assistant_id)
                    continue
                immunity = False
                if not ignore_immunity:
                    immunity = (
                        (kind == "check" and day_status["check_immunity"])
                        or (kind == "point" and day_status["point_immunity"])
                        or (kind == "percent" and day_status["percent_immunity"])
                    )
                if immunity:
                    await cursor.execute(
                        """
                        UPDATE sanction_operation_members
                        SET issue_status = 'skipped_immunity',
                            issue_reason = %s,
                            issued_sanction_id = NULL
                        WHERE operation_id = %s AND assistant_id = %s
                        """,
                        ("Skipped by day immunity", batch_id, assistant_id),
                    )
                    batch_result["skipped_immunity"].append(assistant_id)
                    continue

                sanction_id = await self._insert_sanction_locked(
                    cursor,
                    assistant_id=assistant_id,
                    kind=kind,
                    amount_total=float(batch["sanction_amount"] or 0),
                    auto_relief_date=batch.get("auto_relief_date"),
                    issued_at=run_started_at,
                    source_type="queued_batch",
                    source_batch_id=batch_id,
                    basis_date=batch["basis_date"],
                    policy_month=self._month_start_for(batch["basis_date"]),
                )
                assistant_sanction_workoffs = await self._create_sanction_workoff_items_locked(
                    cursor,
                    sanction_id=sanction_id,
                    workoff_items=batch_workoff_items,
                )
                if assistant_sanction_workoffs:
                    await self._sync_sanction_workoff_summary_locked(
                        cursor,
                        sanction_id=sanction_id,
                        workoff_items=assistant_sanction_workoffs,
                    )
                await cursor.execute(
                    """
                    UPDATE sanction_operation_members
                    SET issue_status = 'issued',
                        issue_reason = NULL,
                        issued_sanction_id = %s
                    WHERE operation_id = %s AND assistant_id = %s
                    """,
                    (sanction_id, batch_id, assistant_id),
                )
                batch_result["issued"].append(
                    {"assistant_id": assistant_id, "sanction_id": sanction_id}
                )
                if kind == "check" and apply_check_cycle:
                    cycle_result = await self._apply_check_cycle_locked(
                        cursor,
                        assistant_id=assistant_id,
                        basis_date=batch["basis_date"],
                        source_batch_id=batch_id,
                        run_timestamp=run_started_at,
                    )
                    if cycle_result:
                        batch_result["derived"].append(cycle_result)
            except Exception as exc:
                await cursor.execute(
                    """
                    UPDATE sanction_operation_members
                    SET issue_status = 'failed',
                        issue_reason = %s,
                        issued_sanction_id = NULL
                    WHERE operation_id = %s AND assistant_id = %s
                    """,
                    (str(exc)[:255], batch_id, assistant_id),
                )
                batch_result["failed"].append(
                    {"assistant_id": assistant_id, "error": str(exc)}
                )

        return batch_result

    async def _claim_operation_for_processing_locked(
        self,
        cursor,
        *,
        operation_id: int,
        processing_mode: str,
        processed_by_id: Optional[int],
    ) -> Optional[Dict[str, Any]]:
        await cursor.execute(
            """
            UPDATE sanction_operations
            SET status = 'processing',
                processing_mode = %s,
                processed_by_id = %s
            WHERE id = %s
              AND status = 'queued'
            """,
            (processing_mode, processed_by_id, operation_id),
        )
        if cursor.rowcount <= 0:
            return None
        await cursor.execute(
            """
            SELECT
                id,
                operation_date AS basis_date,
                penalty_kind AS sanction_kind,
                penalty_amount AS sanction_amount,
                auto_relief_date,
                recipient_mode AS audience_mode,
                status,
                processing_mode,
                processed_by_id,
                queued_at,
                processed_at,
                failure_reason
            FROM sanction_operations
            WHERE id = %s
            """,
            (operation_id,),
        )
        return await cursor.fetchone()

    async def _process_single_sanction_operation_locked(
        self,
        cursor,
        *,
        operation_id: int,
        run_started_at: datetime,
        ignore_immunity: bool,
        processing_mode: str,
        processed_by_id: Optional[int] = None,
        assistant_filter: Optional[Set[int]] = None,
        apply_check_cycle: bool = True,
    ) -> Optional[Dict[str, Any]]:
        batch = await self._claim_operation_for_processing_locked(
            cursor,
            operation_id=operation_id,
            processing_mode=processing_mode,
            processed_by_id=processed_by_id,
        )
        if not batch:
            return None
        batch_result = await self._execute_queued_batch_locked(
            cursor,
            batch=batch,
            run_started_at=run_started_at,
            ignore_immunity=ignore_immunity,
            assistant_filter=assistant_filter,
            apply_check_cycle=apply_check_cycle,
        )
        new_status = await self._refresh_queued_batch_status_locked(
            cursor,
            batch_id=operation_id,
        )
        await cursor.execute(
            """
            UPDATE sanction_operations
            SET failure_reason = %s
            WHERE id = %s
            """,
            (
                json.dumps(batch_result["failed"], default=str)
                if batch_result["failed"]
                else None,
                operation_id,
            ),
        )
        batch_result["status"] = new_status
        return batch_result

    async def _replay_check_cycles_for_day_locked(
        self,
        cursor,
        *,
        assistant_id: int,
        basis_date: date,
        run_started_at: datetime,
    ) -> List[Dict[str, Any]]:
        await cursor.execute(
            """
            SELECT id, operation_id AS source_batch_id
            FROM assistant_sanctions
            WHERE assistant_id = %s
              AND kind = 'check'
              AND basis_date = %s
            ORDER BY issued_at ASC, id ASC
            """,
            (assistant_id, basis_date),
        )
        check_rows = await cursor.fetchall() or []
        derived: List[Dict[str, Any]] = []
        for row in check_rows:
            cycle_result = await self._apply_check_cycle_locked(
                cursor,
                assistant_id=assistant_id,
                basis_date=basis_date,
                source_batch_id=row.get("source_batch_id"),
                run_timestamp=run_started_at,
            )
            if cycle_result:
                derived.append(cycle_result)
        return derived

    async def _purge_assistant_derived_outputs_locked(
        self,
        cursor,
        *,
        assistant_id: int,
        start_date: date,
        end_date: date,
    ) -> None:
        await cursor.execute(
            """
            UPDATE sanction_operation_members m
            JOIN sanction_operations b ON b.id = m.operation_id
            SET m.issue_status = 'pending',
                m.issue_reason = NULL,
                m.issued_sanction_id = NULL
            WHERE m.assistant_id = %s
              AND b.operation_date BETWEEN %s AND %s
              AND b.status <> 'cancelled'
            """,
            (assistant_id, start_date, end_date),
        )

        await cursor.execute(
            """
            DELETE sr
            FROM assistant_sanction_reliefs sr
            JOIN assistant_sanctions s ON s.id = sr.sanction_id
            WHERE s.assistant_id = %s
              AND sr.basis_date BETWEEN %s AND %s
              AND sr.relief_type IN ('default', 'custom_workoff', 'cycle_reset', 'month_reset', 'auto_expire')
            """,
            (assistant_id, start_date, end_date),
        )

        await cursor.execute(
            """
            SELECT id
            FROM assistant_sanctions
            WHERE assistant_id = %s
              AND basis_date BETWEEN %s AND %s
              AND source_type IN ('queued_batch', 'check_cycle')
            """,
            (assistant_id, start_date, end_date),
        )
        sanction_rows = await cursor.fetchall() or []
        sanction_ids = [int(row["id"]) for row in sanction_rows]
        if sanction_ids:
            placeholders = ", ".join(["%s"] * len(sanction_ids))
            await cursor.execute(
                f"DELETE FROM assistant_sanction_reliefs WHERE sanction_id IN ({placeholders})",
                tuple(sanction_ids),
            )
            await cursor.execute(
                f"DELETE FROM assistant_sanctions WHERE id IN ({placeholders})",
                tuple(sanction_ids),
            )

    @db_retry()
    async def process_queued_sanction_batches_for_date(
        self,
        basis_date: date,
        *,
        force: bool = False,
    ) -> Dict[str, Any]:
        nightly_context = self._nightly_run_context_for_basis_date(basis_date)
        processing_date = nightly_context["processing_date"]
        run_started_at = nightly_context["run_started_at"]
        if not force and self._current_msk_date() < processing_date:
            return {
                "basis_date": basis_date,
                "processing_date": processing_date,
                "processed_batches": [],
                "custom_workoff": {"relieved": []},
                "warning_auto_expiry": {"relieved": []},
                "default_relief": {"relieved": []},
                "month_reset": {"reset_count": 0},
                "nightly_run": {
                    "claimed": False,
                    "status": "too_early",
                },
                "skipped": True,
            }
        processed_batches: List[Dict[str, Any]] = []
        custom_workoff_result: Dict[str, Any] = {"relieved": []}
        warning_auto_expiry_result: Dict[str, Any] = {"relieved": []}
        relief_result: Dict[str, Any] = {"relieved": []}
        month_reset_result: Dict[str, Any] = {"reset_count": 0}
        nightly_run_state: Dict[str, Any] = {"claimed": False, "status": None}
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                acquired = await self._acquire_named_lock(
                    cursor,
                    lock_name=SANCTIONS_GLOBAL_LOCK_NAME,
                )
                if not acquired:
                    raise RuntimeError("Timed out acquiring sanctions processing lock")
                try:
                    nightly_run_state = await self._claim_sanction_nightly_run_locked(
                        cursor,
                        basis_date=basis_date,
                    )
                    if not nightly_run_state.get("claimed"):
                        await conn.commit()
                        return {
                            "basis_date": basis_date,
                            "processing_date": processing_date,
                            "processed_batches": [],
                            "custom_workoff": {"relieved": []},
                            "warning_auto_expiry": {"relieved": []},
                            "default_relief": {"relieved": []},
                            "month_reset": {"reset_count": 0},
                            "nightly_run": nightly_run_state,
                            "skipped": True,
                        }
                    await cursor.execute(
                        """
                        SELECT
                            id
                        FROM sanction_operations
                        WHERE operation_date = %s
                          AND status = 'queued'
                        ORDER BY id ASC
                        """,
                        (basis_date,),
                    )
                    batches = await cursor.fetchall() or []

                    for batch in batches:
                        batch_result = await self._process_single_sanction_operation_locked(
                            cursor,
                            operation_id=int(batch["id"]),
                            run_started_at=run_started_at,
                            ignore_immunity=False,
                            processing_mode="nightly_auto",
                            processed_by_id=None,
                        )
                        if batch_result:
                            processed_batches.append(batch_result)

                    custom_workoff_result = await self._apply_custom_workoff_relief_locked(
                        cursor,
                        basis_date=basis_date,
                        run_started_at=run_started_at,
                    )
                    relief_result = await self._apply_default_auto_relief_locked(
                        cursor,
                        basis_date=basis_date,
                        run_started_at=run_started_at,
                    )
                    warning_auto_expiry_result = await self._apply_warning_auto_expiry_locked(
                        cursor,
                        current_date=processing_date,
                        run_started_at=run_started_at,
                    )
                    month_reset_result = await self._apply_month_end_check_reset_locked(
                        cursor,
                        basis_date=basis_date,
                        run_started_at=run_started_at,
                    )
                    await self._complete_sanction_nightly_run_locked(
                        cursor,
                        basis_date=basis_date,
                    )
                    nightly_run_state = {**nightly_run_state, "status": "completed"}
                    await conn.commit()
                except Exception as exc:
                    await self._fail_sanction_nightly_run_locked(
                        cursor,
                        basis_date=basis_date,
                        failure_reason=str(exc),
                    )
                    await conn.commit()
                    raise
                finally:
                    await self._release_named_lock(
                        cursor,
                        lock_name=SANCTIONS_GLOBAL_LOCK_NAME,
                    )
        return {
            "basis_date": basis_date,
            "processing_date": processing_date,
            "processed_batches": processed_batches,
            "custom_workoff": custom_workoff_result,
            "warning_auto_expiry": warning_auto_expiry_result,
            "default_relief": relief_result,
            "month_reset": month_reset_result,
            "nightly_run": nightly_run_state,
            "skipped": False,
        }

    @db_retry()
    async def process_sanction_operation_now(
        self,
        operation_id: int,
        *,
        requested_by_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        run_started_at = datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None)
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                acquired = await self._acquire_named_lock(
                    cursor,
                    lock_name=SANCTIONS_GLOBAL_LOCK_NAME,
                )
                if not acquired:
                    raise RuntimeError("Timed out acquiring sanctions processing lock")
                try:
                    result = await self._process_single_sanction_operation_locked(
                        cursor,
                        operation_id=int(operation_id),
                        run_started_at=run_started_at,
                        ignore_immunity=True,
                        processing_mode="manual_now",
                        processed_by_id=requested_by_id,
                    )
                    if result is None:
                        await cursor.execute(
                            "SELECT status FROM sanction_operations WHERE id = %s",
                            (int(operation_id),),
                        )
                        operation = await cursor.fetchone()
                        await conn.commit()
                        return {
                            "operation_id": int(operation_id),
                            "processed": False,
                            "status": operation.get("status") if operation else None,
                            "missing": operation is None,
                        }
                    await conn.commit()
                    return {
                        "operation_id": int(operation_id),
                        "processed": True,
                        **result,
                    }
                finally:
                    await self._release_named_lock(
                        cursor,
                        lock_name=SANCTIONS_GLOBAL_LOCK_NAME,
                    )

    @db_retry()
    async def recalculate_assistant_sanction_derivations(
        self,
        *,
        assistant_id: int,
        start_date: date,
        end_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        today_msk = self._current_msk_date()
        last_closed_day = today_msk - timedelta(days=1)
        replay_end = min(end_date or last_closed_day, last_closed_day)
        if start_date > replay_end:
            return {
                "assistant_id": assistant_id,
                "start_date": start_date,
                "end_date": replay_end,
                "replayed_days": [],
                "skipped": True,
            }

        replayed_days: List[Dict[str, Any]] = []
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                acquired = await self._acquire_named_lock(
                    cursor,
                    lock_name=SANCTIONS_GLOBAL_LOCK_NAME,
                )
                if not acquired:
                    raise RuntimeError("Timed out acquiring sanctions replay lock")
                try:
                    await self._purge_assistant_derived_outputs_locked(
                        cursor,
                        assistant_id=assistant_id,
                        start_date=start_date,
                        end_date=replay_end,
                    )

                    cursor_day = start_date
                    while cursor_day <= replay_end:
                        run_started_at = datetime.combine(
                            cursor_day + timedelta(days=1),
                            datetime.min.time(),
                        )
                        await cursor.execute(
                            """
                            SELECT
                                id,
                                operation_date AS basis_date,
                                penalty_kind AS sanction_kind,
                                penalty_amount AS sanction_amount,
                                recipient_mode AS audience_mode,
                                status,
                                queued_at,
                                processed_at,
                                failure_reason
                            FROM sanction_operations
                            WHERE operation_date = %s
                              AND status IN ('processing', 'completed', 'failed')
                            ORDER BY id ASC
                            """,
                            (cursor_day,),
                        )
                        batches = await cursor.fetchall() or []
                        day_result = {
                            "basis_date": cursor_day,
                            "batches": [],
                            "derived": [],
                            "custom_workoff": None,
                            "warning_auto_expiry": None,
                            "default_relief": None,
                            "month_reset": None,
                        }

                        for batch in batches:
                            batch_result = await self._execute_queued_batch_locked(
                                cursor,
                                batch=batch,
                                run_started_at=run_started_at,
                                assistant_filter={assistant_id},
                                apply_check_cycle=False,
                            )
                            await self._refresh_queued_batch_status_locked(
                                cursor,
                                batch_id=int(batch["id"]),
                            )
                            await cursor.execute(
                                """
                                UPDATE sanction_operations
                                SET failure_reason = %s
                                WHERE id = %s
                                """,
                                (
                                    json.dumps(batch_result["failed"], default=str)
                                    if batch_result["failed"]
                                    else None,
                                    int(batch["id"]),
                                ),
                            )
                            day_result["batches"].append(batch_result)

                        day_result["derived"] = await self._replay_check_cycles_for_day_locked(
                            cursor,
                            assistant_id=assistant_id,
                            basis_date=cursor_day,
                            run_started_at=run_started_at,
                        )
                        day_result["custom_workoff"] = await self._apply_custom_workoff_relief_locked(
                            cursor,
                            basis_date=cursor_day,
                            run_started_at=run_started_at,
                            assistant_filter={assistant_id},
                        )
                        day_result["warning_auto_expiry"] = await self._apply_warning_auto_expiry_locked(
                            cursor,
                            current_date=run_started_at.date(),
                            run_started_at=run_started_at,
                            assistant_filter={assistant_id},
                        )
                        day_result["default_relief"] = await self._apply_default_auto_relief_locked(
                            cursor,
                            basis_date=cursor_day,
                            run_started_at=run_started_at,
                            assistant_filter={assistant_id},
                        )
                        day_result["month_reset"] = await self._apply_month_end_check_reset_locked(
                            cursor,
                            basis_date=cursor_day,
                            run_started_at=run_started_at,
                            assistant_filter={assistant_id},
                        )
                        replayed_days.append(day_result)
                        cursor_day += timedelta(days=1)

                    await conn.commit()
                finally:
                    await self._release_named_lock(
                        cursor,
                        lock_name=SANCTIONS_GLOBAL_LOCK_NAME,
                    )

        return {
            "assistant_id": assistant_id,
            "start_date": start_date,
            "end_date": replay_end,
            "replayed_days": replayed_days,
            "skipped": False,
        }
