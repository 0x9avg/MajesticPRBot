"""
Monitoring and Dashboard routes for API.
"""

from fastapi import APIRouter, Depends, Request

from schemas.monitoring import MonitoringRefreshRequest, DashboardStatusResponse
from config import Config

router = APIRouter(tags=["Monitoring"])


def get_db(request: Request):
    """Get database from app state."""
    return request.app.state.database


def get_broker(request: Request):
    """Get broker from app state."""
    return request.app.state.broker


@router.post("/monitoring/refresh")
async def refresh_monitoring(
    data: MonitoringRefreshRequest = MonitoringRefreshRequest(),
    db=Depends(get_db),
    broker=Depends(get_broker),
):
    """
    Trigger monitoring message refresh.
    Sends event to Discord bot to update monitoring embeds.
    """
    if broker:
        await broker.publish("monitoring.refresh", {
            "event": "monitoring.refresh",
            "guild_id": Config.GUILD_ID,
            "force": data.force,
        })
        return {"status": "refresh_requested", "force": data.force}
    
    return {"status": "broker_unavailable"}


@router.get("/dashboard/status", response_model=DashboardStatusResponse)
async def get_dashboard_status(db=Depends(get_db)):
    """Get system dashboard status."""
    # Get streamer counts
    all_streamers = await db.list_all_streamers()
    online_streamers = [s for s in all_streamers if s.get("is_online")]
    gta_streamers = [
        s for s in online_streamers
        if str(s.get("game_id")) == Config.GTA5_GAME_ID
    ]
    
    # Get active specs count
    active_specs = [s for s in all_streamers if s.get("assigned_pr_id")]
    
    # Get assistants count
    async with db.pool.acquire() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute("SELECT COUNT(*) as count FROM assistants")
            result = await cursor.fetchone()
            assistants_count = result["count"] if result else 0
    
    return DashboardStatusResponse(
        total_streamers=len(all_streamers),
        online_streamers=len(online_streamers),
        gta_streamers=len(gta_streamers),
        active_specs=len(active_specs),
        total_assistants=assistants_count,
        system_status="healthy",
    )


@router.get("/stats/daily")
async def get_daily_stats(days: int = 7, db=Depends(get_db)):
    """Get aggregated daily stats for the last N days."""
    async with db.pool.acquire() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(
                """
                SELECT 
                    date,
                    SUM(p0_seconds) as total_p0,
                    SUM(p1_seconds) as total_p1,
                    SUM(p2_seconds) as total_p2,
                    SUM(p3_seconds) as total_p3,
                    SUM(total_points) as total_points,
                    COUNT(DISTINCT pr_id) as active_prs
                FROM daily_stats
                WHERE date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
                GROUP BY date
                ORDER BY date DESC
                """,
                (days,),
            )
            stats = await cursor.fetchall()
    
    return {"days": days, "stats": [dict(s) for s in stats]}


@router.get("/stats/leaderboard")
async def get_leaderboard(limit: int = 10, db=Depends(get_db)):
    """Get top PR assistants by total spec time."""
    async with db.pool.acquire() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(
                """
                SELECT pr_id, total_spec_seconds, session_count
                FROM assistants
                ORDER BY total_spec_seconds DESC
                LIMIT %s
                """,
                (limit,),
            )
            leaderboard = await cursor.fetchall()
    
    return {
        "limit": limit,
        "leaderboard": [
            {
                "rank": i + 1,
                "pr_id": entry["pr_id"],
                "total_seconds": entry["total_spec_seconds"],
                "total_formatted": f"{entry['total_spec_seconds'] // 3600}ч {(entry['total_spec_seconds'] % 3600) // 60}м",
                "session_count": entry["session_count"],
            }
            for i, entry in enumerate(leaderboard)
        ],
    }
