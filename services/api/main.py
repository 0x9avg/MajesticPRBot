"""
API Service Entry Point.
FastAPI application with lifespan management for database and RabbitMQ connections.
"""

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import Config

import sys

logger = Config.setup_logging("API")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle - startup and shutdown."""
    # Startup
    logger.info(f"Starting {Config.APP_NAME}...")

    missing_vars = Config.validate_env_vars()
    if missing_vars:
        logger.error(
            f"Missing required environment variables: {', '.join(missing_vars)}"
        )

        sys.exit(1)

    logger.info("✓ Environment variables validated")

    # Initialize database
    from database import Database

    app.state.database = Database(
        db_host=Config.DB_HOST,
        db_user=Config.DB_USER,
        db_password=Config.DB_PASSWORD,
        db_name=Config.DB_NAME,
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

    app.state.auth = AuthService(secret_key=Config.JWT_SECRET)
    logger.info("✓ Auth service initialized")

    logger.info(f"✓ {Config.APP_NAME} started on {Config.API_HOST}:{Config.API_PORT}")

    yield

    # Shutdown
    logger.info("Shutting down...")

    if app.state.broker:
        await app.state.broker.disconnect()
        logger.info("✓ RabbitMQ disconnected")

    await app.state.database.close()
    logger.info("✓ Database disconnected")

    logger.info(f"✓ {Config.APP_NAME} stopped")


# Create FastAPI application
app = FastAPI(
    title=Config.APP_NAME,
    version="2.0.0",
    description="PRMajesticBot Central API Service",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=Config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
from routes import router as api_router

app.include_router(api_router)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": Config.APP_NAME,
        "version": "2.0.0",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=Config.API_HOST,
        port=Config.API_PORT,
        log_level=Config.LOG_LEVEL.lower(),
    )
