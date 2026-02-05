from __future__ import annotations
from typing import TYPE_CHECKING, Annotated, List, Optional, Union

if TYPE_CHECKING:
    from database import Database
    from services.broker import BrokerService

from config import Config
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

router = APIRouter(prefix="/streamers", tags=["Streamers"])


def get_db(request: Request):
    """Get database from app state."""
    return request.app.state.database


def get_broker(request: Request):
    """Get broker from app state."""
    return request.app.state.broker


@router.get("")
async def list_streamers(
    request: Request,
    db: "Database" = Depends(get_db),
    online_only: bool = Query(False, description="Filter only online streamers"),
):
    """Get all streamers."""
    trace_id = get_trace_id(request)

    if online_only:
        streamers = await db.list_online_streamers()
    else:
        streamers = await db.list_all_streamers()

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
):
    """
    Add a new streamer.

    Two modes:
    1. URL mode (Discord/Web): Provide `twitch_url` → triggers async verification
    2. Full mode (Twitch bot): Provide `streamer_id` + `streamer_name` → direct creation
    """
    trace_id = get_trace_id(request)

    # Mode B: Full data from Twitch bot - direct creation
    if data.is_full_mode:
        await db.create_streamer(
            streamer_id=data.streamer_id,
            streamer_name=data.streamer_name,
            is_online=data.is_online,
            started_at=data.started_at,
            priority=data.priority,
            added_by_id=data.added_by_id,
            game_id=data.game_id,
            game_name=data.game_name,
            stream_title=data.stream_title,
            stream_thumbnail_url=data.stream_thumbnail_url,
            profile_image_url=data.profile_image_url,
        )

        streamer = await db.get_streamer(data.streamer_id)

        if not streamer:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to retrieve created streamer {data.streamer_id}",
            )

        if broker:
            await broker.emit_streamer_added(
                data.streamer_id,
                data.streamer_name,
                {"priority": data.priority},
                trace_id=trace_id,
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

    if broker:
        # Emit verification event so Twitch Bot can resolve ID
        await broker.emit_streamer_verify(
            username,
            {"priority": data.priority, "added_by_id": data.added_by_id},
            trace_id=trace_id,
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
):
    """Update streamer properties."""
    trace_id = get_trace_id(request)

    streamer = await db.get_streamer(twitch_id)
    if not streamer:
        raise HTTPException(status_code=404, detail="Стример не найден")

    # Build update data
    update_data = {}
    if data.priority is not None:
        update_data["priority"] = data.priority
    if data.is_pinned is not None:
        update_data["is_pinned"] = data.is_pinned
    if data.stream_points_override is not None:
        update_data["stream_points_override"] = data.stream_points_override

    if update_data:
        # Update via database method
        await db.update_streamer(
            twitch_id,
            priority=update_data.get("priority"),
            is_pinned=update_data.get("is_pinned"),
            stream_points_override=update_data.get("stream_points_override"),
        )

    # Get updated streamer
    streamer = await db.get_streamer(twitch_id)

    if broker:
        await broker.emit_streamer_updated(
            twitch_id,
            streamer["streamer_name"],
            update_data,
            trace_id=trace_id,
        )

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
):
    """Delete a streamer."""
    trace_id = get_trace_id(request)

    streamer = await db.get_streamer(twitch_id)
    if not streamer:
        raise HTTPException(status_code=404, detail="Стример не найден")

    streamer_name = streamer["streamer_name"]

    await db.remove_streamer(twitch_id)

    if broker:
        await broker.emit_streamer_removed(twitch_id, streamer_name, trace_id=trace_id)

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
):
    """
    Update streamer online status.
    Called by Twitch bot when receiving EventSub events.
    Accepts JSON body for proper REST semantics.
    Now also publishes appropriate RabbitMQ events based on state changes.
    """
    trace_id = get_trace_id(request)

    # Get current state BEFORE update
    streamer = await db.get_streamer(twitch_id)
    if not streamer:
        raise HTTPException(status_code=404, detail="Стример не найден")

    old_is_online = streamer.get("is_online", False)
    old_game_id = str(streamer.get("game_id")) if streamer.get("game_id") else None

    # Update database
    await db.update_streamer_status(
        streamer_id=twitch_id,
        is_online=data.is_online,
        started_at=data.started_at,
        game_id=data.game_id,
        game_name=data.game_name,
        stream_title=data.stream_title,
        stream_thumbnail_url=data.stream_thumbnail_url,
    )

    # Publish events based on state changes
    if broker:
        streamer_name = streamer["streamer_name"]
        new_game_id = str(data.game_id) if data.game_id else None

        broker.logger.info(
            f"DEBUG Check: {streamer_name} | Online: {old_is_online}->{data.is_online} | GameID: {old_game_id}->{new_game_id} | GameName: {data.game_name}"
        )

        # === AUTO-UNASSIGN LOGIC ===
        should_unassign = False
        unassign_reason = ""

        # Case 1: Stream went OFFLINE
        if not data.is_online and old_is_online:
            should_unassign = True
            unassign_reason = "stream_offline"

        # Case 2: Category changed FROM GTA while online
        elif data.is_online and old_is_online:
            was_gta = old_game_id == Config.gta5_game_id
            is_gta = new_game_id == Config.gta5_game_id
            if was_gta and not is_gta:
                should_unassign = True
                unassign_reason = "category_from_gta"

        # Execute auto-unassign if needed
        if should_unassign:
            unassign_results = await db.unassign_pr_from_streamer(
                twitch_id, pr_id=None, end_reason=unassign_reason
            )
            for result in unassign_results:
                broker.logger.info(
                    f"AUTO-UNASSIGN: {streamer_name} | Reason: {unassign_reason} | PR: {result['pr_id']} | Duration: {result['duration_seconds']}s"
                )
                # Emit spec unclaimed event for Discord bot to update UI
                await broker.emit_spec_unclaimed(
                    streamer_id=twitch_id,
                    streamer_name=streamer_name,
                    pr_id=result["pr_id"],
                    duration_seconds=result["duration_seconds"],
                    reason=unassign_reason,
                    trace_id=trace_id,
                )

        # === BROKER NOTIFICATIONS ===
        # Online/Offline state change
        if data.is_online and not old_is_online:
            # Stream went ONLINE
            await broker.emit_stream_online(
                streamer_id=twitch_id,
                streamer_name=streamer_name,
                game_id=data.game_id,
                game_name=data.game_name,
                stream_title=data.stream_title,
                thumbnail_url=data.stream_thumbnail_url,
                trace_id=trace_id,
            )
        elif not data.is_online and old_is_online:
            # Stream went OFFLINE
            await broker.emit_stream_offline(
                streamer_id=twitch_id,
                streamer_name=streamer_name,
                trace_id=trace_id,
            )
        elif data.is_online and old_is_online and old_game_id != new_game_id:
            # Category changed while online
            await broker.emit_category_change(
                streamer_id=twitch_id,
                streamer_name=streamer_name,
                old_game_id=old_game_id,
                new_game_id=new_game_id,
                new_game_name=data.game_name,
                stream_title=data.stream_title,
                thumbnail_url=data.stream_thumbnail_url,
                trace_id=trace_id,
            )

    # trace_id already extracted at the start of function
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
