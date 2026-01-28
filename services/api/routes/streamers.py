"""
Streamers routes for API.
CRUD operations for Twitch streamers.
"""

from typing import List, Optional, Union
from fastapi import APIRouter, Depends, HTTPException, Request, status, Query

from schemas.streamer import (
    StreamerCreate,
    StreamerUpdate,
    StreamerResponse,
    StreamerListResponse,
)
from config import Config

router = APIRouter(prefix="/streamers", tags=["Streamers"])


def get_db(request: Request):
    """Get database from app state."""
    return request.app.state.database


def get_broker(request: Request):
    """Get broker from app state."""
    return request.app.state.broker


@router.get("", response_model=StreamerListResponse)
async def list_streamers(
    online_only: bool = Query(False, description="Filter only online streamers"),
    db=Depends(get_db),
):
    """Get all streamers."""
    if online_only:
        streamers = await db.list_online_streamers()
    else:
        streamers = await db.list_all_streamers()

    # Count stats
    online_count = sum(1 for s in streamers if s.get("is_online"))
    gta_count = sum(
        1
        for s in streamers
        if s.get("is_online") and str(s.get("game_id")) == Config.GTA5_GAME_ID
    )

    return StreamerListResponse(
        total=len(streamers),
        online_count=online_count,
        gta_count=gta_count,
        streamers=[StreamerResponse(**s) for s in streamers],
    )


@router.get("/{twitch_id}", response_model=StreamerResponse)
async def get_streamer(twitch_id: int, db=Depends(get_db)):
    """Get a specific streamer by Twitch ID."""
    streamer = await db.get_streamer(twitch_id)
    if not streamer:
        raise HTTPException(status_code=404, detail="Стример не найден")
    return StreamerResponse(**streamer)


@router.post("", response_model=StreamerResponse, status_code=status.HTTP_201_CREATED)
async def create_streamer(
    request: Request,
    data: StreamerCreate,
    db=Depends(get_db),
    broker=Depends(get_broker),
):
    """
    Add a new streamer.

    Note: This endpoint expects the Discord bot or web UI to resolve
    the Twitch username to ID before calling. For full resolution,
    the Twitch bot handles get_streamer_id.
    """
    # Parse URL or username
    url = data.twitch_url
    if url.startswith("https://www.twitch.tv/"):
        username = url.replace("https://www.twitch.tv/", "").rstrip("/").strip()
    else:
        username = url.rstrip("/").strip()

    # Create streamer logic refactored for async verification
    # User requested to ensure Twitch ID is present before DB insertion.

    if broker:
        # Emit verification event so Twitch Bot can resolve ID
        await broker.emit_streamer_verify(
            username, {"priority": data.priority, "added_by_id": 0}
        )

        # Return accepted status
        # Note: Response model StreamerResponse requires fields that we don't have yet.
        # We should probably change response code or model, but to keep signature:
        # We return a dummy accepted response or raise HTTPException asking client to wait?
        # Better: Return specific 202 Accepted with message.
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "status": "pending_verification",
                "message": f"Request to add {username} sent for verification",
            },
        )

    # If no broker (fallback mode), we try to proceed or fail
    # Since we can't resolve ID without Twitch Bot (via Broker), we must fail or insert 0
    # But user explicitely blocked 0.
    raise HTTPException(
        status_code=503, detail="Broker unavailable. Cannot verify Twitch ID."
    )

    # Original logic removed to prevent ID=0 insertion
    """
    await db.create_streamer(
        streamer_id=0,
        streamer_name=username,
        is_online=False,
        priority=data.priority,
        added_by_id=0,
    )
    ...
    """


@router.post(
    "/full", response_model=StreamerResponse, status_code=status.HTTP_201_CREATED
)
async def create_streamer_full(
    request: Request,
    streamer_id: int,
    streamer_name: str,
    is_online: bool = False,
    started_at: Optional[str] = None,
    priority: int = 0,
    added_by_id: int = 0,
    game_id: Optional[int] = None,
    game_name: Optional[str] = None,
    stream_title: Optional[str] = None,
    stream_thumbnail_url: Optional[str] = None,
    db=Depends(get_db),
    broker=Depends(get_broker),
):
    """
    Add a new streamer with full data.
    This is called by the Discord bot after resolving Twitch data.
    """
    await db.create_streamer(
        streamer_id=streamer_id,
        streamer_name=streamer_name,
        is_online=is_online,
        started_at=started_at,
        priority=priority,
        added_by_id=added_by_id,
        game_id=game_id,
        game_name=game_name,
        stream_title=stream_title,
        stream_thumbnail_url=stream_thumbnail_url,
    )

    streamer = await db.get_streamer(streamer_id)

    if broker:
        await broker.emit_streamer_added(
            streamer_id,
            streamer_name,
            {"priority": priority},
        )

    return StreamerResponse(**streamer)


@router.patch("/{twitch_id}", response_model=StreamerResponse)
async def update_streamer(
    twitch_id: int,
    data: StreamerUpdate,
    db=Depends(get_db),
    broker=Depends(get_broker),
):
    """Update streamer properties."""
    streamer = await db.get_streamer(twitch_id)
    if not streamer:
        raise HTTPException(status_code=404, detail="Стример не найден")

    # Build update data
    update_data = {}
    if data.priority is not None:
        update_data["priority"] = data.priority

    if update_data:
        # Update via database method
        await db.update_streamer(
            twitch_id,
            priority=update_data.get("priority"),
        )

    # Get updated streamer
    streamer = await db.get_streamer(twitch_id)

    if broker:
        await broker.emit_streamer_updated(
            twitch_id,
            streamer["streamer_name"],
            update_data,
        )

    return StreamerResponse(**streamer)


@router.delete("/{twitch_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_streamer(
    twitch_id: int,
    db=Depends(get_db),
    broker=Depends(get_broker),
):
    """Delete a streamer."""
    streamer = await db.get_streamer(twitch_id)
    if not streamer:
        raise HTTPException(status_code=404, detail="Стример не найден")

    streamer_name = streamer["streamer_name"]

    await db.delete_streamer(twitch_id)

    if broker:
        await broker.emit_streamer_removed(twitch_id, streamer_name)

    return None


@router.patch("/{twitch_id}/status")
async def update_streamer_status(
    twitch_id: int,
    is_online: bool,
    started_at: Optional[str] = None,
    game_id: Optional[Union[int, str]] = None,
    game_name: Optional[str] = None,
    stream_title: Optional[str] = None,
    stream_thumbnail_url: Optional[str] = None,
    db=Depends(get_db),
    broker=Depends(get_broker),
):
    """
    Update streamer online status.
    Called by Twitch bot when receiving EventSub events.
    Now also publishes appropriate RabbitMQ events based on state changes.
    """
    # Handle game_id being passed as empty string
    if game_id == "":
        game_id = None
    elif game_id is not None:
        try:
            game_id = int(game_id)
        except ValueError:
            game_id = None

    # Get current state BEFORE update
    streamer = await db.get_streamer(twitch_id)
    if not streamer:
        raise HTTPException(status_code=404, detail="Стример не найден")

    old_is_online = streamer.get("is_online", False)
    old_game_id = str(streamer.get("game_id")) if streamer.get("game_id") else None

    # Update database
    await db.update_streamer_status(
        streamer_id=twitch_id,
        is_online=is_online,
        started_at=started_at,
        game_id=game_id,
        game_name=game_name,
        stream_title=stream_title,
        stream_thumbnail_url=stream_thumbnail_url,
    )

    # Publish events based on state changes
    if broker:
        streamer_name = streamer["streamer_name"]
        new_game_id = str(game_id) if game_id else None
        
        broker.logger.info(f"DEBUG Check: {streamer_name} | Online: {old_is_online}->{is_online} | GameID: {old_game_id}->{new_game_id} | GameName: {game_name}")

        # Online/Offline state change
        if is_online and not old_is_online:
            # Stream went ONLINE
            await broker.emit_stream_online(
                streamer_id=twitch_id,
                streamer_name=streamer_name,
                game_id=game_id,
                game_name=game_name,
                stream_title=stream_title,
                thumbnail_url=stream_thumbnail_url,
                guild_id=Config.GUILD_ID,
            )
        elif not is_online and old_is_online:
            # Stream went OFFLINE
            await broker.emit_stream_offline(
                streamer_id=twitch_id,
                streamer_name=streamer_name,
                guild_id=Config.GUILD_ID,
            )
        elif is_online and old_is_online and old_game_id != new_game_id:
            # Category changed while online
            await broker.emit_category_change(
                streamer_id=twitch_id,
                streamer_name=streamer_name,
                old_game_id=old_game_id,
                new_game_id=new_game_id,
                new_game_name=game_name,
                stream_title=stream_title,
                thumbnail_url=stream_thumbnail_url,
                guild_id=Config.GUILD_ID,
            )


    return {"status": "updated"}


@router.post("/sync_status")
async def sync_streamers_status(
    updates: List[dict],
    db=Depends(get_db),
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
        
        valid_updates.append({
            "streamer_id": update["streamer_id"],
            "is_online": update["is_online"],
            "started_at": update.get("started_at"),
            "game_id": game_id,
            "game_name": update.get("game_name"),
            "stream_title": update.get("stream_title"),
            "stream_thumbnail_url": update.get("stream_thumbnail_url"),
        })
    
    updated_count = await db.update_streamers_status_bulk(valid_updates)
    
    return {"status": "synced", "updated_count": updated_count}
