"""
Централизованная конфигурация PRMajesticBot.
Содержит константы, настройки и валидацию переменных окружения.
"""

import os
import logging
from typing import Dict, Optional
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

# Load environment variables BEFORE accessing them
load_dotenv()


class Config:
    """Класс конфигурации бота."""

    # ID игр Twitch
    GTA5_GAME_ID = "32982"

    # Баллы в час (По умолчанию)
    DEFAULT_POINTS = {0: 0.25, 1: 0.4, 2: 0.5, 3: 0.6}

    # Отслеживаемые игры (можно расширить)
    MONITORED_GAMES: Dict[str, str] = {
        "Grand Theft Auto V": GTA5_GAME_ID,
    }

    EVENT_TYPE_LABELS = {
        "stream_online": "🔴 Начало стрима",
        "stream_offline": "⚫ Конец стрима",
        "category_to_gta": "🎮 Смена категории на GTA 5",
        "category_from_gta": "🎮 Смена категории с GTA 5 на другую",
    }

    # Шаблоны уведомлений по умолчанию
    TEMPLATE_DEFAULTS = {
        "stream_online": "@everyone 🔴 {streamer_name} начал стрим!",
        "stream_offline": "⚫ {streamer_name} закончил стрим",
        "category_to_gta": "@everyone 🎮 {streamer_name} сменил категорию на GTA 5!",
        "category_from_gta": "🎮 {streamer_name} сменил категорию с GTA 5 на другую",
    }

    # Разрешенные типы событий (защита от SQL-инъекций)
    ALLOWED_EVENT_TYPES = [
        "stream_online",
        "stream_offline",
        "category_to_gta",
        "category_from_gta",
    ]

    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

    GUILD_ID = int(os.getenv("GUILD_ID", "0"))

    # Настройка логирования
    LOG_DIR = "logs"
    LOG_FILE = "bot.log"
    LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB
    LOG_BACKUP_COUNT = 5

    # Формат логов
    LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

    # Обязательные переменные окружения
    REQUIRED_ENV_VARS = [
        "CLIENT_ID",
        "CLIENT_SECRET",
        "BOT_ID",
        "DISCORD_TOKEN",
        "GUILD_ID",
        "DB_HOST",
        "DB_USER",
        "DB_PASSWORD",
        "DB_NAME",
    ]

    @staticmethod
    def validate_env_vars() -> Optional[list[str]]:
        """
        Проверка наличия всех обязательных переменных окружения.

        Returns:
            Список отсутствующих переменных или None.
        """
        missing = [var for var in Config.REQUIRED_ENV_VARS if not os.getenv(var)]
        return missing if missing else None

    @staticmethod
    def get_log_level() -> int:
        """
        Получение уровня логирования из окружения.

        Returns:
            Уровень логирования (DEBUG, INFO, WARNING, ERROR).
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
        Настройка конфигурации логирования.

        Args:
            logger_name: Имя логгера. Если None, возвращает root логгер.

        Returns:
            Настроенный экземпляр логгера.
        """
        # Создаем папку логов, если нет
        os.makedirs(Config.LOG_DIR, exist_ok=True)

        log_level = Config.get_log_level()

        # Получаем или создаем логгер
        logger = logging.getLogger(logger_name)
        logger.setLevel(log_level)

        # Не добавляем обработчики повторно
        if logger.handlers:
            return logger

        # Создаем форматеры
        formatter = logging.Formatter(Config.LOG_FORMAT, datefmt=Config.LOG_DATE_FORMAT)

        # Файловый обработчик с ротацией
        log_path = os.path.join(Config.LOG_DIR, Config.LOG_FILE)
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=Config.LOG_MAX_BYTES,
            backupCount=Config.LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)  # Всегда пишем все в файл
        file_handler.setFormatter(formatter)

        # Консольный обработчик (учитывает уровень логов)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(log_level)
        console_handler.setFormatter(formatter)

        # Добавляем обработчики
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

        # Запрещаем распространение, чтобы избежать дублей
        logger.propagate = False

        return logger
