"""Schemas for sanction operations, manual sanctions, workoff items and monthly settings."""

from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from schemas.common import Snowflake


SanctionKind = Literal["check", "point", "percent", "oral", "strict"]
ManualReliefType = Literal["manual", "custom_workoff"]
OperationRecipientMode = Literal[
    "all_active",
    "live_without_active_session",
    "selected_only",
]
WorkoffMetric = Literal["spec", "complaints", "mchat"]


class WorkoffItemInput(BaseModel):
    metric: WorkoffMetric
    multiplier: float = Field(..., gt=0)
    period_start: date
    period_end: date

    @model_validator(mode="after")
    def validate_period(self):
        if self.period_end < self.period_start:
            raise ValueError("period_end must be greater than or equal to period_start")
        return self


class WorkoffPreviewRequest(BaseModel):
    assistant_ids: list[Snowflake] = Field(default_factory=list)
    workoff_items: list[WorkoffItemInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_preview_request(self):
        if not self.assistant_ids:
            raise ValueError("Нужно указать хотя бы одного ассистента")
        if len(self.assistant_ids) != len(set(self.assistant_ids)):
            raise ValueError("Нельзя добавить одного ассистента в предпросмотр несколько раз")
        metrics = [item.metric for item in self.workoff_items]
        if len(metrics) != len(set(metrics)):
            raise ValueError("Каждый тип отработки можно выбрать только один раз")
        return self


class AssistantDayPointAdjustmentUpsertRequest(BaseModel):
    assistant_id: Snowflake
    work_date: date
    delta_points: float


class AssistantDayMchatUpsertRequest(BaseModel):
    assistant_id: Snowflake
    work_date: date
    mchat_count: int = Field(..., ge=0)


class ManualSanctionCreateRequest(BaseModel):
    assistant_id: Snowflake
    kind: SanctionKind
    amount: Optional[float] = Field(None, gt=0)
    auto_relief_date: Optional[date] = None
    workoff_items: list[WorkoffItemInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_manual_sanction(self):
        metrics = [item.metric for item in self.workoff_items]
        if len(metrics) != len(set(metrics)):
            raise ValueError("Каждый тип отработки можно выбрать только один раз")
        if self.kind in {"oral", "strict"} and self.auto_relief_date is None:
            raise ValueError("Для устного и строгого требуется дата автоматического снятия")
        return self


class SanctionReliefCreateRequest(BaseModel):
    amount: float = Field(..., gt=0)
    relief_type: ManualReliefType = "manual"
    basis_date: Optional[date] = None


class SanctionReplaceRequest(BaseModel):
    new_kind: SanctionKind
    new_amount: float = Field(..., gt=0)
    new_auto_relief_date: Optional[date] = None
    basis_date: Optional[date] = None
    reason: Optional[str] = None
    workoff_items: list[WorkoffItemInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_replace_request(self):
        metrics = [item.metric for item in self.workoff_items]
        if len(metrics) != len(set(metrics)):
            raise ValueError("Каждый тип отработки можно выбрать только один раз")
        if self.new_kind in {"oral", "strict"} and self.new_auto_relief_date is None:
            raise ValueError("Для устного и строгого требуется дата автоматического снятия")
        return self


class SanctionOperationCreateRequest(BaseModel):
    penalty_kind: SanctionKind
    penalty_amount: Optional[float] = Field(None, gt=0)
    auto_relief_date: Optional[date] = None
    recipient_mode: OperationRecipientMode
    assistant_ids: list[Snowflake] = Field(default_factory=list)
    workoff_items: list[WorkoffItemInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_operation(self):
        metrics = [item.metric for item in self.workoff_items]
        if len(metrics) != len(set(metrics)):
            raise ValueError("Каждый тип отработки можно выбрать только один раз")
        if len(self.assistant_ids) != len(set(self.assistant_ids)):
            raise ValueError("Нельзя добавить одного ассистента в выдачу несколько раз")
        if self.penalty_kind in {"oral", "strict"} and self.auto_relief_date is None:
            raise ValueError("Для устного и строгого требуется дата автоматического снятия")
        return self


class SanctionOperationUpdateRequest(BaseModel):
    penalty_kind: Optional[SanctionKind] = None
    penalty_amount: Optional[float] = Field(None, gt=0)
    auto_relief_date: Optional[date] = None
    recipient_mode: Optional[OperationRecipientMode] = None
    assistant_ids: Optional[list[Snowflake]] = None
    workoff_items: Optional[list[WorkoffItemInput]] = None

    @model_validator(mode="after")
    def validate_unique_workoff_metrics(self):
        if self.workoff_items is None:
            if self.assistant_ids is not None and len(self.assistant_ids) != len(set(self.assistant_ids)):
                raise ValueError("Нельзя добавить одного ассистента в выдачу несколько раз")
            return self
        metrics = [item.metric for item in self.workoff_items]
        if len(metrics) != len(set(metrics)):
            raise ValueError("Каждый тип отработки можно выбрать только один раз")
        if self.assistant_ids is not None and len(self.assistant_ids) != len(set(self.assistant_ids)):
            raise ValueError("Нельзя добавить одного ассистента в выдачу несколько раз")
        return self


class SanctionOperationMemberAddRequest(BaseModel):
    assistant_id: Snowflake


class MonthlySanctionSettingsUpdateRequest(BaseModel):
    check_cycle_size: Optional[int] = Field(None, ge=1)
    check_immunity_hours_per_day: Optional[float] = Field(None, ge=0)
    point_immunity_hours_per_day: Optional[float] = Field(None, ge=0)
    percent_immunity_hours_per_day: Optional[float] = Field(None, ge=0)
    check_relief_hours_per_day: Optional[float] = Field(None, ge=0)
    point_relief_hours_per_day: Optional[float] = Field(None, ge=0)
    percent_relief_hours_per_day: Optional[float] = Field(None, ge=0)
    check_relief_min_streak_days: Optional[int] = Field(None, ge=1)
    point_relief_min_streak_days: Optional[int] = Field(None, ge=1)
    percent_relief_min_streak_days: Optional[int] = Field(None, ge=1)
    percent_relief_step_amount: Optional[float] = Field(None, ge=0)
    daily_norm_spec: Optional[float] = Field(None, ge=0)
    daily_norm_complaints: Optional[int] = Field(None, ge=0)
    daily_norm_mchat: Optional[int] = Field(None, ge=0)


class MonthlyCheckRuleItem(BaseModel):
    range_start: int = Field(..., ge=1)
    range_end: int | None = Field(None, ge=1)
    penalty_kind: Literal["point", "percent", "oral", "strict"]
    penalty_amount: float = Field(..., gt=0)

    @model_validator(mode="after")
    def validate_range(self):
        if self.range_end is not None and self.range_end < self.range_start:
            raise ValueError("range_end must be greater than or equal to range_start")
        return self


class MonthlyCheckRulesReplaceRequest(BaseModel):
    rules: list[MonthlyCheckRuleItem]

    @model_validator(mode="after")
    def validate_non_empty_rules(self):
        if not self.rules:
            raise ValueError("Нужно задать хотя бы одно правило галок")
        return self
