"""
Скрипт для сброса счетчика неудачных попыток входа.

Запуск: python services/api/scripts/reset_login.py
"""

import asyncio
import os
import sys

# Добавляем родительскую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from config import Config
from database import Database

load_dotenv()


async def reset():
    """Reset failed login attempts for all users."""
    logger = Config.setup_logging("ResetScript")
    
    db = Database(
        db_host=Config.DB_HOST,
        db_user=Config.DB_USER,
        db_password=Config.DB_PASSWORD,
        db_name=Config.DB_NAME,
        logger=logger
    )
    
    try:
        await db.start()
        
        async with db.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("UPDATE web_auth SET failed_login_attempts = 0")
                await conn.commit()
                print("✅ SUCCESS: Reset failed_login_attempts for all users (web_auth).")
    except Exception as e:
        print(f"❌ ERROR: {e}")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(reset())
