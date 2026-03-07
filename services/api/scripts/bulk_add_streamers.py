"""
Скрипт для массового добавления стримеров через API.

Запуск: python services/api/scripts/bulk_add_streamers.py streamers.json

Формат файла (JSON):
[
  {"url": "twitch.tv/user1", "priority": 1},
  {"url": "https://twitch.tv/user2", "priority": 2}
]
"""

import asyncio
import json
import os
import sys
from typing import List, TypedDict

import aiohttp

# Добавляем родительскую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config


def _get_service_token() -> str:
    """Extract a service token from Config.service_token_map."""
    token_map = Config.service_token_map
    # Prefer discord_service token; fall back to any available token
    for name in ("discord_service", "twitch_service"):
        if name in token_map:
            return token_map[name]
    if token_map:
        return next(iter(token_map.values()))
    raise RuntimeError(
        "SERVICE_TOKENS is not configured. "
        "Set SERVICE_TOKENS in the API .env file."
    )


class StreamerEntry(TypedDict):
    url: str
    priority: int


async def add_streamer(
    session: aiohttp.ClientSession,
    base_url: str,
    entry: StreamerEntry,
    index: int,
) -> bool:
    """Add a single streamer via API."""
    payload = {
        "twitch_url": entry["url"],
        "priority": entry.get("priority", 0),
    }

    try:
        async with session.post(f"{base_url}/api/streamers", json=payload) as resp:
            data = await resp.json()

            if resp.status in (201, 202):
                print(f"  ✅ [{index}] {entry['url']} — OK (code: {data.get('code')})")
                return True
            else:
                detail = data.get("detail") or data.get("message") or str(data)
                print(f"  ❌ [{index}] {entry['url']} — FAIL: {detail}")
                return False

    except aiohttp.ClientError as e:
        print(f"  ❌ [{index}] {entry['url']} — Connection error: {e}")
        return False


async def bulk_add(filepath: str) -> None:
    """Read JSON file and add streamers via API."""
    # Load data
    with open(filepath, "r", encoding="utf-8") as f:
        data: List[StreamerEntry] = json.load(f)

    if not isinstance(data, list):
        print("❌ ERROR: JSON file must contain an array of objects.")
        return

    print(f"📂 Loaded {len(data)} entries from {filepath}")

    base_url = f"http://{Config.api_host}:{Config.api_port}"
    token = _get_service_token()
    print(f"🔗 API URL: {base_url}")
    print(f"🔑 Using service token: {token[:6]}...{token[-4:]}")

    success_count = 0
    fail_count = 0

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    async with aiohttp.ClientSession(headers=headers) as session:
        for i, entry in enumerate(data, start=1):
            if "url" not in entry:
                print(f"  ⚠️ [{i}] Skipping entry without 'url': {entry}")
                fail_count += 1
                continue

            result = await add_streamer(session, base_url, entry, i)
            if result:
                success_count += 1
            else:
                fail_count += 1

            # Small delay to avoid overwhelming the API
            await asyncio.sleep(0.1)

    print()
    print(f"📊 Results: {success_count} added, {fail_count} failed")


def main():
    if len(sys.argv) < 2:
        print("Usage: python bulk_add_streamers.py <streamers.json>")
        print()
        print("JSON format:")
        print('  [{"url": "twitch.tv/user", "priority": 1}, ...]')
        sys.exit(1)

    filepath = sys.argv[1]
    if not os.path.exists(filepath):
        print(f"❌ ERROR: File not found: {filepath}")
        sys.exit(1)

    asyncio.run(bulk_add(filepath))


if __name__ == "__main__":
    main()
