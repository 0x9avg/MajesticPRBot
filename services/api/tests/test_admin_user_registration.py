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


async def patch_user_role(app, discord_id: int, role: str):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.patch(f"/api/admin/users/{discord_id}/role", json={"role": role})


async def post_deactivate_user(app, discord_id: int, reason: str | None = None):
    payload = {}
    if reason is not None:
        payload["reason"] = reason
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(f"/api/admin/users/{discord_id}/deactivate", json=payload)


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


async def test_developer_can_create_all_staff_roles(app, set_current_user):
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


async def test_assistant_failure_rolls_back_created_user(app, fake_db, set_current_user):
    set_current_user(
        role="manager", permissions={"admin.users.create": True}, nickname="Boss"
    )
    fake_db.raise_on_create_or_update_assistant = Exception("assistant insert failed")

    payload = user_payload(
        username="rollback_user",
        nickname="Rollback User",
        role="employee",
        discord_id=9151,
    )

    response = await post_create_user(app, payload)

    assert response.status_code == 500
    assert "rollback_user" not in fake_db.users_by_username
    assert 9151 not in fake_db.users_by_discord
    assert 9151 not in fake_db.assistants_by_id


async def test_admin_log_failure_does_not_fail_created_user(
    app, fake_db, set_current_user
):
    set_current_user(
        role="manager", permissions={"admin.users.create": True}, nickname="Boss"
    )
    fake_db.raise_on_log_admin_action = Exception("log insert failed")

    payload = user_payload(
        username="log_failure_user",
        nickname="Log Failure User",
        role="employee",
        discord_id=9152,
    )

    response = await post_create_user(app, payload)

    assert response.status_code == 200
    assert fake_db.users_by_username["log_failure_user"]["discord_id"] == 9152
    assert fake_db.assistants_by_id[9152]["role"] == "employee"
    assert fake_db.logged_actions == []


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


async def test_role_update_requires_manageable_target_role(app, fake_db, set_current_user):
    set_current_user(
        role="manager",
        permissions={"admin.users.role.update": True},
        nickname="Manager",
    )
    await fake_db.create_user_with_assistant(
        discord_id=8101,
        username="assistant_dev",
        password_hash="hash",
        nickname="Assistant Dev",
        role="developer",
    )

    response = await patch_user_role(app, 8101, "employee")

    assert response.status_code == 403
    assert "ролью выше вашей" in response.json()["detail"]


async def test_role_update_rejects_same_rank_target(app, fake_db, set_current_user):
    set_current_user(
        role="manager",
        permissions={"admin.users.role.update": True},
        nickname="Manager",
    )
    await fake_db.create_user_with_assistant(
        discord_id=8103,
        username="assistant_manager",
        password_hash="hash",
        nickname="Assistant Manager",
        role="manager",
    )

    response = await patch_user_role(app, 8103, "employee")

    assert response.status_code == 403
    assert "идентичной ролью" in response.json()["detail"]


async def test_role_update_applies_to_manageable_account(app, fake_db, set_current_user):
    set_current_user(
        role="manager",
        permissions={"admin.users.role.update": True},
        nickname="Manager",
    )
    await fake_db.create_user_with_assistant(
        discord_id=8102,
        username="assistant_employee",
        password_hash="hash",
        nickname="Assistant Employee",
        role="employee",
    )

    response = await patch_user_role(app, 8102, "junior_employee")

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["discord_id"] == "8102"
    assert body["role"] == "junior_employee"
    assert fake_db.users_by_discord[8102]["role"] == "junior_employee"
    assert fake_db.assistants_by_id[8102]["role"] == "junior_employee"


async def test_role_update_allows_self_account(app, fake_db, set_current_user):
    set_current_user(
        role="manager",
        permissions={"admin.users.role.update": True},
        nickname="Manager",
    )
    await fake_db.create_user_with_assistant(
        discord_id=1001,
        username="manager_self",
        password_hash="hash",
        nickname="Manager",
        role="manager",
    )

    response = await patch_user_role(app, 1001, "employee")

    assert response.status_code == 200
    assert response.json()["data"]["role"] == "employee"
    assert fake_db.users_by_discord[1001]["role"] == "employee"
    assert fake_db.assistants_by_id[1001]["role"] == "employee"


async def test_developer_can_update_other_developer_account(app, fake_db, set_current_user):
    set_current_user(
        role="developer",
        permissions={"admin.users.role.update": True},
        nickname="Developer",
    )
    await fake_db.create_user_with_assistant(
        discord_id=1001,
        username="developer_self",
        password_hash="hash",
        nickname="Developer",
        role="developer",
    )
    await fake_db.create_user_with_assistant(
        discord_id=8104,
        username="assistant_developer",
        password_hash="hash",
        nickname="Assistant Developer",
        role="developer",
    )

    response = await patch_user_role(app, 8104, "manager")

    assert response.status_code == 200
    assert response.json()["data"]["role"] == "manager"
    assert fake_db.users_by_discord[8104]["role"] == "manager"


async def test_deactivate_user_requires_manageable_account(app, fake_db, set_current_user):
    set_current_user(
        role="manager",
        permissions={"admin.users.deactivate": True},
        nickname="Manager",
    )
    await fake_db.create_user_with_assistant(
        discord_id=8201,
        username="assistant_dev",
        password_hash="hash",
        nickname="Assistant Dev",
        role="developer",
    )

    response = await post_deactivate_user(app, 8201, reason="cleanup")

    assert response.status_code == 403
    assert "ролью выше вашей" in response.json()["detail"]


async def test_deactivate_user_rejects_same_rank_target(
    app, fake_db, set_current_user
):
    set_current_user(
        role="manager",
        permissions={"admin.users.deactivate": True},
        nickname="Manager",
    )
    await fake_db.create_user_with_assistant(
        discord_id=8203,
        username="assistant_manager",
        password_hash="hash",
        nickname="Assistant Manager",
        role="manager",
    )

    response = await post_deactivate_user(app, 8203, reason="cleanup")

    assert response.status_code == 403
    assert "идентичной ролью" in response.json()["detail"]


async def test_deactivate_user_sets_inactive_and_revokes_sessions(
    app, fake_db, set_current_user
):
    set_current_user(
        role="manager",
        permissions={"admin.users.deactivate": True},
        nickname="Manager",
    )
    await fake_db.create_user_with_assistant(
        discord_id=8202,
        username="assistant_employee",
        password_hash="hash",
        nickname="Assistant Employee",
        role="employee",
    )
    fake_db.sessions.append({"id": 1, "user_id": 8202, "revoked": False})

    response = await post_deactivate_user(app, 8202, reason="cleanup")

    assert response.status_code == 200
    assert response.json()["data"]["discord_id"] == "8202"
    assert fake_db.users_by_discord[8202]["is_active"] is False
    assert fake_db.assistants_by_id[8202]["dismissed_at"] is not None
    assert fake_db.sessions[0]["revoked"] is True


async def test_developer_can_deactivate_other_developer_account(
    app, fake_db, set_current_user
):
    set_current_user(
        role="developer",
        permissions={"admin.users.deactivate": True},
        nickname="Developer",
    )
    await fake_db.create_user_with_assistant(
        discord_id=1001,
        username="developer_self",
        password_hash="hash",
        nickname="Developer",
        role="developer",
    )
    await fake_db.create_user_with_assistant(
        discord_id=8204,
        username="assistant_developer",
        password_hash="hash",
        nickname="Assistant Developer",
        role="developer",
    )

    response = await post_deactivate_user(app, 8204, reason="cleanup")

    assert response.status_code == 200
    assert fake_db.users_by_discord[8204]["is_active"] is False


async def test_deactivate_user_accepts_empty_body(app, fake_db, set_current_user):
    set_current_user(
        role="manager",
        permissions={"admin.users.deactivate": True},
        nickname="Manager",
    )
    await fake_db.create_user_with_assistant(
        discord_id=8205,
        username="assistant_employee_2",
        password_hash="hash",
        nickname="Assistant Employee 2",
        role="employee",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/admin/users/8205/deactivate")

    assert response.status_code == 200
    assert fake_db.users_by_discord[8205]["is_active"] is False
