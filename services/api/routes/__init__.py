"""
Routes package - aggregates all API routers.
"""

from fastapi import APIRouter

from routes.auth import router as auth_router
from routes.admin import router as admin_router
from routes.streamers import router as streamers_router
from routes.assistants import router as assistants_router
from routes.guilds import router as guilds_router
from routes.spec import router as spec_router
from routes.monitoring import router as monitoring_router
from routes.events import router as events_router
from routes.stats import router as stats_router
from routes.notifications import router as notifications_router
from routes.logs import router as logs_router
from routes.returns import router as returns_router
from routes.services import router as services_router
from routes.sanctions import router as sanctions_router

# Main router that includes all sub-routers
router = APIRouter(prefix="/api")

# Include all routers
router.include_router(auth_router)
router.include_router(admin_router)
router.include_router(streamers_router)
router.include_router(assistants_router)
router.include_router(guilds_router)
router.include_router(spec_router)
router.include_router(monitoring_router)
router.include_router(events_router)
router.include_router(stats_router)
router.include_router(notifications_router)
router.include_router(logs_router)
router.include_router(returns_router)
router.include_router(services_router)
router.include_router(sanctions_router)

__all__ = ["router"]
