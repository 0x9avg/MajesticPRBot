"""
Monitoring/Dashboard schemas for API requests and responses.
"""

from pydantic import BaseModel, Field


class MonitoringRefreshResponse(BaseModel):
    force: bool = Field(default=False, description="Force refresh even if recent")



