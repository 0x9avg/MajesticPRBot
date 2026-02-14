"""
API Service Entry Point.
FastAPI application with lifespan management for database and RabbitMQ connections.
"""

import time
from contextlib import asynccontextmanager

from config import Config
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from middleware import TracingMiddleware
from middleware.exceptions import register_exception_handlers
from routes import router as api_router

logger = Config.setup_logging("API")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle - startup and shutdown."""
    import time

    # Startup
    app.state._start_time = time.time()
    logger.info(f"Starting {Config.app_name}...")

    # Initialize database
    from database import Database

    app.state.database = Database(
        db_host=Config.db_host,
        db_user=Config.db_user,
        db_password=Config.db_password,
        db_name=Config.db_name,
        logger=Config.setup_logging("Database"),
    )
    await app.state.database.start()
    logger.info("✓ Database connected")

    # Initialize RabbitMQ broker (lazy import to avoid circular deps)
    try:
        from services.broker import BrokerService

        app.state.broker = BrokerService(logger=Config.setup_logging("Broker"))
        await app.state.broker.connect()
        logger.info("✓ RabbitMQ connected")
    except Exception as e:
        logger.warning(f"RabbitMQ not available: {e}. Running without message broker.")
        app.state.broker = None

    # Initialize Auth service
    from services.auth import AuthService

    app.state.auth = AuthService(secret_key=Config.jwt_secret)
    logger.info("✓ Auth service initialized")

    logger.info(f"✓ {Config.app_name} started on {Config.api_host}:{Config.api_port}")

    yield

    # Shutdown
    logger.info("Shutting down...")

    if app.state.broker:
        await app.state.broker.disconnect()
        logger.info("✓ RabbitMQ disconnected")

    await app.state.database.close()
    logger.info("✓ Database disconnected")

    logger.info(f"✓ {Config.app_name} stopped")


# Create FastAPI application
app = FastAPI(
    title=Config.app_name,
    version="2.0.0",
    description="PRMajesticBot Central API Service",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=Config.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Tracing middleware (must be after CORS to access request)
app.add_middleware(TracingMiddleware)

# Exception handlers (for envelope responses)

register_exception_handlers(app)

# Include routers

app.include_router(api_router)


@app.get("/health")
async def health_check():
    """Health check endpoint with detailed stats."""

    # Calculate uptime
    uptime_seconds = 0
    if hasattr(app.state, "_start_time"):
        uptime_seconds = int(time.time() - app.state._start_time)

    # Component status - active checks
    db_status = "disconnected"
    broker_status = "disconnected"

    # Database: try a simple query
    try:
        if app.state.database and app.state.database.pool:
            async with app.state.database.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("SELECT 1")
                    await cursor.fetchone()
            db_status = "connected"
    except Exception as e:
        logger.warning(f"Health check: DB connection failed: {e}")
        db_status = "disconnected"

    # RabbitMQ: check connection is_closed
    try:
        if app.state.broker:
            conn = getattr(app.state.broker, "connection", None)
            if conn and not conn.is_closed:
                broker_status = "connected"
    except Exception as e:
        logger.warning(f"Health check: Broker check failed: {e}")
        broker_status = "disconnected"

    # Entity stats
    stats = {
        "streamers_total": 0,
        "streamers_online": 0,
        "active_specs": 0,
    }

    try:
        if db_status == "connected":
            streamers = await app.state.database.list_all_streamers()
            stats["streamers_total"] = len(streamers)
            stats["streamers_online"] = sum(1 for s in streamers if s.get("is_online"))

            specs = await app.state.database.get_active_sessions()
            stats["active_specs"] = len(specs) if specs else 0
    except Exception as e:
        logger.warning(f"Health stats query failed: {e}")

    return {
        "status": "healthy" if db_status == "connected" else "degraded",
        "service": Config.app_name,
        "version": "2.0.0",
        "uptime_seconds": uptime_seconds,
        "components": {
            "database": db_status,
            "broker": broker_status,
        },
        "stats": stats,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=Config.api_host,
        port=Config.api_port,
        log_level=Config.log_level.lower(),
    )
