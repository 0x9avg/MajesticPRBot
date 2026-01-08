from typing import List, Dict
import math
import datetime
import discord


def _unix(dt: datetime.datetime | None) -> str:
    if not dt:
        return "—"
    return f"<t:{int(dt.replace(tzinfo=datetime.timezone.utc).timestamp())}:R>"


def generate_streamer_embeds(
    streamers: List[Dict],
    chunk_size: int = 5,
) -> List[discord.Embed]:

    # сортировка: приоритет → онлайн → время старта
    streamers = sorted(
        streamers,
        key=lambda s: (
            -s.get("Priority", 0),
            -s.get("isOnline", 0),
            s.get("startedAt") or datetime.datetime.max,
        ),
    )

    embeds: List[discord.Embed] = []
    total = len(streamers)
    now = datetime.datetime.now(datetime.timezone.utc)

    for page_index in range(0, total, chunk_size):
        chunk = streamers[page_index : page_index + chunk_size]

        embed = discord.Embed(
            title="Кто онлайн сейчас",
            description="🟢 — в GTA · 🟠 — не в GTA",
            color=9520895,
            timestamp=now,
        )

        for i, s in enumerate(chunk, start=page_index + 1):
            name = s["StreamerName"]
            stream_url = f"https://twitch.tv/{name}"

            is_online = bool(s.get("isOnline"))
            is_gta = s.get("gameID") == 32982
            status = "🟢" if is_gta else "🟠"

            started = _unix(s.get("startedAt")) if is_online else "Оффлайн"

            paid = "💎 " if s.get("isPaid") else ""
            priority = s.get("Priority", 0)

            field_name = f"{i}. {status} {paid}{name}"

            field_value = (
                f"[Открыть стрим]({stream_url})\n"
                f"{status} **{'В GTA' if is_gta else 'Не в GTA'}** · 🏷 Приоритет: **{priority}**\n"
                f"🕒 Старт: {started}"
            )

            embed.add_field(name=field_name, value=field_value, inline=False)

        embed.set_footer(
            text=f"Показаны {page_index + 1}–{page_index + len(chunk)} из {total}"
        )

        embeds.append(embed)

    return embeds
