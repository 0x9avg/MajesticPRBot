"""
Централизованная конфигурация API Service.
Использует pydantic-settings для type-safe конфигурации.
"""

import logging
import os
import sys
from functools import lru_cache
from logging.handlers import RotatingFileHandler
from typing import List

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
    env: str = Field(
        default="development", validation_alias="ENV"
    )  # development, production

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
    refresh_token_expire_days: int = 30

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

    # Service tokens for bots (comma-separated list of pre-shared secrets)
    # Strict format:
    # - "discord_service:<token>,twitch_service:<token>"
    # - only named entries are accepted
    service_tokens: str = Field(default="", validation_alias="SERVICE_TOKENS")
    required_service_principals: tuple[str, ...] = ("discord_service", "twitch_service")

    @property
    def service_token_list(self) -> List[str]:
        """Return only token values from SERVICE_TOKENS."""
        return list(self.service_token_map.values())

    @property
    def service_token_map(self) -> dict[str, str]:
        """Parse SERVICE_TOKENS into a strict name->token mapping."""
        return self._parse_service_token_map_strict()

    def _parse_service_token_map_strict(self) -> dict[str, str]:
        """
        Parse SERVICE_TOKENS strictly.

        Allowed format:
            SERVICE_TOKENS=discord_service:<token>,twitch_service:<token>

        Rules:
        - unnamed entries are forbidden
        - empty names/tokens are forbidden
        - duplicate names are forbidden
        - duplicate token values are forbidden
        - required service principals must be present
        """
        raw = (self.service_tokens or "").strip()
        if not raw:
            raise ValueError(
                "SERVICE_TOKENS is required and must be in format "
                "'discord_service:<token>,twitch_service:<token>'."
            )

        mapping: dict[str, str] = {}
        seen_values: set[str] = set()
        for item in [part.strip() for part in raw.split(",") if part.strip()]:
            if ":" not in item:
                raise ValueError(
                    f"Invalid SERVICE_TOKENS entry '{item}'. Named format "
                    "'<service_name>:<token>' is required."
                )

            name, token = item.split(":", 1)
            key = name.strip()
            value = token.strip()

            if not key:
                raise ValueError(
                    f"Invalid SERVICE_TOKENS entry '{item}': service name is empty."
                )
            if not value:
                raise ValueError(
                    f"Invalid SERVICE_TOKENS entry '{item}': token is empty."
                )
            if key in mapping:
                raise ValueError(
                    f"Invalid SERVICE_TOKENS: duplicate service name '{key}'."
                )
            if value in seen_values:
                raise ValueError(
                    f"Invalid SERVICE_TOKENS: duplicate token value for service '{key}'."
                )

            mapping[key] = value
            seen_values.add(value)

        missing = [
            name for name in self.required_service_principals if name not in mapping
        ]
        if missing:
            raise ValueError(
                "SERVICE_TOKENS is missing required principals: " + ", ".join(missing)
            )

        return mapping

    def validate_service_tokens_contract(self) -> None:
        """Fail-fast validation for strict SERVICE_TOKENS contract."""
        self._parse_service_token_map_strict()

    # ==========================================================================
    # Cookie Settings for Refresh Token
    # ==========================================================================
    cookie_secure: bool = Field(default=False, validation_alias="COOKIE_SECURE")
    cookie_samesite: str = "lax"
    cookie_path: str = "/api/auth"
    cookie_domain: str = Field(default="", validation_alias="COOKIE_DOMAIN")

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
        "stream_online": "**{streamer_name}** начал стрим!",
        "stream_offline": "**{streamer_name}** закончил стрим",
        "category_to_gta": "**{streamer_name}** сменил категорию на GTA 5!",
        "category_from_gta": "**{streamer_name}** ушел с GTA 5",
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

    # ==========================================================================
    # Insecure Default Constants (for fail-fast checks)
    # ==========================================================================
    _INSECURE_JWT_SECRETS = frozenset({"changeme", "secret", "test", ""})
    _INSECURE_DB_PASSWORDS = frozenset({"root", "password", "test", ""})

    def validate_production_security(self) -> None:
        """Fail-fast: block startup in production with insecure defaults."""
        if self.env.lower() != "production":
            return

        errors: list[str] = []

        if self.jwt_secret in self._INSECURE_JWT_SECRETS:
            errors.append(
                "JWT_SECRET_KEY is set to an insecure default. "
                "Set a strong secret in production."
            )
        if len(self.jwt_secret) < 32:
            errors.append(
                f"JWT_SECRET_KEY is too short ({len(self.jwt_secret)} chars). "
                "Use at least 32 characters in production."
            )
        if self.db_password in self._INSECURE_DB_PASSWORDS:
            errors.append(
                "DB_PASSWORD is set to an insecure default. "
                "Use a strong password in production."
            )

        if errors:
            for e in errors:
                print(f"FATAL SECURITY ERROR: {e}", file=sys.stderr)
            sys.exit(1)

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
