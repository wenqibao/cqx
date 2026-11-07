"""C05 否定免责声明 + C06 可修正拒绝口径。"""
from __future__ import annotations

from datetime import timedelta

import pytest

from backend.app.agent import orchestrator
from backend.app.agent.llm import LLMResponse, ToolCall
from backend.app.db.connection import iso, now
from backend.app.safety.gate import check_text
from backend.app.services import patients
from backend.app.tasks import service as tasks


class _ScriptedLLM:
    mode = "real"
    model_name = "scripted-c05c06"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def plan_actions(self, **kwargs):
        index = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return self.responses[index]


def _patient(conn, pid="C56"):
    patients.create_patient(conn, {"id": pid, "name": "组合", "age": 60, "duration_years": 5, "goals": ["稳定"]})


@pytest.mark.parametrize("text", [
    "本系统未提供用药调整建议。",
    "未提供任何用药调整建议，请咨询医生。",
    "本回复不提供用药调整建议。",
    "未给出用药调整方案。",
])
def test_c05_negated_disclaimer_allowed(text):
    assert check_text(text, generated=True)["allowed"] is True
    assert check_text(text)["allowed"] is True


def test_c05_run_with_disclaimer_completes(conn):
    _patient(conn)
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[
            ToolCall("create_notification", {"patient_id": "C56", "title": "复核已创建", "body": "请等待医生"},
                     "c1"),
            ToolCall("respond", {"patient_id": "C56",
                                 "text": "已提交人工复核。本系统未提供用药调整建议，请遵医嘱。"}, "c2"),
        ], raw={}),
    ])
    result = orchestrator.run_agent(conn, "C56", trigger_type="user_request", message="提交复核", llm=llm)
    assert result["status"] == "completed", result
    assert not [r for r in result["rejections"] if r["code"] == "FORBIDDEN_ACTION"]


def test_c06_correctable_rejection_resolved_by_retry(conn):
    _patient(conn)
    due = iso(now(conn) + timedelta(days=1))
    # 两条待办 → 无 task_id 的复评无法唯一关联，第一次被拒
    task_a, _ = tasks.create_task(conn, "C56", task_type="record_glucose", title="A", due_at=due, schedule_review=False)
    tasks.create_task(conn, "C56", task_type="record_activity", title="B", due_at=due, schedule_review=False)

    class TwoRound:
        mode = "real"
        model_name = "two-round"

        def __init__(self, task_id):
            self.calls = 0
            self.task_id = task_id

        def plan_actions(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(content="", tool_calls=[ToolCall(
                    "schedule_review", {"patient_id": "C56", "delay_hours": 24}, "c1")], raw={})
            if self.calls == 2:
                return LLMResponse(content="", tool_calls=[ToolCall(
                    "schedule_review", {"patient_id": "C56", "delay_hours": 24, "task_id": self.task_id}, "c2")], raw={})
            return LLMResponse(content="已安排复评。", tool_calls=[], raw={})

    result = orchestrator.run_agent(conn, "C56", trigger_type="user_request", message="安排复评",
                                    llm=TwoRound(task_a["id"]))
    assert result["status"] == "completed", result
    assert result.get("warnings"), "被纠正的拒绝应保留为 warnings"
    assert conn.execute("SELECT COUNT(*) c FROM reviews WHERE patient_id='C56'").fetchone()["c"] == 1


def test_c06_safety_rejection_is_not_masked(conn):
    _patient(conn)
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[ToolCall("create_task", {
            "patient_id": "C56", "task_type": "record_glucose", "title": "记录",
            "description": "建议把降糖药停掉",
            "due_at": (now(conn) + timedelta(days=1)).isoformat()}, "c1")], raw={}),
        LLMResponse(content="好的。", tool_calls=[], raw={}),
    ])
    result = orchestrator.run_agent(conn, "C56", trigger_type="user_request", message="帮我建个任务", llm=llm)
    assert result["status"] == "failed"
    assert any(r["code"] == "FORBIDDEN_ACTION" for r in result["rejections"])
