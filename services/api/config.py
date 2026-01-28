"""
Централизованная конфигурация API Service.
Содержит настройки для FastAPI, базы данных, JWT и RabbitMQ.
"""

import os
import logging
from typing import Optional, List
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

load_dotenv()


class Config:
    """API Service configuration."""

    # ==========================================================================
    # Application Settings
    # ==========================================================================
    APP_NAME = "PRMajesticBot API"

    API_HOST = os.getenv("API_HOST", "0.0.0.0")
    API_PORT = int(os.getenv("API_PORT", "8000"))

    # ==========================================================================
    # Database Settings
    # ==========================================================================
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = int(os.getenv("DB_PORT", "3306"))
    DB_USER = os.getenv("DB_USER", "root")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")
    DB_NAME = os.getenv("DB_NAME", "prmajesticbot")

    # ==========================================================================
    # JWT Settings
    # ==========================================================================
    JWT_SECRET = os.getenv("JWT_SECRET_KEY", os.getenv("DISCORD_TOKEN", "changeme"))
    JWT_ALGORITHM = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES = 15
    REFRESH_TOKEN_EXPIRE_DAYS = 7

    # ==========================================================================
    # RabbitMQ Settings
    # ==========================================================================
    RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
    RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
    RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
    RABBITMQ_PASSWORD = os.getenv("RABBITMQ_PASSWORD", "guest")
    RABBITMQ_VHOST = os.getenv("RABBITMQ_VHOST", "/")

    @property
    def RABBITMQ_URL(self) -> str:
        return f"amqp://{self.RABBITMQ_USER}:{self.RABBITMQ_PASSWORD}@{self.RABBITMQ_HOST}:{self.RABBITMQ_PORT}/{self.RABBITMQ_VHOST}"

    # Exchange for bot events
    EXCHANGE_NAME = "prmajesticbot"

    # ==========================================================================
    # CORS Settings
    # ==========================================================================
    CORS_ORIGINS = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        os.getenv("WEB_PANEL_URL", "http://localhost:5173"),
    ]

    # ==========================================================================
    # Security Settings
    # ==========================================================================
    MAX_LOGIN_ATTEMPTS = 5
    LOGIN_ATTEMPT_WINDOW = 300  # seconds
    ACCOUNT_LOCKOUT_DURATION = 900  # seconds

    # ==========================================================================
    # Guild Settings (Single-tenant mode)
    # ==========================================================================
    GUILD_ID = str(os.getenv("GUILD_ID", "0"))

    # ==========================================================================
    # Game IDs
    # ==========================================================================
    GTA5_GAME_ID = "32982"

    # ==========================================================================
    # Notification Templates
    # ==========================================================================
    ALLOWED_EVENT_TYPES = [
        "stream_online",
        "stream_offline",
        "category_to_gta",
        "category_from_gta",
    ]

    TEMPLATE_DEFAULTS = {
        "stream_online": "@everyone 🔴 {streamer_name} начал стрим!",
        "stream_offline": "⚫ {streamer_name} закончил стрим",
        "category_to_gta": "@everyone 🎮 {streamer_name} сменил категорию на GTA 5!",
        "category_from_gta": "🎮 {streamer_name} сменил категорию с GTA 5 на другую",
    }

    # ==========================================================================
    # Points Configuration
    # ==========================================================================
    DEFAULT_POINTS = {0: 0.25, 1: 0.4, 2: 0.5, 3: 0.6}

    # ==========================================================================
    # Logging Settings
    # ==========================================================================
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
    # Project root logs directory: services/api -> services -> root -> logs
    LOG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../logs"))
    LOG_FILE = "api.log"
    LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB
    LOG_BACKUP_COUNT = 5
    LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

    # ==========================================================================
    # Environment Validation
    # ==========================================================================
    REQUIRED_ENV_VARS = [
        "DB_HOST",
        "DB_USER",
        "DB_NAME",
        "GUILD_ID",
    ]

    @classmethod
    def validate_env_vars(cls) -> Optional[List[str]]:
        """Check that all required environment variables are set."""
        missing = [var for var in cls.REQUIRED_ENV_VARS if not os.getenv(var)]
        return missing if missing else None

    @classmethod
    def get_log_level(cls) -> int:
        """Get logging level from environment."""
        level_map = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
        }
        return level_map.get(cls.LOG_LEVEL, logging.INFO)

    @classmethod
    def setup_logging(cls, logger_name: str = None) -> logging.Logger:
        """Configure logging for the application."""
        os.makedirs(cls.LOG_DIR, exist_ok=True)

        log_level = cls.get_log_level()
        logger = logging.getLogger(logger_name)
        logger.setLevel(log_level)

        if logger.handlers:
            return logger

        formatter = logging.Formatter(cls.LOG_FORMAT, datefmt=cls.LOG_DATE_FORMAT)

        # File handler
        log_path = os.path.join(cls.LOG_DIR, cls.LOG_FILE)
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=cls.LOG_MAX_BYTES,
            backupCount=cls.LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(log_level)
        console_handler.setFormatter(formatter)

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        logger.propagate = False

        return logger
