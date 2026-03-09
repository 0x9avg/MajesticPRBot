from __future__ import annotations

from pathlib import Path

from versioning import APP_VERSION, read_project_version


EXPECTED_VERSION = Path(__file__).resolve().parents[3].joinpath("VERSION").read_text(
    encoding="utf-8"
).strip()


def test_read_project_version_matches_root_version_file() -> None:
    assert read_project_version() == EXPECTED_VERSION


def test_app_version_constant_is_loaded_from_root_version_file() -> None:
    assert APP_VERSION == EXPECTED_VERSION
