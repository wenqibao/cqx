"""HTTP 输入输出结构（与 docs/api_contract.yaml 保持一致）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class PatientCreate(BaseModel):
    id: str | None = None
    name: str = Field(min_length=1)
    age: int | None = Field(default=None, ge=0, le=120)
    sex: str | None = None
    diabetes_type: str = "T2DM"
    duration_years: float | None = Field(default=None, ge=0, le=100)
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

    @field_validator("recorded_at")
    @classmethod
    def _check_recorded_at(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return value
        try:
            parse = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"recorded_at 不是合法时间: {value}") from exc
        if parse.tzinfo is None:
            raise ValueError("recorded_at 必须带时区")
        return value

    @model_validator(mode="after")
    def _check_payload(self) -> "RecordCreate":
        if self.kind == "bp":
            systolic = self.payload.get("systolic")
            diastolic = self.payload.get("diastolic")
            try:
                systolic = float(systolic)
                diastolic = float(diastolic)
            except (TypeError, ValueError) as exc:
                raise ValueError("bp 需要数值型 systolic/diastolic") from exc
            if not 40 <= systolic <= 300 or not 20 <= diastolic <= 200:
                raise ValueError("血压超出合理范围（收缩压 40-300，舒张压 20-200）")
        return self


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

    @model_validator(mode="after")
    def _require_answer(self) -> "AnswerRequest":
        meaningful = (self.answer_text or "").strip() or (self.option or "").strip()
        has_value = self.answer_value not in (None, "", [], {})
        if not meaningful and not has_value:
            raise ValueError("答复不能为空：answer_text / option / answer_value 至少一个非空")
        return self


class TaskCompleteRequest(BaseModel):
    changed_by: str = "patient"
    note: str | None = None
    run_agent: bool = True


class TaskRescheduleRequest(BaseModel):
    due_at: str
    reason: str = "患者申请调整时间"
    changed_by: str = "patient"

    @field_validator("due_at")
    @classmethod
    def _check_due_at(cls, value: str) -> str:
        try:
            parse = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"due_at 不是合法时间: {value}") from exc
        if parse.tzinfo is None:
            raise ValueError("due_at 必须带时区")
        return value


class PreferenceCreate(BaseModel):
    kind: str
    value: str
    source: str = "patient_confirmed"

    @model_validator(mode="after")
    def _check_preference(self) -> "PreferenceCreate":
        self.value = (self.value or "").strip()
        if not self.value:
            raise ValueError("偏好值不能为空")
        if self.kind == "preferred_time_window":
            allowed = {"morning", "evening", "noon"}
            if self.value not in allowed and not __import__("re").fullmatch(r"([01]\d|2[0-3]):[0-5]\d", self.value):
                raise ValueError("preferred_time_window 只接受 morning/evening/noon 或 HH:MM")
        return self


class ReviewResolveRequest(BaseModel):
    decision: str
    note: str = ""

    @field_validator("decision")
    @classmethod
    def _require_decision(cls, value: str) -> str:
        text = (value or "").strip()
        if not text:
            raise ValueError("人工结论不能为空")
        return text


class TickRequest(BaseModel):
    advance_seconds: int | None = None
    limit: int = 50


class ClockRequest(BaseModel):
    advance_seconds: int = 0
    reset: bool = False
