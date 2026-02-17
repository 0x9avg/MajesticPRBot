"""Unified seed script for the current DB architecture.

What it seeds:
  - Streamers (resolved from Twitch API)
  - Web users + assistants
  - Events
  - Active + historical spec_sessions
  - Assistant points/sanctions/warnings snapshots
  - Compact universal admin_logs entries

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
from typing import Any, Dict, Optional

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


PRIORITY_RATES = {0: 0.25, 1: 0.4, 2: 0.5, 3: 0.6}


def make_log_details(
    summary: str,
    *,
    changes: Optional[Dict[str, Any]] = None,
    payload: Optional[Dict[str, Any]] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    details: Dict[str, Any] = {"summary": summary}
    if changes:
        details["changes"] = changes
    if payload:
        details["payload"] = payload
    if meta:
        details["meta"] = meta
    return details


def random_rate_for_priority(priority: int) -> float:
    return PRIORITY_RATES.get(min(max(priority, 0), 3), 0.25)



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
                    for table in [
                        "admin_logs",
                        "auth_logs",
                        "sessions",
                        "spec_sessions",
                        "events",
                        "assistants",
                        "web_auth",
                        "streamers",
                    ]:
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
                if not streamer_rows:
                    raise RuntimeError(
                        "Не удалось получить ни одного стримера с Twitch API. Seed остановлен."
                    )
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
                        INSERT INTO assistants (pr_id, nickname, role, appointed_at)
                        VALUES (%s, %s, %s, UTC_TIMESTAMP())
                        ON DUPLICATE KEY UPDATE
                            nickname = VALUES(nickname),
                            role = VALUES(role),
                            appointed_at = VALUES(appointed_at)
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
                    appointed_at = (datetime.now(timezone.utc) - timedelta(days=exp_days)).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )

                    await cursor.execute(
                        """
                        INSERT INTO assistants (pr_id, nickname, role, appointed_at)
                        VALUES (%s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            nickname = VALUES(nickname),
                            role = VALUES(role),
                            appointed_at = VALUES(appointed_at)
                        """,
                        (pr["discord_id"], pr["nickname"], pr["role"], appointed_at),
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
                                random_rate_for_priority(streamer["priority"]),
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
                            (pr_id, event["id"], started_at, 0, random_rate_for_priority(0)),
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
                        if streamer_rows and (not event_rows or random.random() < 0.8):
                            target_type = "streamer"
                            target = random.choice(streamer_rows)
                            target_id = target["id"]
                            priority = target["priority"]
                        elif event_rows:
                            target_type = "event"
                            target = random.choice(event_rows)
                            target_id = target["id"]
                            priority = 0
                        else:
                            continue

                        rate = random_rate_for_priority(priority)
                        duration_seconds = int((end - start).total_seconds())
                        credited_points = round((duration_seconds / 3600.0) * rate, 4)

                        await cursor.execute(
                            """
                            INSERT INTO spec_sessions 
                                (pr_id, target_type, target_id, is_probation,
                                 started_at, ended_at, end_reason,
                                 priority_auto, rate_auto, credited_points)
                            VALUES (%s, %s, %s, %s, %s, %s, 'completed', %s, %s, %s)
                            """,
                            (
                                pr_id, target_type, target_id,
                                random.random() < 0.1,
                                start.strftime("%Y-%m-%d %H:%M:%S"),
                                end.strftime("%Y-%m-%d %H:%M:%S"),
                                priority, rate, credited_points,
                            ),
                        )
                        historical_count += 1

                await conn.commit()
                print(f"   ✅ {historical_count} исторических сессий создано\n")

                # ── Step 6.5: Reconcile points + seed sanctions/warnings ────
                print("🧮  Синхронизация баллов ассистентов...")
                await cursor.execute(
                    """
                    UPDATE spec_sessions
                    SET credited_points = ROUND(
                        CASE
                            WHEN ended_at IS NULL OR deleted_at IS NOT NULL THEN 0
                            ELSE (COALESCE(duration_seconds, 0) / 3600.0) * COALESCE(applied_hourly_rate, 0)
                        END,
                        4
                    )
                    """
                )
                await cursor.execute(
                    """
                    UPDATE assistants a
                    LEFT JOIN (
                        SELECT pr_id, ROUND(COALESCE(SUM(credited_points), 0), 4) AS computed_auto_points
                        FROM spec_sessions
                        GROUP BY pr_id
                    ) s ON s.pr_id = a.pr_id
                    SET a.auto_points_total = COALESCE(s.computed_auto_points, 0)
                    """
                )

                assistant_adjustments: dict[int, dict[str, Any]] = {}
                seeded_sanctions = 0
                for pr_id in all_pr_ids:
                    manual_adjustment = (
                        round(random.uniform(-2.0, 5.0), 4)
                        if random.random() < 0.45
                        else 0.0
                    )
                    penalty_points = (
                        round(random.uniform(0.5, 4.5), 4)
                        if random.random() < 0.25
                        else 0.0
                    )
                    penalty_percent = (
                        float(random.choice([5, 10, 15, 20]))
                        if random.random() < 0.30
                        else 0.0
                    )
                    warnings_units = random.choice([0, 0, 1, 2, 3, 4, 5])

                    await cursor.execute(
                        """
                        UPDATE assistants
                        SET manual_points_adjustment = %s,
                            penalty_points = %s,
                            penalty_percent = %s,
                            warnings_units = %s
                        WHERE pr_id = %s
                        """,
                        (
                            manual_adjustment,
                            penalty_points,
                            penalty_percent,
                            warnings_units,
                            pr_id,
                        ),
                    )
                    assistant_adjustments[pr_id] = {
                        "manual_points_adjustment": manual_adjustment,
                        "penalty_points": penalty_points,
                        "penalty_percent": penalty_percent,
                        "warnings_units": warnings_units,
                    }
                    if penalty_points > 0 or penalty_percent > 0 or warnings_units > 0:
                        seeded_sanctions += 1

                await conn.commit()
                print(f"   ✅ Синхронизированы auto/manual баллы")
                print(f"   ✅ Санкции/выговоры выставлены для {seeded_sanctions} ассистентов\n")

                # ── Step 7: Admin logs (compact universal schema) ───────────
                print("📝  Создание логов администрирования...")
                log_count = 0
                now = datetime.now(timezone.utc)
                ip_pool = ["192.168.1.10", "10.0.0.5", "172.16.0.100", None]
                admin_pool = [
                    {
                        "name": user["nickname"],
                        "role": user["role"],
                        "actor_id": user["discord_id"],
                    }
                    for user in ADMIN_USERS
                ]

                log_entries: list[dict[str, Any]] = []

                # user.create
                for admin in ADMIN_USERS:
                    ts = now - timedelta(
                        days=random.randint(28, 30), hours=random.randint(0, 12)
                    )
                    ip = random.choice(ip_pool)
                    log_entries.append(
                        {
                            "actor_name": admin["nickname"],
                            "actor_role": admin["role"],
                            "action": "user.create",
                            "target_type": "user",
                            "target_id": str(admin["discord_id"]),
                            "created_at": ts,
                            "details": make_log_details(
                                f"Создан пользователь {admin['username']}",
                                payload={
                                    "username": admin["username"],
                                    "nickname": admin["nickname"],
                                    "discord_id": admin["discord_id"],
                                    "role": admin["role"],
                                },
                                meta={"actor_id": admin["discord_id"], "ip": ip},
                            ),
                        }
                    )

                # streamer.add
                for streamer in streamer_rows:
                    actor = random.choice(admin_pool)
                    ip = random.choice(ip_pool)
                    ts = now - timedelta(
                        days=random.randint(20, 28), hours=random.randint(0, 23)
                    )
                    log_entries.append(
                        {
                            "actor_name": actor["name"],
                            "actor_role": actor["role"],
                            "action": "streamer.add",
                            "target_type": "streamer",
                            "target_id": str(streamer["id"]),
                            "created_at": ts,
                            "details": make_log_details(
                                f"Добавлен стример {streamer['name']}",
                                payload={
                                    "streamer_name": streamer["name"],
                                    "priority": streamer["priority"],
                                },
                                meta={"actor_id": actor["actor_id"], "ip": ip},
                            ),
                        }
                    )

                # streamer.update + event.create + event.update
                for streamer in random.sample(streamer_rows, min(6, len(streamer_rows))):
                    actor = random.choice(admin_pool)
                    ip = random.choice(ip_pool)
                    old_priority = streamer["priority"]
                    new_priority = random.choice([p for p in [0, 1, 2, 3] if p != old_priority])
                    ts = now - timedelta(
                        days=random.randint(8, 18), hours=random.randint(0, 23)
                    )
                    log_entries.append(
                        {
                            "actor_name": actor["name"],
                            "actor_role": actor["role"],
                            "action": "streamer.update",
                            "target_type": "streamer",
                            "target_id": str(streamer["id"]),
                            "created_at": ts,
                            "details": make_log_details(
                                f"Изменен приоритет стримера {streamer['name']}",
                                changes={
                                    "before": {"priority": old_priority},
                                    "after": {"priority": new_priority},
                                    "delta": {"priority": new_priority - old_priority},
                                    "source": "manual_update",
                                },
                                meta={"actor_id": actor["actor_id"], "ip": ip},
                            ),
                        }
                    )

                for event in event_rows:
                    actor = random.choice(admin_pool)
                    ip = random.choice(ip_pool)
                    ts_create = now - timedelta(
                        days=random.randint(5, 15), hours=random.randint(0, 12)
                    )
                    log_entries.append(
                        {
                            "actor_name": actor["name"],
                            "actor_role": actor["role"],
                            "action": "event.create",
                            "target_type": "event",
                            "target_id": str(event["id"]),
                            "created_at": ts_create,
                            "details": make_log_details(
                                f"Создано событие {event['name']}",
                                payload={"name": event["name"]},
                                meta={"actor_id": actor["actor_id"], "ip": ip},
                            ),
                        }
                    )

                    ts_update = ts_create + timedelta(days=random.randint(1, 3))
                    new_priority = random.randint(0, 3)
                    new_slots = random.randint(1, 7)
                    log_entries.append(
                        {
                            "actor_name": actor["name"],
                            "actor_role": actor["role"],
                            "action": "event.update",
                            "target_type": "event",
                            "target_id": str(event["id"]),
                            "created_at": ts_update,
                            "details": make_log_details(
                                f"Обновлено событие {event['name']}",
                                changes={
                                    "before": {
                                        "priority": random.randint(0, 3),
                                        "pr_slots": random.randint(1, 5),
                                    },
                                    "after": {"priority": new_priority, "pr_slots": new_slots},
                                    "delta": {"priority": new_priority, "pr_slots": new_slots},
                                    "source": "event_edit",
                                },
                                meta={"actor_id": actor["actor_id"], "ip": ip},
                            ),
                        }
                    )

                # assistant logs for time/points/sanctions
                for pr in PR_ASSISTANTS:
                    pr_id = pr["discord_id"]
                    adjustments = assistant_adjustments.get(pr_id, {})
                    actor = random.choice(admin_pool)
                    ip = random.choice(ip_pool)
                    ts = now - timedelta(
                        days=random.randint(1, 10), hours=random.randint(0, 23)
                    )
                    delta_minutes = random.randint(30, 180)
                    action = random.choice(
                        ["assistant.spec_time.add", "assistant.spec_time.subtract"]
                    )
                    signed_delta = delta_minutes if action.endswith(".add") else -delta_minutes
                    log_entries.append(
                        {
                            "actor_name": actor["name"],
                            "actor_role": actor["role"],
                            "action": action,
                            "target_type": "assistant",
                            "target_id": str(pr_id),
                            "created_at": ts,
                            "details": make_log_details(
                                f"{'Добавлено' if signed_delta > 0 else 'Убрано'} время спека для {pr['nickname']}",
                                changes={
                                    "delta": {"duration_minutes": signed_delta},
                                    "source": "session_edit",
                                },
                                meta={"actor_id": actor["actor_id"], "ip": ip},
                            ),
                        }
                    )

                    manual_adj = float(adjustments.get("manual_points_adjustment", 0.0))
                    if manual_adj != 0.0:
                        ts_points = ts + timedelta(hours=1)
                        log_entries.append(
                            {
                                "actor_name": actor["name"],
                                "actor_role": actor["role"],
                                "action": "assistant.spec_points.adjust.permanent",
                                "target_type": "assistant",
                                "target_id": str(pr_id),
                                "created_at": ts_points,
                                "details": make_log_details(
                                    f"Ручная корректировка баллов {pr['nickname']}",
                                    changes={
                                        "delta": {"manual_points_adjustment": manual_adj},
                                        "reason": random.choice(
                                            [
                                                "manual_correction",
                                                "retroactive_fix",
                                                "quality_bonus",
                                            ]
                                        ),
                                        "source": "manual_adjust",
                                    },
                                    meta={"actor_id": actor["actor_id"], "ip": ip},
                                ),
                            }
                        )

                # Additional operational actions for new action taxonomy
                for action in [
                    "system.maintenance.enable",
                    "system.maintenance.disable",
                    "rbac.matrix.update",
                    "event.request.approve",
                ]:
                    actor = random.choice(admin_pool)
                    ip = random.choice(ip_pool)
                    ts = now - timedelta(days=random.randint(0, 7), hours=random.randint(0, 23))
                    if action.startswith("system."):
                        target_type = "system"
                        target_id = "global"
                    elif action.startswith("rbac."):
                        target_type = "rbac"
                        target_id = "global"
                    else:
                        target_type = "event"
                        target_id = str(random.choice(event_rows)["id"]) if event_rows else "global"
                    log_entries.append(
                        {
                            "actor_name": actor["name"],
                            "actor_role": actor["role"],
                            "action": action,
                            "target_type": target_type,
                            "target_id": target_id,
                            "created_at": ts,
                            "details": make_log_details(
                                f"Операция {action}",
                                payload={"action": action},
                                meta={"actor_id": actor["actor_id"], "ip": ip},
                            ),
                        }
                    )

                # Sort and insert
                log_entries.sort(key=lambda item: item["created_at"])
                for entry in log_entries:
                    await cursor.execute(
                        """
                        INSERT INTO admin_logs
                            (actor_name, actor_role, action, target_type, target_id, details, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            entry["actor_name"],
                            entry["actor_role"],
                            entry["action"],
                            entry["target_type"],
                            entry["target_id"],
                            json.dumps(entry["details"], ensure_ascii=False, default=str),
                            entry["created_at"].strftime("%Y-%m-%d %H:%M:%S"),
                        ),
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
