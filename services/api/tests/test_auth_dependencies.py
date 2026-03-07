from __future__ import annotations

from datetime import datetime, timedelta, timezone

import dependencies
import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from jose import jwt


pytestmark = pytest.mark.anyio


class _AuthAlwaysNone:
    secret_key = "test-secret"
    algorithm = "HS256"

    def verify_access_token(self, token: str):
        return None


class _DBStub:
    async def is_session_active(self, user_id: int, session_id: int) -> bool:
        return True

    async def get_user_by_id(self, user_id: int):
        return {
            "discord_id": user_id,
            "username": f"user-{user_id}",
            "nickname": "User",
            "role": "employee",
            "permissions": {"streamers.view": True},
            "require_password_change": False,
        }

    async def get_service_principal_by_token(self, token: str):
        return None


def _build_app() -> FastAPI:
    app = FastAPI()
    app.state.database = _DBStub()
    app.state.auth = _AuthAlwaysNone()

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
