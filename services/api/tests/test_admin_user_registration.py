from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.anyio


def user_payload(
    *,
    username: str,
    nickname: str = "Test User",
    role: str = "employee",
    discord_id: int = 1001,
    appointed_at: str | None = None,
) -> dict:
    payload = {
        "username": username,
        "nickname": nickname,
        "role": role,
        "discord_id": discord_id,
    }
    if appointed_at is not None:
        payload["appointed_at"] = appointed_at
    return payload


async def post_create_user(app, payload: dict):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post("/api/admin/users", json=payload)


@pytest.mark.parametrize(
    ("role", "expected_status"),
    [
        ("junior_employee", 200),
        ("employee", 200),
        ("senior_employee", 200),
        ("manager", 403),
        ("developer", 403),
    ],
)
async def test_manager_hierarchy_rules(app, fake_db, set_current_user, role, expected_status):
    set_current_user(
        role="manager", permissions={"admin.users.create": True}, nickname="Manager"
    )
    payload = user_payload(
        username=f"user_{role}",
        nickname=f"Nick {role}",
        role=role,
        discord_id=1100 + hash(role) % 10000,
    )

    response = await post_create_user(app, payload)

    assert response.status_code == expected_status
    if expected_status == 200:
        body = response.json()
        assert body["data"]["username"] == payload["username"]
        assert body["data"]["nickname"] == payload["nickname"]
        assert body["data"]["role"] == payload["role"]
        assert "password" in body["data"]
        assert len(fake_db.logged_actions) == 1
    else:
        assert "detail" in response.json()


async def test_developer_can_create_all_roles(app, set_current_user):
    set_current_user(
        role="developer", permissions={"admin.users.create": True}, nickname="Dev"
    )

    all_roles = [
        "junior_employee",
        "employee",
        "senior_employee",
        "manager",
        "developer",
    ]

    for idx, role in enumerate(all_roles):
        payload = user_payload(
            username=f"dev_created_{role}",
            nickname=f"Dev {role}",
            role=role,
            discord_id=2000 + idx,
        )
        response = await post_create_user(app, payload)
        assert response.status_code == 200
        assert response.json()["data"]["role"] == role


async def test_user_without_register_permission_gets_403(app, set_current_user):
    set_current_user(
        role="manager", permissions={"admin.users.create": False}, nickname="NoPerm"
    )

    payload = user_payload(username="blocked_user", role="employee", discord_id=3001)
    response = await post_create_user(app, payload)

    assert response.status_code == 403
    assert "admin.users.create" in response.json()["detail"]


async def test_non_admin_role_cannot_access_admin_users_endpoint(app, set_current_user):
    set_current_user(
        role="employee", permissions={}, nickname="Employee"
    )
    payload = user_payload(username="blocked_by_role", role="employee", discord_id=3002)
    response = await post_create_user(app, payload)

    assert response.status_code == 403
    assert "admin.users.create" in response.json()["detail"]


async def test_duplicate_username_returns_400(app, fake_db, set_current_user):
    set_current_user(role="manager", permissions={"admin.users.create": True})
    fake_db.users_by_username["existing_login"] = {
        "id": 10,
        "discord_id": 5001,
        "username": "existing_login",
    }

    payload = user_payload(
        username="existing_login", role="employee", discord_id=5002
    )
    response = await post_create_user(app, payload)

    assert response.status_code == 400
    assert "уже существует" in response.json()["detail"]


async def test_duplicate_discord_id_in_web_auth_returns_400(app, fake_db, set_current_user):
    set_current_user(role="manager", permissions={"admin.users.create": True})
    fake_db.users_by_discord[777001] = {
        "id": 10,
        "discord_id": 777001,
        "username": "existing_discord",
    }

    payload = user_payload(
        username="new_login", role="employee", discord_id=777001
    )
    response = await post_create_user(app, payload)

    assert response.status_code == 400
    assert "Discord ID 777001" in response.json()["detail"]


async def test_duplicate_discord_id_in_assistants_returns_400(
    app, fake_db, set_current_user
):
    set_current_user(role="manager", permissions={"admin.users.create": True})
    fake_db.assistants_by_id[888001] = {
        "pr_id": 888001,
        "nickname": "Existing Assistant",
        "role": "employee",
    }

    payload = user_payload(
        username="assistant_dupe", role="employee", discord_id=888001
    )
    response = await post_create_user(app, payload)

    assert response.status_code == 400
    assert "Сотрудник с ID 888001 уже существует" == response.json()["detail"]


async def test_db_duplicate_race_is_mapped_to_400(app, fake_db, set_current_user):
    set_current_user(role="manager", permissions={"admin.users.create": True})
    fake_db.raise_on_create_user = Exception(
        "Duplicate entry '9001' for key 'web_auth.discord_id'"
    )

    payload = user_payload(username="race_user", role="employee", discord_id=9001)
    response = await post_create_user(app, payload)

    assert response.status_code == 400
    assert "Discord ID 9001" in response.json()["detail"]


async def test_success_case_writes_admin_log(app, fake_db, set_current_user):
    set_current_user(
        role="manager", permissions={"admin.users.create": True}, nickname="Boss"
    )
    payload = user_payload(
        username="successful_user",
        nickname="Successful User",
        role="employee",
        discord_id=9101,
    )

    response = await post_create_user(app, payload)
    assert response.status_code == 200

    body = response.json()
    assert body["data"]["username"] == "successful_user"
    assert body["data"]["nickname"] == "Successful User"
    assert body["data"]["role"] == "employee"
    assert "password" in body["data"]

    assert len(fake_db.logged_actions) == 1
    assert fake_db.logged_actions[0]["action"] == "user.create"


async def test_create_user_with_appointed_at(
    app, fake_db, set_current_user
):
    set_current_user(
        role="manager", permissions={"admin.users.create": True}, nickname="Boss"
    )
    response = await post_create_user(
        app,
        user_payload(
            username="appointed_user",
            nickname="Appointed User",
            role="employee",
            discord_id=9201,
            appointed_at="2026-01-05",
        ),
    )

    assert response.status_code == 200
    created = fake_db.assistants_by_id[9201]
    assert created["appointed_at"].strftime("%Y-%m-%d") == "2026-01-05"
    assert len(fake_db.logged_actions) == 1
    payload = fake_db.logged_actions[0].get("details", {}).get("payload", {})
    assert payload.get("appointed_at") == "2026-01-05"
