from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from config import Config
from versioning import APP_VERSION

SERVICE_HEARTBEAT_STALE_SECONDS = 120


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def ensure_service_registry(app) -> dict[str, dict[str, Any]]:
    registry = getattr(app.state, "_service_registry", None)
    if registry is None:
        registry = {}
        app.state._service_registry = registry
    return registry


def record_service_heartbeat(
    app,
    service_name: str,
    *,
    status: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = {
        "service_name": service_name,
        "status": status,
        "details": deepcopy(details or {}),
        "recorded_at": utc_now(),
    }
    ensure_service_registry(app)[service_name] = snapshot
    return deepcopy(snapshot)


def _expected_service_names() -> list[str]:
    try:
        return sorted(Config.service_token_map.keys())
    except Exception:
        return []


def get_service_registry_view(app) -> list[dict[str, Any]]:
    registry = ensure_service_registry(app)
    now = utc_now()
    service_names = sorted(set(registry.keys()) | set(_expected_service_names()))
    records: list[dict[str, Any]] = []

    for service_name in service_names:
        snapshot = registry.get(service_name)
        if not snapshot:
            records.append(
                {
                    "service_name": service_name,
                    "status": "offline",
                    "last_seen_at": None,
                    "heartbeat_age_seconds": None,
                    "details": {},
                }
            )
            continue

        recorded_at = snapshot["recorded_at"]
        age_seconds = max(0, int((now - recorded_at).total_seconds()))
        effective_status = snapshot["status"]
        if age_seconds > SERVICE_HEARTBEAT_STALE_SECONDS:
            effective_status = "stale"

        records.append(
            {
                "service_name": service_name,
                "status": effective_status,
                "reported_status": snapshot["status"],
                "last_seen_at": isoformat_utc(recorded_at),
                "heartbeat_age_seconds": age_seconds,
                "details": deepcopy(snapshot.get("details") or {}),
            }
        )

    return records


async def probe_database(app) -> dict[str, Any]:
    started_at = perf_counter()
    database = getattr(app.state, "database", None)
    pool = getattr(database, "pool", None)

    if not database or not pool:
        return {
            "status": "disconnected",
            "latency_ms": None,
            "error": "not_initialized",
        }

    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT 1")
                await cursor.fetchone()
        latency_ms = round((perf_counter() - started_at) * 1000, 2)
        return {"status": "connected", "latency_ms": latency_ms}
    except Exception as exc:
        latency_ms = round((perf_counter() - started_at) * 1000, 2)
        return {
            "status": "disconnected",
            "latency_ms": latency_ms,
            "error": exc.__class__.__name__,
        }


async def probe_broker(app) -> dict[str, Any]:
    broker = getattr(app.state, "broker", None)
    if not broker:
        return {"status": "disconnected", "latency_ms": None, "error": "not_initialized"}

    try:
        connection = getattr(broker, "connection", None)
        if connection and not connection.is_closed:
            return {"status": "connected", "latency_ms": 0.0}
        return {"status": "disconnected", "latency_ms": None, "error": "connection_closed"}
    except Exception as exc:
        return {
            "status": "disconnected",
            "latency_ms": None,
            "error": exc.__class__.__name__,
        }


async def get_api_runtime_status(app) -> dict[str, Any]:
    db_status, broker_status = await asyncio.gather(
        probe_database(app),
        probe_broker(app),
    )
    startup_complete = bool(getattr(app.state, "_startup_complete", False))
    uptime_seconds = 0
    if hasattr(app.state, "_start_time"):
        uptime_seconds = int(
            max(0, perf_counter() - getattr(app.state, "_perf_start_time", perf_counter()))
        )

    dependencies_ready = (
        db_status["status"] == "connected"
        and broker_status["status"] == "connected"
    )

    return {
        "service": Config.app_name,
        "version": APP_VERSION,
        "status": "healthy" if startup_complete and dependencies_ready else "degraded",
        "ready": startup_complete and dependencies_ready,
        "uptime_seconds": uptime_seconds,
        "startup_complete": startup_complete,
        "checked_at": isoformat_utc(utc_now()),
        "components": {
            "database": db_status,
            "broker": broker_status,
        },
    }
