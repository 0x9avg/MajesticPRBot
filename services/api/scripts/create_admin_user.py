"""
Скрипт для создания первого администратора (разработчика).

Запуск: python services/api/scripts/create_admin_user.py
"""

import asyncio
import os
import sys

# Добавляем родительскую директорию в путь для импортов
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from database import Database
from dotenv import load_dotenv
from services.auth import AuthService

load_dotenv()


async def create_admin(username, password, nickname, role, discord_id):
    """Create first admin user."""
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

        # Create user in web_auth
        created_discord_id = await db.create_user(
            discord_id=discord_id,
            username=username,
            password_hash=password_hash,
            created_by=None,
        )

        # Create/Update assistant profile
        # Since create_user creates web_auth, we need to manually ensure assistant record exists with role/nick
        async with db.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                # Insert or Update assistant
                await cursor.execute(
                    """
                    INSERT INTO assistants (pr_id, nickname, role, added_at)
                    VALUES (%s, %s, %s, NOW())
                    ON DUPLICATE KEY UPDATE nickname = %s, role = %s
                    """,
                    (discord_id, nickname, role, nickname, role),
                )
                await conn.commit()

        logger.info("=" * 50)
        logger.info(f"✅ УСПЕХ! Пользователь создан c Discord ID: {created_discord_id}")
        logger.info(f"Логин: {username}")
        logger.info(f"Пароль: {password}")
        logger.info(f"Discord ID: {discord_id}")
        logger.info(f"Роль: {role} )")
        logger.info("=" * 50)

    except Exception as e:
        logger.error(f"❌ Ошибка создания пользователя: {e}")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(
        create_admin(
            username="developer",
            password="NDDeveloper",
            nickname="Merlin",
            role="developer",
            discord_id=1354899843629453584,
        )
    )

    asyncio.run(
        create_admin(
            username="developer2",
            password="NDDeveloper",
            nickname="Yamato",
            role="developer",
            discord_id=566652404838170625,
        )
    )

    asyncio.run(
        create_admin(
            username="EpikeS",
            password="EpikeSPR",
            nickname="EpikeS",
            role="manager",
            discord_id=278198677947023371,
        )
    )
    # asyncio.run(
    #     create_admin(
    #         username="testUser1",
    #         password="testUser1",
    #         nickname="testUser1",
    #         role="employee",
    #         discord_id=278198677947023370,
    #     )
    # )
