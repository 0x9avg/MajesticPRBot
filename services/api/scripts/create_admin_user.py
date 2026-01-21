"""
Скрипт для создания первого администратора (разработчика).

Запуск: python services/api/scripts/create_admin_user.py
"""

import asyncio
import os
import sys

# Добавляем родительскую директорию в путь для импортов
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from config import Config
from database import Database
from services.auth import AuthService

load_dotenv()


async def create_admin():
    """Create first admin user."""
    # Configuration - change these values
    username = "developer"
    password = "NDDeveloper"  # Change this!
    nickname = "Merlin"
    role = "developer"
    discord_id = 1354899843629453584  # Change to your Discord ID
    
    logger = Config.setup_logging("CreateAdmin")
    
    logger.info("=" * 50)
    logger.info("СОЗДАНИЕ АДМИНИСТРАТОРА")
    logger.info("=" * 50)
    
    # Initialize Auth
    auth = AuthService(secret_key=Config.JWT_SECRET)
    password_hash = auth.hash_password(password)
    
    # Connect to database
    db = Database(
        db_host=Config.DB_HOST,
        db_user=Config.DB_USER,
        db_password=Config.DB_PASSWORD,
        db_name=Config.DB_NAME,
        logger=Config.setup_logging("Database")
    )
    
    try:
        await db.start()
        
        # Check if exists
        existing = await db.get_user_by_username(username)
        if existing:
            logger.warning(f"❌ Пользователь '{username}' уже существует!")
            return
        
        # Create user
        user_id = await db.create_user(
            discord_id=discord_id,
            username=username,
            nickname=nickname,
            password_hash=password_hash,
            role=role,
            created_by=None
        )
        
        logger.info("=" * 50)
        logger.info(f"✅ УСПЕХ! Пользователь создан c ID: {user_id}")
        logger.info(f"Логин: {username}")
        logger.info(f"Пароль: {password}")
        logger.info(f"Discord ID: {discord_id}")
        logger.info("=" * 50)
        
    except Exception as e:
        logger.error(f"❌ Ошибка создания пользователя: {e}")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(create_admin())
