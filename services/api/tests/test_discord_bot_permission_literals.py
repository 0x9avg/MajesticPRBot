from __future__ import annotations

import ast
from pathlib import Path


LEGACY_PERMISSION_LITERALS = {
    "streamers.view",
    "streamers.create",
    "streamers.update",
    "streamers.delete",
    "streamers.status.update",
    "guild.view",
    "guild.settings.view",
    "guild.settings.update",
    "guild.templates.view",
    "guild.templates.update",
    "guild.rates.view",
    "guild.rates.update",
    "events.manage",
    "events.join.self",
    "events.leave.self",
    "spec.view_claimable",
    "spec.view_self_sessions",
}


def test_discord_bot_cogs_do_not_use_legacy_permission_literals() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    cogs_root = repo_root / "services" / "discord_bot" / "cogs"
    offenders: dict[str, list[str]] = {}

    for path in sorted(cogs_root.rglob("*.py")):
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        literals = sorted(
            {
                node.value
                for node in ast.walk(module)
                if isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value in LEGACY_PERMISSION_LITERALS
            }
        )
        if literals:
            offenders[str(path.relative_to(repo_root))] = literals

    assert offenders == {}
