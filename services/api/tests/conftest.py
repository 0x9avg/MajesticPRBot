from __future__ import annotations

import sys
import time
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from services.rbac import (
    STAFF_ROLES,
    build_dense_permission_map,
    get_default_role_permissions,
    get_permission_catalog,
)

@pytest.fixture
def anyio_backend():
    return "asyncio"

import dependencies  # noqa: E402
from routes.admin import router as admin_router  # noqa: E402
from tests.fakes.db import FakeDB
MSK = timezone(timedelta(hours=3))
FIXED_SIZE_SANCTION_KINDS = {"check", "oral", "strict"}
WARNING_SANCTION_KINDS = {"oral", "strict"}


def _default_sanction_policy() -> dict[str, Any]:
    return {
        "check_cycle_size": 5,
        "check_immunity_hours_per_day": 0.0,
        "point_immunity_hours_per_day": 0.0,
        "percent_immunity_hours_per_day": 0.0,
        "check_relief_hours_per_day": 0.0,
        "point_relief_hours_per_day": 0.0,
        "percent_relief_hours_per_day": 0.0,
        "check_relief_min_streak_days": 1,
        "point_relief_min_streak_days": 1,
        "percent_relief_min_streak_days": 1,
        "percent_relief_step_amount": 1.0,
        "daily_norm_spec": 0.0,
        "daily_norm_complaints": 0,
        "daily_norm_mchat": 0,
    }


def _default_check_rules() -> list[dict[str, Any]]:
    return [
        {"cycle_from": 1, "cycle_to": 2, "sanction_kind": "point", "sanction_amount": 1.0},
        {"cycle_from": 3, "cycle_to": 3, "sanction_kind": "point", "sanction_amount": 2.0},
        {"cycle_from": 4, "cycle_to": 5, "sanction_kind": "percent", "sanction_amount": 3.0},
        {"cycle_from": 6, "cycle_to": 6, "sanction_kind": "percent", "sanction_amount": 5.0},
        {"cycle_from": 7, "cycle_to": 7, "sanction_kind": "oral", "sanction_amount": 1.0},
        {"cycle_from": 8, "cycle_to": None, "sanction_kind": "strict", "sanction_amount": 1.0},
    ]


def _week_start(value: date) -> date:
    return value - timedelta(days=value.weekday())


def _canonical_weekly_result(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if normalized == "Ультра-актив":
        return "Ультра-Актив"
    return normalized


def _default_weekly_payout_type_rules() -> dict[str, str]:
    return {
        "EXP": "giveexp",
        "Premium": "setvip",
        "MC": "givedonate",
        "MONEY": "givemoney",
    }


def _default_weekly_payout_amount_rules() -> dict[tuple[str, str, str], str]:
    return {
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


class _DummyLogger:
    def debug(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    def info(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    def warning(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    def error(self, *_args: Any, **_kwargs: Any) -> None:
        pass


class FakeBroker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.logger = _DummyLogger()

    async def publish(self, event: str, payload: dict[str, Any]) -> None:
        self.calls.append((event, payload))

    async def emit_streamer_added(
        self, streamer_id: int, streamer_name: str, meta: dict[str, Any], trace_id: str
    ) -> None:
        self.calls.append(
            (
                "streamer.added",
                {
                    "streamer_id": streamer_id,
                    "streamer_name": streamer_name,
                    "meta": meta,
                    "trace_id": trace_id,
                },
            )
        )

    async def emit_streamer_verify(
        self, username: str, payload: dict[str, Any], trace_id: str
    ) -> None:
        self.calls.append(
            (
                "streamer.verify",
                {"username": username, "payload": payload, "trace_id": trace_id},
            )
        )

    async def emit_streamer_updated(
        self,
        streamer_id: int,
        streamer_name: str,
        payload: dict[str, Any],
        trace_id: str,
    ) -> None:
        self.calls.append(
            (
                "streamer.updated",
                {
                    "streamer_id": streamer_id,
                    "streamer_name": streamer_name,
                    "payload": payload,
                    "trace_id": trace_id,
                },
            )
        )

    async def emit_streamer_removed(
        self, streamer_id: int, streamer_name: str, trace_id: str
    ) -> None:
        self.calls.append(
            (
                "streamer.removed",
                {
                    "streamer_id": streamer_id,
                    "streamer_name": streamer_name,
                    "trace_id": trace_id,
                },
            )
        )

    async def emit_spec_claimed(
        self,
        streamer_id: int,
        streamer_name: str,
        pr_id: int,
        trace_id: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        self.calls.append(
            (
                "spec.claimed",
                {
                    "streamer_id": streamer_id,
                    "streamer_name": streamer_name,
                    "pr_id": pr_id,
                    "data": data or {},
                    "trace_id": trace_id,
                },
            )
        )

    async def emit_spec_unclaimed(
        self,
        streamer_id: int,
        streamer_name: str,
        pr_id: int,
        duration_seconds: int,
        reason: str,
        trace_id: str,
    ) -> None:
        self.calls.append(
            (
                "spec.unclaimed",
                {
                    "streamer_id": streamer_id,
                    "streamer_name": streamer_name,
                    "pr_id": pr_id,
                    "duration_seconds": duration_seconds,
                    "reason": reason,
                    "trace_id": trace_id,
                },
            )
        )

    async def emit_stream_online(self, **kwargs: Any) -> None:
        self.calls.append(("stream.online", kwargs))

    async def emit_stream_offline(self, **kwargs: Any) -> None:
        self.calls.append(("stream.offline", kwargs))

    async def emit_event_joined(self, **kwargs: Any) -> None:
        self.calls.append(("event.joined", kwargs))

    async def emit_event_left(self, **kwargs: Any) -> None:
        self.calls.append(("event.left", kwargs))

    async def emit_category_change(self, **kwargs: Any) -> None:
        self.calls.append(("stream.category_change", kwargs))

    async def emit_guild_settings_updated(
        self, payload: dict[str, Any], trace_id: str
    ) -> None:
        self.calls.append(
            ("guild.settings.updated", {"payload": payload, "trace_id": trace_id})
        )

    async def emit_guild_templates_updated(
        self, payload: dict[str, Any], trace_id: str
    ) -> None:
        self.calls.append(
            ("guild.templates.updated", {"payload": payload, "trace_id": trace_id})
        )

    async def emit_guild_rates_updated(
        self, payload: dict[str, Any], trace_id: str
    ) -> None:
        self.calls.append(
            ("guild.rates.updated", {"payload": payload, "trace_id": trace_id})
        )

class FakeAuth:
    secret_key = "test-secret"
    algorithm = "HS256"

    def __init__(self) -> None:
        self._refresh_counter = 0

    def hash_password(self, password: str) -> str:
        return f"hashed::{password}"

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        if hashed_password.startswith("hashed::"):
            return hashed_password == f"hashed::{plain_password}"
        return plain_password == hashed_password

    @staticmethod
    def hash_token(token: str) -> str:
        return f"hash::{token}"

    @staticmethod
    def generate_family_id() -> str:
        return "family-test"

    def create_refresh_token(self, user_id: int) -> tuple[str, str, datetime]:
        self._refresh_counter += 1
        raw = f"refresh-{user_id}-{self._refresh_counter}"
        return raw, self.hash_token(raw), datetime.now(MSK) + timedelta(days=7)

    def create_access_token(
        self,
        user_id: int,
        username: str,
        role: str,
        sid: int,
        expires_delta: Any = None,
    ) -> str:
        return f"access-{user_id}-{username}-{role}-sid{sid}"

    def verify_access_token(self, token: str) -> dict[str, Any] | None:
        if token == "invalid" or not token.startswith("access-"):
            return None
        try:
            # access-{user_id}-{username}-{role}-sid{sid}
            payload = token.replace("access-", "", 1)
            left, sid_part = payload.rsplit("-sid", 1)
            user_id_str, username, role = left.split("-", 2)
            return {
                "type": "access",
                "user_id": int(user_id_str),
                "username": username,
                "role": role,
                "sid": int(sid_part),
            }
        except Exception:
            return None

    def verify_token(self, token: str) -> dict[str, Any]:
        if token == "valid-token":
            return {
                "type": "access",
                "user_id": 1,
                "username": "tester",
                "role": "manager",
                "sid": 1,
            }
        payload = self.verify_access_token(token)
        if payload is None:
            raise ValueError("Invalid token")
        return payload

@pytest.fixture()
def fake_db() -> FakeDB:
    return FakeDB()


@pytest.fixture()
def fake_auth() -> FakeAuth:
    return FakeAuth()


@pytest.fixture()
def fake_broker() -> FakeBroker:
    return FakeBroker()


@pytest.fixture()
def default_current_user() -> dict[str, Any]:
    manager_permissions = deepcopy(get_default_role_permissions()["manager"])
    return {
        "id": 1,
        "username": "creator",
        "nickname": "Creator",
        "role": "manager",
        "principal_type": "user",
        "discord_id": 1001,
        "require_password_change": False,
        "permissions": manager_permissions,
    }


@pytest.fixture()
def build_api_app(
    fake_db: FakeDB,
    fake_auth: FakeAuth,
    fake_broker: FakeBroker,
    default_current_user: dict[str, Any],
):
    def _build_api_app(
        *routers: Any,
        include_broker: bool = True,
        current_user: dict[str, Any] | None = None,
        current_service: dict[str, Any] | None = None,
        override_auth_dependencies: bool = True,
    ) -> FastAPI:
        app = FastAPI()
        for router in routers:
            app.include_router(router, prefix="/api")

        app.state.database = fake_db
        app.state.auth = fake_auth
        app.state.broker = fake_broker if include_broker else None
        fake_db._broker = app.state.broker
        app.state._service_registry = {}
        app.state._startup_complete = True
        app.state._perf_start_time = time.perf_counter()

        app.state.test_current_user = current_user or deepcopy(default_current_user)
        app.state.test_current_service = current_service or {
            "principal_type": "service",
            "service_name": "discord_service",
            "permissions": {
                "monitoring.view": True,
                "media.status.update": True,
            },
        }

        async def _override_current_user() -> dict[str, Any]:
            return app.state.test_current_user

        async def _override_current_service() -> dict[str, Any]:
            return app.state.test_current_service

        async def _override_db(request: Request) -> FakeDB:
            return request.app.state.database

        async def _override_auth(request: Request) -> FakeAuth:
            return request.app.state.auth

        async def _override_broker(request: Request) -> FakeBroker | None:
            return request.app.state.broker

        # Use async dependency overrides to avoid anyio threadpool hangs in this env.
        if override_auth_dependencies:
            app.dependency_overrides[dependencies.get_current_user] = _override_current_user
            app.dependency_overrides[dependencies.get_current_user_allow_maintenance] = _override_current_user
            app.dependency_overrides[dependencies.get_current_principal] = _override_current_user
            app.dependency_overrides[dependencies.get_current_service] = _override_current_service
        app.dependency_overrides[dependencies.get_db] = _override_db
        app.dependency_overrides[dependencies.get_auth] = _override_auth

        # Router-local deps (get_db/get_auth/get_broker) are also sync functions.
        # Override them by name so all route groups remain testable.
        for route in app.routes:
            dependant = getattr(route, "dependant", None)
            if not dependant:
                continue
            for dep in dependant.dependencies:
                call = getattr(dep, "call", None)
                if not callable(call):
                    continue
                dep_name = getattr(call, "__name__", "")
                if dep_name == "get_db":
                    app.dependency_overrides[call] = _override_db
                elif dep_name == "get_auth":
                    app.dependency_overrides[call] = _override_auth
                elif dep_name == "get_broker":
                    app.dependency_overrides[call] = _override_broker
        return app

    return _build_api_app


@pytest.fixture()
def app(
    build_api_app,
) -> FastAPI:
    return build_api_app(admin_router)


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def set_current_user(app: FastAPI):
    def _set_current_user(**overrides: Any) -> dict[str, Any]:
        manager_permissions = deepcopy(get_default_role_permissions()["manager"])
        base_user: dict[str, Any] = {
            "id": 1,
            "username": "creator",
            "nickname": "Creator",
            "role": "manager",
            "principal_type": "user",
            "discord_id": 1001,
            "require_password_change": False,
            "permissions": manager_permissions,
        }
        base_user.update(overrides)
        app.state.test_current_user = base_user
        return base_user

    return _set_current_user
