"""
Unified seed script — creates all test data in one run.

Combines: bulk_add_streamers.py, create_admin_user.py, generate_test_pr.py

Data sources:
  - Streamers: real Twitch usernames → resolved to real Twitch IDs via Helix API
  - Admins: 3 real admin accounts (developer, developer2, EpikeS)
  - PRs: 16 test assistants with random assignments and historical sessions

Usage:
  cd services/api
  python scripts/seed_data.py            # full seed (clean + populate)
  python scripts/seed_data.py --no-clean # add without truncating
"""

import asyncio
import json
import logging
import os
import random
import sys
from datetime import datetime, timedelta, timezone

import aiohttp

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from database import Database
from dotenv import load_dotenv
from services.auth import AuthService

# Load API .env first, then Twitch bot .env for TWITCH_CLIENT_ID/SECRET
load_dotenv()
TWITCH_BOT_ENV = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "twitch_bot", ".env",
)
load_dotenv(TWITCH_BOT_ENV, override=True)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("SeedData")

# ─── Real streamers (curated from streamers.json) ──────────────────────
# Handpicked to cover all priority levels (p0 → p3)
STREAMERS = [
    # Priority 0
    {"name": "saint_yato",       "priority": 0},
    {"name": "shxwttyy",         "priority": 0},
    # Priority 1
    {"name": "lunae_lumen",      "priority": 1},
    {"name": "actor_step",       "priority": 1},
    {"name": "buichka",          "priority": 1},
    {"name": "crazy_borodach",   "priority": 1},
    # Priority 2
    {"name": "bratishkinoff",    "priority": 2},
    {"name": "muxa___",          "priority": 2},
    {"name": "gagik",            "priority": 2},
    {"name": "deko",             "priority": 2},
    {"name": "krikun",           "priority": 2},
    {"name": "insize",           "priority": 2},
    {"name": "sobran1e",         "priority": 2},
    # Priority 3
    {"name": "sasavot",          "priority": 3},
    {"name": "fatrjx3",          "priority": 3},
]

# ─── Admin users (real accounts) ───────────────────────────────────────
ADMIN_USERS = [
    {
        "username": "developer",
        "password": "NDDeveloper",
        "nickname": "Merlin",
        "role": "developer",
        "discord_id": 1354899843629453584,
    },
    {
        "username": "developer2",
        "password": "NDDeveloper",
        "nickname": "Yamato",
        "role": "developer",
        "discord_id": 566652404838170625,
    },
    {
        "username": "EpikeS",
        "password": "EpikeSPR",
        "nickname": "EpikeS",
        "role": "manager",
        "discord_id": 278198677947023371,
    },
]

# ─── Test PR assistants ────────────────────────────────────────────────
PR_ASSISTANTS = [
    {"nickname": "Stynee",    "role": "senior_employee", "discord_id": 100000000000000001},
    {"nickname": "Kefir",     "role": "employee",        "discord_id": 100000000000000002},
    {"nickname": "Shmel",     "role": "employee",        "discord_id": 100000000000000003},
    {"nickname": "ChocoPie",  "role": "employee",        "discord_id": 100000000000000004},
    {"nickname": "Marmelad",  "role": "senior_employee", "discord_id": 100000000000000005},
    {"nickname": "Cola",      "role": "employee",        "discord_id": 100000000000000006},
    {"nickname": "Pepsi",     "role": "employee",        "discord_id": 100000000000000007},
    {"nickname": "Sprite",    "role": "employee",        "discord_id": 100000000000000008},
    {"nickname": "Bounty",    "role": "employee",        "discord_id": 100000000000000009},
    {"nickname": "Mars",      "role": "senior_employee", "discord_id": 100000000000000010},
    {"nickname": "Snickers",  "role": "employee",        "discord_id": 100000000000000011},
    {"nickname": "Twix",      "role": "employee",        "discord_id": 100000000000000012},
    {"nickname": "KitKat",    "role": "employee",        "discord_id": 100000000000000013},
    {"nickname": "MilkyWay",  "role": "employee",        "discord_id": 100000000000000014},
    {"nickname": "Fanta",     "role": "employee",        "discord_id": 100000000000000015},
    {"nickname": "RedBull",   "role": "senior_employee", "discord_id": 100000000000000016},
]

# ─── Events ────────────────────────────────────────────────────────────
EVENTS = [
    {"name": "стрим сасавот",  "description": "сасавот жесткий стрим"},
    {"name": "казино",     "description": "Последний додеп"},
    {"name": "Синематик",     "description": "я фотограф"},
]



# ─── Twitch API helpers ────────────────────────────────────────────────

async def get_twitch_token(session: aiohttp.ClientSession) -> str:
    """Get Twitch app access token via client credentials."""
    client_id = os.getenv("TWITCH_CLIENT_ID")
    client_secret = os.getenv("TWITCH_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET not set")

    async with session.post(
        "https://id.twitch.tv/oauth2/token",
        params={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
        },
    ) as resp:
        data = await resp.json()
        if "access_token" not in data:
            raise RuntimeError(f"Twitch token error: {data}")
        return data["access_token"]


async def resolve_twitch_ids(
    session: aiohttp.ClientSession, token: str, usernames: list[str]
) -> dict[str, dict]:
    """Batch resolve Twitch usernames → {login: {id, display_name, profile_image_url}}."""
    client_id = os.getenv("TWITCH_CLIENT_ID")
    headers = {"Client-ID": client_id, "Authorization": f"Bearer {token}"}
    resolved = {}

    # Helix allows up to 100 logins per request
    for i in range(0, len(usernames), 100):
        batch = usernames[i : i + 100]
        params = [("login", name) for name in batch]
        async with session.get(
            "https://api.twitch.tv/helix/users", headers=headers, params=params
        ) as resp:
            data = await resp.json()
            for user in data.get("data", []):
                resolved[user["login"].lower()] = {
                    "id": int(user["id"]),
                    "display_name": user["display_name"],
                    "profile_image_url": user.get("profile_image_url"),
                }

    return resolved


async def seed():
    """Main seed function."""
    clean = "--no-clean" not in sys.argv

    auth = AuthService(secret_key=Config.jwt_secret)

    db = Database(
        db_host=Config.db_host,
        db_user=Config.db_user,
        db_password=Config.db_password,
        db_name=Config.db_name,
        logger=Config.setup_logging("SeedDB"),
    )

    try:
        await db.start()

        # ── Resolve Twitch IDs ─────────────────────────────────
        print("🔍  Резолв Twitch ID через Helix API...")
        async with aiohttp.ClientSession() as http:
            token = await get_twitch_token(http)
            usernames = [s["name"] for s in STREAMERS]
            twitch_map = await resolve_twitch_ids(http, token, usernames)

        resolved_count = len(twitch_map)
        print(f"   ✅ Найдено {resolved_count}/{len(STREAMERS)} стримеров\n")

        async with db.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                # ── Step 0: Clean ──────────────────────────────────
                if clean:
                    print("🗑️  Очистка таблиц...")
                    await cursor.execute("SET FOREIGN_KEY_CHECKS=0")
                    for table in ["admin_logs", "spec_sessions", "assistants", "streamers", "events", "web_auth"]:
                        await cursor.execute(f"TRUNCATE TABLE {table}")
                    await cursor.execute("SET FOREIGN_KEY_CHECKS=1")
                    await conn.commit()
                    print("   ✅ Таблицы очищены\n")

                # ── Step 1: Streamers (real Twitch IDs) ────────────
                print("🎥  Создание стримеров...")
                streamer_rows = []
                for s in STREAMERS:
                    username = s["name"].lower()
                    priority = s["priority"]
                    tw = twitch_map.get(username)
                    if not tw:
                        print(f"   ⚠️  {username} — не найден на Twitch, пропуск")
                        continue

                    twitch_id = tw["id"]
                    display_name = tw["display_name"]
                    profile_image = tw.get("profile_image_url")
                    is_online = random.choice([True, True, False])
                    started_at = None
                    if is_online:
                        started_at = (
                            datetime.now(timezone.utc) - timedelta(hours=random.randint(1, 6))
                        ).strftime("%Y-%m-%d %H:%M:%S")

                    await cursor.execute(
                        """
                        INSERT INTO streamers 
                            (streamer_id, streamer_name, is_online, priority, 
                             stream_title, stream_started_at, stream_game_id,
                             profile_image_url)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE streamer_name = VALUES(streamer_name)
                        """,
                        (
                            twitch_id, display_name, is_online, priority,
                            f"Stream by {display_name}" if is_online else None,
                            started_at,
                            "32982" if is_online else None,  # GTA5 game ID
                            profile_image,
                        ),
                    )
                    status_icon = "🟢" if is_online else "⚫"
                    print(f"   {status_icon} {display_name} (p{priority}, twitch_id={twitch_id})")
                    streamer_rows.append({"id": twitch_id, "name": display_name, "online": is_online, "priority": priority})

                await conn.commit()
                print()

                # ── Step 2: Admin users ────────────────────────────
                print("👑  Создание администраторов...")
                admin_pr_ids = []
                for user in ADMIN_USERS:
                    password_hash = auth.hash_password(user["password"])

                    # web_auth
                    await cursor.execute(
                        """
                        INSERT INTO web_auth (discord_id, username, password_hash, is_active)
                        VALUES (%s, %s, %s, TRUE)
                        ON DUPLICATE KEY UPDATE username = VALUES(username)
                        """,
                        (user["discord_id"], user["username"], password_hash),
                    )

                    # assistants profile
                    await cursor.execute(
                        """
                        INSERT INTO assistants (pr_id, nickname, role, added_at)
                        VALUES (%s, %s, %s, NOW())
                        ON DUPLICATE KEY UPDATE nickname = VALUES(nickname), role = VALUES(role)
                        """,
                        (user["discord_id"], user["nickname"], user["role"]),
                    )

                    admin_pr_ids.append(user["discord_id"])
                    print(f"   ✅ {user['nickname']} ({user['role']}) — login: {user['username']}")

                await conn.commit()
                print()

                # ── Step 3: Test PR assistants ─────────────────────
                print("👥  Создание тестовых ПР сотрудников...")
                all_pr_ids = list(admin_pr_ids)  # admins are also potential PRs
                for pr in PR_ASSISTANTS:
                    exp_days = random.randint(10, 300)
                    added_at = (datetime.now(timezone.utc) - timedelta(days=exp_days)).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )

                    await cursor.execute(
                        """
                        INSERT INTO assistants (pr_id, nickname, role, added_at)
                        VALUES (%s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE nickname = VALUES(nickname), role = VALUES(role)
                        """,
                        (pr["discord_id"], pr["nickname"], pr["role"], added_at),
                    )
                    all_pr_ids.append(pr["discord_id"])
                    print(f"   ✅ {pr['nickname']} ({pr['role']}, {exp_days}d exp)")

                await conn.commit()
                print()

                # ── Step 4: Events ─────────────────────────────────
                print("📅  Создание ивентов...")
                event_rows = []
                for i, evt in enumerate(EVENTS):
                    is_active = i < 2  # first 2 active, last inactive
                    start_time = datetime.now(timezone.utc) - timedelta(minutes=random.randint(15, 120))

                    await cursor.execute(
                        """
                        INSERT INTO events (name, description, is_active, start_time, notification_sent, priority, pr_slots)
                        VALUES (%s, %s, %s, %s, FALSE, %s, %s)
                        """,
                        (evt["name"], evt["description"], is_active, start_time, i, 5),
                    )
                    event_id = cursor.lastrowid
                    event_rows.append({"id": event_id, "name": evt["name"], "active": is_active})
                    status_icon = "🟢" if is_active else "⚫"
                    print(f"   {status_icon} {evt['name']} (id={event_id})")

                await conn.commit()
                print()

                # ── Step 5: Active sessions (assignments) ──────────
                print("🔗  Создание активных сессий спека...")
                online_streamers = [s for s in streamer_rows if s["online"]]
                active_events = [e for e in event_rows if e["active"]]
                assigned_pr_ids = set()

                # Assign some PRs to online streamers
                for streamer in online_streamers:
                    if not all_pr_ids:
                        break
                    # 1-2 PRs per online streamer
                    num_prs = random.randint(1, min(2, len(all_pr_ids)))
                    for _ in range(num_prs):
                        available = [p for p in all_pr_ids if p not in assigned_pr_ids]
                        if not available:
                            break
                        pr_id = random.choice(available)
                        assigned_pr_ids.add(pr_id)
                        started_at = (
                            datetime.now(timezone.utc) - timedelta(minutes=random.randint(10, 180))
                        ).strftime("%Y-%m-%d %H:%M:%S")

                        await cursor.execute(
                            """
                            INSERT INTO spec_sessions 
                                (pr_id, target_type, target_id, is_probation, started_at,
                                 priority_auto, rate_auto)
                            VALUES (%s, 'streamer', %s, %s, %s, %s, %s)
                            """,
                            (
                                pr_id, streamer["id"],
                                random.random() < 0.2,  # 20% probation
                                started_at,
                                streamer["priority"],
                                [0.25, 0.4, 0.5, 0.6][min(streamer["priority"], 3)],
                            ),
                        )
                        print(f"   🎮 PR {pr_id} → streamer {streamer['name']}")

                # Assign some PRs to active events
                for event in active_events:
                    available = [p for p in all_pr_ids if p not in assigned_pr_ids]
                    if not available:
                        break
                    num_prs = random.randint(1, min(3, len(available)))
                    for _ in range(num_prs):
                        available = [p for p in all_pr_ids if p not in assigned_pr_ids]
                        if not available:
                            break
                        pr_id = random.choice(available)
                        assigned_pr_ids.add(pr_id)
                        started_at = (
                            datetime.now(timezone.utc) - timedelta(minutes=random.randint(5, 90))
                        ).strftime("%Y-%m-%d %H:%M:%S")

                        await cursor.execute(
                            """
                            INSERT INTO spec_sessions 
                                (pr_id, target_type, target_id, is_probation, started_at,
                                 priority_auto, rate_auto)
                            VALUES (%s, 'event', %s, FALSE, %s, %s, %s)
                            """,
                            (pr_id, event["id"], started_at, 0, 0.25),
                        )
                        print(f"   📅 PR {pr_id} → event {event['name']}")

                await conn.commit()
                print()

                # ── Step 6: Historical (completed) sessions ────────
                print("📊  Создание исторических сессий...")
                historical_count = 0
                for pr_id in all_pr_ids:
                    # Each PR gets 3-15 historical sessions over last 30 days
                    num_past = random.randint(3, 15)
                    for _ in range(num_past):
                        days_ago = random.randint(1, 30)
                        start = datetime.now(timezone.utc) - timedelta(
                            days=days_ago,
                            hours=random.randint(0, 12),
                            minutes=random.randint(0, 59),
                        )
                        duration_min = random.randint(15, 240)
                        end = start + timedelta(minutes=duration_min)

                        # Pick a random streamer or event
                        if random.random() < 0.8:
                            target_type = "streamer"
                            target = random.choice(streamer_rows)
                            target_id = target["id"]
                            priority = target["priority"]
                        else:
                            target_type = "event"
                            target = random.choice(event_rows)
                            target_id = target["id"]
                            priority = 0

                        rate = [0.25, 0.4, 0.5, 0.6][min(priority, 3)]

                        await cursor.execute(
                            """
                            INSERT INTO spec_sessions 
                                (pr_id, target_type, target_id, is_probation,
                                 started_at, ended_at, end_reason,
                                 priority_auto, rate_auto)
                            VALUES (%s, %s, %s, %s, %s, %s, 'completed', %s, %s)
                            """,
                            (
                                pr_id, target_type, target_id,
                                random.random() < 0.1,
                                start.strftime("%Y-%m-%d %H:%M:%S"),
                                end.strftime("%Y-%m-%d %H:%M:%S"),
                                priority, rate,
                            ),
                        )
                        historical_count += 1

                await conn.commit()
                print(f"   ✅ {historical_count} исторических сессий создано\n")

                # ── Step 7: Admin logs (lifecycle simulation) ───────
                print("📝  Создание логов администрирования...")
                log_count = 0
                admin_pool = [(u["nickname"], u["role"]) for u in ADMIN_USERS]
                pr_nicknames = {p["discord_id"]: p["nickname"] for p in PR_ASSISTANTS}
                ip_pool = ["192.168.1.10", "10.0.0.5", "172.16.0.100", None]

                # Build a timeline of events over last 30 days
                log_entries = []
                now = datetime.now(timezone.utc)

                # --- Phase 1: System setup (25-30 days ago) ---
                for admin in ADMIN_USERS:
                    ts = now - timedelta(days=random.randint(28, 30), hours=random.randint(0, 12))
                    log_entries.append((
                        admin["nickname"], admin["role"], "reg_user",
                        "user", str(admin["discord_id"]),
                        json.dumps({"username": admin["username"], "role": admin["role"]}),
                        "192.168.1.10", ts,
                    ))

                # --- Phase 2: Streamer registrations (20-28 days ago) ---
                for s in streamer_rows:
                    admin_name, admin_role = random.choice(admin_pool)
                    ts = now - timedelta(days=random.randint(20, 28), hours=random.randint(0, 23))
                    log_entries.append((
                        admin_name, admin_role, "add_streamer",
                        "streamer", str(s["id"]),
                        json.dumps({"streamer_name": s["name"], "priority": s["priority"]}),
                        random.choice(ip_pool), ts,
                    ))

                # --- Phase 3: Priority updates (10-20 days ago) ---
                for s in random.sample(streamer_rows, min(5, len(streamer_rows))):
                    admin_name, admin_role = random.choice(admin_pool)
                    old_p = s["priority"]
                    new_p = random.choice([p for p in [0, 1, 2, 3] if p != old_p])
                    ts = now - timedelta(days=random.randint(10, 20), hours=random.randint(0, 23))
                    log_entries.append((
                        admin_name, admin_role, "update_streamer",
                        "streamer", str(s["id"]),
                        json.dumps({"priority": {"old": old_p, "new": new_p}}),
                        random.choice(ip_pool), ts,
                    ))

                # --- Phase 4: Event creation (5-15 days ago) ---
                for evt in event_rows:
                    admin_name, admin_role = random.choice(admin_pool)
                    ts = now - timedelta(days=random.randint(5, 15), hours=random.randint(0, 12))
                    log_entries.append((
                        admin_name, admin_role, "create_event",
                        "event", str(evt["id"]),
                        json.dumps({"name": evt["name"]}),
                        random.choice(ip_pool), ts,
                    ))

                # --- Phase 5: PR employee additions (15-25 days ago) ---
                for pr in PR_ASSISTANTS:
                    admin_name, admin_role = random.choice(admin_pool)
                    ts = now - timedelta(days=random.randint(15, 25), hours=random.randint(0, 23))
                    log_entries.append((
                        admin_name, admin_role, "create_assistant",
                        "assistant", str(pr["discord_id"]),
                        json.dumps({"nickname": pr["nickname"], "role": pr["role"]}),
                        random.choice(ip_pool), ts,
                    ))

                # --- Phase 6: Session claims/unclaims (1-15 days ago) ---
                for _ in range(random.randint(15, 25)):
                    admin_name, admin_role = random.choice(admin_pool)
                    s = random.choice(streamer_rows)
                    pr = random.choice(PR_ASSISTANTS)
                    action = random.choice(["assign_pr", "unassign_pr"])
                    ts = now - timedelta(days=random.randint(1, 15), hours=random.randint(0, 23))
                    details = {
                        "streamer_name": s["name"],
                        "pr_nickname": pr["nickname"],
                    }
                    if action == "unassign_pr":
                        details["reason"] = random.choice(["manual", "stream_offline", "category_from_gta"])
                    log_entries.append((
                        admin_name, admin_role, action,
                        "streamer", str(s["id"]),
                        json.dumps(details),
                        random.choice(ip_pool), ts,
                    ))

                # --- Phase 7: Manual sessions (1-10 days ago) ---
                for _ in range(random.randint(3, 6)):
                    admin_name, admin_role = random.choice(admin_pool)
                    pr = random.choice(PR_ASSISTANTS)
                    s = random.choice(streamer_rows)
                    ts = now - timedelta(days=random.randint(1, 10), hours=random.randint(0, 12))
                    dur_min = random.randint(30, 180)
                    log_entries.append((
                        admin_name, admin_role, "create_manual_session",
                        "assistant", str(pr["discord_id"]),
                        json.dumps({
                            "pr_nickname": pr["nickname"],
                            "streamer_name": s["name"],
                            "duration_minutes": dur_min,
                        }),
                        random.choice(ip_pool), ts,
                    ))

                # --- Phase 8: Event endings (0-3 days ago) ---
                inactive_events = [e for e in event_rows if not e["active"]]
                for evt in inactive_events:
                    admin_name, admin_role = random.choice(admin_pool)
                    ts = now - timedelta(days=random.randint(0, 3), hours=random.randint(0, 12))
                    log_entries.append((
                        admin_name, admin_role, "end_event",
                        "event", str(evt["id"]),
                        json.dumps({"name": evt["name"]}),
                        random.choice(ip_pool), ts,
                    ))

                # Sort by timestamp and insert
                log_entries.sort(key=lambda x: x[7])
                for entry in log_entries:
                    admin_name, admin_role, action, target_type, target_id, details, ip, ts = entry
                    await cursor.execute(
                        """
                        INSERT INTO admin_logs 
                            (admin_name, admin_role, action, target_type, target_id, details, ip_address, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (admin_name, admin_role, action, target_type, target_id, details, ip, ts.strftime("%Y-%m-%d %H:%M:%S")),
                    )
                    log_count += 1

                await conn.commit()
                print(f"   ✅ {log_count} записей лога создано\n")

                # ── Summary ────────────────────────────────────────
                print("=" * 50)
                print("✨ Seed завершён!")
                print(f"   🎥 Стримеров: {len(streamer_rows)}")
                print(f"   👑 Админов: {len(ADMIN_USERS)}")
                print(f"   👥 ПР сотрудников: {len(PR_ASSISTANTS)}")
                print(f"   📅 Ивентов: {len(event_rows)}")
                print(f"   🔗 Активных сессий: {len(assigned_pr_ids)}")
                print(f"   📊 Исторических сессий: {historical_count}")
                print(f"   📝 Логов: {log_count}")
                print("=" * 50)

    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(seed())
