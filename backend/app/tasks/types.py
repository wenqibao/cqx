"""任务类型规范化（REAL-A01）：模型只应产生受约束的规范类型。

- 规范类型来自 config/task_rules.yaml 的模板；
- 常见旧别名归一到规范类型，读取旧数据时兼容；
- 未知类型拒绝，并返回候选值供模型修正。
"""
from __future__ import annotations

from typing import Any

from backend.app.config import task_rules

# 兼容旧数据/模型自由生成过的别名
TASK_TYPE_ALIASES: dict[str, str] = {
    "glucose_record_check": "record_glucose",
    "record_glucose_check": "record_glucose",
    "check_glucose": "record_glucose",
    "glucose_record": "record_glucose",
    "record_reminder": "record_glucose",
    "reminder_record": "record_glucose",
    "medication_check": "confirm_medication",
    "confirm_medication_task": "confirm_medication",
    "medication_verification": "confirm_medication",
    "activity_record": "record_activity",
    "record_steps": "record_activity",
    "steps_record": "record_activity",
    "weight_record": "record_weight",
    "followup_review": "review_followup",
    "review": "review_followup",
}


def canonical_task_types() -> list[str]:
    templates = task_rules().get("templates", {}) or {}
    types: set[str] = set()
    for items in templates.values():
        for item in items or []:
            task_type = str(item.get("task_type") or "").strip()
            if task_type:
                types.add(task_type)
    # 人工复核/记录类兜底类型，避免模板未覆盖时缺失
    types.update({"record_bp", "record_symptom", "review_followup"})
    return sorted(types)


def normalize_task_type(raw: Any) -> str | None:
    """返回规范类型；无法识别时返回 None。"""
    if not isinstance(raw if raw is not None else "", (str, int)):
        return None
    value = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not value:
        return None
    if value in TASK_TYPE_ALIASES:
        return TASK_TYPE_ALIASES[value]
    canonical = canonical_task_types()
    return value if value in canonical else None


def task_type_candidates() -> str:
    return "、".join(canonical_task_types())
