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

@pytest.fixture
def anyio_backend():
    return "asyncio"

import dependencies  # noqa: E402
from routes.admin import router as admin_router  # noqa: E402
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
        "current_stream_priority_override": None,
        "current_stream_pr_slots_override": None,
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
        self.raise_on_create_or_update_assistant: Exception | None = None
        self.raise_on_log_admin_action: Exception | None = None
        self._broker: FakeBroker | None = None
        self.outbox_messages: list[dict[str, Any]] = []
        self.next_outbox_message_id = 1

        # Assistants/permissions
        self.assistants_by_id: dict[int, dict[str, Any]] = {}
        self.assistant_logs_by_id: dict[int, list[dict[str, Any]]] = {}
        self.assistant_sessions_by_id: dict[int, list[dict[str, Any]]] = {}
        self.manual_sessions: list[dict[str, Any]] = []
        self.assistant_day_point_adjustments: dict[tuple[int, str], float] = {}
        self.assistant_day_mchat: dict[tuple[int, str], int] = {}
        self.assistant_day_spec_hours: dict[tuple[int, str], float] = {}
        self.assistant_day_complaints: dict[tuple[int, str], int] = {}
        self.assistant_day_status_overrides: dict[tuple[int, str], dict[str, Any]] = {}
        self.assistant_weekly_reviews: dict[tuple[int, str], dict[str, Any]] = {}
        self.weekly_today: date = date(2026, 3, 19)
        self.weekly_payout_type_rules: dict[str, str] = _default_weekly_payout_type_rules()
        self.weekly_payout_amount_rules: dict[tuple[str, str, str], str] = (
            _default_weekly_payout_amount_rules()
        )
        self.weekly_payout_servers: list[str] = [f"RU{i}" for i in range(1, 19)]
        self.assistant_sanctions: dict[int, dict[str, Any]] = {}
        self.sanction_reliefs: list[dict[str, Any]] = []
        self.next_sanction_id = 1
        self.monthly_sanction_policies: dict[str, dict[str, Any]] = {}
        self.monthly_check_rules: dict[str, list[dict[str, Any]]] = {}
        self.current_sanction_policy: dict[str, Any] = _default_sanction_policy()
        self.current_check_rules: list[dict[str, Any]] = _default_check_rules()
        self.sanction_nightly_runs: dict[str, dict[str, Any]] = {}
        self.queued_sanction_batches: dict[int, dict[str, Any]] = {}
        self.next_batch_id = 1
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
                "returns.view": True,
                "returns.create": True,
                "returns.execute": True,
                "returns.history.view": True,
                "returns.manage.self": True,
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
                "returns.view": True,
                "returns.create": True,
                "returns.execute": True,
                "returns.history.view": True,
                "returns.manage.self": True,
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
                "returns.view": True,
                "returns.create": True,
                "returns.execute": True,
                "returns.history.view": True,
                "returns.manage.self": True,
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
                "assistants.weekly.view": True,
                "assistants.weekly.manage": True,
                "returns.view": True,
                "returns.create": True,
                "returns.execute": True,
                "returns.history.view": True,
                "returns.manage.self": True,
                "returns.manage.any": True,
            },
            "developer": {
                "admin.users.create": True,
                "logs.admin.view": True,
                "monitoring.view": True,
                "notifications.render": True,
                "streamers.status.update": True,
                "spec.claim.probation": True,
                "returns.view": True,
                "returns.create": True,
                "returns.execute": True,
                "returns.history.view": True,
                "returns.manage.self": True,
                "returns.manage.any": True,
                "assistants.weekly.view": True,
                "assistants.weekly.manage": True,
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
        self.service_overview_stats: dict[str, Any] = {
            "streamers_total": 0,
            "streamers_online": 0,
            "gta_online": 0,
            "active_spec_sessions": 0,
            "probation_sessions": 0,
            "active_events": 0,
            "assistants_total": 0,
            "web_users_total": 0,
            "admin_actions_24h": 0,
        }

        # Returns
        self.punishment_returns: dict[int, dict[str, Any]] = {}
        self.next_punishment_return_id = 1

    async def _stage_outbox_events(
        self,
        outbox_events: list[dict[str, Any]] | None = None,
    ) -> None:
        if not outbox_events:
            return

        for event in outbox_events:
            record = {
                "id": self.next_outbox_message_id,
                "routing_key": str(event.get("routing_key") or ""),
                "payload": deepcopy(event.get("payload") or {}),
                "status": "sent" if self._broker is not None else "pending",
                "created_at": _now(),
                "sent_at": _now() if self._broker is not None else None,
            }
            self.next_outbox_message_id += 1
            self.outbox_messages.append(record)
            if self._broker is not None:
                await self._broker.publish(record["routing_key"], dict(record["payload"]))

    async def _stage_streamer_status_events(
        self,
        *,
        streamer_id: int,
        old_state: dict[str, Any],
        new_state: dict[str, Any],
        trace_id: str | None,
    ) -> None:
        if not trace_id:
            return

        old_is_online = bool(old_state.get("is_online"))
        new_is_online = bool(new_state.get("is_online"))
        old_game_id = old_state.get("game_id")
        new_game_id = new_state.get("game_id")
        streamer_name = old_state.get("streamer_name") or new_state.get("streamer_name")

        if new_is_online and not old_is_online:
            await self._stage_outbox_events(
                [
                    {
                        "routing_key": "stream.state.online",
                        "payload": {
                            "event": "online",
                            "streamer_id": streamer_id,
                            "streamer_name": streamer_name,
                            "is_online": True,
                            "game_id": new_game_id,
                            "game_name": new_state.get("game_name"),
                            "stream_title": new_state.get("stream_title"),
                            "thumbnail_url": new_state.get("stream_thumbnail_url"),
                            "trace_id": trace_id,
                        },
                    }
                ]
            )
            return

        if not new_is_online and old_is_online:
            await self._stage_outbox_events(
                [
                    {
                        "routing_key": "stream.state.offline",
                        "payload": {
                            "event": "offline",
                            "streamer_id": streamer_id,
                            "streamer_name": streamer_name,
                            "is_online": False,
                            "trace_id": trace_id,
                        },
                    }
                ]
            )
            return

        if new_is_online and old_is_online and str(old_game_id or "") != str(new_game_id or ""):
            await self._stage_outbox_events(
                [
                    {
                        "routing_key": "stream.state.category",
                        "payload": {
                            "event": "category_change",
                            "streamer_id": streamer_id,
                            "streamer_name": streamer_name,
                            "old_game_id": str(old_game_id) if old_game_id is not None else None,
                            "new_game_id": str(new_game_id) if new_game_id is not None else None,
                            "new_game_name": new_state.get("game_name"),
                            "stream_title": new_state.get("stream_title"),
                            "thumbnail_url": new_state.get("stream_thumbnail_url"),
                            "trace_id": trace_id,
                        },
                    }
                ]
            )

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

    async def create_user_with_assistant(
        self,
        discord_id: int,
        username: str,
        password_hash: str,
        nickname: str,
        role: str,
        appointed_at: date | None = None,
        experience_days: int = 0,
        created_by: int | None = None,
    ) -> int:
        await self.create_user(
            discord_id=discord_id,
            username=username,
            password_hash=password_hash,
            created_by=created_by,
        )
        try:
            await self.create_or_update_assistant(
                pr_id=discord_id,
                nickname=nickname,
                role=role,
                experience_days=experience_days,
                appointed_at=appointed_at,
            )
        except Exception:
            self.users_by_username.pop(username, None)
            self.users_by_discord.pop(discord_id, None)
            self.users_by_id.pop(discord_id, None)
            raise
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

    async def find_session_by_refresh_hash(
        self, token_hash: str
    ) -> dict[str, Any] | None:
        for session in self.sessions:
            if session.get("refresh_token_hash") == token_hash:
                return deepcopy(session)
        return None

    async def rotate_session(
        self,
        old_session_id: int,
        old_token_hash: str,
        new_token_hash: str,
        new_expires_at: datetime,
        new_ip: str | None,
        new_user_agent: str | None,
    ) -> int | None:
        old_session: dict[str, Any] | None = None
        for session in self.sessions:
            if int(session.get("id") or 0) == int(old_session_id):
                old_session = session
                break

        if (
            old_session is None
            or old_session.get("refresh_token_hash") != old_token_hash
            or old_session.get("revoked")
            or old_session.get("replaced_by_hash")
        ):
            return None

        old_session["replaced_by_hash"] = new_token_hash
        old_session["revoked"] = True
        old_session["revoked_at"] = _now()
        old_session["last_ip"] = new_ip
        old_session["user_agent"] = new_user_agent

        new_session_id = len(self.sessions) + 1
        self.sessions.append(
            {
                "id": new_session_id,
                "user_id": old_session["user_id"],
                "refresh_token_hash": new_token_hash,
                "family_id": old_session["family_id"],
                "expires_at": new_expires_at,
                "client_ip": old_session.get("client_ip"),
                "last_ip": new_ip,
                "user_agent": new_user_agent,
                "revoked": False,
                "replaced_by_hash": None,
                "revoked_at": None,
                "created_at": _now(),
            }
        )
        return new_session_id

    async def revoke_session_family(self, family_id: str) -> None:
        for session in self.sessions:
            if session.get("family_id") == family_id:
                session["revoked"] = True
                session["revoked_at"] = _now()

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
        if self.raise_on_log_admin_action:
            raise self.raise_on_log_admin_action
        self.logged_actions.append(kwargs)

    async def log_admin_action_v2(self, **kwargs: Any) -> None:
        if self.raise_on_log_admin_action:
            raise self.raise_on_log_admin_action
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
    # Punishment Returns
    # ---------------------------------------------------------------------

    async def create_punishment_return(
        self,
        *,
        punishment_type: str,
        static: int,
        server: int,
        duration: int,
        remove_reason: str,
        discord_message_url: str | None,
        removed_by_id: int,
        removed_by_name: str,
    ) -> dict[str, Any] | None:
        return_id = self.next_punishment_return_id
        self.next_punishment_return_id += 1
        now = _now()
        record = {
            "id": return_id,
            "punishment_type": punishment_type,
            "static": int(static),
            "server": int(server),
            "duration": int(duration),
            "remove_reason": remove_reason,
            "discord_message_url": discord_message_url,
            "removed_by_id": int(removed_by_id),
            "removed_by_name": removed_by_name,
            "removed_at": now,
            "claimed_by_id": None,
            "claimed_by_name": None,
            "claimed_at": None,
            "completed_by_id": None,
            "completed_by_name": None,
            "completed_at": None,
            "status": "pending",
            "created_at": now,
            "updated_at": now,
        }
        self.punishment_returns[return_id] = record
        return deepcopy(record)

    async def get_punishment_return(self, return_id: int) -> dict[str, Any] | None:
        record = self.punishment_returns.get(int(return_id))
        return deepcopy(record) if record else None

    async def list_punishment_returns_queue(self) -> list[dict[str, Any]]:
        now = _now()

        def sort_key(item: dict[str, Any]) -> tuple[int, datetime, int]:
            status = str(item.get("status"))
            removed_at = item.get("removed_at") or now
            ready = removed_at + timedelta(hours=12) <= now
            if status == "pending" and ready:
                rank = 0
            elif status == "claimed":
                rank = 1
            else:
                rank = 2
            return rank, removed_at, int(item.get("id") or 0)

        rows = [
            deepcopy(row)
            for row in self.punishment_returns.values()
            if row.get("status") in {"pending", "claimed"}
        ]
        rows.sort(key=sort_key)
        return rows

    async def claim_punishment_return(
        self,
        return_id: int,
        *,
        claimed_by_id: int,
        claimed_by_name: str,
    ) -> dict[str, Any] | None:
        record = self.punishment_returns.get(int(return_id))
        if not record or record.get("status") != "pending":
            return None
        removed_at = record.get("removed_at") or _now()
        if removed_at + timedelta(hours=12) > _now():
            return None
        record["status"] = "claimed"
        record["claimed_by_id"] = int(claimed_by_id)
        record["claimed_by_name"] = claimed_by_name
        record["claimed_at"] = _now()
        record["updated_at"] = _now()
        return deepcopy(record)

    async def complete_punishment_return(
        self,
        return_id: int,
        *,
        completed_by_id: int,
        completed_by_name: str,
        claimer_only: bool = True,
    ) -> dict[str, Any] | None:
        record = self.punishment_returns.get(int(return_id))
        if not record or record.get("status") != "claimed":
            return None
        if claimer_only and int(record.get("claimed_by_id") or 0) != int(completed_by_id):
            return None
        record["status"] = "completed"
        record["completed_by_id"] = int(completed_by_id)
        record["completed_by_name"] = completed_by_name
        record["completed_at"] = _now()
        record["updated_at"] = _now()
        return deepcopy(record)

    async def update_punishment_return(
        self,
        return_id: int,
        updates: dict[str, Any],
    ) -> dict[str, Any] | None:
        record = self.punishment_returns.get(int(return_id))
        if not record:
            return None
        for key in [
            "punishment_type",
            "static",
            "server",
            "duration",
            "remove_reason",
            "discord_message_url",
        ]:
            if key in updates:
                record[key] = updates[key]
        record["updated_at"] = _now()
        return deepcopy(record)

    async def release_punishment_return(
        self,
        return_id: int,
        *,
        claimed_by_id: int,
        claimer_only: bool = True,
    ) -> dict[str, Any] | None:
        record = self.punishment_returns.get(int(return_id))
        if not record or record.get("status") != "claimed":
            return None
        if claimer_only and int(record.get("claimed_by_id") or 0) != int(claimed_by_id):
            return None
        record["status"] = "pending"
        record["claimed_by_id"] = None
        record["claimed_by_name"] = None
        record["claimed_at"] = None
        record["updated_at"] = _now()
        return deepcopy(record)

    async def delete_punishment_return(self, return_id: int) -> bool:
        return self.punishment_returns.pop(int(return_id), None) is not None

    async def get_punishment_return_history(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        filters = filters or {}
        rows = [
            deepcopy(row)
            for row in self.punishment_returns.values()
            if row.get("status") == "completed"
        ]

        if filters.get("static") is not None:
            rows = [row for row in rows if int(row.get("static") or 0) == int(filters["static"])]
        if filters.get("server") is not None:
            rows = [row for row in rows if int(row.get("server") or 0) == int(filters["server"])]
        if filters.get("punishment_type"):
            rows = [row for row in rows if row.get("punishment_type") == filters["punishment_type"]]
        if filters.get("removed_by_name"):
            needle = str(filters["removed_by_name"]).lower()
            rows = [row for row in rows if needle in str(row.get("removed_by_name") or "").lower()]
        if filters.get("completed_by_name"):
            needle = str(filters["completed_by_name"]).lower()
            rows = [row for row in rows if needle in str(row.get("completed_by_name") or "").lower()]
        if filters.get("date_from"):
            rows = [row for row in rows if row.get("completed_at") and row["completed_at"] >= filters["date_from"]]
        if filters.get("date_to"):
            rows = [row for row in rows if row.get("completed_at") and row["completed_at"] <= filters["date_to"]]

        rows.sort(key=lambda row: (row.get("completed_at") or _now(), row.get("id") or 0), reverse=True)
        return {
            "items": rows[offset : offset + limit],
            "total": len(rows),
        }

    # ---------------------------------------------------------------------
    # Assistants
    # ---------------------------------------------------------------------
    def _recompute_assistant_totals(self, pr_id: int) -> None:
        assistant = self.assistants_by_id.get(pr_id)
        if not assistant:
            return

        auto_points_total = round(float(assistant.get("auto_points_total", 0.0)), 4)
        manual_points_total = round(
            sum(
                value
                for (assistant_id, _work_date), value in self.assistant_day_point_adjustments.items()
                if assistant_id == pr_id
            ),
            4,
        )

        active_sanctions = [
            sanction
            for sanction in self.assistant_sanctions.values()
            if int(sanction["assistant_id"]) == int(pr_id)
        ]
        point_penalty = round(
            sum(
                sanction["active_amount"]
                for sanction in active_sanctions
                if sanction["kind"] == "point"
            ),
            4,
        )
        percent_penalty = round(
            sum(
                sanction["active_amount"]
                for sanction in active_sanctions
                if sanction["kind"] == "percent"
            ),
            4,
        )
        check_marks = round(
            sum(
                sanction["active_amount"]
                for sanction in active_sanctions
                if sanction["kind"] == "check"
            ),
            4,
        )
        oral_warnings = int(
            sum(
                sanction["active_amount"]
                for sanction in active_sanctions
                if sanction["kind"] == "oral"
            )
        )
        strict_warnings = int(
            sum(
                sanction["active_amount"]
                for sanction in active_sanctions
                if sanction["kind"] == "strict"
            )
        )

        assistant["auto_points_total"] = auto_points_total
        assistant["manual_points_adjustment"] = manual_points_total
        assistant["total_points"] = round(auto_points_total + manual_points_total, 4)
        assistant["penalty_points"] = point_penalty
        assistant["penalty_percent"] = percent_penalty
        assistant["display_points"] = round(
            float(assistant["total_points"]) - point_penalty,
            4,
        )
        assistant["check_marks"] = check_marks
        assistant["warnings_units"] = strict_warnings * 2 + oral_warnings
        assistant["strict_warnings"] = strict_warnings
        assistant["oral_warnings"] = oral_warnings
        assistant["warnings_display"] = f"{strict_warnings}/2 {oral_warnings}/2"
        assistant["total_spec_hours"] = round(
            float(assistant.get("total_spec_seconds", 0)) / 3600,
            2,
        )
        assistant["gross_points"] = assistant["total_points"]
        assistant["net_points"] = assistant["display_points"]
        assistant["active_point_penalty"] = point_penalty
        assistant["active_percent_penalty"] = percent_penalty
        assistant["active_checks"] = check_marks
        assistant["active_warning_units"] = assistant["warnings_units"]
        assistant["active_strict_warnings"] = strict_warnings
        assistant["active_oral_warnings"] = oral_warnings
        assistant["active_warnings_display"] = assistant["warnings_display"]

    def _assistant_public_view(self, assistant: dict[str, Any]) -> dict[str, Any]:
        public = deepcopy(assistant)
        public.pop("auto_points_total", None)
        public.pop("manual_points_adjustment", None)
        public.pop("total_points", None)
        public.pop("penalty_points", None)
        public.pop("penalty_percent", None)
        public.pop("display_points", None)
        public.pop("check_marks", None)
        public.pop("warnings_units", None)
        public.pop("strict_warnings", None)
        public.pop("oral_warnings", None)
        public.pop("warnings_display", None)
        return public

    async def get_all_assistants(self) -> list[dict[str, Any]]:
        for pr_id in list(self.assistants_by_id.keys()):
            self._recompute_assistant_totals(pr_id)
        return [self._assistant_public_view(a) for a in self.assistants_by_id.values()]

    async def get_assistant(self, pr_id: int) -> dict[str, Any] | None:
        assistant = self.assistants_by_id.get(pr_id)
        if assistant:
            self._recompute_assistant_totals(pr_id)
        return self._assistant_public_view(assistant) if assistant else None

    async def create_or_update_assistant(
        self,
        pr_id: int,
        nickname: str,
        role: str,
        experience_days: int = 0,
        appointed_at: date | None = None,
    ) -> bool:
        if self.raise_on_create_or_update_assistant:
            raise self.raise_on_create_or_update_assistant
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
            "check_marks": existing.get("check_marks", 0.0),
            "total_spec_hours": round(existing.get("total_spec_seconds", 0) / 3600, 2),
        }
        self._recompute_assistant_totals(pr_id)
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
            self._recompute_assistant_totals(pr_id)

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
        assistant["session_count"] = int(assistant.get("session_count", 0)) + 1
        assistant["total_spec_seconds"] = int(assistant.get("total_spec_seconds", 0)) + duration_seconds
        self._recompute_assistant_totals(pr_id)
        return True

    async def upsert_assistant_day_point_adjustment(
        self,
        assistant_id: int,
        work_date: date,
        delta_points: float,
    ) -> dict[str, Any]:
        key = (assistant_id, work_date.isoformat())
        self.assistant_day_point_adjustments[key] = round(float(delta_points), 4)
        self._recompute_assistant_totals(assistant_id)
        return {
            "assistant_id": assistant_id,
            "work_date": work_date.isoformat(),
            "delta_points": self.assistant_day_point_adjustments[key],
        }

    async def upsert_assistant_day_mchat(
        self,
        assistant_id: int,
        work_date: date,
        mchat_count: int,
    ) -> dict[str, Any]:
        key = (assistant_id, work_date.isoformat())
        self.assistant_day_mchat[key] = int(mchat_count)
        return {
            "assistant_id": assistant_id,
            "work_date": work_date.isoformat(),
            "mchat_count": int(mchat_count),
        }

    async def get_assistant_day_status(
        self,
        assistant_id: int,
        work_date: date,
    ) -> dict[str, Any]:
        work_date_iso = work_date.isoformat()
        delta = self.assistant_day_point_adjustments.get((assistant_id, work_date_iso), 0.0)
        mchat_count = self.assistant_day_mchat.get((assistant_id, work_date_iso), 0)
        return {
            "assistant_id": assistant_id,
            "work_date": work_date_iso,
            "spec_seconds_on_day": 0,
            "spec_hours_on_day": 0.0,
            "spec_points_auto": 0.0,
            "manual_points_delta": round(float(delta), 4),
            "mchat_count": mchat_count,
            "complaints_count": 0,
            "check_immunity": False,
            "point_immunity": False,
            "percent_immunity": False,
            "streak_check_days": 0,
            "streak_point_days": 0,
            "streak_percent_days": 0,
        }

    def _weekly_role_group(self, role: str | None) -> str:
        if role == "junior_employee":
            return "junior"
        if role == "senior_employee":
            return "Senior"
        return "default"

    def _build_weekly_payout_preview(
        self,
        *,
        assistant_role: str | None,
        selected_result: str | None,
        payout_type: str | None,
        payout_server: str | None,
        payout_static: str | None,
    ) -> dict[str, Any]:
        normalized_result = _canonical_weekly_result(selected_result)
        command_name = (
            self.weekly_payout_type_rules.get(payout_type) if payout_type else None
        )
        normalized_static = str(payout_static or "").strip() or None
        preview = {
            "type": payout_type,
            "server": payout_server,
            "static": normalized_static,
            "command_name": command_name,
            "amount": None,
            "command": None,
            "command_available": False,
            "command_unavailable_reason": None,
            "role_group": self._weekly_role_group(assistant_role),
        }
        if normalized_result not in {"Актив", "Ультра-Актив"}:
            preview["command_unavailable_reason"] = "selected_result_not_payout_eligible"
            return preview
        if not payout_type or not payout_server or not normalized_static:
            preview["command_unavailable_reason"] = "incomplete_payout_data"
            return preview
        if not command_name:
            preview["command_unavailable_reason"] = "payout_type_rule_missing"
            return preview
        amount = self.weekly_payout_amount_rules.get(
            (self._weekly_role_group(assistant_role), payout_type, normalized_result)
        )
        if not amount:
            preview["command_unavailable_reason"] = "amount_rule_missing"
            return preview
        preview["amount"] = amount
        preview["command"] = (
            f"{payout_server}:{command_name} {normalized_static} {amount} pr-assist_byStynee"
        )
        preview["command_available"] = True
        return preview

    def _calculate_weekly_suggested_result(
        self,
        *,
        active_day_records: list[dict[str, Any]],
        total_spec_hours: float,
        total_mchat: int,
        total_complaints: int,
        count_p: int,
        count_o: int,
    ) -> dict[str, Any]:
        if not active_day_records:
            return {
                "suggested_result": None,
                "suggested_reason": "unconfigured",
                "metric_hits": 0,
                "weekly_norm_spec": 0.0,
                "weekly_norm_mchat": 0,
                "weekly_norm_complaints": 0,
            }
        if any(
            float(day.get("daily_norm_spec") or 0) <= 0
            or int(day.get("daily_norm_mchat") or 0) <= 0
            or int(day.get("daily_norm_complaints") or 0) <= 0
            for day in active_day_records
        ):
            return {
                "suggested_result": None,
                "suggested_reason": "unconfigured",
                "metric_hits": 0,
                "weekly_norm_spec": 0.0,
                "weekly_norm_mchat": 0,
                "weekly_norm_complaints": 0,
            }

        weekly_norm_spec = round(
            sum(float(day.get("daily_norm_spec") or 0) for day in active_day_records),
            4,
        )
        weekly_norm_mchat = sum(
            int(day.get("daily_norm_mchat") or 0) for day in active_day_records
        )
        weekly_norm_complaints = sum(
            int(day.get("daily_norm_complaints") or 0) for day in active_day_records
        )
        metric_hits = 0
        if total_spec_hours + 1e-9 >= weekly_norm_spec:
            metric_hits += 1
        if total_mchat >= weekly_norm_mchat:
            metric_hits += 1
        if total_complaints >= weekly_norm_complaints:
            metric_hits += 1

        ultra_daily_ok = all(
            (
                day.get("resolved_status") == "O"
                or (
                    float(day.get("spec_hours") or 0) + 1e-9 >= float(day.get("daily_norm_spec") or 0)
                    and int(day.get("mchat_count") or 0) >= int(day.get("daily_norm_mchat") or 0)
                    and int(day.get("complaints_count") or 0) >= int(day.get("daily_norm_complaints") or 0)
                )
            )
            for day in active_day_records
        )
        ultra_boosted = (
            total_spec_hours + 1e-9 >= round(weekly_norm_spec * 1.5, 4)
            or total_mchat >= weekly_norm_mchat * 2
            or total_complaints >= weekly_norm_complaints * 2
        )

        if count_p == 0 and count_o <= 1 and ultra_daily_ok and ultra_boosted:
            suggested_result = "Ультра-Актив"
        elif metric_hits == 3 and count_p <= 1:
            suggested_result = "Актив"
        elif metric_hits == 2 and count_p <= 2:
            suggested_result = "Инактив/Актив"
        else:
            suggested_result = "Инактив"

        return {
            "suggested_result": suggested_result,
            "suggested_reason": None,
            "metric_hits": metric_hits,
            "weekly_norm_spec": weekly_norm_spec,
            "weekly_norm_mchat": weekly_norm_mchat,
            "weekly_norm_complaints": weekly_norm_complaints,
        }

    def _build_assistant_weekly_payload(
        self,
        *,
        week_start: date,
        assistant_id: int | None,
        include_day_matrix: bool,
        include_payout_options: bool,
    ) -> dict[str, Any]:
        normalized_week_start = _week_start(week_start)
        week_end = normalized_week_start + timedelta(days=6)
        week_days = [normalized_week_start + timedelta(days=i) for i in range(7)]
        assistants = []
        for item in self.assistants_by_id.values():
            current_assistant_id = int(item["pr_id"])
            if assistant_id is not None and current_assistant_id != assistant_id:
                continue
            appointed_at = item.get("appointed_at") or item.get("added_at") or _now()
            appointed_date = appointed_at.date() if isinstance(appointed_at, datetime) else normalized_week_start
            dismissed_at = item.get("dismissed_at")
            dismissed_date = dismissed_at.date() if isinstance(dismissed_at, datetime) else None
            if appointed_date > week_end:
                continue
            if dismissed_date is not None and dismissed_date < normalized_week_start:
                continue
            assistants.append(item)

        day_headers = [
            {
                "work_date": work_date.isoformat(),
                "weekday_index": index,
                "weekday_short": ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")[index],
                "label_short": work_date.strftime("%d.%m"),
            }
            for index, work_date in enumerate(week_days)
        ]

        items: list[dict[str, Any]] = []
        for assistant in assistants:
            current_assistant_id = int(assistant["pr_id"])
            appointed_at = assistant.get("appointed_at") or assistant.get("added_at") or _now()
            appointed_date = appointed_at.date() if isinstance(appointed_at, datetime) else normalized_week_start
            dismissed_at = assistant.get("dismissed_at")
            dismissed_date = dismissed_at.date() if isinstance(dismissed_at, datetime) else None
            day_payloads: list[dict[str, Any]] = []
            active_day_records: list[dict[str, Any]] = []
            total_spec_hours = 0.0
            total_mchat = 0
            total_complaints = 0
            count_p = 0
            count_u = 0
            count_o = 0

            for index, work_date in enumerate(week_days):
                work_date_iso = work_date.isoformat()
                month_policy = self.monthly_sanction_policies.get(
                    work_date.replace(day=1).isoformat(),
                    self.current_sanction_policy,
                )
                daily_norm_spec = round(float(month_policy.get("daily_norm_spec") or 0), 4)
                daily_norm_mchat = int(month_policy.get("daily_norm_mchat") or 0)
                daily_norm_complaints = int(month_policy.get("daily_norm_complaints") or 0)
                is_roster_day = work_date >= appointed_date and (
                    dismissed_date is None or work_date <= dismissed_date
                )
                spec_hours = round(
                    float(self.assistant_day_spec_hours.get((current_assistant_id, work_date_iso), 0.0)),
                    4,
                )
                mchat_count = int(self.assistant_day_mchat.get((current_assistant_id, work_date_iso), 0))
                complaints_count = int(
                    self.assistant_day_complaints.get((current_assistant_id, work_date_iso), 0)
                )
                override = self.assistant_day_status_overrides.get(
                    (current_assistant_id, work_date_iso),
                    {},
                )
                has_manual_override = (
                    current_assistant_id,
                    work_date_iso,
                ) in self.assistant_day_status_overrides
                raw_manual_status = override.get("manual_status")
                manual_status = None if raw_manual_status in (None, "NONE") else raw_manual_status
                auto_status = None
                if (
                    is_roster_day
                    and work_date < self.weekly_today
                    and spec_hours + 1e-9 < daily_norm_spec
                ):
                    auto_status = "P"
                resolved_status = manual_status if has_manual_override else auto_status
                status_source = "manual" if has_manual_override else ("auto" if auto_status else "none")
                if is_roster_day and resolved_status == "P":
                    count_p += 1
                elif is_roster_day and resolved_status == "U":
                    count_u += 1
                elif is_roster_day and resolved_status == "O":
                    count_o += 1

                total_spec_hours = round(total_spec_hours + spec_hours, 4)
                total_mchat += mchat_count
                total_complaints += complaints_count

                day_payload = {
                    "work_date": work_date_iso,
                    "weekday_index": index,
                    "is_roster_day": is_roster_day,
                    "spec_seconds": int(round(spec_hours * 3600)),
                    "spec_hours": spec_hours,
                    "mchat_count": mchat_count,
                    "complaints_count": complaints_count,
                    "daily_norm_spec": daily_norm_spec,
                    "daily_norm_mchat": daily_norm_mchat,
                    "daily_norm_complaints": daily_norm_complaints,
                    "manual_status": manual_status,
                    "auto_status": auto_status,
                    "resolved_status": resolved_status,
                    "status_source": status_source,
                    "manual_status_updated_at": override.get("updated_at"),
                    "manual_status_updated_by_id": override.get("updated_by_id"),
                }
                day_payloads.append(day_payload)
                if is_roster_day:
                    active_day_records.append(day_payload)

            suggestion = self._calculate_weekly_suggested_result(
                active_day_records=active_day_records,
                total_spec_hours=total_spec_hours,
                total_mchat=total_mchat,
                total_complaints=total_complaints,
                count_p=count_p,
                count_o=count_o,
            )
            review = self.assistant_weekly_reviews.get(
                (current_assistant_id, normalized_week_start.isoformat()),
                {},
            )
            selected_result = _canonical_weekly_result(review.get("selected_result"))
            payout = self._build_weekly_payout_preview(
                assistant_role=assistant.get("role"),
                selected_result=selected_result,
                payout_type=review.get("payout_type"),
                payout_server=review.get("payout_server"),
                payout_static=review.get("payout_static"),
            )
            row = {
                "assistant_id": current_assistant_id,
                "nickname": assistant.get("nickname"),
                "role": assistant.get("role"),
                "week_start": normalized_week_start.isoformat(),
                "week_end": week_end.isoformat(),
                "totals": {
                    "spec_hours": round(total_spec_hours, 4),
                    "mchat_count": total_mchat,
                    "complaints_count": total_complaints,
                },
                "counts": {
                    "P": count_p,
                    "U": count_u,
                    "O": count_o,
                },
                "suggested_result": suggestion["suggested_result"],
                "suggested_reason": suggestion["suggested_reason"],
                "suggestion_metrics": {
                    "metric_hits": suggestion["metric_hits"],
                    "weekly_norm_spec": suggestion["weekly_norm_spec"],
                    "weekly_norm_mchat": suggestion["weekly_norm_mchat"],
                    "weekly_norm_complaints": suggestion["weekly_norm_complaints"],
                },
                "selected_result": selected_result,
                "result_display": selected_result or suggestion["suggested_result"],
                "payout": payout,
                "payout_issue_status": str(review.get("payout_issue_status") or "pending"),
                "payout_issued_at": review.get("payout_issued_at"),
                "payout_issued_by_id": review.get("payout_issued_by_id"),
                "review_updated_at": review.get("updated_at"),
                "review_updated_by_id": review.get("updated_by_id"),
            }
            if include_day_matrix:
                row["days"] = day_payloads
            items.append(row)

        payload = {
            "week_start": normalized_week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "day_headers": day_headers,
            "items": items,
        }
        if include_payout_options:
            payload["payout_options"] = {
                "types": [
                    {"value": key, "command_name": value}
                    for key, value in self.weekly_payout_type_rules.items()
                ],
                "servers": list(self.weekly_payout_servers),
                "selected_results": [
                    "Ультра-Актив",
                    "Актив",
                    "Актив/Отпуск",
                    "Инактив",
                    "Инактив/Отпуск",
                    "Отпуск",
                    "Инактив/Актив",
                ],
                "manual_statuses": ["P", "U", "O"],
            }
        return payload

    async def get_current_assistant_weekly_overview(self) -> dict[str, Any]:
        return self._build_assistant_weekly_payload(
            week_start=self.weekly_today,
            assistant_id=None,
            include_day_matrix=True,
            include_payout_options=False,
        )

    async def get_assistant_weekly_admin_overview(
        self,
        *,
        week_start: date | None = None,
    ) -> dict[str, Any]:
        target_week_start = week_start or self.weekly_today
        return self._build_assistant_weekly_payload(
            week_start=target_week_start,
            assistant_id=None,
            include_day_matrix=False,
            include_payout_options=True,
        )

    async def get_assistant_weekly_admin_detail(
        self,
        *,
        assistant_id: int,
        week_start: date | None = None,
    ) -> dict[str, Any] | None:
        target_week_start = week_start or self.weekly_today
        payload = self._build_assistant_weekly_payload(
            week_start=target_week_start,
            assistant_id=assistant_id,
            include_day_matrix=True,
            include_payout_options=True,
        )
        if not payload["items"]:
            return None
        return {
            "week_start": payload["week_start"],
            "week_end": payload["week_end"],
            "day_headers": payload["day_headers"],
            "payout_options": payload["payout_options"],
            "detail": payload["items"][0],
        }

    async def save_assistant_weekly_admin_review(
        self,
        *,
        assistant_id: int,
        week_start: date,
        actor_id: int | None,
        day_overrides: list[dict[str, Any]],
        selected_result: str | None,
        payout_type: str | None,
        payout_server: str | None,
        payout_static: str | None,
    ) -> dict[str, Any]:
        if assistant_id not in self.assistants_by_id:
            raise ValueError("Ассистент не найден")
        normalized_week_start = _week_start(week_start)
        week_end = normalized_week_start + timedelta(days=6)
        normalized_result = _canonical_weekly_result(selected_result)
        normalized_static = str(payout_static or "").strip() or None
        if payout_server is not None and payout_server not in self.weekly_payout_servers:
            raise ValueError("Невалидный payout server")
        review_key = (assistant_id, normalized_week_start.isoformat())
        previous_review = dict(self.assistant_weekly_reviews.get(review_key, {}))
        previous_result = _canonical_weekly_result(previous_review.get("selected_result"))
        previous_static = str(previous_review.get("payout_static") or "").strip() or None
        payout_issue_reset = (
            bool(previous_review)
            and str(previous_review.get("payout_issue_status") or "pending") == "issued"
            and (
                previous_result != normalized_result
                or previous_review.get("payout_type") != payout_type
                or previous_review.get("payout_server") != payout_server
                or previous_static != normalized_static
            )
        )
        payout_issue_transition = None
        if payout_issue_reset:
            payout_issue_transition = {
                "from_status": "issued",
                "to_status": "pending",
                "issued_at": previous_review.get("payout_issued_at"),
                "issued_by_id": previous_review.get("payout_issued_by_id"),
                "generated_payout_command": self._build_weekly_payout_preview(
                    assistant_role=self.assistants_by_id[assistant_id].get("role"),
                    selected_result=previous_result,
                    payout_type=previous_review.get("payout_type"),
                    payout_server=previous_review.get("payout_server"),
                    payout_static=previous_static,
                ).get("command"),
                "auto_reset": True,
            }
        seen_dates: set[date] = set()
        for item in day_overrides:
            work_date = item.get("work_date")
            manual_status = item.get("manual_status")
            is_manual_override = bool(item.get("is_manual_override"))
            if work_date is None:
                raise ValueError("work_date is required")
            if work_date in seen_dates:
                raise ValueError("Повторяющиеся daily overrides недопустимы")
            seen_dates.add(work_date)
            if work_date < normalized_week_start or work_date > week_end:
                raise ValueError("work_date должен находиться внутри выбранной недели")
            key = (assistant_id, work_date.isoformat())
            if not is_manual_override:
                self.assistant_day_status_overrides.pop(key, None)
            else:
                self.assistant_day_status_overrides[key] = {
                    "manual_status": manual_status or "NONE",
                    "updated_at": _now(),
                    "updated_by_id": actor_id,
                }

        if (
            normalized_result is None
            and payout_type is None
            and payout_server is None
            and normalized_static is None
        ):
            self.assistant_weekly_reviews.pop(review_key, None)
        else:
            self.assistant_weekly_reviews[review_key] = {
                "selected_result": normalized_result,
                "payout_type": payout_type,
                "payout_server": payout_server,
                "payout_static": normalized_static,
                "payout_issue_status": "pending" if payout_issue_reset else str(previous_review.get("payout_issue_status") or "pending"),
                "payout_issued_at": None if payout_issue_reset else previous_review.get("payout_issued_at"),
                "payout_issued_by_id": None if payout_issue_reset else previous_review.get("payout_issued_by_id"),
                "updated_at": _now(),
                "updated_by_id": actor_id,
            }

        detail = await self.get_assistant_weekly_admin_detail(
            assistant_id=assistant_id,
            week_start=normalized_week_start,
        )
        assert detail is not None
        if payout_issue_transition:
            detail["payout_issue_transition"] = payout_issue_transition
        return detail

    async def save_assistant_weekly_payout_issue_status(
        self,
        *,
        assistant_id: int,
        week_start: date,
        actor_id: int | None,
        payout_issue_status: str,
    ) -> dict[str, Any]:
        if assistant_id not in self.assistants_by_id:
            raise ValueError("Ассистент не найден")
        normalized_week_start = _week_start(week_start)
        review_key = (assistant_id, normalized_week_start.isoformat())
        review = dict(self.assistant_weekly_reviews.get(review_key, {}))
        normalized_status = str(payout_issue_status or "pending")

        if not review:
            if normalized_status == "issued":
                raise ValueError("Нельзя отметить выдачу без сохранённой weekly review")
            detail = await self.get_assistant_weekly_admin_detail(
                assistant_id=assistant_id,
                week_start=normalized_week_start,
            )
            assert detail is not None
            return detail

        selected_result = _canonical_weekly_result(review.get("selected_result"))
        payout_preview = self._build_weekly_payout_preview(
            assistant_role=self.assistants_by_id[assistant_id].get("role"),
            selected_result=selected_result,
            payout_type=review.get("payout_type"),
            payout_server=review.get("payout_server"),
            payout_static=review.get("payout_static"),
        )
        current_status = str(review.get("payout_issue_status") or "pending")
        if normalized_status == current_status:
            detail = await self.get_assistant_weekly_admin_detail(
                assistant_id=assistant_id,
                week_start=normalized_week_start,
            )
            assert detail is not None
            return detail

        if normalized_status == "issued" and not payout_preview.get("command_available"):
            raise ValueError("Команда недоступна для выдачи")

        self.assistant_weekly_reviews[review_key] = {
            **review,
            "payout_issue_status": normalized_status,
            "payout_issued_at": _now() if normalized_status == "issued" else None,
            "payout_issued_by_id": actor_id if normalized_status == "issued" else None,
            "updated_at": _now(),
            "updated_by_id": actor_id,
        }
        detail = await self.get_assistant_weekly_admin_detail(
            assistant_id=assistant_id,
            week_start=normalized_week_start,
        )
        assert detail is not None
        detail["payout_issue_transition"] = {
            "from_status": current_status,
            "to_status": normalized_status,
            "issued_at": review.get("payout_issued_at"),
            "issued_by_id": review.get("payout_issued_by_id"),
            "generated_payout_command": payout_preview.get("command"),
            "auto_reset": False,
        }
        return detail

    @staticmethod
    def _normalize_manual_status(value: Any) -> str | None:
        normalized = str(value or "").strip().upper()
        if normalized in {"", "NONE"}:
            return None
        if normalized not in {"P", "U", "O"}:
            return None
        return normalized

    def _daily_norm_amount(
        self,
        *,
        metric: str,
        work_date: date,
        multiplier: float,
    ) -> float:
        month_policy = self.monthly_sanction_policies.get(
            work_date.replace(day=1).isoformat(),
            self.current_sanction_policy,
        )
        field_name = {
            "spec": "daily_norm_spec",
            "complaints": "daily_norm_complaints",
            "mchat": "daily_norm_mchat",
        }[metric]
        amount = float(month_policy.get(field_name) or 0) * float(multiplier)
        if metric == "spec":
            return round(amount, 4)
        return float(int(round(amount)))

    def _day_metric_amount(
        self,
        *,
        assistant_id: int,
        metric: str,
        work_date: date,
    ) -> float:
        key = (assistant_id, work_date.isoformat())
        if metric == "spec":
            return round(float(self.assistant_day_spec_hours.get(key, 0.0)), 4)
        if metric == "complaints":
            return float(int(self.assistant_day_complaints.get(key, 0)))
        return float(int(self.assistant_day_mchat.get(key, 0)))

    def _evaluate_workoff_item(
        self,
        *,
        assistant_id: int,
        item: dict[str, Any],
        evaluation_cutoff: date | None = None,
    ) -> dict[str, Any]:
        metric = str(item["metric"])
        period_start = item["period_start"]
        period_end = item["period_end"]
        cutoff = evaluation_cutoff or _now().date()
        required_work_days = (period_end - period_start).days + 1
        counted_projected_days = 0
        counted_work_days = 0
        uo_days_count = 0
        amount_done = 0.0
        target_amount = 0.0
        failed = False
        effective_period_end = period_end
        days: list[dict[str, Any]] = []
        cursor_day = period_start

        while counted_projected_days < required_work_days:
            override = self.assistant_day_status_overrides.get(
                (assistant_id, cursor_day.isoformat()),
                {},
            )
            manual_status = self._normalize_manual_status(override.get("manual_status"))
            is_leave_day = manual_status in {"U", "O"}
            actual_amount = None
            required_amount = None

            if is_leave_day:
                uo_days_count += 1
                counts_for_workoff = False
                day_status = "leave_skipped"
            else:
                counts_for_workoff = True
                required_amount = self._daily_norm_amount(
                    metric=metric,
                    work_date=cursor_day,
                    multiplier=float(item.get("multiplier") or 0),
                )
                target_amount += float(required_amount or 0)
                counted_projected_days += 1
                if cursor_day > cutoff:
                    day_status = "pending"
                else:
                    actual_amount = self._day_metric_amount(
                        assistant_id=assistant_id,
                        metric=metric,
                        work_date=cursor_day,
                    )
                    counted_work_days += 1
                    amount_done += float(actual_amount or 0)
                    if float(actual_amount or 0) + 1e-9 >= float(required_amount or 0):
                        day_status = "completed"
                    else:
                        day_status = "failed"
                        failed = True

            days.append(
                {
                    "date": cursor_day.isoformat(),
                    "manual_status": manual_status,
                    "counts_for_workoff": counts_for_workoff,
                    "required_amount": round(float(required_amount), 4)
                    if required_amount is not None and metric == "spec"
                    else (int(round(required_amount)) if required_amount is not None else None),
                    "actual_amount": round(float(actual_amount), 4)
                    if actual_amount is not None and metric == "spec"
                    else (int(round(actual_amount)) if actual_amount is not None else None),
                    "day_status": day_status,
                }
            )
            effective_period_end = cursor_day
            cursor_day += timedelta(days=1)

        if failed:
            status = "failed"
        elif cutoff < effective_period_end:
            status = "pending"
        else:
            status = "completed"

        normalized_target = round(target_amount, 4) if metric == "spec" else int(round(target_amount))
        normalized_done = round(amount_done, 4) if metric == "spec" else int(round(amount_done))
        remaining_amount = max(float(normalized_target) - float(normalized_done), 0.0)
        normalized_remaining = (
            round(remaining_amount, 4)
            if metric == "spec"
            else int(round(remaining_amount))
        )
        return {
            **deepcopy(item),
            "required_work_days": required_work_days,
            "counted_work_days": counted_work_days,
            "effective_period_end": effective_period_end.isoformat(),
            "uo_days_count": uo_days_count,
            "status": status,
            "days": days,
            "target_amount": normalized_target,
            "amount_done": normalized_done,
            "remaining_amount": normalized_remaining,
            "is_completed": status == "completed",
        }

    def _build_workoff_summary(
        self,
        *,
        assistant_id: int,
        workoff_items: list[dict[str, Any]],
        evaluation_cutoff: date | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        items = [
            self._evaluate_workoff_item(
                assistant_id=assistant_id,
                item=deepcopy(item),
                evaluation_cutoff=evaluation_cutoff,
            )
            for item in workoff_items
        ]
        summary = {
            "has_workoff": bool(items),
            "total_items": len(items),
            "completed_items": sum(1 for item in items if item.get("status") == "completed"),
            "items": deepcopy(items),
        }
        return items, summary

    def _get_sanction_workoff_state(
        self,
        *,
        sanction: dict[str, Any],
        evaluation_cutoff: date,
    ) -> dict[str, Any]:
        items, _summary = self._build_workoff_summary(
            assistant_id=int(sanction["assistant_id"]),
            workoff_items=list(sanction.get("workoff_items") or []),
            evaluation_cutoff=evaluation_cutoff,
        )
        if not items:
            return {
                "has_workoff": False,
                "items": [],
                "effective_period_end": None,
                "all_completed": False,
            }
        effective_period_end = max(item["effective_period_end"] for item in items)
        return {
            "has_workoff": True,
            "items": items,
            "effective_period_end": effective_period_end,
            "all_completed": all(item.get("status") == "completed" for item in items),
        }

    async def _apply_custom_workoff_relief(
        self,
        *,
        basis_date: date,
    ) -> dict[str, Any]:
        relieved: list[dict[str, Any]] = []
        for sanction in list(self.assistant_sanctions.values()):
            if float(sanction.get("active_amount") or 0) <= 0:
                continue
            state = self._get_sanction_workoff_state(
                sanction=sanction,
                evaluation_cutoff=basis_date,
            )
            if not state["has_workoff"]:
                continue
            effective_period_end = state.get("effective_period_end")
            if effective_period_end is None or effective_period_end > basis_date.isoformat():
                continue
            if not state.get("all_completed"):
                continue
            if any(
                int(relief["sanction_id"]) == int(sanction["sanction_id"])
                and relief["relief_type"] == "custom_workoff"
                for relief in self.sanction_reliefs
            ):
                continue
            await self.add_sanction_relief(
                sanction_id=int(sanction["sanction_id"]),
                amount=float(sanction["active_amount"]),
                relief_type="custom_workoff",
                basis_date=basis_date,
            )
            relieved.append(
                {
                    "assistant_id": int(sanction["assistant_id"]),
                    "sanction_id": int(sanction["sanction_id"]),
                    "kind": sanction["kind"],
                    "amount": sanction["amount_total"],
                    "effective_period_end": effective_period_end,
                }
            )
        return {"relieved": relieved}

    async def preview_workoff_for_assistants(
        self,
        *,
        assistant_ids: list[int],
        workoff_items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        previews: list[dict[str, Any]] = []
        for assistant_id in sorted({int(value) for value in assistant_ids}):
            assistant = self.assistants_by_id.get(assistant_id)
            if not assistant:
                continue
            items, _summary = self._build_workoff_summary(
                assistant_id=assistant_id,
                workoff_items=workoff_items,
            )
            previews.append(
                {
                    "assistant_id": assistant_id,
                    "nickname": assistant.get("nickname"),
                    "items": items,
                }
            )
        return previews

    async def get_assistant_sanctions_summary(
        self,
        assistant_id: int,
        as_of_date: date | None = None,
    ) -> dict[str, Any]:
        sanctions = await self.get_assistant_active_sanctions(assistant_id)
        summary = {
            "assistant_id": assistant_id,
            "as_of_date": (as_of_date or _now().date()).isoformat(),
            "check": 0.0,
            "point": 0.0,
            "percent": 0.0,
            "oral": 0.0,
            "strict": 0.0,
            "warnings_units": 0,
            "strict_warnings": 0,
            "oral_warnings": 0,
            "warnings_display": "0/2 0/2",
        }
        for sanction in sanctions:
            kind = sanction["kind"]
            summary[kind] = round(float(summary.get(kind, 0.0)) + float(sanction["active_amount"]), 4)
        summary["strict_warnings"] = int(summary["strict"])
        summary["oral_warnings"] = int(summary["oral"])
        summary["warnings_units"] = summary["strict_warnings"] * 2 + summary["oral_warnings"]
        summary["warnings_display"] = f"{summary['strict_warnings']}/2 {summary['oral_warnings']}/2"
        return summary

    async def get_assistant_active_sanctions(self, assistant_id: int) -> list[dict[str, Any]]:
        sanctions = []
        for sanction in self.assistant_sanctions.values():
            if int(sanction["assistant_id"]) != int(assistant_id) or float(sanction["active_amount"]) <= 0:
                continue
            payload = deepcopy(sanction)
            progress_items, progress_summary = self._build_workoff_summary(
                assistant_id=int(assistant_id),
                workoff_items=list(payload.get("workoff_items") or []),
            )
            payload["workoff_items"] = progress_items
            payload["workoff_progress_summary"] = progress_summary
            sanctions.append(payload)
        sanctions.sort(key=lambda item: int(item["sanction_id"]))
        return sanctions

    @staticmethod
    def _normalize_runtime_sanction(
        kind: str,
        amount: float | None,
        auto_relief_date: date | None,
    ) -> tuple[float, date | None]:
        if kind in FIXED_SIZE_SANCTION_KINDS:
            normalized_amount = 1.0
        else:
            if amount is None or float(amount) <= 0:
                raise ValueError("Для выбранной санкции требуется положительный размер")
            normalized_amount = round(float(amount), 4)
        normalized_auto_relief_date = auto_relief_date if kind in WARNING_SANCTION_KINDS else None
        if kind in WARNING_SANCTION_KINDS and normalized_auto_relief_date is None:
            raise ValueError("Для устного и строгого требуется дата автоматического снятия")
        return normalized_amount, normalized_auto_relief_date

    async def create_manual_sanction(
        self,
        assistant_id: int,
        kind: str,
        amount: float,
        auto_relief_date: date | None,
        basis_date: date,
        workoff_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        normalized_amount, normalized_auto_relief_date = self._normalize_runtime_sanction(
            kind,
            amount,
            auto_relief_date,
        )
        sanction_id = self.next_sanction_id
        self.next_sanction_id += 1
        normalized_items = []
        for idx, item in enumerate(workoff_items, start=1):
            normalized_items.append(
                {
                    "id": idx,
                    "sanction_id": sanction_id,
                    **deepcopy(item),
                }
            )
        sanction = {
            "sanction_id": sanction_id,
            "assistant_id": assistant_id,
            "kind": kind,
            "amount_total": normalized_amount,
            "relieved_amount": 0.0,
            "active_amount": normalized_amount,
            "auto_relief_date": (
                normalized_auto_relief_date.isoformat()
                if normalized_auto_relief_date
                else None
            ),
            "issued_at": _now(),
            "display_issued_at": _now(),
            "source_type": "manual",
            "operation_id": None,
            "basis_date": basis_date.isoformat(),
            "settings_month": basis_date.replace(day=1).isoformat(),
            "check_rule_hit_no": None,
            "workoff_items": normalized_items,
            "workoff_progress_summary": self._build_workoff_summary(
                assistant_id=assistant_id,
                workoff_items=normalized_items,
            )[1],
        }
        self.assistant_sanctions[sanction_id] = sanction
        self._recompute_assistant_totals(assistant_id)
        return deepcopy(sanction)

    async def add_sanction_relief(
        self,
        sanction_id: int,
        amount: float,
        relief_type: str,
        basis_date: date | None = None,
    ) -> dict[str, Any] | None:
        sanction = self.assistant_sanctions.get(int(sanction_id))
        if not sanction or float(sanction["active_amount"]) <= 0:
            return None
        relief_amount = min(round(float(amount), 4), float(sanction["active_amount"]))
        sanction["relieved_amount"] = round(float(sanction["relieved_amount"]) + relief_amount, 4)
        sanction["active_amount"] = round(float(sanction["amount_total"]) - float(sanction["relieved_amount"]), 4)
        sanction["last_relief_type"] = relief_type
        sanction["last_relief_basis_date"] = basis_date.isoformat() if basis_date else None
        relief_id = len(self.sanction_reliefs) + 1
        self.sanction_reliefs.append(
            {
                "id": relief_id,
                "sanction_id": int(sanction_id),
                "amount": relief_amount,
                "relief_type": relief_type,
                "basis_date": basis_date.isoformat() if basis_date else None,
                "relieved_at": _now(),
            }
        )
        self._recompute_assistant_totals(int(sanction["assistant_id"]))
        return deepcopy(sanction)

    async def replace_sanction(
        self,
        sanction_id: int,
        new_kind: str,
        new_amount: float,
        new_auto_relief_date: date | None = None,
        basis_date: date | None = None,
        workoff_items: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        sanction = self.assistant_sanctions.get(int(sanction_id))
        if not sanction:
            return None
        normalized_amount, normalized_auto_relief_date = self._normalize_runtime_sanction(
            new_kind,
            new_amount,
            new_auto_relief_date,
        )
        sanction["kind"] = new_kind
        sanction["amount_total"] = normalized_amount
        sanction["relieved_amount"] = 0.0
        sanction["active_amount"] = normalized_amount
        sanction["auto_relief_date"] = (
            normalized_auto_relief_date.isoformat()
            if normalized_auto_relief_date
            else None
        )
        sanction["basis_date"] = basis_date.isoformat() if basis_date else sanction.get("basis_date")
        items = workoff_items or []
        sanction["workoff_items"] = [
            {
                "id": idx,
                "sanction_id": sanction["sanction_id"],
                **deepcopy(item),
            }
            for idx, item in enumerate(items, start=1)
        ]
        sanction["workoff_progress_summary"] = self._build_workoff_summary(
            assistant_id=int(sanction["assistant_id"]),
            workoff_items=list(sanction["workoff_items"]),
        )[1]
        self._recompute_assistant_totals(int(sanction["assistant_id"]))
        return deepcopy(sanction)

    async def get_sanction_workoff_progress(self, sanction_id: int) -> dict[str, Any] | None:
        sanction = self.assistant_sanctions.get(int(sanction_id))
        if not sanction:
            return None
        items, summary = self._build_workoff_summary(
            assistant_id=int(sanction["assistant_id"]),
            workoff_items=list(sanction.get("workoff_items") or []),
        )
        return {
            "sanction_id": sanction["sanction_id"],
            "assistant_id": sanction["assistant_id"],
            "kind": sanction["kind"],
            "active_amount": sanction["active_amount"],
            "has_workoff": bool(items),
            "items": items,
            "completed_items": summary["completed_items"],
            "total_items": summary["total_items"],
            "workoff_progress_summary": summary,
        }

    async def get_monthly_sanction_policy(self, month_start: date) -> dict[str, Any]:
        key = month_start.isoformat()
        existing = self.monthly_sanction_policies.get(key)
        if existing:
            return deepcopy(existing)
        return {
            "month_start": key,
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

    async def get_current_sanction_policy(self) -> dict[str, Any]:
        return deepcopy(self.current_sanction_policy)

    async def upsert_monthly_sanction_policy(
        self,
        month_start: date,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        policy = await self.get_monthly_sanction_policy(month_start)
        policy.update(deepcopy(payload))
        self.monthly_sanction_policies[month_start.isoformat()] = policy
        return deepcopy(policy)

    async def upsert_current_sanction_policy(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self.current_sanction_policy.update(deepcopy(payload))
        return deepcopy(self.current_sanction_policy)

    async def get_monthly_check_cycle_rules(self, month_start: date) -> list[dict[str, Any]]:
        return deepcopy(self.monthly_check_rules.get(month_start.isoformat(), []))

    @staticmethod
    def _normalize_check_rules_payload(
        rules: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not rules:
            raise ValueError("Нужно задать хотя бы одно правило галок")
        normalized = []
        for idx, rule in enumerate(rules, start=1):
            cycle_from = int(rule["cycle_from"])
            raw_cycle_to = rule.get("cycle_to")
            cycle_to = int(raw_cycle_to) if raw_cycle_to is not None else None
            if cycle_to is not None and cycle_to < cycle_from:
                raise ValueError("Диапазон правила галок задан некорректно")
            normalized.append(
                {
                    "id": idx,
                    "cycle_from": cycle_from,
                    "cycle_to": cycle_to,
                    "sanction_kind": str(rule["sanction_kind"]),
                    "sanction_amount": round(float(rule["sanction_amount"]), 4),
                }
            )
        sorted_rules = sorted(
            normalized,
            key=lambda item: (
                item["cycle_from"],
                item["cycle_to"] if item["cycle_to"] is not None else 4_294_967_295,
            ),
        )
        for index, current in enumerate(sorted_rules[:-1]):
            current_end = (
                int(current["cycle_to"])
                if current["cycle_to"] is not None
                else 4_294_967_295
            )
            next_rule = sorted_rules[index + 1]
            if int(next_rule["cycle_from"]) <= current_end:
                raise ValueError("Диапазоны правил галок не должны пересекаться")
        return normalized

    async def replace_monthly_check_cycle_rules(
        self,
        month_start: date,
        rules: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        normalized = []
        for rule in self._normalize_check_rules_payload(rules):
            normalized.append(
                {
                    **rule,
                    "month_start": month_start.isoformat(),
                }
            )
        self.monthly_check_rules[month_start.isoformat()] = normalized
        return deepcopy(normalized)

    async def get_current_check_cycle_rules(self) -> list[dict[str, Any]]:
        rules = []
        for idx, rule in enumerate(self.current_check_rules, start=1):
            rules.append({"id": idx, **deepcopy(rule)})
        return rules

    async def replace_current_check_cycle_rules(
        self,
        rules: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        self.current_check_rules = self._normalize_check_rules_payload(rules)
        return deepcopy(self.current_check_rules)

    async def list_queued_sanction_batches(self, status: str | None = None) -> list[dict[str, Any]]:
        batches = list(self.queued_sanction_batches.values())
        if status:
            batches = [batch for batch in batches if str(batch.get("status")) == status]
        batches.sort(key=lambda item: int(item["id"]))
        return deepcopy(batches)

    async def create_queued_sanction_batch(
        self,
        basis_date: date,
        created_by_id: int | None,
        sanction_kind: str,
        sanction_amount: float,
        auto_relief_date: date | None,
        audience_mode: str,
        assistant_ids: list[int],
        workoff_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        normalized_amount, normalized_auto_relief_date = self._normalize_runtime_sanction(
            sanction_kind,
            sanction_amount,
            auto_relief_date,
        )
        batch_id = self.next_batch_id
        self.next_batch_id += 1
        members = [
            {
                "batch_id": batch_id,
                "assistant_id": assistant_id,
                "nickname": self.assistants_by_id.get(assistant_id, {}).get("nickname"),
                "execution_status": "pending",
                "execution_reason": None,
                "issued_sanction_id": None,
            }
            for assistant_id in assistant_ids
        ]
        batch = {
            "id": batch_id,
            "basis_date": basis_date.isoformat(),
            "created_at": _now(),
            "created_by_id": created_by_id,
            "created_by_name": None,
            "sanction_kind": sanction_kind,
            "sanction_amount": normalized_amount,
            "auto_relief_date": (
                normalized_auto_relief_date.isoformat()
                if normalized_auto_relief_date
                else None
            ),
            "audience_mode": audience_mode,
            "status": "queued",
            "processing_mode": None,
            "processed_by_id": None,
            "processed_by_name": None,
            "queued_at": _now(),
            "processed_at": None,
            "cancelled_at": None,
            "failure_reason": None,
            "members_total": len(members),
            "effective_members": len(members),
            "issued_members": 0,
            "skipped_immunity_members": 0,
            "skipped_leave_members": 0,
            "members": members,
            "workoff_items": [
                {"batch_id": batch_id, **deepcopy(item)} for item in workoff_items
            ],
        }
        self.queued_sanction_batches[batch_id] = batch
        return deepcopy(batch)

    async def get_queued_sanction_batch(self, batch_id: int) -> dict[str, Any] | None:
        batch = self.queued_sanction_batches.get(int(batch_id))
        return deepcopy(batch) if batch else None

    async def update_queued_sanction_batch(
        self,
        batch_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        batch = self.queued_sanction_batches.get(int(batch_id))
        if not batch:
            return None
        updates = deepcopy(payload)
        if "assistant_ids" in updates:
            assistant_ids = list(updates.pop("assistant_ids"))
            batch["members"] = [
                {
                    "batch_id": int(batch_id),
                    "assistant_id": assistant_id,
                    "nickname": self.assistants_by_id.get(assistant_id, {}).get("nickname"),
                    "execution_status": "pending",
                    "execution_reason": None,
                    "issued_sanction_id": None,
                }
                for assistant_id in assistant_ids
            ]
            batch["members_total"] = len(batch["members"])
            batch["effective_members"] = len(batch["members"])
        if "workoff_items" in updates:
            batch["workoff_items"] = [
                {"batch_id": int(batch_id), **deepcopy(item)}
                for item in updates.pop("workoff_items")
            ]
        if any(
            field in updates
            for field in ("sanction_kind", "sanction_amount", "auto_relief_date")
        ):
            effective_kind = str(updates.get("sanction_kind") or batch["sanction_kind"])
            normalized_amount, normalized_auto_relief_date = self._normalize_runtime_sanction(
                effective_kind,
                updates.get("sanction_amount", batch["sanction_amount"]),
                updates.get("auto_relief_date")
                if "auto_relief_date" in updates
                else (
                    date.fromisoformat(batch["auto_relief_date"])
                    if batch.get("auto_relief_date")
                    else None
                ),
            )
            updates["sanction_kind"] = effective_kind
            updates["sanction_amount"] = normalized_amount
            updates["auto_relief_date"] = (
                normalized_auto_relief_date.isoformat()
                if normalized_auto_relief_date
                else None
            )
        batch.update(updates)
        return deepcopy(batch)

    async def add_queued_batch_member(
        self,
        batch_id: int,
        assistant_id: int,
    ) -> dict[str, Any] | None:
        batch = self.queued_sanction_batches.get(int(batch_id))
        if not batch:
            return None
        if any(int(member["assistant_id"]) == int(assistant_id) for member in batch["members"]):
            raise ValueError("Ассистент уже добавлен в операцию")
        batch["members"].append(
            {
                "batch_id": int(batch_id),
                "assistant_id": int(assistant_id),
                "nickname": self.assistants_by_id.get(int(assistant_id), {}).get("nickname"),
                "execution_status": "pending",
                "execution_reason": None,
                "issued_sanction_id": None,
            }
        )
        batch["members_total"] = len(batch["members"])
        batch["effective_members"] = len(batch["members"])
        return deepcopy(batch)

    async def remove_queued_batch_member(
        self,
        batch_id: int,
        assistant_id: int,
    ) -> dict[str, Any] | None:
        batch = self.queued_sanction_batches.get(int(batch_id))
        if not batch:
            return None
        before = len(batch["members"])
        batch["members"] = [
            member for member in batch["members"] if int(member["assistant_id"]) != int(assistant_id)
        ]
        if len(batch["members"]) == before:
            raise ValueError("Ассистент не найден в операции")
        batch["members_total"] = len(batch["members"])
        batch["effective_members"] = len(batch["members"])
        return deepcopy(batch)

    async def cancel_queued_sanction_batch(self, batch_id: int) -> dict[str, Any] | None:
        batch = self.queued_sanction_batches.get(int(batch_id))
        if not batch:
            return None
        if batch.get("status") == "cancelled":
            raise ValueError("Операция уже отменена")
        batch["status"] = "cancelled"
        batch["cancelled_at"] = _now()
        return deepcopy(batch)

    async def _issue_queued_batch(
        self,
        batch_id: int,
        *,
        processing_mode: str,
        processed_by_id: int | None,
    ) -> dict[str, Any] | None:
        batch = self.queued_sanction_batches.get(int(batch_id))
        if not batch:
            return None
        if str(batch.get("status")) != "queued":
            return {
                "batch_id": int(batch_id),
                "issued": [],
                "failed": [],
                "skipped_immunity": [],
                "skipped_leave": [],
                "derived": [],
                "status": batch.get("status"),
            }

        batch["status"] = "processing"
        batch["processing_mode"] = processing_mode
        batch["processed_by_id"] = processed_by_id

        issued: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        skipped_immunity: list[int] = []
        skipped_leave: list[int] = []
        workoff_items = [
            {key: value for key, value in item.items() if key != "batch_id"}
            for item in batch.get("workoff_items", [])
        ]
        for member in batch.get("members", []):
            assistant_id = int(member["assistant_id"])
            if assistant_id not in self.assistants_by_id:
                member["execution_status"] = "failed"
                member["execution_reason"] = "Ассистент не найден"
                member["issued_sanction_id"] = None
                failed.append({"assistant_id": assistant_id, "error": "Ассистент не найден"})
                continue
            try:
                basis_date = date.fromisoformat(batch["basis_date"])
                override = self.assistant_day_status_overrides.get(
                    (assistant_id, basis_date.isoformat()),
                    {},
                )
                manual_status = self._normalize_manual_status(override.get("manual_status"))
                is_leave_day = manual_status in {"U", "O"}
                month_policy = self.monthly_sanction_policies.get(
                    basis_date.replace(day=1).isoformat(),
                    self.current_sanction_policy,
                )
                spec_hours = float(
                    self.assistant_day_spec_hours.get((assistant_id, basis_date.isoformat()), 0.0)
                )
                kind = str(batch["sanction_kind"])
                if processing_mode == "nightly_auto" and is_leave_day:
                    member["execution_status"] = "skipped_leave"
                    member["execution_reason"] = "Skipped by U/O day override"
                    member["issued_sanction_id"] = None
                    skipped_leave.append(assistant_id)
                    continue
                if processing_mode == "nightly_auto":
                    immunity = (
                        (kind == "check" and spec_hours + 1e-9 >= float(month_policy.get("check_immunity_hours_per_day") or 0))
                        or (kind == "point" and spec_hours + 1e-9 >= float(month_policy.get("point_immunity_hours_per_day") or 0))
                        or (kind == "percent" and spec_hours + 1e-9 >= float(month_policy.get("percent_immunity_hours_per_day") or 0))
                    )
                    if immunity:
                        member["execution_status"] = "skipped_immunity"
                        member["execution_reason"] = "Skipped by day immunity"
                        member["issued_sanction_id"] = None
                        skipped_immunity.append(assistant_id)
                        continue
                sanction = await self.create_manual_sanction(
                    assistant_id=assistant_id,
                    kind=kind,
                    amount=float(batch["sanction_amount"]),
                    auto_relief_date=(
                        date.fromisoformat(batch["auto_relief_date"])
                        if batch.get("auto_relief_date")
                        else None
                    ),
                    basis_date=basis_date,
                    workoff_items=workoff_items,
                )
            except Exception as exc:
                member["execution_status"] = "failed"
                member["execution_reason"] = str(exc)
                member["issued_sanction_id"] = None
                failed.append({"assistant_id": assistant_id, "error": str(exc)})
                continue
            stored = self.assistant_sanctions[int(sanction["sanction_id"])]
            stored["source_type"] = "queued_batch"
            stored["operation_id"] = int(batch_id)
            stored["display_issued_at"] = batch.get("queued_at") or stored["issued_at"]
            member["execution_status"] = "issued"
            member["execution_reason"] = None
            member["issued_sanction_id"] = int(sanction["sanction_id"])
            issued.append(
                {
                    "assistant_id": assistant_id,
                    "sanction_id": int(sanction["sanction_id"]),
                }
            )

        batch["status"] = "failed" if failed and not issued else "completed"
        batch["processed_at"] = _now()
        batch["failure_reason"] = failed or None
        batch["issued_members"] = len(issued)
        batch["skipped_immunity_members"] = len(skipped_immunity)
        batch["skipped_leave_members"] = len(skipped_leave)
        batch["effective_members"] = len(batch.get("members", []))
        return {
            "batch_id": int(batch_id),
            "issued": issued,
            "failed": failed,
            "skipped_immunity": skipped_immunity,
            "skipped_leave": skipped_leave,
            "derived": [],
            "status": batch["status"],
        }

    async def _apply_warning_auto_expiry(
        self,
        current_date: date,
    ) -> dict[str, Any]:
        relieved: list[dict[str, Any]] = []
        for sanction in list(self.assistant_sanctions.values()):
            if sanction["kind"] not in WARNING_SANCTION_KINDS:
                continue
            if float(sanction.get("active_amount") or 0) <= 0:
                continue
            auto_relief_date = sanction.get("auto_relief_date")
            if not auto_relief_date or date.fromisoformat(auto_relief_date) > current_date:
                continue
            if any(
                int(relief["sanction_id"]) == int(sanction["sanction_id"])
                and relief["relief_type"] == "auto_expire"
                for relief in self.sanction_reliefs
            ):
                continue
            await self.add_sanction_relief(
                sanction_id=int(sanction["sanction_id"]),
                amount=float(sanction["active_amount"]),
                relief_type="auto_expire",
                basis_date=current_date,
            )
            relieved.append(
                {
                    "assistant_id": int(sanction["assistant_id"]),
                    "sanction_id": int(sanction["sanction_id"]),
                }
            )
        return {"relieved": relieved}

    async def process_queued_sanction_batches_for_date(
        self,
        basis_date: date,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        processing_date = basis_date + timedelta(days=1)
        run_key = basis_date.isoformat()
        if not force and _now().date() < processing_date:
            return {
                "basis_date": basis_date,
                "processing_date": processing_date,
                "processed_batches": [],
                "custom_workoff": {"relieved": []},
                "warning_auto_expiry": {"relieved": []},
                "default_relief": {"relieved": []},
                "month_reset": {"reset_count": 0},
                "nightly_run": {"claimed": False, "status": "too_early"},
                "skipped": True,
            }
        existing_run = self.sanction_nightly_runs.get(run_key)
        if existing_run and existing_run.get("status") in {"processing", "completed"}:
            return {
                "basis_date": basis_date,
                "processing_date": processing_date,
                "processed_batches": [],
                "custom_workoff": {"relieved": []},
                "warning_auto_expiry": {"relieved": []},
                "default_relief": {"relieved": []},
                "month_reset": {"reset_count": 0},
                "nightly_run": {"claimed": False, "status": existing_run.get("status")},
                "skipped": True,
            }
        self.sanction_nightly_runs[run_key] = {
            "status": "processing",
            "started_at": _now(),
        }
        processed_batches: list[dict[str, Any]] = []
        for batch in sorted(self.queued_sanction_batches.values(), key=lambda item: int(item["id"])):
            if str(batch.get("basis_date")) != basis_date.isoformat():
                continue
            if str(batch.get("status")) != "queued":
                continue
            result = await self._issue_queued_batch(
                int(batch["id"]),
                processing_mode="nightly_auto",
                processed_by_id=None,
            )
            if result:
                processed_batches.append(result)
        custom_workoff = await self._apply_custom_workoff_relief(
            basis_date=basis_date,
        )
        warning_auto_expiry = await self._apply_warning_auto_expiry(processing_date)
        self.sanction_nightly_runs[run_key] = {
            "status": "completed",
            "started_at": self.sanction_nightly_runs[run_key]["started_at"],
            "finished_at": _now(),
        }
        return {
            "basis_date": basis_date,
            "processing_date": processing_date,
            "processed_batches": processed_batches,
            "custom_workoff": custom_workoff,
            "warning_auto_expiry": warning_auto_expiry,
            "default_relief": {"relieved": []},
            "month_reset": {"reset_count": 0},
            "nightly_run": {"claimed": True, "status": "completed"},
            "skipped": False,
        }

    async def process_sanction_operation_now(
        self,
        operation_id: int,
        *,
        requested_by_id: int | None = None,
    ) -> dict[str, Any]:
        result = await self._issue_queued_batch(
            int(operation_id),
            processing_mode="manual_now",
            processed_by_id=requested_by_id,
        )
        if result is None:
            return {
                "operation_id": int(operation_id),
                "processed": False,
                "status": None,
                "missing": True,
            }
        batch = self.queued_sanction_batches.get(int(operation_id))
        return {
            "operation_id": int(operation_id),
            "processed": str(batch.get("status")) == "completed",
            **result,
        }

    async def update_assistant_session(
        self,
        pr_id: int,
        session_id: int,
        patch: dict[str, Any],
        outbox_trace_id: str | None = None,
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
    async def list_all_streamers(
        self,
        include_assignments: bool = False,
    ) -> list[dict[str, Any]]:
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
        outbox_events: list[dict[str, Any]] | None = None,
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
        await self._stage_outbox_events(outbox_events)

    async def update_streamer(
        self,
        twitch_id: int,
        priority: int | None = None,
        pr_slots: int | None = None,
        is_pinned: bool | None = None,
        allow_juniors: bool | None = None,
        priority_override: int | None = None,
        pr_slots_override: int | None = None,
        outbox_events: list[dict[str, Any]] | None = None,
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
            streamer["current_stream_priority_override"] = priority_override
        if pr_slots_override is not None:
            streamer["current_stream_pr_slots_override"] = pr_slots_override
        await self._stage_outbox_events(outbox_events)

    async def remove_streamer(
        self,
        twitch_id: int,
        outbox_events: list[dict[str, Any]] | None = None,
    ) -> None:
        self.streamers_by_id.pop(twitch_id, None)
        await self._stage_outbox_events(outbox_events)

    async def update_streamer_status(
        self,
        streamer_id: int,
        is_online: bool,
        started_at: str | None = None,
        game_id: int | None = None,
        game_name: str | None = None,
        stream_title: str | None = None,
        stream_thumbnail_url: str | None = None,
        profile_image_url: str | None = None,
        outbox_trace_id: str | None = None,
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
                "profile_image_url": profile_image_url,
            }
        )
        new_state = deepcopy(streamer)
        await self._stage_streamer_status_events(
            streamer_id=streamer_id,
            old_state=old_state,
            new_state=new_state,
            trace_id=outbox_trace_id,
        )
        return old_state, new_state

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
        self,
        streamer_id: int,
        pr_id: int,
        is_probation: bool = False,
        outbox_events: list[dict[str, Any]] | None = None,
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
        await self._stage_outbox_events(outbox_events)

    async def unassign_pr_from_streamer(
        self,
        streamer_id: int,
        pr_id: int | None = None,
        end_reason: str = "manual_unclaim",
        outbox_trace_id: str | None = None,
        outbox_events: list[dict[str, Any]] | None = None,
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
        staged_outbox_events = list(outbox_events or [])
        if outbox_trace_id:
            for result in results:
                staged_outbox_events.append(
                    {
                        "routing_key": "spec.unclaimed",
                        "payload": {
                            "event": "spec.unclaimed",
                            "streamer_id": streamer_id,
                            "streamer_name": streamer.get("streamer_name"),
                            "pr_id": result["pr_id"],
                            "duration_seconds": result.get("duration_seconds", 0),
                            "reason": end_reason,
                            "trace_id": outbox_trace_id,
                        },
                    }
                )
        await self._stage_outbox_events(staged_outbox_events)
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
        is_pinned: bool = False,
        points: float | None = None,
        outbox_trace_id: str | None = None,
        outbox_events: list[dict[str, Any]] | None = None,
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
            "is_pinned": is_pinned,
            "points": points,
            "start_time": start_time,
            "created_by": created_by,
            "is_active": True,
            "created_at": _now(),
            "notification_sent": notification_sent,
        }
        self.event_participants[event_id] = {}
        staged_outbox_events = list(outbox_events or [])
        if outbox_trace_id:
            staged_outbox_events.append(
                {
                    "routing_key": "event.added",
                    "payload": {
                        "event": "event.added",
                        "event_id": event_id,
                        "event_name": name,
                        "trace_id": outbox_trace_id,
                    },
                }
            )
        await self._stage_outbox_events(staged_outbox_events)
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

    async def join_event(
        self,
        event_id: int,
        user_id: int,
        outbox_trace_id: str | None = None,
        outbox_events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        event = self.events_by_id.get(event_id)
        if not event or not event.get("is_active"):
            return {"status": "error", "detail": "Event not found or inactive"}
        participants = self.event_participants.setdefault(event_id, {})
        if user_id in participants:
            return {"status": "error", "detail": "Already reserved for this event"}
        participants[user_id] = _now()
        staged_outbox_events = list(outbox_events or [])
        if outbox_trace_id:
            staged_outbox_events.append(
                {
                    "routing_key": "event.joined",
                    "payload": {
                        "event": "event.joined",
                        "event_id": event_id,
                        "event_name": event.get("name"),
                        "pr_id": user_id,
                        "trace_id": outbox_trace_id,
                    },
                }
            )
        await self._stage_outbox_events(staged_outbox_events)
        return {"status": "joined", "detail": "Joined active event"}

    async def leave_event(
        self,
        event_id: int,
        user_id: int,
        end_reason: str = "manual_unclaim",
        outbox_trace_id: str | None = None,
        outbox_events: list[dict[str, Any]] | None = None,
    ) -> int:
        participants = self.event_participants.setdefault(event_id, {})
        participants.pop(user_id, None)
        staged_outbox_events = list(outbox_events or [])
        if outbox_trace_id:
            staged_outbox_events.append(
                {
                    "routing_key": "event.left",
                    "payload": {
                        "event": "event.left",
                        "event_id": event_id,
                        "event_name": self.events_by_id.get(event_id, {}).get("name"),
                        "pr_id": user_id,
                        "duration_seconds": 60,
                        "ended_at": None,
                        "trace_id": outbox_trace_id,
                    },
                }
            )
        await self._stage_outbox_events(staged_outbox_events)
        return 60

    async def get_user_active_event_participation(self, user_id: int) -> dict[str, Any] | None:
        for event_id, participants in self.event_participants.items():
            if user_id in participants:
                event = self.events_by_id.get(event_id)
                if event and event.get("is_active"):
                    return {"event_id": event_id, "name": event.get("name")}
        return None

    async def end_event(
        self,
        event_id: int,
        outbox_trace_id: str | None = None,
        outbox_events: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        event = self.events_by_id.get(event_id)
        if event:
            event["is_active"] = False
        participants = self.event_participants.get(event_id, {})
        results = [{"pr_id": p_id, "duration": 60} for p_id in participants.keys()]
        staged_outbox_events = list(outbox_events or [])
        if outbox_trace_id and event:
            for participant in results:
                staged_outbox_events.append(
                    {
                        "routing_key": "event.left",
                        "payload": {
                            "event": "event.left",
                            "event_id": event_id,
                            "event_name": event.get("name"),
                            "pr_id": participant["pr_id"],
                            "duration_seconds": participant["duration"],
                            "ended_at": None,
                            "trace_id": outbox_trace_id,
                        },
                    }
                )
            staged_outbox_events.append(
                {
                    "routing_key": "event.ended",
                    "payload": {
                        "event": "event.ended",
                        "event_id": event_id,
                        "event_name": event.get("name"),
                        "trace_id": outbox_trace_id,
                    },
                }
            )
        await self._stage_outbox_events(staged_outbox_events)
        return results

    async def update_event(
        self,
        event_id: int,
        name: str | None = None,
        description: str | None = None,
        required_pr_count: int | None = None,
        priority: int | None = None,
        is_pinned: bool | None = None,
        points: float | None = None,
        outbox_trace_id: str | None = None,
        outbox_events: list[dict[str, Any]] | None = None,
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
        staged_outbox_events = list(outbox_events or [])
        if outbox_trace_id:
            staged_outbox_events.append(
                {
                    "routing_key": "event.updated",
                    "payload": {
                        "event": "event.updated",
                        "event_id": event_id,
                        "event_name": event.get("name"),
                        "trace_id": outbox_trace_id,
                    },
                }
            )
        await self._stage_outbox_events(staged_outbox_events)
        return True

    async def mark_event_notification_sent(self, event_id: int) -> None:
        if event_id in self.events_by_id:
            self.events_by_id[event_id]["notification_sent"] = True

    async def update_event_message_id(self, event_id: int, message_id: int) -> None:
        return None

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

    async def create_spec_request(
        self,
        name: str,
        description: str,
        requested_by: int,
        priority: int = 0,
        outbox_trace_id: str | None = None,
        outbox_events: list[dict[str, Any]] | None = None,
    ) -> int | None:
        event_id = self.next_event_id
        self.next_event_id += 1
        self.events_by_id[event_id] = {
            "id": event_id,
            "name": name,
            "description": description,
            "required_pr_count": 1,
            "pr_slots": 1,
            "priority": priority,
            "is_pinned": False,
            "points": None,
            "start_time": _now(),
            "created_by": requested_by,
            "requested_by": requested_by,
            "event_kind": "spec_request",
            "approval_status": "pending",
            "is_active": True,
            "created_at": _now(),
            "notification_sent": True,
        }
        self.event_participants[event_id] = {requested_by: _now()}
        staged_outbox_events = list(outbox_events or [])
        if outbox_trace_id:
            staged_outbox_events.append(
                {
                    "routing_key": "event.joined",
                    "payload": {
                        "event": "event.joined",
                        "event_id": event_id,
                        "event_name": name,
                        "pr_id": requested_by,
                        "trace_id": outbox_trace_id,
                    },
                }
            )
        await self._stage_outbox_events(staged_outbox_events)
        return event_id

    async def approve_spec_request(
        self,
        event_id: int,
        approved_by: int,
        outbox_trace_id: str | None = None,
        outbox_events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | bool:
        event = self.events_by_id.get(event_id)
        if not event:
            return False
        event["approval_status"] = "approved"
        event["approved_by"] = approved_by
        event["approved_at"] = _now()
        await self._stage_outbox_events(outbox_events)
        return {"success": True, "closed_sessions": []}

    async def reject_spec_request(self, event_id: int, rejected_by: int) -> bool:
        event = self.events_by_id.get(event_id)
        if not event:
            return False
        event["approval_status"] = "rejected"
        event["rejected_by"] = rejected_by
        event["rejected_at"] = _now()
        event["is_active"] = False
        return True

    async def get_pending_spec_requests(self) -> list[dict[str, Any]]:
        return [
            self._event_view(e)
            for e in self.events_by_id.values()
            if e.get("approval_status") == "pending"
        ]

    async def start_event_sessions(
        self,
        event_id: int,
        outbox_trace_id: str | None = None,
        outbox_events: list[dict[str, Any]] | None = None,
    ) -> list[int]:
        participants = list(self.event_participants.get(event_id, {}).keys())
        await self._stage_outbox_events(outbox_events)
        return participants

    # ---------------------------------------------------------------------
    # Guild/settings
    # ---------------------------------------------------------------------
    async def get_guild(self) -> dict[str, Any] | None:
        return deepcopy(self.guild_settings) if self.guild_settings else None

    async def create_or_update_guild(
        self,
        outbox_events: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> bool:
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
                    "stream_online_gta": "Online GTA: {streamer_name}",
                    "stream_online_other": "Online: {streamer_name}",
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
        await self._stage_outbox_events(outbox_events)
        return True

    async def update_guild_templates(
        self,
        template_stream_online_gta: str | None = None,
        template_stream_online_other: str | None = None,
        template_stream_offline: str | None = None,
        template_category_to_gta: str | None = None,
        template_category_from_gta: str | None = None,
        outbox_events: list[dict[str, Any]] | None = None,
    ) -> bool:
        await self.create_or_update_guild()
        templates = self.guild_settings.setdefault("notification_templates", {})
        if template_stream_online_gta is not None:
            templates["stream_online_gta"] = template_stream_online_gta
        if template_stream_online_other is not None:
            templates["stream_online_other"] = template_stream_online_other
        if template_stream_offline is not None:
            templates["stream_offline"] = template_stream_offline
        if template_category_to_gta is not None:
            templates["category_to_gta"] = template_category_to_gta
        if template_category_from_gta is not None:
            templates["category_from_gta"] = template_category_from_gta
        await self._stage_outbox_events(outbox_events)
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
        outbox_events: list[dict[str, Any]] | None = None,
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
        await self._stage_outbox_events(outbox_events)
        return True

    # ---------------------------------------------------------------------
    # Stats
    # ---------------------------------------------------------------------
    async def get_dashboard_stats(self) -> dict[str, Any]:
        return deepcopy(self.dashboard_stats)

    async def get_service_overview_stats(self) -> dict[str, Any]:
        return deepcopy(self.service_overview_stats)


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
            "assistants.weekly.view": True,
            "assistants.weekly.manage": True,
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
            "returns.view": True,
            "returns.create": True,
            "returns.execute": True,
            "returns.history.view": True,
            "returns.manage.self": True,
            "returns.manage.any": True,
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
        current_service: dict[str, Any] | None = None,
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
                "streamers.status.update": True,
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
        app.dependency_overrides[dependencies.get_current_user] = _override_current_user
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
                "assistants.weekly.view": True,
                "assistants.weekly.manage": True,
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
            "monitoring.view": True,
            "streamers.status.update": True,
        },
    }
        base_user.update(overrides)
        app.state.test_current_user = base_user
        return base_user

    return _set_current_user
