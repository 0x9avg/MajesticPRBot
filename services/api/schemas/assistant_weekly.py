"""Schemas for weekly assistant statistics review module."""

from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


WeeklyDayStatus = Literal["P", "U", "O"]
WeeklySuggestedResult = Literal["Ультра-Актив", "Актив", "Инактив/Актив", "Инактив"]
WeeklySelectedResult = Literal[
    "Ультра-Актив",
    "Актив",
    "Актив/Отпуск",
    "Инактив",
    "Инактив/Отпуск",
    "Отпуск",
    "Инактив/Актив",
]
WeeklyPayoutType = Literal["EXP", "Premium", "MC", "MONEY"]
WeeklyPayoutIssueStatus = Literal["pending", "issued"]


class AssistantWeeklyDayOverrideInput(BaseModel):
    work_date: date
    manual_status: Optional[WeeklyDayStatus] = None
    is_manual_override: bool = False


class AssistantWeeklyAdminSaveRequest(BaseModel):
    day_overrides: list[AssistantWeeklyDayOverrideInput] = Field(default_factory=list)
    selected_result: Optional[WeeklySelectedResult] = None
    payout_type: Optional[WeeklyPayoutType] = None
    payout_server: Optional[str] = None
    payout_static: Optional[str] = None

    @model_validator(mode="after")
    def validate_unique_days(self):
        dates = [item.work_date for item in self.day_overrides]
        if len(dates) != len(set(dates)):
            raise ValueError("day_overrides contains duplicate work_date values")
        return self


class AssistantWeeklyPayoutIssueRequest(BaseModel):
    status: WeeklyPayoutIssueStatus
