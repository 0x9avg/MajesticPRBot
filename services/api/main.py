"""
API Service Entry Point.
FastAPI application with lifespan management for database and RabbitMQ connections.
"""

import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import Config

logger = Config.setup_logging("API")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle - startup and shutdown."""
    # Startup
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

# Include routers
from routes import router as api_router

app.include_router(api_router)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": Config.app_name,
        "version": "2.0.0",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=Config.api_host,
        port=Config.api_port,
        log_level=Config.log_level.lower(),
    )
