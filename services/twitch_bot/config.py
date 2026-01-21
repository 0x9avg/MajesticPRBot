"""
Конфигурация Twitch Bot микросервиса.
Полностью независимый от других сервисов.
"""

import os
import logging
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Twitch Bot Service configuration."""

    # ==========================================================================
    # Twitch Settings
    # ==========================================================================
    TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID", "")
    TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET", "")
    TWITCH_BOT_ID = int(os.getenv("TWITCH_BOT_ID", "0"))
    
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
    
    # ==========================================================================
    # Game IDs
    # ==========================================================================
    GTA5_GAME_ID = "32982"
    
    # ==========================================================================
    # Guild (for routing events to correct Discord server)
    # ==========================================================================
    GUILD_ID = int(os.getenv("GUILD_ID", "0"))
    
    # ==========================================================================
    # Logging
    # ==========================================================================
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
    # Project root logs directory: services/twitch_bot -> services -> root -> logs
    LOG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../logs"))
    LOG_FILE = "twitch_bot.log"
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
        
        file_handler = RotatingFileHandler(
            os.path.join(cls.LOG_DIR, cls.LOG_FILE),
            maxBytes=10*1024*1024,
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
    
    @classmethod
    def validate(cls) -> list:
        """Validate required settings."""
        missing = []
        if not cls.TWITCH_CLIENT_ID:
            missing.append("TWITCH_CLIENT_ID")
        if not cls.TWITCH_CLIENT_SECRET:
            missing.append("TWITCH_CLIENT_SECRET")
        if not cls.TWITCH_BOT_ID:
            missing.append("TWITCH_BOT_ID")
        return missing
