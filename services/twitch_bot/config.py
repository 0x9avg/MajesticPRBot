"""
Конфигурация Twitch Bot микросервиса.
Полностью независимый от других сервисов.
Uses pydantic-settings for type validation and .env loading.
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from typing import ClassVar

from pydantic import Field
from pydantic_settings import BaseSettings


class Config(BaseSettings):
    """Twitch Bot Service configuration using pydantic-settings."""

    _PLACEHOLDER_VALUES: ClassVar[frozenset[str]] = frozenset(
        {
            "",
            "0",
            "your_twitch_client_id",
            "your_twitch_client_secret",
            "replace_with_twitch_service_token",
        }
    )

    # ==========================================================================
    # Twitch Settings
    # ==========================================================================
    twitch_client_id: str = Field(default="", alias="TWITCH_CLIENT_ID")
    twitch_client_secret: str = Field(default="", alias="TWITCH_CLIENT_SECRET")
    twitch_bot_id: int = Field(default=0, alias="TWITCH_BOT_ID")
    twitch_tokens_file: str = Field(
        default=".tio.tokens.json",
        alias="TWITCH_TOKENS_FILE",
    )

    # ==========================================================================
    # API Service Connection
    # ==========================================================================
    api_base_url: str = Field(default="", alias="API_BASE_URL")
    api_timeout: int = Field(default=30, alias="API_TIMEOUT")
    service_token: str = Field(default="", alias="SERVICE_TOKEN")

    # ==========================================================================
    # RabbitMQ Settings
    # ==========================================================================
    rabbitmq_host: str = Field(default="", alias="RABBITMQ_HOST")
    rabbitmq_port: int = Field(default=0, alias="RABBITMQ_PORT")
    rabbitmq_user: str = Field(default="", alias="RABBITMQ_USER")
    rabbitmq_password: str = Field(default="", alias="RABBITMQ_PASSWORD")
    rabbitmq_vhost: str = Field(default="", alias="RABBITMQ_VHOST")
    rabbitmq_exchange: str = "prmajesticbot"

    # ==========================================================================
    # Game IDs
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
    log_file: ClassVar[str] = "twitch_bot.log"
    log_format: ClassVar[str] = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "populate_by_name": True,  # Allow both alias and field name
        "extra": "ignore",
    }

    @classmethod
    def _looks_like_placeholder(cls, value: str) -> bool:
        normalized = value.strip().lower()
        return (
            normalized in cls._PLACEHOLDER_VALUES
            or normalized.startswith("replace_with_")
            or normalized.startswith("your_")
            or normalized.endswith("_here")
        )

    @staticmethod
    def _is_blank(value: str) -> bool:
        return not value or not value.strip()

    def validate_twitch_credentials(self) -> None:
        errors: list[str] = []
        if self._is_blank(self.twitch_client_id):
            errors.append("TWITCH_CLIENT_ID is required.")
        elif self._looks_like_placeholder(self.twitch_client_id):
            errors.append("TWITCH_CLIENT_ID must not use a placeholder value.")

        if self._is_blank(self.twitch_client_secret):
            errors.append("TWITCH_CLIENT_SECRET is required.")
        elif self._looks_like_placeholder(self.twitch_client_secret):
            errors.append("TWITCH_CLIENT_SECRET must not use a placeholder value.")

        if self.twitch_bot_id <= 0:
            errors.append("TWITCH_BOT_ID must be a positive Twitch user ID.")

        if errors:
            raise ValueError("Invalid Twitch credentials:\n- " + "\n- ".join(errors))

    def validate_api_config(self) -> None:
        errors: list[str] = []
        if self._is_blank(self.api_base_url):
            errors.append("API_BASE_URL is required.")
        if self.api_timeout <= 0:
            errors.append("API_TIMEOUT must be a positive integer.")
        if self._is_blank(self.service_token):
            errors.append("SERVICE_TOKEN is required.")
        elif self._looks_like_placeholder(self.service_token):
            errors.append("SERVICE_TOKEN must not use a placeholder value.")

        if errors:
            raise ValueError("Invalid Twitch API configuration:\n- " + "\n- ".join(errors))

    def validate_broker_config(self) -> None:
        errors: list[str] = []
        if self._is_blank(self.rabbitmq_host):
            errors.append("RABBITMQ_HOST is required.")
        if self.rabbitmq_port <= 0:
            errors.append("RABBITMQ_PORT must be a positive integer.")
        if self._is_blank(self.rabbitmq_user):
            errors.append("RABBITMQ_USER is required.")
        if self._is_blank(self.rabbitmq_password):
            errors.append("RABBITMQ_PASSWORD is required.")
        if self._is_blank(self.rabbitmq_vhost):
            errors.append("RABBITMQ_VHOST is required.")

        if errors:
            raise ValueError(
                "Invalid Twitch RabbitMQ configuration:\n- " + "\n- ".join(errors)
            )

    def validate_startup_config(self) -> None:
        """Fail-fast validation for Twitch bot startup settings."""
        errors: list[str] = []

        for validator in (
            self.validate_twitch_credentials,
            self.validate_api_config,
            self.validate_broker_config,
        ):
            try:
                validator()
            except ValueError as exc:
                errors.append(str(exc))

        if errors:
            raise ValueError("\n".join(errors))

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

        file_handler = RotatingFileHandler(
            os.path.join(self.log_dir, self.log_file),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        logger.propagate = False

        return logger


# Singleton instance - instantiate once at module load
Config = Config()
