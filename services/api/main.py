"""
API Service Entry Point.
FastAPI application with lifespan management for database and RabbitMQ connections.
"""

import asyncio
import time
from contextlib import asynccontextmanager

from config import Config
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from middleware import TracingMiddleware
from middleware.exceptions import register_exception_handlers
from runtime_status import get_api_runtime_status
from routes import router as api_router
from versioning import APP_VERSION

logger = Config.setup_logging("API")


async def _broker_connect_loop(broker, retry_interval: float = 5.0) -> None:
    """Background task: keep retrying broker connection until success."""
    while True:
        try:
            await broker.connect()
            logger.info("✓ RabbitMQ connected (background retry)")
            return
        except Exception as e:
            logger.debug(f"Broker retry failed: {e}")
            await asyncio.sleep(retry_interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle - startup and shutdown."""
    # Startup
    app.state._start_time = time.time()
    app.state._perf_start_time = time.perf_counter()
    app.state._startup_complete = False
    app.state._broker_retry_task = None
    app.state._outbox_relay_task = None
    app.state._service_registry = {}

    Config.validate_service_startup()
    # Fail-fast: block insecure defaults in production
    Config.validate_production_security()

    logger.info(f"Starting {Config.app_name} (env={Config.env})...")

    # Initialize database
    from db import Database

    app.state.database = Database(
        db_host=Config.db_host,
        db_port=Config.db_port,
        db_user=Config.db_user,
        db_password=Config.db_password,
        db_name=Config.db_name,
        logger=Config.setup_logging("Database"),
    )
    await app.state.database.start()
    logger.info("✓ Database connected")

    # Initialize RabbitMQ broker (lazy import to avoid circular deps)
    from services.broker import BrokerService

    app.state.broker = BrokerService(
        host=Config.rabbitmq_host,
        port=Config.rabbitmq_port,
        user=Config.rabbitmq_user,
        password=Config.rabbitmq_password,
        vhost=Config.rabbitmq_vhost,
        exchange_name=Config.exchange_name,
        logger=Config.setup_logging("Broker"),
    )
    try:
        await app.state.broker.connect()
        logger.info("✓ RabbitMQ connected")
    except Exception as e:
        logger.warning(
            f"RabbitMQ not available: {e}. Retrying in background..."
        )
        app.state._broker_retry_task = asyncio.create_task(
            _broker_connect_loop(app.state.broker)
        )

    # Initialize Auth service
    from services.auth import AuthService

    app.state.auth = AuthService(
        secret_key=Config.jwt_secret,
        algorithm=Config.jwt_algorithm,
        access_token_expire_minutes=Config.access_token_expire_minutes,
        refresh_token_expire_days=Config.refresh_token_expire_days,
    )
    logger.info("✓ Auth service initialized")

    from services.outbox import outbox_enabled, outbox_relay_loop

    if outbox_enabled(app):
        app.state._outbox_relay_task = asyncio.create_task(outbox_relay_loop(app))
        logger.info("✓ Outbox relay started")

    app.state._startup_complete = True

    logger.info(f"✓ {Config.app_name} started on {Config.api_host}:{Config.api_port}")

    yield

    # Shutdown
    logger.info("Shutting down...")

    # Cancel broker retry task if still running
    if app.state._broker_retry_task and not app.state._broker_retry_task.done():
        app.state._broker_retry_task.cancel()
        try:
            await app.state._broker_retry_task
        except asyncio.CancelledError:
            pass

    if app.state._outbox_relay_task and not app.state._outbox_relay_task.done():
        app.state._outbox_relay_task.cancel()
        try:
            await app.state._outbox_relay_task
        except asyncio.CancelledError:
            pass

    if app.state.broker:
        await app.state.broker.disconnect()
        logger.info("✓ RabbitMQ disconnected")

    await app.state.database.close()
    logger.info("✓ Database disconnected")

    logger.info(f"✓ {Config.app_name} stopped")


def _get_uptime_seconds() -> int:
    if hasattr(app.state, "_start_time"):
        return int(time.time() - app.state._start_time)
    return 0


async def _get_component_status() -> tuple[str, str]:
    """Return lightweight dependency status checks for readiness diagnostics."""
    db_status = "disconnected"
    broker_status = "disconnected"

    try:
        database = getattr(app.state, "database", None)
        pool = getattr(database, "pool", None)
        if database and pool:
            async with pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("SELECT 1")
                    await cursor.fetchone()
            db_status = "connected"
    except Exception as e:
        logger.warning(f"Health check: DB connection failed: {e}")

    try:
        broker = getattr(app.state, "broker", None)
        if broker:
            conn = getattr(broker, "connection", None)
            if conn and not conn.is_closed:
                broker_status = "connected"
    except Exception as e:
        logger.warning(f"Health check: Broker check failed: {e}")

    return db_status, broker_status


# Create FastAPI application
app = FastAPI(
    title=Config.app_name,
    version=APP_VERSION,
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


@app.get("/api/health")
async def health_check():
    """Liveness endpoint used by container healthcheck."""
    return {
        "status": "alive",
        "service": Config.app_name,
        "version": APP_VERSION,
        "uptime_seconds": _get_uptime_seconds(),
        "startup_complete": bool(getattr(app.state, "_startup_complete", False)),
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


@app.get("/api/health/ready")
async def readiness_check():
    """Readiness endpoint with dependency diagnostics."""
    snapshot = await get_api_runtime_status(app)

    return {
        "status": "ready" if snapshot["ready"] else "not_ready",
        "service": snapshot["service"],
        "version": snapshot["version"],
        "uptime_seconds": snapshot["uptime_seconds"],
        "startup_complete": snapshot["startup_complete"],
        "checked_at": snapshot["checked_at"],
        "components": snapshot["components"],
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=Config.api_host,
        port=Config.api_port,
        log_level=Config.log_level.lower(),
    )
