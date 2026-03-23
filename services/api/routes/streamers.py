from __future__ import annotations

from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from db import Database
    from services.broker import BrokerService

from config import Config
from dependencies import require_permission
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from middleware import get_trace_id
from schemas.envelope import accepted_envelope, success_envelope
from schemas.streamer import (
    StreamerCreate,
    StreamerListResponse,
    StreamerResponse,
    StreamerStatusUpdate,
    StreamerUpdate,
)
from services.outbox import publish_integration_event

router = APIRouter(prefix="/streamers", tags=["Streamers"])


def get_db(request: Request):
    """Get database from app state."""
    return request.app.state.database


def get_broker(request: Request):
    """Get broker from app state."""
    return request.app.state.broker


def _resolve_actor_id(principal: dict) -> int:
    """Resolve immutable actor ID for audit fields from auth principal."""
    if principal.get("principal_type") == "service":
        return 0
    discord_id = principal.get("discord_id")
    if discord_id is None:
        raise HTTPException(status_code=400, detail="User has no discord_id")
    try:
        return int(discord_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid discord_id")


@router.get("")
async def list_streamers(
    request: Request,
    db: "Database" = Depends(get_db),
    online_only: bool = Query(False, description="Filter only online streamers"),
    gta_only: bool = Query(False, description="Filter only GTA 5 streamers (used with online_only)"),
    include_assignments: bool = Query(
        False,
        description="Include active assignment slots for all streamers",
    ),
    _principal: dict = Depends(require_permission("media.view")),
):
    """Get all streamers."""
    trace_id = get_trace_id(request)

    if online_only:
        streamers = await db.list_online_streamers()
        if gta_only:
            streamers = [
                s for s in streamers
                if str(s.get("game_id")) == Config.gta5_game_id
            ]
    else:
        streamers = await db.list_all_streamers(
            include_assignments=include_assignments
        )

    # Count stats
    online_count = sum(1 for s in streamers if s.get("is_online"))
    gta_count = sum(
        1 for s in streamers if str(s.get("game_id")) == Config.gta5_game_id
    )

    data = StreamerListResponse(
        total=len(streamers),
        online_count=online_count,
        gta_count=gta_count,
        streamers=[StreamerResponse(**s) for s in streamers],
    )

    return JSONResponse(
        content=success_envelope(
            data=data.model_dump(mode="json"),
            message=f"Found {len(streamers)} streamers",
            trace_id=trace_id,
        )
    )


@router.get("/{twitch_id}")
async def get_streamer(
    request: Request,
    twitch_id: int,
    db: "Database" = Depends(get_db),
    _principal: dict = Depends(require_permission("media.view")),
):
    """Get a specific streamer by Twitch ID."""
    trace_id = get_trace_id(request)

    streamer = await db.get_streamer(twitch_id)
    if not streamer:
        raise HTTPException(status_code=404, detail="Стример не найден")

    data = StreamerResponse(**streamer)
    return JSONResponse(
        content=success_envelope(
            data=data.model_dump(mode="json"),
            message="Streamer found",
            trace_id=trace_id,
        )
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_streamer(
    request: Request,
    data: StreamerCreate,
    db: "Database" = Depends(get_db),
    broker: "BrokerService" = Depends(get_broker),
    principal: dict = Depends(require_permission("media.create")),
):
    """
    Add a new streamer.

    Two modes:
    1. URL mode (Discord/Web): Provide `twitch_url` → triggers async verification
    2. Full mode (Twitch bot): Provide `streamer_id` + `streamer_name` → direct creation
    """
    trace_id = get_trace_id(request)
    added_by_id = _resolve_actor_id(principal)
    actor_name = principal.get("nickname") or principal.get("username")
    if principal.get("principal_type") == "service":
        actor_name = f"service:{principal.get('service_name', 'unknown')}"

    # Mode B: Full data from Twitch bot - direct creation
    if data.is_full_mode:
        await db.create_streamer(
            streamer_id=data.streamer_id,
            streamer_name=data.streamer_name,
            is_online=data.is_online,
            started_at=data.started_at,
            priority=data.priority,
            pr_slots=data.pr_slots,
            allow_juniors=data.allow_juniors,
            added_by_id=added_by_id,
            game_id=data.game_id,
            game_name=data.game_name,
            stream_title=data.stream_title,
            stream_thumbnail_url=data.stream_thumbnail_url,
            profile_image_url=data.profile_image_url,
            outbox_events=[
                {
                    "routing_key": "streamer.added",
                    "payload": {
                        "event": "streamer.added",
                        "streamer_id": data.streamer_id,
                        "streamer_name": data.streamer_name,
                        "data": {"priority": data.priority, "pr_slots": data.pr_slots},
                        "trace_id": trace_id,
                    },
                }
            ],
        )

        streamer = await db.get_streamer(data.streamer_id)

        if not streamer:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve created streamer {data.streamer_id}",
            )

        await db.log_admin_action_v2(
            actor_name=actor_name or "Unknown",
            actor_role=principal.get("role")
            if principal.get("principal_type") == "user"
            else "service",
            action="streamer.create",
            target_type="streamer",
            target_id=str(data.streamer_id),
            details={
                "summary": f"Created streamer {data.streamer_name}",
                "changes": {
                    "after": {
                        "streamer_id": data.streamer_id,
                        "streamer_name": data.streamer_name,
                        "priority": data.priority,
                        "pr_slots": data.pr_slots,
                        "allow_juniors": data.allow_juniors,
                    }
                },
                "meta": {
                    "ip": request.client.host if request.client else None,
                    "request_path": str(request.url.path),
                    "method": request.method,
                    "actor_id": added_by_id,
                    "principal_type": principal.get("principal_type"),
                    "service_name": principal.get("service_name")
                    if principal.get("principal_type") == "service"
                    else None,
                },
            },
        )

        response_data = StreamerResponse(**streamer)
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content=success_envelope(
                data=response_data.model_dump(mode="json"),
                message=f"Streamer {data.streamer_name} added",
                code="STREAMER_ADDED",
                trace_id=trace_id,
            ),
        )

    # Mode A: URL mode - needs Twitch verification
    username = data.twitch_url

    publish_ok = await publish_integration_event(
        request.app,
        routing_key="streamer.verify",
        payload={
            "event": "streamer.verify",
            "username": username,
            "added_by": {
                "priority": data.priority,
                "pr_slots": data.pr_slots,
                "added_by_id": added_by_id,
            },
            "trace_id": trace_id,
        },
    )

    if publish_ok:

        await db.log_admin_action_v2(
            actor_name=actor_name or "Unknown",
            actor_role=principal.get("role")
            if principal.get("principal_type") == "user"
            else "service",
            action="streamer.create.requested",
            target_type="streamer",
            target_id=username or "unknown",
            details={
                "summary": f"Requested streamer verification for {username}",
                "changes": {
                    "after": {
                        "twitch_url": username,
                        "priority": data.priority,
                        "pr_slots": data.pr_slots,
                    }
                },
                "meta": {
                    "ip": request.client.host if request.client else None,
                    "request_path": str(request.url.path),
                    "method": request.method,
                    "actor_id": added_by_id,
                    "principal_type": principal.get("principal_type"),
                    "service_name": principal.get("service_name")
                    if principal.get("principal_type") == "service"
                    else None,
                },
            },
        )

        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=accepted_envelope(
                data={"username": username},
                message=f"Request to add {username} sent for verification",
                code="STREAMER_ADD_PENDING",
                trace_id=trace_id,
            ),
        )

    raise HTTPException(
        status_code=503, detail="Broker unavailable. Cannot verify Twitch ID."
    )


@router.patch("/{twitch_id}")
async def update_streamer(
    request: Request,
    twitch_id: int,
    data: StreamerUpdate,
    db: "Database" = Depends(get_db),
    broker: "BrokerService" = Depends(get_broker),
    user: dict = Depends(require_permission("media.update")),
):
    """Update streamer properties."""
    trace_id = get_trace_id(request)

    streamer = await db.get_streamer(twitch_id)
    if not streamer:
        raise HTTPException(status_code=404, detail="Стример не найден")

    # Build update data & track changes for logging
    update_data = {}
    changes = {}

    if data.priority is not None:
        if data.priority != streamer["priority"]:
            changes["priority"] = {"old": streamer["priority"], "new": data.priority}
            update_data["priority"] = data.priority

    if data.pr_slots is not None:
        if data.pr_slots != streamer.get("pr_slots", 1):
            changes["pr_slots"] = {
                "old": streamer.get("pr_slots", 1),
                "new": data.pr_slots,
            }
            update_data["pr_slots"] = data.pr_slots

    if data.is_pinned is not None:
        if data.is_pinned != streamer.get("is_pinned", False):
            changes["is_pinned"] = {
                "old": streamer.get("is_pinned", False),
                "new": data.is_pinned,
            }
            update_data["is_pinned"] = data.is_pinned


    if data.allow_juniors is not None:
        if data.allow_juniors != streamer.get("allow_juniors", True):
            changes["allow_juniors"] = {
                "old": streamer.get("allow_juniors", True),
                "new": data.allow_juniors,
            }
            update_data["allow_juniors"] = data.allow_juniors

    if data.current_stream_priority_override is not None:
        if data.current_stream_priority_override != streamer.get("current_stream_priority_override"):
            changes["current_stream_priority_override"] = {
                "old": streamer.get("current_stream_priority_override"),
                "new": data.current_stream_priority_override,
            }
            update_data["priority_override"] = data.current_stream_priority_override

    if data.current_stream_pr_slots_override is not None:
        if data.current_stream_pr_slots_override != streamer.get("current_stream_pr_slots_override"):
            changes["current_stream_pr_slots_override"] = {
                "old": streamer.get("current_stream_pr_slots_override"),
                "new": data.current_stream_pr_slots_override,
            }
            update_data["pr_slots_override"] = data.current_stream_pr_slots_override

    if update_data:
        # Update via database method
        await db.update_streamer(
            twitch_id,
            priority=update_data.get("priority"),
            pr_slots=update_data.get("pr_slots"),
            is_pinned=update_data.get("is_pinned"),
            allow_juniors=update_data.get("allow_juniors"),
            priority_override=update_data.get("priority_override"),
            pr_slots_override=update_data.get("pr_slots_override"),
            outbox_events=[
                {
                    "routing_key": "streamer.updated",
                    "payload": {
                        "event": "streamer.updated",
                        "streamer_id": twitch_id,
                        "streamer_name": streamer["streamer_name"],
                        "data": update_data,
                        "trace_id": trace_id,
                    },
                }
            ],
        )

        # Retroactive update: propagate priority changes to active sessions
        if "priority" in update_data or "priority_override" in update_data:
            await db.recalc_target_active_sessions(
                target_type="streamer",
                target_id=twitch_id,
            )

        # Log to admin_logs
        if changes:
            await db.log_admin_action_v2(
                actor_name=user.get("nickname", user.get("username", "Unknown")),
                actor_role=user.get("role"),
                action="streamer.update",
                target_type="streamer",
                target_id=str(twitch_id),
                details={
                    "summary": f"Updated streamer {streamer.get('streamer_name', twitch_id)}",
                    "changes": {
                        "before": {
                            key: value.get("old")
                            for key, value in changes.items()
                        },
                        "after": {
                            key: value.get("new")
                            for key, value in changes.items()
                        },
                        "delta": changes,
                        "source": "manual_update",
                    },
                    "meta": {
                        "ip": request.client.host if request.client else None,
                        "request_path": str(request.url.path),
                        "method": request.method,
                        "actor_id": user.get("id"),
                    },
                },
            )

    # Get updated streamer
    streamer = await db.get_streamer(twitch_id)

    response_data = StreamerResponse(**streamer)
    return JSONResponse(
        content=success_envelope(
            data=response_data.model_dump(mode="json"),
            message="Streamer updated",
            code="STREAMER_UPDATED",
            trace_id=trace_id,
        )
    )


@router.delete("/{twitch_id}")
async def remove_streamer(
    request: Request,
    twitch_id: int,
    db: "Database" = Depends(get_db),
    broker: "BrokerService" = Depends(get_broker),
    _principal: dict = Depends(require_permission("media.delete")),
):
    """Delete a streamer."""
    trace_id = get_trace_id(request)

    streamer = await db.get_streamer(twitch_id)
    if not streamer:
        raise HTTPException(status_code=404, detail="Стример не найден")

    streamer_name = streamer["streamer_name"]

    await db.remove_streamer(
        twitch_id,
        outbox_events=[
            {
                "routing_key": "streamer.removed",
                "payload": {
                    "event": "streamer.removed",
                    "streamer_id": twitch_id,
                    "streamer_name": streamer_name,
                    "trace_id": trace_id,
                },
            }
        ],
    )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=success_envelope(
            data={"streamer_id": twitch_id, "streamer_name": streamer_name},
            message=f"Streamer {streamer_name} removed",
            code="STREAMER_REMOVED",
            trace_id=trace_id,
        ),
    )


@router.patch("/{twitch_id}/status")
async def update_streamer_status(
    request: Request,
    twitch_id: int,
    data: StreamerStatusUpdate,
    db: "Database" = Depends(get_db),
    broker: "BrokerService" = Depends(get_broker),
    _principal: dict = Depends(require_permission("media.status.update")),
):
    """
    Update streamer online status.
    Called by Twitch bot when receiving EventSub events.
    Uses atomic database update to prevent race conditions.
    """
    trace_id = get_trace_id(request)

    # Atomic update - returns (old_state, new_state) with row locking
    old_state, new_state = await db.update_streamer_status(
        streamer_id=twitch_id,
        is_online=data.is_online,
        started_at=data.started_at,
        game_id=data.game_id,
        game_name=data.game_name,
        stream_title=data.stream_title,
        stream_thumbnail_url=data.stream_thumbnail_url,
        profile_image_url=data.profile_image_url,
        outbox_trace_id=trace_id,
    )

    if old_state is None:
        raise HTTPException(status_code=404, detail="Стример не найден")

    # Extract state values
    streamer_name = old_state["streamer_name"]
    old_is_online = old_state["is_online"]
    old_game_id = old_state["game_id"]
    new_game_id = new_state["game_id"]

    # Publish events based on state changes
    if broker:
        broker.logger.info(
            f"Atomic update: {streamer_name} | Online: {old_is_online}->{data.is_online} | GameID: {old_game_id}->{new_game_id}"
        )

    # === AUTO-UNASSIGN LOGIC ===
    should_unassign = False
    unassign_reason = ""

    # Case 1: Stream went OFFLINE
    if not data.is_online and old_is_online:
        should_unassign = True
        unassign_reason = "stream_end"

    # Case 2: Category changed FROM GTA while online
    elif data.is_online and old_is_online:
        was_gta = old_game_id == Config.gta5_game_id
        is_gta = new_game_id == Config.gta5_game_id
        if was_gta and not is_gta:
            should_unassign = True
            unassign_reason = "category_change"

    # Execute auto-unassign if needed
    if should_unassign:
        unassign_results = await db.unassign_pr_from_streamer(
            twitch_id,
            pr_id=None,
            end_reason=unassign_reason,
            outbox_trace_id=trace_id,
        )
        for result in unassign_results:
            if broker:
                broker.logger.info(
                    f"AUTO-UNASSIGN: {streamer_name} | Reason: {unassign_reason} | PR: {result['pr_id']} | Duration: {result['duration_seconds']}s"
                )

    return JSONResponse(
        content=success_envelope(
            data={"streamer_id": twitch_id},
            message="Status updated",
            code="STATUS_UPDATED",
            trace_id=trace_id,
        )
    )


@router.post("/sync_status")
async def sync_streamers_status(
    request: Request,
    updates: List[dict],
    db: "Database" = Depends(get_db),
    _principal: dict = Depends(require_permission("media.status.update")),
):
    """
    Bulk update streamer statuses.
    Called by Twitch bot during sync to update multiple streamers efficiently.

    Each update should contain:
    - streamer_id (required)
    - is_online (required)
    - started_at (optional)
    - game_id (optional)
    - game_name (optional)
    - stream_title (optional)
    - stream_thumbnail_url (optional)
    """
    if not updates:
        return {"status": "no_updates", "updated_count": 0}

    # Validate and clean updates
    valid_updates = []
    for update in updates:
        if "streamer_id" not in update or "is_online" not in update:
            continue

        # Handle game_id being passed as empty string
        game_id = update.get("game_id")
        if game_id == "":
            game_id = None
        elif game_id is not None:
            try:
                game_id = int(game_id)
            except ValueError:
                game_id = None

        valid_updates.append(
            {
                "streamer_id": update["streamer_id"],
                "is_online": update["is_online"],
                "started_at": update.get("started_at"),
                "game_id": game_id,
                "game_name": update.get("game_name"),
                "stream_title": update.get("stream_title"),
                "stream_thumbnail_url": update.get("stream_thumbnail_url"),
                "profile_image_url": update.get("profile_image_url"),
            }
        )

    updated_count = await db.update_streamers_status_bulk(valid_updates)

    trace_id = get_trace_id(request)
    return JSONResponse(
        content=success_envelope(
            data={"updated_count": updated_count},
            message=f"Synced {updated_count} streamers",
            code="SYNC_COMPLETE",
            trace_id=trace_id,
        )
    )
