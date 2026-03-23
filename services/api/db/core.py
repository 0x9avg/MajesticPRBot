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
from services.rbac import (
    SITE_SETTINGS_REQUIRED_PERMISSIONS,
    STAFF_ROLES,
    build_dense_permission_map,
    build_dense_service_permission_map,
    get_default_role_permissions,
    get_permission_catalog,
    normalize_permission_flags,
)

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
WEEKLY_PAYOUT_SUFFIX = "pr-assist_byStynee"
COMPLAINT_STATUS_VALUES_SQL = "'draft', 'pending', 'issued', 'claimed', 'completed', 'cancelled'"
WORKFLOW_STATUS_VALUES_SQL = "'draft', 'pending', 'issued'"


def _permission_catalog() -> set[str]:
    return set(get_permission_catalog())


def _default_role_permissions() -> dict[str, dict[str, bool]]:
    return get_default_role_permissions()


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




class DatabaseCore:
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


__all__ = [
    'asyncio',
    'hashlib',
    'json',
    'time',
    'date',
    'datetime',
    'timedelta',
    'timezone',
    'Any',
    'Dict',
    'List',
    'Optional',
    'Set',
    'aiomysql',
    'Config',
    'SITE_SETTINGS_REQUIRED_PERMISSIONS',
    'STAFF_ROLES',
    'build_dense_permission_map',
    'build_dense_service_permission_map',
    'get_default_role_permissions',
    'get_permission_catalog',
    'normalize_permission_flags',
    'SPEC_SESSION_END_REASONS',
    'SPEC_SESSION_END_REASON_VALUES_SQL',
    'SPEC_SESSION_END_REASON_UNKNOWN',
    'SPEC_SESSION_END_REASON_ADMIN_CLOSED',
    'BROKER_OUTBOX_STATUS_PENDING',
    'BROKER_OUTBOX_STATUS_PROCESSING',
    'BROKER_OUTBOX_STATUS_SENT',
    'SANCTIONS_GLOBAL_LOCK_NAME',
    'SANCTIONS_NIGHTLY_STALE_SECONDS',
    'CURRENT_SANCTION_POLICY_MONTH',
    'FIXED_SIZE_SANCTION_KINDS',
    'WARNING_SANCTION_KINDS',
    'MSK',
    'WEEKLY_DAY_STATUS_VALUES',
    'WEEKLY_MANUAL_STATUSES',
    'LEAVE_MANUAL_STATUSES',
    'WEEKLY_MANUAL_STATUS_NONE',
    'WEEKLY_SUGGESTED_RESULT_ULTRA',
    'WEEKLY_SUGGESTED_RESULT_ACTIVE',
    'WEEKLY_SUGGESTED_RESULT_MIXED',
    'WEEKLY_SUGGESTED_RESULT_INACTIVE',
    'WEEKLY_SUGGESTED_RESULT_OPTIONS',
    'WEEKLY_SUGGESTED_RESULTS',
    'WEEKLY_SELECTED_RESULT_OPTIONS',
    'WEEKLY_SELECTED_RESULTS',
    'WEEKLY_RESULT_ALIASES',
    'WEEKLY_PAYOUT_TYPES',
    'WEEKLY_PAYOUT_ISSUE_STATUS_PENDING',
    'WEEKLY_PAYOUT_ISSUE_STATUS_ISSUED',
    'WEEKLY_PAYOUT_ISSUE_STATUS_OPTIONS',
    'WEEKLY_PAYOUT_ISSUE_STATUSES',
    'WEEKLY_PAYOUT_TYPE_COMMANDS',
    'WEEKLY_PAYOUT_ROLE_GROUPS',
    'WEEKLY_PAYOUT_AMOUNT_RULES',
    'WEEKLY_PAYOUT_SUFFIX',
    'COMPLAINT_STATUS_VALUES_SQL',
    'WORKFLOW_STATUS_VALUES_SQL',
    '_permission_catalog',
    '_default_role_permissions',
    '_msk_now',
    '_msk_today',
    '_week_start_msk',
    '_week_dates',
    '_month_start',
    '_date_only',
    '_canonical_weekly_result',
    '_canonical_weekly_payout_issue_status',
    '_weekly_role_group',
    '_sum_numeric',
    'db_retry',
    'DatabaseCore',
]
