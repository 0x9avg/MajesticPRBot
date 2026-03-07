from __future__ import annotations

import sys
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

@pytest.fixture
def anyio_backend():
    return "asyncio"

import dependencies  # noqa: E402
from routes.admin import router as admin_router  # noqa: E402
MSK = timezone(timedelta(hours=3))


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

    async def emit_monitoring_refresh(self, trace_id: str) -> None:
        self.calls.append(("monitoring.refresh", {"trace_id": trace_id}))


class FakeAuth:
    secret_key = "test-secret"
    algorithm = "HS256"

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
        raw = f"refresh-{user_id}"
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


def _now() -> datetime:
    return datetime.now(MSK)


def _default_streamer(streamer_id: int, streamer_name: str) -> dict[str, Any]:
    return {
        "streamer_id": streamer_id,
        "streamer_name": streamer_name,
        "is_online": True,
        "is_pinned": False,
        "started_at": None,
        "priority": 0,
        "pr_slots": 1,
        "game_id": None,
        "game_name": None,
        "stream_title": None,
        "stream_thumbnail_url": None,
        "profile_image_url": None,
        "allow_juniors": True,
        "priority_override": None,
        "pr_slots_override": None,
        "added_at": _now(),
        "added_by_id": 0,
        "assignments": [],
        "assigned_pr_id": None,
    }


class FakeDB:
    def __init__(self) -> None:
        # Auth/user storage
        self.users_by_username: dict[str, dict[str, Any]] = {}
        self.users_by_discord: dict[int, dict[str, Any]] = {}
        self.users_by_id: dict[int, dict[str, Any]] = {}
        self.next_user_id = 1
        self.sessions: list[dict[str, Any]] = []
        self.auth_logs: list[dict[str, Any]] = []
        self.raise_on_create_user: Exception | None = None

        # Assistants/permissions
        self.assistants_by_id: dict[int, dict[str, Any]] = {}
        self.assistant_logs_by_id: dict[int, list[dict[str, Any]]] = {}
        self.assistant_sessions_by_id: dict[int, list[dict[str, Any]]] = {}
        self.manual_sessions: list[dict[str, Any]] = []
        self.role_permissions: dict[str, dict[str, bool]] = {
            "junior_employee": {
                "spec.claim.probation": True,
                "spec.claim.main": True,
                "spec.view_claimable": True,
                "spec.unclaim.self": True,
                "events.view": True,
                "events.join.self": True,
                "events.leave.self": True,
                "events.spec.request": True,
                "assistants.view": True,
                "dashboard.view": True,
                "streamers.view": True,
                "logs.pr_actions.view": True,
            },
            "employee": {
                "spec.claim.main": True,
                "spec.view_claimable": True,
                "spec.unclaim.self": True,
                "events.view": True,
                "events.join.self": True,
                "events.leave.self": True,
                "events.spec.request": True,
                "assistants.view": True,
                "dashboard.view": True,
                "streamers.view": True,
                "logs.pr_actions.view": True,
            },
            "senior_employee": {
                "events.create": True,
                "spec.claim.main": True,
                "spec.view_claimable": True,
                "spec.unclaim.self": True,
                "events.view": True,
                "events.join.self": True,
                "events.leave.self": True,
                "events.spec.request": True,
                "assistants.view": True,
                "dashboard.view": True,
                "streamers.view": True,
                "logs.pr_actions.view": True,
            },
            "manager": {
                "admin.users.create": True,
                "logs.admin.view": True,
                "events.create": True,
                "events.manage": True,
                "events.update": True,
                "events.spec.manage": True,
                "events.leave.any": True,
                "spec.unclaim.any": True,
                "assistants.create": True,
                "assistants.update": True,
                "assistants.delete": True,
                "assistants.logs.view": True,
                "assistants.sessions.view": True,
                "assistants.sessions.manage": True,
                "assistants.points.manage": True,
                "assistants.sanctions.manage": True,
                "assistants.warnings.manage": True,
            },
            "developer": {
                "admin.users.create": True,
                "logs.admin.view": True,
                "monitoring.view": True,
                "monitoring.refresh": True,
                "notifications.render": True,
                "streamers.status.update": True,
                "spec.claim.probation": True,
            },
        }

        # Streamers/spec
        self.streamers_by_id: dict[int, dict[str, Any]] = {}
        self.pr_current_streamer: dict[int, dict[str, Any]] = {}
        self.pr_sessions: dict[int, list[dict[str, Any]]] = {}

        # Events
        self.events_by_id: dict[int, dict[str, Any]] = {}
        self.event_participants: dict[int, dict[int, datetime]] = {}
        self.next_event_id = 1
        self.force_create_event_fail = False

        # Guild/settings
        self.guild_settings: dict[str, Any] | None = None

        # Logs/stats
        self.logged_actions: list[dict[str, Any]] = []
        self.admin_logs_entries: list[dict[str, Any]] = []
        self.dashboard_stats: dict[str, Any] = {
            "assigned_pr_count": 0,
            "unassigned_media_count": 0,
            "events_today_count": 0,
        }

    # ---------------------------------------------------------------------
    # Auth/user operations
    # ---------------------------------------------------------------------
    async def create_user(
        self,
        discord_id: int,
        username: str,
        password_hash: str,
        created_by: int | None = None,
    ) -> int:
        if self.raise_on_create_user:
            raise self.raise_on_create_user
        user_id = self.next_user_id
        self.next_user_id += 1
        user = {
            "discord_id": discord_id,
            "username": username,
            "password_hash": password_hash,
            "is_active": True,
            "require_password_change": True,
            "failed_login_attempts": 0,
            "last_failed_login": None,
            "last_login": None,
            "created_by": created_by,
            "role": "employee",
            "nickname": username,
            "permissions": self.role_permissions.get("employee", {}),
        }
        self.users_by_username[username] = user
        self.users_by_discord[discord_id] = user
        self.users_by_id[discord_id] = user
        return discord_id

    async def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        return self.users_by_username.get(username)

    async def get_user_by_discord_id(self, discord_id: int) -> dict[str, Any] | None:
        return self.users_by_discord.get(discord_id)

    async def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        return self.users_by_id.get(user_id)

    async def increment_failed_login(self, username: str) -> None:
        user = self.users_by_username.get(username)
        if user:
            user["failed_login_attempts"] = (
                int(user.get("failed_login_attempts") or 0) + 1
            )
            user["last_failed_login"] = _now()

    async def reset_failed_login(self, user_id: int) -> None:
        user = self.users_by_id.get(user_id)
        if user:
            user["failed_login_attempts"] = 0
            user["last_failed_login"] = None
            user["last_login"] = _now()

    async def create_session(
        self,
        user_id: int,
        refresh_token_hash: str,
        family_id: str,
        expires_at: datetime,
        client_ip: str | None,
        user_agent: str | None,
    ) -> int:
        session_id = len(self.sessions) + 1
        self.sessions.append(
            {
                "id": session_id,
                "user_id": user_id,
                "refresh_token_hash": refresh_token_hash,
                "family_id": family_id,
                "expires_at": expires_at,
                "client_ip": client_ip,
                "user_agent": user_agent,
                "revoked": False,
            }
        )
        return session_id

    async def revoke_user_sessions(self, user_id: int) -> None:
        for session in self.sessions:
            if session["user_id"] == user_id:
                session["revoked"] = True

    async def log_auth_event(
        self,
        user_id: int | None,
        username: str,
        action: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> None:
        self.auth_logs.append(
            {
                "user_id": user_id,
                "username": username,
                "action": action,
                "ip_address": ip_address,
                "user_agent": user_agent,
            }
        )

    # ---------------------------------------------------------------------
    # Common logging
    # ---------------------------------------------------------------------
    async def log_admin_action(self, **kwargs: Any) -> None:
        self.logged_actions.append(kwargs)

    async def log_admin_action_v2(self, **kwargs: Any) -> None:
        self.logged_actions.append(kwargs)

    async def get_admin_logs(
        self,
        limit: int = 100,
        offset: int = 0,
        filters: dict[str, Any] | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> list[dict[str, Any]]:
        logs = list(self.admin_logs_entries)
        filters = filters or {}

        action_filter = filters.get("action")
        if action_filter:
            action_set = (
                set(action_filter)
                if isinstance(action_filter, list)
                else {str(action_filter)}
            )
            logs = [row for row in logs if row.get("action") in action_set]

        actor_filter = filters.get("actor_name") or filters.get("admin_name")
        if actor_filter:
            actor_filter_l = str(actor_filter).lower()
            logs = [
                row
                for row in logs
                if actor_filter_l in str(
                    row.get("actor_name") or row.get("admin_name") or ""
                ).lower()
            ]

        target_type = filters.get("target_type")
        if target_type:
            logs = [row for row in logs if row.get("target_type") == target_type]

        kind = filters.get("kind")
        if kind:
            if kind == "other":
                logs = [row for row in logs if "." not in str(row.get("action", ""))]
            else:
                prefix = f"{kind}."
                logs = [
                    row for row in logs if str(row.get("action", "")).startswith(prefix)
                ]

        if sort_by in {"created_at", "admin_name", "actor_name", "action", "target_name"}:
            logs.sort(
                key=lambda x: x.get(sort_by)
                or x.get("actor_name")
                or x.get("admin_name")
                or "",
                reverse=(sort_order.lower() == "desc"),
            )
        return logs[offset : offset + limit]

    async def count_admin_logs(self, filters: dict[str, Any] | None = None) -> int:
        logs = await self.get_admin_logs(limit=1000, offset=0, filters=filters)
        return len(logs)

    async def get_pr_action_logs(
        self,
        limit: int = 20,
        offset: int = 0,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {"items": [], "total": 0}

    # ---------------------------------------------------------------------
    # Assistants
    # ---------------------------------------------------------------------
    async def get_all_assistants(self) -> list[dict[str, Any]]:
        return [deepcopy(a) for a in self.assistants_by_id.values()]

    async def get_assistant(self, pr_id: int) -> dict[str, Any] | None:
        assistant = self.assistants_by_id.get(pr_id)
        return deepcopy(assistant) if assistant else None

    async def create_or_update_assistant(
        self,
        pr_id: int,
        nickname: str,
        role: str,
        experience_days: int = 0,
        appointed_at: date | None = None,
    ) -> bool:
        existing = self.assistants_by_id.get(pr_id, {})
        appointed_at_dt = (
            datetime.combine(appointed_at, datetime.min.time(), tzinfo=MSK)
            if appointed_at
            else _now() - timedelta(days=max(int(experience_days or 0), 0))
        )
        self.assistants_by_id[pr_id] = {
            "pr_id": pr_id,
            "nickname": nickname,
            "role": role,
            "experience_days": max(int(experience_days or 0), 0),
            "status": existing.get("status", "free"),
            "assigned_to_type": existing.get("assigned_to_type"),
            "assigned_to_id": existing.get("assigned_to_id"),
            "assigned_to_name": existing.get("assigned_to_name"),
            "total_spec_seconds": existing.get("total_spec_seconds", 0),
            "session_count": existing.get("session_count", 0),
            "added_at": existing.get("added_at", _now()),
            "appointed_at": appointed_at_dt,
            "updated_at": _now(),
            "auto_points_total": existing.get("auto_points_total", 0.0),
            "manual_points_adjustment": existing.get("manual_points_adjustment", 0.0),
            "total_points": existing.get("total_points", 0.0),
            "penalty_points": existing.get("penalty_points", 0.0),
            "penalty_percent": existing.get("penalty_percent", 0.0),
            "display_points": existing.get("display_points", 0.0),
            "warnings_units": existing.get("warnings_units", 0),
            "strict_warnings": existing.get("strict_warnings", 0),
            "oral_warnings": existing.get("oral_warnings", 0),
            "warnings_display": existing.get("warnings_display", "0/2 0/2"),
            "total_spec_hours": round(existing.get("total_spec_seconds", 0) / 3600, 2),
        }
        return True

    async def update_assistant_assignment(
        self,
        pr_id: int,
        assigned_to_type: str | None,
        assigned_to_id: int | None,
        assigned_to_name: str | None,
    ) -> bool:
        assistant = self.assistants_by_id.get(pr_id)
        if not assistant:
            return False
        assistant["assigned_to_type"] = assigned_to_type
        assistant["assigned_to_id"] = assigned_to_id
        assistant["assigned_to_name"] = assigned_to_name
        assistant["status"] = "free" if not assigned_to_type else "assigned"
        return True

    async def delete_assistant(self, user_id: int) -> bool:
        return self.assistants_by_id.pop(user_id, None) is not None

    async def get_assistant_logs(self, pr_id: int) -> list[dict[str, Any]]:
        return deepcopy(self.assistant_logs_by_id.get(pr_id, []))

    async def get_assistant_sessions_detailed(
        self,
        pr_id: int,
        limit: int = 50,
        include_deleted: bool = False,
    ) -> list[dict[str, Any]]:
        sessions = deepcopy(self.assistant_sessions_by_id.get(pr_id, []))
        if not include_deleted:
            sessions = [s for s in sessions if not s.get("deleted_at")]
        sessions.sort(key=lambda x: x.get("started_at") or "", reverse=True)
        return sessions[: max(1, min(int(limit or 50), 200))]

    async def get_role_permissions(self, role: str) -> dict[str, bool]:
        return deepcopy(self.role_permissions.get(role, {}))

    async def reset_assistant_stats(self, pr_id: int) -> None:
        assistant = self.assistants_by_id.get(pr_id)
        if assistant:
            assistant["total_spec_seconds"] = 0
            assistant["session_count"] = 0
            assistant["total_spec_hours"] = 0.0
            assistant["auto_points_total"] = 0.0
            assistant["total_points"] = round(
                float(assistant.get("manual_points_adjustment", 0.0)), 4
            )
            assistant["display_points"] = round(
                float(assistant.get("total_points", 0.0))
                - float(assistant.get("penalty_points", 0.0)),
                4,
            )

    async def create_manual_spec_session(
        self,
        pr_id: int,
        target_type: str,
        target_id: int | None,
        started_at: datetime,
        ended_at: datetime,
        is_probation: bool,
        priority: int,
        target_name: str | None = None,
    ) -> bool:
        if ended_at <= started_at:
            return False
        if target_type == "manual":
            if target_id is not None:
                return False
        elif target_type in {"streamer", "event"}:
            if target_id is None:
                return False
        else:
            return False

        duration_seconds = max(int((ended_at - started_at).total_seconds()), 1)
        self.manual_sessions.append(
            {
                "pr_id": pr_id,
                "target_type": target_type,
                "target_id": target_id,
                "started_at": started_at,
                "ended_at": ended_at,
                "duration_seconds": duration_seconds,
                "is_probation": is_probation,
                "priority": priority,
                "target_name": target_name,
            }
        )
        assistant = self.assistants_by_id.setdefault(
            pr_id,
            {
                "pr_id": pr_id,
                "nickname": None,
                "role": "employee",
                "status": "free",
                "total_spec_seconds": 0,
                "session_count": 0,
                "added_at": _now(),
            },
        )
        points = round((duration_seconds / 3600) * (priority if priority else 0.5), 4)
        assistant["auto_points_total"] = round(
            float(assistant.get("auto_points_total", 0.0)) + points, 4
        )
        assistant["total_points"] = round(
            float(assistant.get("auto_points_total", 0.0))
            + float(assistant.get("manual_points_adjustment", 0.0)),
            4,
        )
        assistant["display_points"] = round(
            float(assistant.get("total_points", 0.0))
            - float(assistant.get("penalty_points", 0.0)),
            4,
        )
        return True

    async def adjust_assistant_points(
        self,
        pr_id: int,
        delta: float,
        source: str = "manual_adjust",
    ) -> dict[str, Any] | None:
        assistant = self.assistants_by_id.get(pr_id)
        if not assistant:
            return None
        before = deepcopy(assistant)
        assistant["manual_points_adjustment"] = round(
            float(assistant.get("manual_points_adjustment", 0.0)) + float(delta), 4
        )
        assistant["total_points"] = round(
            float(assistant.get("auto_points_total", 0.0))
            + float(assistant.get("manual_points_adjustment", 0.0)),
            4,
        )
        assistant["display_points"] = round(
            float(assistant.get("total_points", 0.0))
            - float(assistant.get("penalty_points", 0.0)),
            4,
        )
        return {
            "pr_id": pr_id,
            "delta": round(float(delta), 4),
            "source": source,
            "before": before,
            "after": deepcopy(assistant),
        }

    async def update_assistant_sanctions(
        self,
        pr_id: int,
        penalty_points: float | None = None,
        penalty_percent: float | None = None,
    ) -> dict[str, Any] | None:
        assistant = self.assistants_by_id.get(pr_id)
        if not assistant:
            return None
        before = deepcopy(assistant)
        if penalty_points is not None:
            assistant["penalty_points"] = max(round(float(penalty_points), 4), 0.0)
        if penalty_percent is not None:
            assistant["penalty_percent"] = max(round(float(penalty_percent), 4), 0.0)
        assistant["display_points"] = round(
            float(assistant.get("total_points", 0.0))
            - float(assistant.get("penalty_points", 0.0)),
            4,
        )
        return {
            "pr_id": pr_id,
            "before": before,
            "after": deepcopy(assistant),
        }

    async def update_assistant_warnings(
        self,
        pr_id: int,
        oral_delta: int = 0,
        strict_delta: int = 0,
    ) -> dict[str, Any] | None:
        assistant = self.assistants_by_id.get(pr_id)
        if not assistant:
            return None
        units_delta = int(oral_delta) + int(strict_delta) * 2
        if units_delta == 0:
            return None
        before = deepcopy(assistant)
        next_units = max(int(assistant.get("warnings_units", 0)) + units_delta, 0)
        assistant["warnings_units"] = next_units
        assistant["strict_warnings"] = next_units // 2
        assistant["oral_warnings"] = next_units % 2
        assistant["warnings_display"] = (
            f"{assistant['strict_warnings']}/2 {assistant['oral_warnings']}/2"
        )
        return {
            "pr_id": pr_id,
            "units_delta": units_delta,
            "oral_delta": int(oral_delta),
            "strict_delta": int(strict_delta),
            "before": before,
            "after": deepcopy(assistant),
        }

    async def update_assistant_session(
        self, pr_id: int, session_id: int, patch: dict[str, Any]
    ) -> dict[str, Any] | None:
        sessions = self.assistant_sessions_by_id.setdefault(pr_id, [])
        session = next((s for s in sessions if int(s.get("id", 0)) == int(session_id)), None)
        if session is None:
            session = {
                "id": session_id,
                "pr_id": pr_id,
                "target_type": "streamer",
                "target_id": "1",
                "started_at": _now().isoformat(),
                "ended_at": (_now() + timedelta(hours=1)).isoformat(),
            }
            sessions.append(session)

        before = deepcopy(session)
        for key, value in patch.items():
            session[key] = value

        if session.get("target_type") == "manual":
            session["target_id"] = None

        after = deepcopy(session)
        return {"session_id": session_id, "before": before, "after": after}

    async def soft_delete_assistant_session(
        self,
        pr_id: int,
        session_id: int,
        deleted_by_id: int | None = None,
        reason: str | None = None,
    ) -> dict[str, Any] | None:
        session = {
            "id": session_id,
            "pr_id": pr_id,
            "deleted_by_id": deleted_by_id,
            "reason": reason,
        }
        return {"session_id": session_id, "before": deepcopy(session), "after": deepcopy(session)}

    # ---------------------------------------------------------------------
    # Streamers / Spec
    # ---------------------------------------------------------------------
    async def list_all_streamers(self) -> list[dict[str, Any]]:
        return [deepcopy(s) for s in self.streamers_by_id.values()]

    async def list_online_streamers(self) -> list[dict[str, Any]]:
        return [
            deepcopy(s) for s in self.streamers_by_id.values() if s.get("is_online")
        ]

    async def get_streamer(self, streamer_id: int) -> dict[str, Any] | None:
        streamer = self.streamers_by_id.get(streamer_id)
        return deepcopy(streamer) if streamer else None

    async def create_streamer(
        self,
        streamer_id: int,
        streamer_name: str,
        is_online: bool = False,
        started_at: str | None = None,
        priority: int = 0,
        pr_slots: int = 1,
        added_by_id: int = 0,
        game_id: int | None = None,
        game_name: str | None = None,
        stream_title: str | None = None,
        stream_thumbnail_url: str | None = None,
        profile_image_url: str | None = None,
        allow_juniors: bool = True,
    ) -> None:
        streamer = _default_streamer(streamer_id, streamer_name)
        streamer.update(
            {
                "is_online": is_online,
                "started_at": started_at,
                "priority": priority,
                "pr_slots": pr_slots,
                "allow_juniors": allow_juniors,
                "added_by_id": added_by_id,
                "game_id": game_id,
                "game_name": game_name,
                "stream_title": stream_title,
                "stream_thumbnail_url": stream_thumbnail_url,
                "profile_image_url": profile_image_url,
            }
        )
        self.streamers_by_id[streamer_id] = streamer

    async def update_streamer(
        self,
        twitch_id: int,
        priority: int | None = None,
        pr_slots: int | None = None,
        is_pinned: bool | None = None,
        allow_juniors: bool | None = None,
        priority_override: int | None = None,
        pr_slots_override: int | None = None,
    ) -> None:
        streamer = self.streamers_by_id[twitch_id]
        if priority is not None:
            streamer["priority"] = priority
        if pr_slots is not None:
            streamer["pr_slots"] = pr_slots
        if is_pinned is not None:
            streamer["is_pinned"] = is_pinned
        if allow_juniors is not None:
            streamer["allow_juniors"] = allow_juniors
        if priority_override is not None:
            streamer["priority_override"] = priority_override
        if pr_slots_override is not None:
            streamer["pr_slots_override"] = pr_slots_override

    async def remove_streamer(self, twitch_id: int) -> None:
        self.streamers_by_id.pop(twitch_id, None)

    async def update_streamer_status(
        self,
        streamer_id: int,
        is_online: bool,
        started_at: str | None = None,
        game_id: int | None = None,
        game_name: str | None = None,
        stream_title: str | None = None,
        stream_thumbnail_url: str | None = None,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        streamer = self.streamers_by_id.get(streamer_id)
        if not streamer:
            return None, None
        old_state = deepcopy(streamer)
        streamer.update(
            {
                "is_online": is_online,
                "started_at": started_at,
                "game_id": game_id,
                "game_name": game_name,
                "stream_title": stream_title,
                "stream_thumbnail_url": stream_thumbnail_url,
            }
        )
        return old_state, deepcopy(streamer)

    async def update_streamers_status_bulk(self, updates: list[dict[str, Any]]) -> int:
        updated = 0
        for update in updates:
            streamer_id = update["streamer_id"]
            streamer = self.streamers_by_id.get(streamer_id)
            if not streamer:
                continue
            streamer.update(update)
            updated += 1
        return updated

    async def get_pr_current_streamer(self, pr_id: int) -> dict[str, Any] | None:
        current = self.pr_current_streamer.get(pr_id)
        return deepcopy(current) if current else None

    async def assign_pr_to_streamer(
        self, streamer_id: int, pr_id: int, is_probation: bool = False
    ) -> None:
        if pr_id in self.pr_current_streamer:
            raise ValueError("PR is already assigned")
        streamer = self.streamers_by_id.get(streamer_id)
        if not streamer:
            raise ValueError("Streamer not found")

        assignments = streamer.setdefault("assignments", [])
        for assignment in assignments:
            if assignment.get("is_probation") == is_probation:
                raise ValueError("Slot already occupied")

        assignments.append(
            {
                "pr_id": pr_id,
                "nickname": f"user{pr_id}",
                "is_probation": is_probation,
            }
        )
        if not streamer.get("assigned_pr_id") and not is_probation:
            streamer["assigned_pr_id"] = pr_id

        self.pr_current_streamer[pr_id] = {
            "streamer_id": streamer_id,
            "streamer_name": streamer["streamer_name"],
            "assigned_at": _now(),
        }

    async def unassign_pr_from_streamer(
        self, streamer_id: int, pr_id: int | None = None, end_reason: str = "manual_unclaim"
    ) -> list[dict[str, Any]]:
        streamer = self.streamers_by_id.get(streamer_id)
        if not streamer:
            return []

        assignments = streamer.get("assignments", [])
        if pr_id is None:
            removed = assignments
            assignments = []
        else:
            removed = [a for a in assignments if int(a["pr_id"]) == int(pr_id)]
            assignments = [a for a in assignments if int(a["pr_id"]) != int(pr_id)]

        streamer["assignments"] = assignments
        if pr_id is None:
            streamer["assigned_pr_id"] = None
        elif streamer.get("assigned_pr_id") == pr_id:
            streamer["assigned_pr_id"] = None

        results = []
        for assignment in removed:
            assignee_id = int(assignment["pr_id"])
            self.pr_current_streamer.pop(assignee_id, None)
            results.append(
                {
                    "pr_id": assignee_id,
                    "duration_seconds": 123,
                    "is_probation": assignment.get("is_probation", False),
                    "end_reason": end_reason,
                }
            )
        return results



    async def get_pr_spec_sessions(
        self, pr_id: int, limit: int = 50
    ) -> list[dict[str, Any]]:
        sessions = self.pr_sessions.get(pr_id, [])
        return sessions[:limit]

    # ---------------------------------------------------------------------
    # Events
    # ---------------------------------------------------------------------
    async def create_event(
        self,
        name: str,
        description: str,
        created_by: int,
        start_time: datetime | None = None,
        required_pr_count: int = 1,
        notification_sent: bool = False,
        pr_slots: int = 1,
        priority: int = 0,
    ) -> int | None:
        if self.force_create_event_fail:
            return None
        event_id = self.next_event_id
        self.next_event_id += 1
        self.events_by_id[event_id] = {
            "id": event_id,
            "name": name,
            "description": description,
            "required_pr_count": required_pr_count,
            "pr_slots": pr_slots,
            "priority": priority,
            "is_pinned": False,
            "start_time": start_time,
            "channel_id": None,
            "created_by": created_by,
            "is_active": True,
            "created_at": _now(),
            "notification_sent": notification_sent,
            "message_id": None,
        }
        self.event_participants[event_id] = {}
        return event_id

    def _event_view(self, event: dict[str, Any]) -> dict[str, Any]:
        event_id = int(event["id"])
        participants = [
            {"pr_id": pr_id, "nickname": f"user{pr_id}"}
            for pr_id in self.event_participants.get(event_id, {}).keys()
        ]
        return {
            **event,
            "current_participants": len(participants),
            "participants": participants,
        }

    async def get_active_events(self) -> list[dict[str, Any]]:
        return [
            self._event_view(e)
            for e in self.events_by_id.values()
            if e.get("is_active")
        ]

    async def get_all_events(self) -> list[dict[str, Any]]:
        events = [self._event_view(e) for e in self.events_by_id.values()]
        events.sort(
            key=lambda e: (
                1 if e.get("is_active") else 0,
                1 if e.get("is_pinned") else 0,
                e.get("created_at") or datetime.min.replace(tzinfo=MSK),
            ),
            reverse=True,
        )
        return events

    async def get_scheduled_events(self) -> list[dict[str, Any]]:
        return [
            self._event_view(e)
            for e in self.events_by_id.values()
            if e.get("is_active")
            and e.get("start_time")
            and not e.get("notification_sent")
        ]

    async def get_event(self, event_id: int) -> dict[str, Any] | None:
        event = self.events_by_id.get(event_id)
        return self._event_view(event) if event else None

    async def get_event_participants(self, event_id: int) -> list[dict[str, Any]]:
        return (
            self._event_view(self.events_by_id[event_id]).get("participants", [])
            if event_id in self.events_by_id
            else []
        )

    async def join_event(self, event_id: int, user_id: int) -> dict[str, Any]:
        event = self.events_by_id.get(event_id)
        if not event or not event.get("is_active"):
            return {"status": "error", "detail": "Event not found or inactive"}
        participants = self.event_participants.setdefault(event_id, {})
        if user_id in participants:
            return {"status": "error", "detail": "Already reserved for this event"}
        participants[user_id] = _now()
        return {"status": "joined", "detail": "Joined active event"}

    async def leave_event(self, event_id: int, user_id: int, end_reason: str = "manual_unclaim") -> int:
        participants = self.event_participants.setdefault(event_id, {})
        participants.pop(user_id, None)
        return 60

    async def get_user_active_event_participation(self, user_id: int) -> dict[str, Any] | None:
        for event_id, participants in self.event_participants.items():
            if user_id in participants:
                event = self.events_by_id.get(event_id)
                if event and event.get("is_active"):
                    return {"event_id": event_id, "name": event.get("name")}
        return None

    async def end_event(self, event_id: int) -> list[dict[str, Any]]:
        event = self.events_by_id.get(event_id)
        if event:
            event["is_active"] = False
        participants = self.event_participants.get(event_id, {})
        return [{"user_id": p_id, "duration": 60} for p_id in participants.keys()]

    async def update_event(
        self,
        event_id: int,
        name: str | None = None,
        description: str | None = None,
        required_pr_count: int | None = None,
        priority: int | None = None,
        is_pinned: bool | None = None,
        points: float | None = None,
    ) -> bool:
        event = self.events_by_id.get(event_id)
        if not event:
            return False
        if name is not None:
            event["name"] = name
        if description is not None:
            event["description"] = description
        if required_pr_count is not None:
            event["required_pr_count"] = required_pr_count
        if priority is not None:
            event["priority"] = priority
        if is_pinned is not None:
            event["is_pinned"] = is_pinned
        if points is not None:
            event["points"] = points
        return True

    async def mark_event_notification_sent(self, event_id: int) -> None:
        if event_id in self.events_by_id:
            self.events_by_id[event_id]["notification_sent"] = True

    async def update_event_message_id(self, event_id: int, message_id: int) -> None:
        if event_id in self.events_by_id:
            self.events_by_id[event_id]["message_id"] = message_id

    async def recalc_target_active_sessions(self, target_type: str, target_id: int) -> None:
        pass

    async def update_pending_spec_request(
        self,
        event_id: int,
        name: str | None = None,
        description: str | None = None,
        priority: int | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> bool:
        event = self.events_by_id.get(event_id)
        if not event:
            return False
        if name is not None:
            event["name"] = name
        if description is not None:
            event["description"] = description
        if priority is not None:
            event["priority"] = priority
        if start_time is not None:
            event["start_time"] = start_time
        if end_time is not None:
            event["end_time"] = end_time
        return True

    async def approve_spec_request(self, event_id: int, approved_by: int) -> bool:
        event = self.events_by_id.get(event_id)
        if not event:
            return False
        event["approval_status"] = "approved"
        event["approved_by"] = approved_by
        event["approved_at"] = _now()
        return True

    async def get_pending_spec_requests(self) -> list[dict[str, Any]]:
        return [
            self._event_view(e)
            for e in self.events_by_id.values()
            if e.get("approval_status") == "pending"
        ]

    # ---------------------------------------------------------------------
    # Guild/settings
    # ---------------------------------------------------------------------
    async def get_guild(self) -> dict[str, Any] | None:
        return deepcopy(self.guild_settings) if self.guild_settings else None

    async def create_or_update_guild(self, **kwargs: Any) -> bool:
        if not self.guild_settings:
            self.guild_settings = {
                "notification_channel_id": None,
                "monitoring_channel_id": None,
                "monitoring_message_id": None,
                "monitoring_filter_gta": False,
                "pr_actions_channel_id": None,
                "control_panel_channel_id": None,
                "control_panel_message_id": None,
                "notification_templates": {
                    "stream_online": "Online: {streamer_name}",
                    "stream_offline": "Offline: {streamer_name}",
                    "category_to_gta": "To GTA: {streamer_name}",
                    "category_from_gta": "From GTA: {streamer_name}",
                },
                "p0_rate": 1.0,
                "p1_rate": 1.2,
                "p2_rate": 1.5,
                "p3_rate": 2.0,
                "probation_rate": 1.2,
            }
        for key, value in kwargs.items():
            if value is not None:
                self.guild_settings[key] = value
        return True

    async def update_guild_templates(
        self,
        template_stream_online: str | None = None,
        template_stream_offline: str | None = None,
        template_category_to_gta: str | None = None,
        template_category_from_gta: str | None = None,
    ) -> bool:
        await self.create_or_update_guild()
        templates = self.guild_settings.setdefault("notification_templates", {})
        if template_stream_online is not None:
            templates["stream_online"] = template_stream_online
        if template_stream_offline is not None:
            templates["stream_offline"] = template_stream_offline
        if template_category_to_gta is not None:
            templates["category_to_gta"] = template_category_to_gta
        if template_category_from_gta is not None:
            templates["category_from_gta"] = template_category_from_gta
        return True

    async def get_notification_template(self, event_type: str) -> str:
        await self.create_or_update_guild()
        return self.guild_settings.get("notification_templates", {}).get(event_type, "")

    async def update_guild_rates(
        self,
        p0_rate: float | None = None,
        p1_rate: float | None = None,
        p2_rate: float | None = None,
        p3_rate: float | None = None,
        probation_rate: float | None = None,
    ) -> bool:
        await self.create_or_update_guild()
        if p0_rate is not None:
            self.guild_settings["p0_rate"] = p0_rate
        if p1_rate is not None:
            self.guild_settings["p1_rate"] = p1_rate
        if p2_rate is not None:
            self.guild_settings["p2_rate"] = p2_rate
        if p3_rate is not None:
            self.guild_settings["p3_rate"] = p3_rate
        if probation_rate is not None:
            self.guild_settings["probation_rate"] = probation_rate
        return True

    # ---------------------------------------------------------------------
    # Stats
    # ---------------------------------------------------------------------
    async def get_dashboard_stats(self) -> dict[str, Any]:
        return deepcopy(self.dashboard_stats)


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
    return {
        "id": 1,
        "username": "creator",
        "nickname": "Creator",
        "role": "manager",
        "principal_type": "user",
        "discord_id": 1001,
        "require_password_change": False,
        "permissions": {
            "dashboard.view": True,
            "streamers.view": True,
            "admin.users.create": True,
            "logs.admin.view": True,
            "logs.pr_actions.view": True,
            "assistants.view": True,
            "assistants.create": True,
            "assistants.update": True,
            "assistants.delete": True,
            "assistants.sessions.view": True,
            "assistants.sessions.manage": True,
            "assistants.logs.view": True,
            "assistants.points.manage": True,
            "assistants.sanctions.manage": True,
            "assistants.warnings.manage": True,
            "spec.view_claimable": True,
            "spec.view_self_sessions": True,
            "spec.claim.main": True,
            "spec.claim.probation": True,
            "spec.unclaim.self": True,
            "spec.unclaim.any": True,
            "events.view": True,
            "events.join.self": True,
            "events.leave.self": True,
            "events.create": True,
            "events.manage": True,
            "events.update": True,
            "events.spec.manage": True,
            "events.leave.any": True,
            "streamers.create": True,
            "streamers.update": True,
            "streamers.delete": True,
            "guild.view": True,
            "guild.settings.view": True,
            "guild.settings.update": True,
            "guild.templates.view": True,
            "guild.templates.update": True,
            "guild.rates.view": True,
            "guild.rates.update": True,
            "notifications.render": True,
        },
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
    ) -> FastAPI:
        app = FastAPI()
        for router in routers:
            app.include_router(router, prefix="/api")

        app.state.database = fake_db
        app.state.auth = fake_auth
        app.state.broker = fake_broker if include_broker else None

        app.state.test_current_user = current_user or deepcopy(default_current_user)

        async def _override_current_user() -> dict[str, Any]:
            return app.state.test_current_user

        async def _override_db(request: Request) -> FakeDB:
            return request.app.state.database

        async def _override_auth(request: Request) -> FakeAuth:
            return request.app.state.auth

        async def _override_broker(request: Request) -> FakeBroker | None:
            return request.app.state.broker

        # Use async dependency overrides to avoid anyio threadpool hangs in this env.
        app.dependency_overrides[dependencies.get_current_user] = _override_current_user
        app.dependency_overrides[dependencies.get_current_principal] = _override_current_user
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
        base_user: dict[str, Any] = {
            "id": 1,
            "username": "creator",
            "nickname": "Creator",
            "role": "manager",
            "principal_type": "user",
            "discord_id": 1001,
            "require_password_change": False,
            "permissions": {
                "dashboard.view": True,
                "streamers.view": True,
                "admin.users.create": True,
                "logs.admin.view": True,
                "logs.pr_actions.view": True,
                "assistants.view": True,
                "assistants.create": True,
                "assistants.update": True,
                "assistants.delete": True,
                "assistants.sessions.view": True,
                "assistants.sessions.manage": True,
                "assistants.logs.view": True,
                "assistants.points.manage": True,
                "assistants.sanctions.manage": True,
                "assistants.warnings.manage": True,
                "spec.view_claimable": True,
                "spec.view_self_sessions": True,
                "spec.claim.main": True,
                "spec.claim.probation": True,
                "spec.unclaim.self": True,
                "spec.unclaim.any": True,
                "events.view": True,
                "events.join.self": True,
                "events.leave.self": True,
                "events.create": True,
                "events.manage": True,
                "events.update": True,
                "events.spec.manage": True,
                "events.leave.any": True,
                "streamers.create": True,
                "streamers.update": True,
                "streamers.delete": True,
                "guild.view": True,
                "guild.settings.view": True,
                "guild.settings.update": True,
                "guild.templates.view": True,
                "guild.templates.update": True,
                "guild.rates.view": True,
                "guild.rates.update": True,
                "notifications.render": True,
            },
        }
        base_user.update(overrides)
        app.state.test_current_user = base_user
        return base_user

    return _set_current_user
