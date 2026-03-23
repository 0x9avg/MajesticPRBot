"""Public game servers catalog routes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from dependencies import require_any_permission
from middleware import get_trace_id
from schemas.envelope import success_envelope
from schemas.guild import GameServerDto

if TYPE_CHECKING:
    from db import Database


router = APIRouter(tags=["Game Servers"])


def get_db(request: Request):
    return request.app.state.database


@router.get("/game-servers")
async def list_game_servers(
    request: Request,
    db: "Database" = Depends(get_db),
    _principal: dict = Depends(
        require_any_permission(
            "dashboard.view",
            "game_servers.view",
        )
    ),
):
    trace_id = get_trace_id(request)
    servers = await db.list_game_servers(include_inactive=True)
    return JSONResponse(
        content=success_envelope(
            data=[
                GameServerDto.model_validate(server).model_dump(mode="json")
                for server in servers
            ],
            message="Game servers loaded",
            trace_id=trace_id,
        )
    )
