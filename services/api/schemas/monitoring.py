"""
Monitoring/Dashboard schemas for API requests and responses.
"""

from pydantic import BaseModel, Field


class MonitoringRefreshRequest(BaseModel):
    force: bool = Field(default=False, description="Force refresh even if recent")


class DashboardStatusResponse(BaseModel):
    total_streamers: int
    online_streamers: int
    gta_streamers: int
    active_specs: int
    total_assistants: int
    system_status: str = "healthy"
