"""
Конфигурация Discord Bot микросервиса.
Полностью независимый от других сервисов.
Uses pydantic-settings for type validation and .env loading.
"""

import os
import logging
from typing import Optional, List, ClassVar
from logging.handlers import RotatingFileHandler
from pydantic_settings import BaseSettings
from pydantic import Field


class Config(BaseSettings):
    """Discord Bot Service configuration using pydantic-settings."""

    version: ClassVar[str] = "2.0.0 (Microservices)"

    # ==========================================================================
    # Discord Settings
    # ==========================================================================
    discord_token: str = Field(default="", alias="DISCORD_TOKEN")
    guild_id: str = Field(default="0", alias="GUILD_ID")

    # ==========================================================================
    # API Service Connection
    # ==========================================================================
    api_base_url: str = Field(default="http://localhost:8000", alias="API_BASE_URL")
    api_timeout: int = Field(default=30, alias="API_TIMEOUT")

    # ==========================================================================
    # RabbitMQ Settings
    # ==========================================================================
    rabbitmq_host: str = Field(default="localhost", alias="RABBITMQ_HOST")
    rabbitmq_port: int = Field(default=5672, alias="RABBITMQ_PORT")
    rabbitmq_user: str = Field(default="guest", alias="RABBITMQ_USER")
    rabbitmq_password: str = Field(default="guest", alias="RABBITMQ_PASSWORD")
    rabbitmq_vhost: str = Field(default="/", alias="RABBITMQ_VHOST")
    rabbitmq_exchange: str = "prmajesticbot"
    rabbitmq_queue: str = "discord_bot"

    # ==========================================================================
    # Game IDs (for filtering)
    # ==========================================================================
    gta5_game_id: str = "32982"

    # ==========================================================================
    # Logging
    # ==========================================================================
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    
    # ClassVars are not validated or loaded from env
    log_dir: ClassVar[str] = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../../logs")
    )
    log_file: ClassVar[str] = "discord_bot.log"
    log_format: ClassVar[str] = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    # ==========================================================================
    # Required Environment Variables for Validation
    # ==========================================================================
    required_env_vars: ClassVar[List[str]] = [
        "DISCORD_TOKEN",
        "GUILD_ID",
    ]

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "populate_by_name": True,  # Allow both alias and field name
        "extra": "ignore",
    }

    def validate_env_vars(self) -> Optional[List[str]]:
        """Check that all required environment variables are set."""
        missing = []
        if not self.discord_token:
            missing.append("DISCORD_TOKEN")
        if self.guild_id == "0":
            missing.append("GUILD_ID")
        return missing if missing else None

    def get_log_level(self) -> int:
        level_map = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
        }
        return level_map.get(self.log_level.upper(), logging.INFO)

    def setup_logging(self, logger_name: str = None) -> logging.Logger:
        """Configure logging."""
        os.makedirs(self.log_dir, exist_ok=True)

        logger = logging.getLogger(logger_name)
        logger.setLevel(self.get_log_level())

        if logger.handlers:
            return logger

        formatter = logging.Formatter(self.log_format)

        # File handler
        file_handler = RotatingFileHandler(
            os.path.join(self.log_dir, self.log_file),
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


# Singleton instance - instantiate once at module load
Config = Config()
