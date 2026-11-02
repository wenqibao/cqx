"""HTTP 输入输出结构（与 docs/api_contract.yaml 保持一致）。"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class PatientCreate(BaseModel):
    id: str | None = None
    name: str
    age: int | None = None
    sex: str | None = None
    diabetes_type: str = "T2DM"
    duration_years: float | None = None
    complications: list[str] = Field(default_factory=list)
    goals: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    baseline: dict[str, Any] = Field(default_factory=dict)
    is_synthetic: bool = True


class RecordCreate(BaseModel):
    kind: Literal[
        "fasting_glucose",
        "postprandial_glucose",
        "steps",
        "weight",
        "medication_taken",
        "symptom",
        "meal",
        "bp",
    ]
    value: float | None = None
    unit: str | None = None
    recorded_at: str | None = None
    note: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    trigger_agent: bool = True


class RecordImport(BaseModel):
    csv_text: str | None = None
    json_rows: list[dict[str, Any]] | None = None
    trigger_agent: bool = True


class AgentRunRequest(BaseModel):
    message: str | None = None
    event_ids: list[str] | None = None
    trigger_type: str = "user_request"


class AnswerRequest(BaseModel):
    answer_text: str | None = None
    answer_value: Any = None
    option: str | None = None
    trigger_agent: bool = True


class TaskCompleteRequest(BaseModel):
    changed_by: str = "patient"
    note: str | None = None
    run_agent: bool = True


class TaskRescheduleRequest(BaseModel):
    due_at: str
    reason: str = "患者申请调整时间"
    changed_by: str = "patient"


class PreferenceCreate(BaseModel):
    kind: str
    value: str
    source: str = "patient_confirmed"


class ReviewResolveRequest(BaseModel):
    decision: str
    note: str = ""


class TickRequest(BaseModel):
    advance_seconds: int | None = None
    limit: int = 50


class ClockRequest(BaseModel):
    advance_seconds: int = 0
    reset: bool = False
