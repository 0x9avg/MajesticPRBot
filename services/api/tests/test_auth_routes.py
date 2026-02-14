from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from routes.auth import router as auth_router

pytestmark = pytest.mark.anyio


def _seed_auth_user(
    fake_db, username: str, password_hash: str = "hashed::secret"
) -> None:
    user = {
        "id": 1,
        "discord_id": 1001,
        "username": username,
        "password_hash": password_hash,
        "is_active": True,
        "require_password_change": False,
        "failed_login_attempts": 0,
        "last_failed_login": None,
        "last_login": None,
        "created_at": datetime.now(timezone.utc),
        "role": "manager",
        "nickname": "Manager",
        "permissions": {"can_register_users": True},
    }
    fake_db.users_by_username[username] = user
    fake_db.users_by_id[user["id"]] = user
    fake_db.users_by_discord[user["discord_id"]] = user


async def _client(build_api_app):
    app = build_api_app(auth_router)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_login_success(build_api_app, fake_db) -> None:
    _seed_auth_user(fake_db, "manager")

    async with await _client(build_api_app) as auth_client:
        response = await auth_client.post(
            "/api/auth/login",
            json={"username": "manager", "password": "secret"},
            headers={"User-Agent": "pytest-agent"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["access_token"].startswith("access-")
    assert payload["refresh_token"].startswith("refresh-")
    assert len(fake_db.sessions) == 1
    assert any(log["action"] == "login_success" for log in fake_db.auth_logs)


async def test_login_invalid_credentials(build_api_app, fake_db) -> None:
    _seed_auth_user(fake_db, "manager")

    async with await _client(build_api_app) as auth_client:
        response = await auth_client.post(
            "/api/auth/login",
            json={"username": "manager", "password": "wrong"},
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "Неверный логин или пароль"
    assert any(log["action"] == "login_failed" for log in fake_db.auth_logs)


async def test_login_rate_limited_when_locked(build_api_app, fake_db) -> None:
    from config import Config

    _seed_auth_user(fake_db, "locked")
    fake_db.users_by_username["locked"][
        "failed_login_attempts"
    ] = Config.max_login_attempts
    fake_db.users_by_username["locked"]["last_failed_login"] = datetime.now(timezone.utc)

    async with await _client(build_api_app) as auth_client:
        response = await auth_client.post(
            "/api/auth/login",
            json={"username": "locked", "password": "secret"},
        )

    assert response.status_code == 429
    assert "Слишком много попыток входа" in response.json()["detail"]


async def test_logout_returns_success_even_on_invalid_token(build_api_app) -> None:
    async with await _client(build_api_app) as auth_client:
        response = await auth_client.post(
            "/api/auth/logout",
            headers={"Authorization": "Bearer invalid"},
        )

    assert response.status_code == 200
    assert response.json()["message"] == "Выход выполнен успешно"


async def test_logout_revokes_sessions_on_valid_token(build_api_app, fake_db) -> None:
    fake_db.sessions.extend(
        [
            {"id": 1, "user_id": 1, "revoked": False},
            {"id": 2, "user_id": 2, "revoked": False},
        ]
    )

    async with await _client(build_api_app) as auth_client:
        response = await auth_client.post(
            "/api/auth/logout",
            headers={"Authorization": "Bearer valid-token"},
        )

    assert response.status_code == 200
    assert response.json()["message"] == "Выход выполнен успешно"
    assert fake_db.sessions[0]["revoked"] is True
    assert fake_db.sessions[1]["revoked"] is False
    assert any(log["action"] == "logout" for log in fake_db.auth_logs)


async def test_me_returns_current_user_info(build_api_app) -> None:
    async with await _client(build_api_app) as auth_client:
        response = await auth_client.get("/api/auth/me")

    assert response.status_code == 200
    payload = response.json()
    assert payload["username"] == "creator"
    assert payload["permissions"]["can_register_users"] is True
