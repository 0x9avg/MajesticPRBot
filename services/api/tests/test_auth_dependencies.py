from __future__ import annotations

from datetime import datetime, timedelta, timezone

import dependencies
import pytest
from fastapi import Depends, FastAPI, Request
from httpx import ASGITransport, AsyncClient
from jose import jwt


pytestmark = pytest.mark.anyio


class _AuthAlwaysNone:
    secret_key = "test-secret"
    algorithm = "HS256"

    def verify_access_token(self, token: str):
        return None


class _AuthAccepting:
    secret_key = "test-secret"
    algorithm = "HS256"

    def verify_access_token(self, token: str):
        if token != "good-access":
            return None
        return {
            "type": "access",
            "user_id": 1001,
            "username": "tester",
            "role": "employee",
            "sid": 1,
        }


class _DBStub:
    def __init__(
        self,
        *,
        site_maintenance_enabled: bool = False,
        user_permissions: dict[str, bool] | None = None,
        service_principal: dict | None = None,
    ) -> None:
        self.site_maintenance_enabled = site_maintenance_enabled
        self.user_permissions = user_permissions or {"media.view": True}
        self.service_principal = service_principal

    async def is_session_active(self, user_id: int, session_id: int) -> bool:
        return True

    async def get_user_by_id(self, user_id: int):
        return {
            "discord_id": user_id,
            "username": f"user-{user_id}",
            "nickname": "User",
            "role": "employee",
            "permissions": dict(self.user_permissions),
            "require_password_change": False,
            "is_active": True,
        }

    async def get_service_principal_by_token(self, token: str):
        if token == "svc-token":
            return self.service_principal
        return None

    async def is_site_maintenance_enabled(self) -> bool:
        return bool(self.site_maintenance_enabled)


def _build_app(db: _DBStub | None = None, auth: object | None = None) -> FastAPI:
    app = FastAPI()
    app.state.database = db or _DBStub()
    app.state.auth = auth or _AuthAlwaysNone()

    async def _override_db(request: Request):
        return request.app.state.database

    async def _override_auth(request: Request):
        return request.app.state.auth

    app.dependency_overrides[dependencies.get_db] = _override_db
    app.dependency_overrides[dependencies.get_auth] = _override_auth

    @app.get("/probe-user")
    async def probe_user(_user: dict = Depends(dependencies.get_current_user)):
        return {"ok": True}

    @app.get("/probe-principal")
    async def probe_principal(_principal: dict = Depends(dependencies.get_current_principal)):
        return {"ok": True}

    return app


def _expired_access_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "type": "access",
        "user_id": 1001,
        "username": "tester",
        "role": "employee",
        "sid": 1,
        "exp": now - timedelta(minutes=5),
    }
    return jwt.encode(payload, _AuthAlwaysNone.secret_key, algorithm=_AuthAlwaysNone.algorithm)


@pytest.mark.parametrize("path", ["/probe-user", "/probe-principal"])
async def test_expired_access_returns_token_expired(path: str) -> None:
    app = _build_app()
    token = _expired_access_token()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(path, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "TOKEN_EXPIRED"


@pytest.mark.parametrize("path", ["/probe-user", "/probe-principal"])
async def test_invalid_access_returns_token_invalid(path: str) -> None:
    app = _build_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(path, headers={"Authorization": "Bearer not-a-jwt"})

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "TOKEN_INVALID"


@pytest.mark.parametrize("path", ["/probe-user", "/probe-principal"])
async def test_site_maintenance_blocks_human_user_dependencies(path: str) -> None:
    app = _build_app(
        db=_DBStub(site_maintenance_enabled=True),
        auth=_AuthAccepting(),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(path, headers={"Authorization": "Bearer good-access"})

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "SITE_MAINTENANCE"


async def test_site_maintenance_allows_bypass_user_dependencies() -> None:
    app = _build_app(
        db=_DBStub(
            site_maintenance_enabled=True,
            user_permissions={
                "media.view": True,
                "maintenance.bypass": True,
            },
        ),
        auth=_AuthAccepting(),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/probe-principal",
            headers={"Authorization": "Bearer good-access"},
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}


async def test_site_maintenance_does_not_block_service_principal() -> None:
    app = _build_app(
        db=_DBStub(
            site_maintenance_enabled=True,
            service_principal={
                "principal_type": "service",
                "service_name": "discord_service",
                "permissions": {"media.view": True},
            },
        ),
        auth=_AuthAccepting(),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/probe-principal",
            headers={"Authorization": "Bearer svc-token"},
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}


async def test_inactive_user_is_rejected_even_with_active_session() -> None:
    class _InactiveDB(_DBStub):
        async def get_user_by_id(self, user_id: int):
            payload = await super().get_user_by_id(user_id)
            payload["is_active"] = False
            return payload

    app = _build_app(db=_InactiveDB(), auth=_AuthAccepting())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/probe-user",
            headers={"Authorization": "Bearer good-access"},
        )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "SESSION_REVOKED"
