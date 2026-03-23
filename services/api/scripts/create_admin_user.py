"""
Скрипт для создания первого администратора (разработчика).

Запуск:
  python scripts/create_admin_user.py --username admin --nickname Admin --role developer --discord-id 123
"""

import argparse
import asyncio
import os
import sys
from getpass import getpass

# Добавляем родительскую директорию в путь для импортов
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from db import Database
from dotenv import load_dotenv
from services.auth import AuthService

load_dotenv()


async def create_admin(username, password, nickname, role, discord_id):
    """Create first admin user."""
    Config.validate_database_config()
    Config.validate_auth_config()
    logger = Config.setup_logging("CreateAdmin")

    logger.info("=" * 50)
    logger.info("СОЗДАНИЕ АДМИНИСТРАТОРА")
    logger.info("=" * 50)

    # Initialize Auth
    auth = AuthService(secret_key=Config.jwt_secret)
    password_hash = auth.hash_password(password)

    # Connect to database
    db = Database(
        db_host=Config.db_host,
        db_port=Config.db_port,
        db_user=Config.db_user,
        db_password=Config.db_password,
        db_name=Config.db_name,
        logger=Config.setup_logging("Database"),
    )

    try:
        await db.start()  # Init pool

        # Check if exists in web_auth
        existing = await db.get_user_by_username(username)
        if existing:
            logger.warning(f"❌ Пользователь '{username}' уже существует!")
            return

        created_discord_id = await db.create_user_with_assistant(
            discord_id=discord_id,
            username=username,
            password_hash=password_hash,
            nickname=nickname,
            role=role,
            created_by=None,
        )

        logger.info("=" * 50)
        logger.info(f"✅ УСПЕХ! Пользователь создан c Discord ID: {created_discord_id}")
        logger.info(f"Логин: {username}")
        logger.info(f"Discord ID: {discord_id}")
        logger.info(f"Роль: {role} )")
        logger.info("=" * 50)

    except Exception as e:
        logger.error(f"❌ Ошибка создания пользователя: {e}")
    finally:
        await db.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a privileged web user without storing credentials in code."
    )
    parser.add_argument("--username", required=True, help="Web panel username")
    parser.add_argument("--nickname", required=True, help="Assistant nickname")
    parser.add_argument(
        "--role",
        required=True,
        choices=[
            "developer",
            "manager",
            "senior_employee",
            "employee",
            "junior_employee",
        ],
        help="Assistant role",
    )
    parser.add_argument(
        "--discord-id",
        required=True,
        type=int,
        help="Discord user ID for the assistant/web user",
    )
    parser.add_argument(
        "--password",
        help="Password for the new user. Avoid passing it in shell history; prefer interactive prompt.",
    )
    parser.add_argument(
        "--password-env",
        default="ADMIN_PASSWORD",
        help="Environment variable name to read password from when --password is omitted.",
    )
    return parser


def _resolve_password(args: argparse.Namespace) -> str:
    if args.password:
        return args.password

    env_password = os.getenv(args.password_env)
    if env_password:
        return env_password

    if sys.stdin.isatty():
        password = getpass("Password: ").strip()
        password_confirm = getpass("Confirm password: ").strip()
        if password != password_confirm:
            raise SystemExit("Passwords do not match.")
        if not password:
            raise SystemExit("Password must not be empty.")
        return password

    raise SystemExit(
        "Password is required. Pass --password, set the environment variable "
        f"{args.password_env}, or run interactively."
    )


if __name__ == "__main__":
    parser = _build_parser()
    cli_args = parser.parse_args()
    password = _resolve_password(cli_args)

    asyncio.run(
        create_admin(
            username=cli_args.username,
            password=password,
            nickname=cli_args.nickname,
            role=cli_args.role,
            discord_id=cli_args.discord_id,
        )
    )
