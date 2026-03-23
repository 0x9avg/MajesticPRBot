"""Schemas for developer-facing site settings management."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class RbacSnapshot(BaseModel):
    roles: list[str]
    permissions: list[str]
    matrix: dict[str, dict[str, bool]]
    permission_implications: dict[str, list[str]]

    model_config = ConfigDict(extra="forbid")


class SiteMaintenanceUpdateRequest(BaseModel):
    enabled: bool

    model_config = ConfigDict(extra="forbid")


class SiteMaintenanceSnapshot(BaseModel):
    enabled: bool

    model_config = ConfigDict(extra="forbid")


class SiteRolePermissionsUpdateRequest(BaseModel):
    matrix: dict[str, dict[str, bool]]

    model_config = ConfigDict(extra="forbid")
