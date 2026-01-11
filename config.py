"""
Centralized configuration for PRMajesticBot.
Contains constants, settings, and environment variable validation.
"""

import os
import logging
from typing import Dict, Optional
from logging.handlers import RotatingFileHandler


class Config:
    """Main configuration class for the bot."""

    # Twitch Game IDs
    GTA5_GAME_ID = "32982"

    # Monitored games (can be extended)
    MONITORED_GAMES: Dict[str, str] = {
        "GTA5": GTA5_GAME_ID,
    }

    # Default notification templates
    TEMPLATE_DEFAULTS = {
        "stream_online": "@everyone 🔴 {streamer_name} начал стрим!",
        "stream_offline": "⚫ {streamer_name} закончил стрим",
        "category_to_gta": "@everyone 🎮 {streamer_name} переключился на GTA 5!",
        "category_from_gta": "🎮 {streamer_name} ушёл с GTA 5",
    }

    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

    # Logging configuration
    LOG_DIR = "logs"
    LOG_FILE = "bot.log"
    LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB
    LOG_BACKUP_COUNT = 5

    # Log format
    LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

    # Required environment variables
    REQUIRED_ENV_VARS = [
        "CLIENT_ID",
        "CLIENT_SECRET",
        "BOT_ID",
        "DISCORD_TOKEN",
        "DB_HOST",
        "DB_USER",
        "DB_PASSWORD",
        "DB_NAME",
    ]

    @staticmethod
    def validate_env_vars() -> Optional[list[str]]:
        """
        Validate that all required environment variables are set.

        Returns:
            List of missing variables, or None if all are present.
        """
        missing = [var for var in Config.REQUIRED_ENV_VARS if not os.getenv(var)]
        return missing if missing else None

    @staticmethod
    def get_log_level() -> int:
        """
        Get logging level from environment.

        Returns:
            Logging level (DEBUG, INFO, WARNING, ERROR).
        """
        level_str = os.getenv("LOG_LEVEL", "INFO").upper()
        level_map = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
        }
        return level_map.get(level_str, logging.INFO)

    @staticmethod
    def setup_logging(logger_name: str = None) -> logging.Logger:
        """
        Setup logging configuration for the bot.

        Args:
            logger_name: Name of the logger. If None, returns root logger.

        Returns:
            Configured logger instance.
        """
        # Create logs directory if it doesn't exist
        os.makedirs(Config.LOG_DIR, exist_ok=True)

        log_level = Config.get_log_level()

        # Get or create logger
        logger = logging.getLogger(logger_name)
        logger.setLevel(log_level)

        # Avoid adding handlers multiple times
        if logger.handlers:
            return logger

        # Create formatters
        formatter = logging.Formatter(Config.LOG_FORMAT, datefmt=Config.LOG_DATE_FORMAT)

        # File handler with rotation
        log_path = os.path.join(Config.LOG_DIR, Config.LOG_FILE)
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=Config.LOG_MAX_BYTES,
            backupCount=Config.LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)  # Always log everything to file
        file_handler.setFormatter(formatter)

        # Console handler (respects log level)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(log_level)
        console_handler.setFormatter(formatter)

        # Add handlers
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

        # CRITICAL FIX: Prevent propagation to avoid duplicate logs from parent loggers
        logger.propagate = False

        return logger
