from __future__ import annotations

import inspect
import json
from datetime import datetime, timedelta, timezone

import pytest

from db import Database
from services.rbac import build_dense_service_permission_map, get_default_role_permissions


def test_database_exposes_get_assistant_logs_coroutine() -> None:
    method = getattr(Database, "get_assistant_logs", None)

    assert method is not None
    assert inspect.iscoroutinefunction(method)


def test_database_exposes_batch_workoff_reader_helper() -> None:
    method = getattr(Database, "_get_batch_workoff_items_locked", None)

    assert method is not None
    assert inspect.iscoroutinefunction(method)


@pytest.mark.parametrize(
    "helper_name",
    (
        "_enqueue_outbox_messages_with_cursor",
        "_ensure_monthly_policy_row",
        "_get_day_manual_status_locked",
        "_get_day_spec_metrics_locked",
        "_get_points_config",
        "_get_probation_rate",
    ),
)
def test_database_exposes_cross_mixin_helper_coroutines(helper_name: str) -> None:
    method = getattr(Database, helper_name, None)

    assert method is not None
    assert inspect.iscoroutinefunction(method)


def test_database_normalize_manual_status_uses_canonical_weekly_rules() -> None:
    assert Database._normalize_manual_status(None) is None
    assert Database._normalize_manual_status(" none ") is None
    assert Database._normalize_manual_status("u") == "U"
    assert Database._normalize_manual_status("invalid") is None


def test_default_role_permissions_match_canonical_admin_bundles() -> None:
    permissions = get_default_role_permissions()

    junior = permissions["junior_employee"]
    assert junior["dashboard.view"] is True
    assert junior["assistants.view"] is True
    assert junior["assistants.logs.view"] is True
    assert junior["logs.assistant_actions.view"] is True
    assert junior["returns.process"] is True
    assert junior["complaints.issue"] is True
    assert junior["removals.issue"] is True
    assert junior["spec.claim.probation"] is True
    assert junior["admin.panel.view"] is False

    employee = permissions["employee"]
    assert employee["assistants.view"] is True
    assert employee["assistants.logs.view"] is True
    assert employee["logs.assistant_actions.view"] is True
    assert employee["returns.process"] is True
    assert employee["complaints.issue"] is True
    assert employee["removals.issue"] is True
    assert employee["spec.claim.probation"] is False
    assert employee["admin.panel.view"] is False

    senior = permissions["senior_employee"]
    assert senior["admin.panel.view"] is True
    assert senior["events.create"] is True
    assert senior["assistants.view"] is True
    assert senior["assistants.logs.view"] is True
    assert senior["logs.assistant_actions.view"] is True
    assert senior["returns.process"] is True
    assert senior["complaints.issue"] is True
    assert senior["removals.issue"] is True
    assert senior["admin.users.create"] is False
    assert senior["rbac.view"] is False
    assert senior["site.maintenance.view"] is False

    manager = permissions["manager"]
    assert manager["admin.panel.view"] is True
    assert manager["admin.users.create"] is True
    assert manager["admin.users.role.update"] is True
    assert manager["admin.users.deactivate"] is True
    assert manager["assistants.sessions.manage"] is True
    assert manager["rbac.view"] is False
    assert manager["site.maintenance.view"] is False
    assert manager["maintenance.bypass"] is True
    assert manager["monitoring.view"] is False
    assert manager["media.status.update"] is False
    assert manager["notifications.render"] is False

    developer = permissions["developer"]
    assert developer["admin.panel.view"] is True
    assert developer["rbac.view"] is True
    assert developer["rbac.update"] is True
    assert developer["site.maintenance.view"] is True
    assert developer["site.maintenance.update"] is True
    assert developer["maintenance.bypass"] is True
    assert developer["monitoring.view"] is True
    assert developer["media.status.update"] is True
    assert developer["notifications.render"] is True


def test_default_service_permissions_match_built_in_service_scopes() -> None:
    discord_scope = Database._get_default_service_permissions("discord_service")
    assert {
        permission for permission, enabled in discord_scope.items() if enabled
    } == {
        "dashboard.view",
        "media.create",
        "media.update",
        "media.delete",
        "media.status.update",
        "spec.sessions.self.view",
        "spec.claim.main",
        "spec.claim.probation",
        "spec.unclaim.any",
        "assistants.view",
        "assistants.sessions.manage",
        "events.create",
        "events.runtime.manage",
        "events.participation.any.leave",
        "game_servers.view",
        "game_servers.settings.update",
        "game_servers.templates.update",
        "game_servers.rates.update",
        "monitoring.view",
        "notifications.render",
    }

    twitch_scope = Database._get_default_service_permissions("twitch_service")
    assert {
        permission for permission, enabled in twitch_scope.items() if enabled
    } == {
        "media.create",
        "media.status.update",
        "spec.unclaim.any",
    }


def test_dense_service_permissions_do_not_leak_admin_panel_view() -> None:
    permissions = build_dense_service_permission_map(
        {
            "assistants.sessions.manage": True,
            "monitoring.view": True,
            "game_servers.settings.update": True,
        }
    )

    assert permissions["assistants.sessions.view"] is True
    assert permissions["assistants.view"] is True
    assert permissions["game_servers.settings.view"] is True
    assert permissions["game_servers.view"] is True
    assert permissions["admin.panel.view"] is False


@pytest.mark.anyio
async def test_init_default_service_principals_reconciles_builtin_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    monkeypatch.setattr(
        db,
        "_configured_service_tokens",
        lambda: [("discord_service", "discord-service-token")],
    )

    async def _column_exists(*_args, **_kwargs) -> bool:
        return True

    async def _noop(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(db, "_column_exists", _column_exists)
    monkeypatch.setattr(db, "_migrate_service_principals_hash_only", _noop)

    await db._init_default_service_principals(conn)

    insert_sql, params = next(
        (sql, params)
        for sql, params in cursor.executed
        if "INSERT INTO service_principals" in sql
    )
    assert insert_sql
    assert params is not None

    reconciled = json.loads(params[2])
    assert reconciled["dashboard.view"] is True
    assert reconciled["media.status.update"] is True
    assert reconciled["assistants.logs.view"] is False
    assert reconciled["events.spec_requests.review"] is False
    assert reconciled["admin.panel.view"] is False


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
        self.rowcount = 0
        self._fetchone_result = None
        self._fetchall_result = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, sql: str, params: tuple | None = None) -> None:
        self.executed.append((sql, params))

    async def fetchone(self):
        return self._fetchone_result

    async def fetchall(self):
        return self._fetchall_result


class _DummyConn:
    def __init__(self, cursor: _DummyCursor) -> None:
        self._cursor = cursor
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def cursor(self, *_args, **_kwargs) -> _DummyCursor:
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
        "permissions": {"media.view": True},
        "is_active": 1,
    }

    principal = await db.get_service_principal_by_token(token)

    assert principal is not None
    assert principal["principal_type"] == "service"
    assert principal["service_name"] == "discord_service"
    assert principal["permissions"]["media.view"] is True
    assert cursor.executed
    _, params = cursor.executed[0]
    assert params == (expected_hash,)


@pytest.mark.anyio
async def test_list_pending_outbox_messages_parses_payload_with_dict_cursor() -> None:
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
    cursor._fetchall_result = [
        {
            "id": 1,
            "routing_key": "test.key",
            "payload": '{"value": 1}',
            "attempts": 0,
            "created_at": "2026-03-22T00:00:00",
        }
    ]

    messages = await db.list_pending_outbox_messages(limit=5)

    assert len(messages) == 1
    assert messages[0]["payload"] == {"value": 1}
    assert cursor.executed
    _, params = cursor.executed[0]
    assert params == (5,)


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

    db._get_points_config = _get_points_config
    db._get_probation_rate = _get_probation_rate
    db._recalc_session_points_delta = _recalc_session_points_delta
    db._recalculate_assistant_sanction_derivations = (
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


@pytest.mark.anyio
async def test_update_punishment_return_returns_existing_record_on_noop_update() -> None:
    cursor = _DummyCursor()
    cursor.rowcount = 0
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

    expected = {
        "id": 15,
        "punishment_type": "mute",
        "static": 27253,
        "server": 14,
        "duration": 60,
        "remove_reason": "На видео",
        "discord_message_url": None,
        "removed_by_id": 1001,
        "removed_by_name": "Creator",
        "removed_at": datetime.now(timezone.utc),
        "claimed_by_id": None,
        "claimed_by_name": None,
        "claimed_at": None,
        "completed_by_id": None,
        "completed_by_name": None,
        "completed_at": None,
        "status": "pending",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }

    async def _get_punishment_return(return_id: int):
        if int(return_id) == 15:
            return expected
        return None

    db.get_punishment_return = _get_punishment_return  # type: ignore[method-assign]

    result = await db.update_punishment_return(15, {"duration": 60})

    assert result == expected
    assert conn.committed is True
    assert cursor.executed
    assert "UPDATE punishment_returns" in cursor.executed[0][0]
