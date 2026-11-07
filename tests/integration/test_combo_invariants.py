"""组合级不变量：复评单一责任/作用域、完成副作用一致、通知幂等。"""
from __future__ import annotations

from datetime import timedelta

import pytest

from backend.app.agent import orchestrator
from backend.app.agent.llm import LLMResponse, ToolCall
from backend.app.db.connection import iso, now
from backend.app.services import notifications, patients
from backend.app.reviews import service as reviews
from backend.app.tasks import service as tasks


class _ScriptedLLM:
    mode = "real"
    model_name = "scripted-combo"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def plan_actions(self, **kwargs):
        index = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return self.responses[index]


def _patient(conn, pid="CB1"):
    patients.create_patient(conn, {"id": pid, "name": "组合", "age": 60, "duration_years": 5, "goals": ["稳定"]})


def test_auto_and_explicit_review_merge_into_one(conn):
    _patient(conn)
    task, _ = tasks.create_task(conn, "CB1", task_type="record_glucose", title="记录",
                                due_at=iso(now(conn) + timedelta(days=1)))  # 自动 48h 复评
    before = conn.execute("SELECT COUNT(*) c FROM reviews WHERE task_id=?", (task["id"],)).fetchone()["c"]
    assert before == 1
    explicit = reviews.schedule_review(conn, "CB1", task_id=task["id"], delay_hours=24)
    assert explicit.get("updated") is True
    rows = conn.execute("SELECT id, scheduled_for FROM reviews WHERE task_id=?", (task["id"],)).fetchall()
    assert len(rows) == 1
    due = rows[0]["scheduled_for"]
    assert due == explicit["scheduled_for"]


def test_review_without_scope_is_rejected_when_ambiguous(conn):
    _patient(conn)
    for i in range(2):
        tasks.create_task(conn, "CB1", task_type=f"record_{i}", title=f"任务{i}",
                          due_at=iso(now(conn) + timedelta(days=1 + i)), schedule_review=False)
    with pytest.raises(reviews.ReviewError):
        reviews.schedule_review(conn, "CB1", delay_hours=24)


def test_review_attaches_unique_pending_task(conn):
    _patient(conn)
    task, _ = tasks.create_task(conn, "CB1", task_type="record_glucose", title="记录",
                                due_at=iso(now(conn) + timedelta(days=1)), schedule_review=False)
    review = reviews.schedule_review(conn, "CB1", delay_hours=24)
    assert review["task_id"] == task["id"]


def test_agent_complete_runs_same_side_effects(conn):
    _patient(conn, "CB2")
    task, _ = tasks.create_task(conn, "CB2", task_type="record_glucose", title="记录",
                                due_at=iso(now(conn) + timedelta(days=1)))  # 自动复评
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[ToolCall("complete_task", {"task_id": task["id"]}, "c1")], raw={}),
        LLMResponse(content="已完成任务。", tool_calls=[], raw={}),
    ])
    result = orchestrator.run_agent(conn, "CB2", trigger_type="user_request", message="帮我完成任务", llm=llm)
    assert result["status"] == "completed", result
    status = conn.execute("SELECT status FROM reviews WHERE task_id=?", (task["id"],)).fetchone()["status"]
    assert status != "scheduled", "Agent 完成任务必须触发复评评估，而不是只改状态"
    outbox_done = conn.execute("SELECT COUNT(*) c FROM automation_outbox WHERE status='done'").fetchone()["c"]
    assert outbox_done >= 1


def test_notification_is_idempotent_for_same_reference(conn):
    _patient(conn, "CB3")
    first = notifications.create_notification(conn, "CB3", kind="review_created", title="复核已创建",
                                              body="请等待医生", ref_type="review", ref_id="REV-1")
    second = notifications.create_notification(conn, "CB3", kind="review_created", title="复核已创建",
                                               body="请等待医生", ref_type="review", ref_id="REV-1")
    assert second["id"] == first["id"]
    assert second.get("duplicate") is True
    count = conn.execute("SELECT COUNT(*) c FROM notifications WHERE patient_id='CB3'").fetchone()["c"]
    assert count == 1


def test_notification_same_text_without_ref_is_deduped(conn):
    _patient(conn, "CB4")
    first = notifications.create_notification(conn, "CB4", kind="info", title="提醒", body="记录血糖")
    second = notifications.create_notification(conn, "CB4", kind="info", title="提醒", body="记录血糖")
    assert second["id"] == first["id"]
