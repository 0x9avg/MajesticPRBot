"""
Monitoring/Dashboard schemas for API requests and responses.
"""

from pydantic import BaseModel, Field


class MonitoringRefreshRequest(BaseModel):
    force: bool = Field(default=False, description="Force refresh even if recent")



