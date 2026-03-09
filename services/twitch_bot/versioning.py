from __future__ import annotations

from pathlib import Path

DEFAULT_APP_VERSION = "0.0.0-dev"


def read_project_version() -> str:
    version_file = Path(__file__).resolve().parents[2] / "VERSION"

    try:
        version = version_file.read_text(encoding="utf-8").strip()
    except OSError:
        return DEFAULT_APP_VERSION

    return version or DEFAULT_APP_VERSION


APP_VERSION = read_project_version()
