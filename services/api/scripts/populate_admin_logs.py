
import asyncio
import os
import sys
import random
import json
from datetime import datetime, timedelta

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from database import Database
from dotenv import load_dotenv

load_dotenv()

async def populate_logs():
    logger = Config.setup_logging("PopulateLogs")
    db = Database(
        db_host=Config.db_host,
        db_user=Config.db_user,
        db_password=Config.db_password,
        db_name=Config.db_name,
        logger=logger,
    )
    
    await db.start()
    
    print("\n--- Populating admin_logs with fake data ---")
    
    admins = [
        {"name": "Merlin", "role": "developer"},
        {"name": "Yamato", "role": "developer"},
        {"name": "EpikeS", "role": "manager"},
        {"name": "dev3", "role": "admin"},
    ]
    
    actions = [
        "update_streamer",
        "create_event",
        "delete_streamer",
        "ban_user",
        "update_settings",
        "send_notification"
    ]
    
    targets = [
        {"type": "streamer", "ids": ["1001", "1002", "1005"]},
        {"type": "event", "ids": ["1", "2"]},
        {"type": "user", "ids": ["50", "99"]},
        {"type": "system", "ids": ["settings"]},
    ]

    try:
        async with db.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                # Generate 50 logs
                for i in range(50):
                    admin = random.choice(admins)
                    target_group = random.choice(targets)
                    target_type = target_group["type"]
                    target_id = random.choice(target_group["ids"])
                    action = random.choice(actions)
                    
                    # Random date within last 30 days
                    days_ago = random.randint(0, 30)
                    hours_ago = random.randint(0, 23)
                    created_at = datetime.now() - timedelta(days=days_ago, hours=hours_ago)
                    
                    details = {
                        "old_value": random.choice([True, False, 1, 0, "old_name"]),
                        "new_value": random.choice([True, False, 1, 0, "new_name"]),
                        "reason": f"Test log entry #{i+1}"
                    }

                    await cursor.execute(
                        """
                        INSERT INTO admin_logs 
                            (admin_name, admin_role, action, target_type, target_id, details, ip_address, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            admin["name"],
                            admin["role"],
                            action,
                            target_type,
                            target_id,
                            json.dumps(details),
                            f"192.168.1.{random.randint(1, 255)}",
                            created_at
                        )
                    )
                
                await conn.commit()
                print("✅ Successfully added 50 fake log entries!")
                    
    finally:
        await db.close()

if __name__ == "__main__":
    asyncio.run(populate_logs())
