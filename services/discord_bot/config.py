"""
Конфигурация Discord Bot микросервиса.
Полностью независимый от других сервисов.
"""

import os
import logging
from typing import Optional, List
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Discord Bot Service configuration."""

    VERSION = "2.0.0 (Microservices)"

    # ==========================================================================
    # Discord Settings
    # ==========================================================================
    DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
    GUILD_ID = str(os.getenv("GUILD_ID", "0"))

    # ==========================================================================
    # API Service Connection
    # ==========================================================================
    API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
    API_TIMEOUT = int(os.getenv("API_TIMEOUT", "30"))

    # ==========================================================================
    # RabbitMQ Settings
    # ==========================================================================
    RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
    RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
    RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
    RABBITMQ_PASSWORD = os.getenv("RABBITMQ_PASSWORD", "guest")
    RABBITMQ_VHOST = os.getenv("RABBITMQ_VHOST", "/")
    RABBITMQ_EXCHANGE = "prmajesticbot"
    RABBITMQ_QUEUE = "discord_bot"

    # ==========================================================================
    # Game IDs (for filtering)
    # ==========================================================================
    GTA5_GAME_ID = "32982"

    # ==========================================================================
    # Environment Validation
    # ==========================================================================

    REQUIRED_ENV_VARS = [
        "DISCORD_TOKEN",
        "GUILD_ID",
    ]

    @classmethod
    def validate_env_vars(cls) -> Optional[List[str]]:
        """Check that all required environment variables are set."""
        missing = [var for var in cls.REQUIRED_ENV_VARS if not os.getenv(var)]
        return missing if missing else None

    # ==========================================================================
    # Logging
    # ==========================================================================
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
    # Project root logs directory: services/discord_bot -> services -> root -> logs
    LOG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../logs"))
    LOG_FILE = "discord_bot.log"
    LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    @classmethod
    def get_log_level(cls) -> int:
        level_map = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
        }
        return level_map.get(cls.LOG_LEVEL, logging.INFO)

    @classmethod
    def setup_logging(cls, logger_name: str = None) -> logging.Logger:
        """Configure logging."""
        os.makedirs(cls.LOG_DIR, exist_ok=True)

        logger = logging.getLogger(logger_name)
        logger.setLevel(cls.get_log_level())

        if logger.handlers:
            return logger

        formatter = logging.Formatter(cls.LOG_FORMAT)

        # File handler
        file_handler = RotatingFileHandler(
            os.path.join(cls.LOG_DIR, cls.LOG_FILE),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        logger.propagate = False

        return logger
