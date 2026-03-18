from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone

import pytest

from database import Database


def test_database_exposes_get_assistant_logs_coroutine() -> None:
    method = getattr(Database, "get_assistant_logs", None)

    assert method is not None
    assert inspect.iscoroutinefunction(method)


def test_plan_service_principal_token_hash_dedup_prefers_configured_keeper() -> None:
    rows = [
        {"name": "legacy_alpha", "token_hash": "hash_dup", "is_active": 1},
        {"name": "discord_service", "token_hash": "hash_dup", "is_active": 1},
        {"name": "legacy_beta", "token_hash": "hash_dup", "is_active": 1},
        {"name": "twitch_service", "token_hash": "hash_ok", "is_active": 1},
    ]

    updates, conflict_groups = Database._plan_service_principal_token_hash_dedup(
        rows,
        {"discord_service", "twitch_service"},
    )

    assert conflict_groups == 1
    assert {item["name"] for item in updates} == {"legacy_alpha", "legacy_beta"}
    assert all(item["old_hash"] == "hash_dup" for item in updates)
    assert all(item["new_hash"] != "hash_dup" for item in updates)
    assert len({item["new_hash"] for item in updates}) == len(updates)


def test_plan_service_principal_token_hash_dedup_falls_back_to_lexicographic_keeper() -> None:
    rows = [
        {"name": "zeta", "token_hash": "hash_dup", "is_active": 1},
        {"name": "alpha", "token_hash": "hash_dup", "is_active": 1},
    ]

    updates, conflict_groups = Database._plan_service_principal_token_hash_dedup(
        rows,
        set(),
    )

    assert conflict_groups == 1
    assert len(updates) == 1
    assert updates[0]["name"] == "zeta"
    assert updates[0]["old_hash"] == "hash_dup"
    assert updates[0]["new_hash"] != "hash_dup"


class _DummyLogger:
    def debug(self, *_args, **_kwargs) -> None:
        pass

    def info(self, *_args, **_kwargs) -> None:
        pass

    def warning(self, *_args, **_kwargs) -> None:
        pass

    def error(self, *_args, **_kwargs) -> None:
        pass


class _DummyCursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple | None]] = []
        self.lastrowid = 0
        self._fetchone_result = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, sql: str, params: tuple | None = None) -> None:
        self.executed.append((sql, params))

    async def fetchone(self):
        return self._fetchone_result


class _DummyConn:
    def __init__(self, cursor: _DummyCursor) -> None:
        self._cursor = cursor
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def cursor(self) -> _DummyCursor:
        return self._cursor

    async def commit(self) -> None:
        self.committed = True


class _DummyAcquire:
    def __init__(self, conn: _DummyConn) -> None:
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _DummyPool:
    def __init__(self, conn: _DummyConn) -> None:
        self._conn = conn

    def acquire(self) -> _DummyAcquire:
        return _DummyAcquire(self._conn)


@pytest.mark.anyio
async def test_create_user_returns_discord_id_pk_contract() -> None:
    cursor = _DummyCursor()
    conn = _DummyConn(cursor)
    db = Database(
        db_host="localhost",
        db_port=3306,
        db_user="root",
        db_password="root",
        db_name="test",
        logger=_DummyLogger(),
    )
    db.pool = _DummyPool(conn)

    result = await db.create_user(
        discord_id=123456789,
        username="contract_user",
        password_hash="hashed",
    )

    assert result == 123456789
    assert conn.committed is True
    assert cursor.executed
    _, params = cursor.executed[0]
    assert params == (123456789, "contract_user", "hashed")


@pytest.mark.anyio
async def test_get_service_principal_by_token_uses_hash_only_lookup() -> None:
    cursor = _DummyCursor()
    conn = _DummyConn(cursor)
    db = Database(
        db_host="localhost",
        db_port=3306,
        db_user="root",
        db_password="root",
        db_name="test",
        logger=_DummyLogger(),
    )
    db.pool = _DummyPool(conn)

    token = "discord-service-token"
    expected_hash = Database._hash_service_token(token)
    cursor._fetchone_result = {
        "name": "discord_service",
        "permissions": {"streamers.view": True},
        "is_active": 1,
    }

    principal = await db.get_service_principal_by_token(token)

    assert principal is not None
    assert principal["principal_type"] == "service"
    assert principal["service_name"] == "discord_service"
    assert principal["permissions"]["streamers.view"] is True
    assert cursor.executed
    _, params = cursor.executed[0]
    assert params == (expected_hash,)


@pytest.mark.anyio
async def test_create_manual_spec_session_uses_admin_closed_end_reason() -> None:
    cursor = _DummyCursor()
    cursor.lastrowid = 77
    conn = _DummyConn(cursor)
    db = Database(
        db_host="localhost",
        db_port=3306,
        db_user="root",
        db_password="root",
        db_name="test",
        logger=_DummyLogger(),
    )
    db.pool = _DummyPool(conn)

    async def _get_points_config():
        return {0: 0.5, 1: 1.0, 2: 1.5, 3: 2.0}

    async def _get_probation_rate():
        return 0.25

    async def _recalc_session_points_delta(_conn, _session_id: int, lock: bool = True):
        return None

    async def _recalculate_assistant_sanction_derivations(**_kwargs):
        return None

    db.get_points_config = _get_points_config
    db._get_probation_rate = _get_probation_rate
    db._recalc_session_points_delta = _recalc_session_points_delta
    db.recalculate_assistant_sanction_derivations = (
        _recalculate_assistant_sanction_derivations
    )

    started_at = datetime.now(timezone.utc) + timedelta(days=1)
    ended_at = started_at + timedelta(hours=1)

    created = await db.create_manual_spec_session(
        pr_id=566652404838170625,
        target_type="streamer",
        target_id=5001,
        started_at=started_at,
        ended_at=ended_at,
        is_probation=False,
        priority=2,
        target_name="StreamerY",
    )

    assert created is True
    assert conn.committed is True
    assert len(cursor.executed) >= 2
    insert_sql, insert_params = cursor.executed[1]
    assert "INSERT INTO spec_sessions" in insert_sql
    assert insert_params is not None
    assert insert_params[6] == "admin_closed"


@pytest.mark.anyio
async def test_create_event_stages_outbox_message_before_commit() -> None:
    cursor = _DummyCursor()
    cursor.lastrowid = 501
    conn = _DummyConn(cursor)
    db = Database(
        db_host="localhost",
        db_port=3306,
        db_user="root",
        db_password="root",
        db_name="test",
        logger=_DummyLogger(),
    )
    db.pool = _DummyPool(conn)

    event_id = await db.create_event(
        name="Outbox Event",
        description="event with outbox",
        created_by=42,
        outbox_trace_id="trace-123",
    )

    assert event_id == 501
    assert conn.committed is True
    assert len(cursor.executed) >= 2
    insert_sqls = [sql for sql, _params in cursor.executed]
    assert any("INSERT INTO events" in sql for sql in insert_sqls)
    assert any("INSERT INTO broker_outbox" in sql for sql in insert_sqls)
