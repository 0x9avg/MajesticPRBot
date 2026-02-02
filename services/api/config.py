"""
Централизованная конфигурация API Service.
Использует pydantic-settings для type-safe конфигурации.
"""

import logging
import os
from functools import lru_cache
from logging.handlers import RotatingFileHandler
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """API Service configuration using Pydantic Settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ==========================================================================
    # Application Settings
    # ==========================================================================
    app_name: str = "PRMajesticBot API"
    api_host: str = Field(default="0.0.0.0", validation_alias="API_HOST")
    api_port: int = Field(default=8000, validation_alias="API_PORT")

    # ==========================================================================
    # Database Settings
    # ==========================================================================
    db_host: str = Field(default="localhost", validation_alias="DB_HOST")
    db_port: int = Field(default=3306, validation_alias="DB_PORT")
    db_user: str = Field(default="root", validation_alias="DB_USER")
    db_password: str = Field(default="root", validation_alias="DB_PASSWORD")
    db_name: str = Field(default="prmajesticbot", validation_alias="DB_NAME")

    # ==========================================================================
    # JWT Settings
    # ==========================================================================
    jwt_secret: str = Field(default="changeme", validation_alias="JWT_SECRET_KEY")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # ==========================================================================
    # RabbitMQ Settings
    # ==========================================================================
    rabbitmq_host: str = Field(default="localhost", validation_alias="RABBITMQ_HOST")
    rabbitmq_port: int = Field(default=5672, validation_alias="RABBITMQ_PORT")
    rabbitmq_user: str = Field(default="guest", validation_alias="RABBITMQ_USER")
    rabbitmq_password: str = Field(
        default="guest", validation_alias="RABBITMQ_PASSWORD"
    )
    rabbitmq_vhost: str = Field(default="/", validation_alias="RABBITMQ_VHOST")
    exchange_name: str = "prmajesticbot"

    @property
    def rabbitmq_url(self) -> str:
        return f"amqp://{self.rabbitmq_user}:{self.rabbitmq_password}@{self.rabbitmq_host}:{self.rabbitmq_port}/{self.rabbitmq_vhost}"

    # ==========================================================================
    # CORS Settings
    # ==========================================================================
    web_panel_url: str = Field(
        default="http://localhost:5173", validation_alias="WEB_PANEL_URL"
    )

    @property
    def cors_origins(self) -> List[str]:
        return [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            self.web_panel_url,
        ]

    # ==========================================================================
    # Security Settings
    # ==========================================================================
    max_login_attempts: int = 5
    login_attempt_window: int = 300  # seconds
    account_lockout_duration: int = 900  # seconds

    # ==========================================================================
    # Guild Settings (Single-tenant mode)
    # ==========================================================================
    guild_id: str = Field(default="0", validation_alias="GUILD_ID")

    # ==========================================================================
    # Game IDs
    # ==========================================================================
    gta5_game_id: str = "32982"

    # ==========================================================================
    # Notification Templates
    # ==========================================================================
    allowed_event_types: List[str] = [
        "stream_online",
        "stream_offline",
        "category_to_gta",
        "category_from_gta",
    ]

    template_defaults: dict = {
        "stream_online": "🔴 {streamer_name} начал стрим!",
        "stream_offline": "⚫ {streamer_name} закончил стрим",
        "category_to_gta": "🎮 {streamer_name} сменил категорию на GTA 5!",
        "category_from_gta": "🎮 {streamer_name} сменил категорию с GTA 5 на другую",
    }

    # ==========================================================================
    # Points Configuration
    # ==========================================================================
    default_points: dict = {0: 0.25, 1: 0.4, 2: 0.5, 3: 0.6}

    # ==========================================================================
    # Logging Settings
    # ==========================================================================
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    log_dir: str = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../../logs")
    )
    log_file: str = "api.log"
    log_max_bytes: int = 10 * 1024 * 1024  # 10MB
    log_backup_count: int = 5
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    log_date_format: str = "%Y-%m-%d %H:%M:%S"

    def get_log_level(self) -> int:
        """Get logging level from environment."""
        level_map = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
        }
        return level_map.get(self.log_level.upper(), logging.INFO)

    def setup_logging(self, logger_name: str = None) -> logging.Logger:
        """Configure logging for the application."""
        os.makedirs(self.log_dir, exist_ok=True)

        log_level = self.get_log_level()
        logger = logging.getLogger(logger_name)
        logger.setLevel(log_level)

        if logger.handlers:
            return logger

        formatter = logging.Formatter(self.log_format, datefmt=self.log_date_format)

        # File handler
        log_path = os.path.join(self.log_dir, self.log_file)
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=self.log_max_bytes,
            backupCount=self.log_backup_count,
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


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance."""
    return Settings()


# Backward compatibility: expose as Config for existing imports
Config = get_settings()
