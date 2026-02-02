"""
Скрипт для создания тестовых данных (V2 Schema).
Создает:
- Стримеров (онлайн/оффлайн)
- Ивенты (активные/завершенные)
- PR сотрудников (с разными ролями и стажем)
- Активные сессии спека (связь PR -> Streamer/Event)
"""

import asyncio
import logging
import os
import random
import sys
from datetime import datetime, timedelta

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import Config, Database

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("GenerateData")

# Constants
NICKNAMES = [
    "Yamato",
    "EpikeS",
    "Stynee",
    "Kefir",
    "Shmel",
    "ChocoPie",
    "Marmelad",
    "Cola",
    "Pepsi",
    "Sprite",
    "Bounty",
    "Mars",
    "Snickers",
    "Twix",
    "KitKat",
    "MilkyWay",
]

ROLES = ["employee", "senior_employee", "manager", "developer"]

STREAMERS_LIST = [
    (1001, "Sasavot", 615),  # ID, Name, GameID
    (1002, "Muxa", 313),
    (1003, "fatr", 615),
    (1004, "xqc", 313),
    (1005, "bratishkinoff", 615),
]

EVENTS_LIST = ["Спек сасавот", "Спек муха", "Синематик", "Последний деп"]


async def create_test_data():
    db = Database(
        db_host=Config.db_host,
        db_user=Config.db_user,
        db_password=Config.db_password,
        db_name=Config.db_name,
        logger=logger,
    )

    try:
        print("🔗 Подключение к базе данных...")
        await db.start()

        async with db.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                # 1. Clean Data
                print("🗑️  Очистка таблиц...")
                await cursor.execute("SET FOREIGN_KEY_CHECKS=0")
                await cursor.execute("TRUNCATE TABLE assistants")
                await cursor.execute("TRUNCATE TABLE spec_sessions")
                await cursor.execute("TRUNCATE TABLE streamers")
                await cursor.execute("TRUNCATE TABLE events")
                await cursor.execute("SET FOREIGN_KEY_CHECKS=1")

                # 2. Create Streamers
                print("🎥 Создание стримеров...")
                streamer_ids = []
                for s_id, s_name, game_id in STREAMERS_LIST:
                    is_online = random.choice([True, False])
                    # Если онлайн, то начали 1-4 часа назад
                    started_at = None
                    if is_online:
                        started_at = (
                            datetime.now() - timedelta(hours=random.randint(1, 4))
                        ).strftime("%Y-%m-%d %H:%M:%S")

                    await cursor.execute(
                        """
                        INSERT INTO streamers (streamer_id, streamer_name, is_online, stream_game_id, stream_title, stream_started_at)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            s_id,
                            s_name,
                            is_online,
                            game_id,
                            f"Stream of {s_name}",
                            started_at,
                        ),
                    )
                    streamer_ids.append(
                        {"id": s_id, "name": s_name, "online": is_online}
                    )

                # 3. Create Events
                print("📅 Создание ивентов...")
                event_ids = []
                for name in EVENTS_LIST:
                    is_active = random.choice([True, False])
                    # Start time
                    if is_active:
                        start_time = datetime.now() - timedelta(
                            minutes=random.randint(10, 120)
                        )
                    else:
                        start_time = datetime.now() + timedelta(
                            days=random.randint(1, 5)
                        )

                    await cursor.execute(
                        """
                        INSERT INTO events (name, description, is_active, start_time, notification_sent)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (name, "Test description", is_active, start_time, False),
                    )
                    event_id = cursor.lastrowid
                    event_ids.append(
                        {"id": event_id, "name": name, "active": is_active}
                    )

                # 4. Create Assistants & Assign
                print("👥 Создание сотрудников и назначений...")
                for i, nickname in enumerate(NICKNAMES):
                    pr_id = 900000 + i
                    role = random.choices(ROLES, weights=[40, 30, 20, 10], k=1)[0]

                    # Experience (backdate added_at)
                    exp_days = random.randint(5, 365)
                    added_at = datetime.now() - timedelta(days=exp_days)

                    # Assignment Logic
                    assigned_type = None
                    assigned_id = None

                    # 50% chance to be busy
                    if random.random() < 0.5:
                        # Decide target type
                        target_candidates = []

                        # Find online streamers
                        online_streamers = [s for s in streamer_ids if s["online"]]
                        active_events = [e for e in event_ids if e["active"]]

                        # Mix them
                        if online_streamers:
                            for s in online_streamers:
                                target_candidates.append(("streamer", s["id"]))

                        if active_events:
                            for e in active_events:
                                target_candidates.append(("event", e["id"]))

                        # Pick one if available
                        if target_candidates:
                            t_type, t_id = random.choice(target_candidates)
                            assigned_type = t_type
                            assigned_id = t_id

                    # Stats
                    total_seconds = random.randint(3600, 360000)
                    sessions = random.randint(10, 500)

                    # Insert Assistant
                    await cursor.execute(
                        """
                        INSERT INTO assistants (
                            pr_id, nickname, role,
                            assigned_to_type, assigned_to_id,
                            total_spec_seconds, session_count, added_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            pr_id,
                            nickname,
                            role,
                            assigned_type,
                            assigned_id,
                            total_seconds,
                            sessions,
                            added_at,
                        ),
                    )

                    # If assigned, create active session
                    status_text = "Free"
                    if assigned_type:
                        await cursor.execute(
                            """
                            INSERT INTO spec_sessions (pr_id, target_type, target_id, started_at)
                            VALUES (%s, %s, %s, NOW())
                            """,
                            (pr_id, assigned_type, assigned_id),
                        )
                        status_text = f"Spectating {assigned_type} {assigned_id}"

                    print(f"✅ {nickname} ({role}) - {exp_days}d exp - {status_text}")

                await conn.commit()
                print("\n✨ Тестовые данные успешно сгенерированы!")

    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        import traceback

        traceback.print_exc()
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(create_test_data())
