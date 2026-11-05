"""A-REAL-01 回归：生成文本里的否定式边界不能被误判为"调整用药"。

真实 R02：模型创建任务时带说明"本任务仅为数据采集，不含用药调整建议"，
被 gate 以 CHANGE_MEDICATION 拒绝，导致任务数为 0、run failed。
修复：把"不含/不包括/无须"纳入免责声明否定词，且否定仍然只作用于当前分句。
"""
from __future__ import annotations

import pytest

from backend.app.agent import llm as llm_module
from backend.app.agent import orchestrator
from backend.app.agent.llm import LLMResponse, ToolCall
from backend.app.db.connection import iso, now
from backend.app.events.detector import detect_events
from backend.app.safety import gate, validators
from backend.app.services import patients, records
from backend.app.tasks import service as tasks
from datetime import timedelta

ALLOWED_NEGATIONS = [
    "本任务仅为数据采集，不含用药调整建议。",
    "不得自行调整用药，如有不适请就医。",
    "不涉及任何药物或胰岛素剂量调整。",
    "本任务只做记录，不包括调药。",
    "本记录不包含任何用药或剂量调整方案。",
]

BLOCKED_REQUESTS = [
    "建议把降糖药停掉。",
    "请把胰岛素加两个单位。",
    "不含诊断，但建议你停药。",            # 免责声明不得掩盖后一分句的指令
    "本系统不提供诊断，但我现在诊断为糖尿病。",
]


@pytest.mark.parametrize("text", ALLOWED_NEGATIONS)
def test_negation_boundary_is_allowed(text):
    assert gate.check_text(text, generated=True)["allowed"] is True, text


@pytest.mark.parametrize("text", BLOCKED_REQUESTS)
def test_real_changes_and_mixed_text_still_blocked(text):
    assert gate.check_text(text, generated=True)["allowed"] is False, text


@pytest.mark.parametrize("text", ALLOWED_NEGATIONS)
def test_patient_input_with_negation_marker_stays_strict(text):
    """患者输入路径不放宽：同一句话里只要出现真正的调整指令仍要拦。"""
    assert gate.check_text("请帮我" + text)["allowed"] in (True, False)  # 不应抛异常
    assert gate.check_text("不含用药调整，但请把药停了")["allowed"] is False


def test_create_task_with_disclaimer_is_allowed(conn):
    patients.create_patient(conn, {"id": "DIS1", "name": "声明", "age": 60, "duration_years": 5, "goals": ["稳定"]})
    plan = {"actions": [{
        "tool": "create_task",
        "args": {
            "patient_id": "DIS1",
            "task_type": "record_glucose",
            "title": "补录空腹血糖",
            "description": "本任务仅为数据采集，不含用药调整建议。",
            "due_at": (now() + timedelta(days=1)).isoformat(),
        },
    }]}
    result = validators.validate_plan(conn, patient_id="DIS1", plan=plan, state={})
    assert result["ok"] is True, result["rejections"]


def test_create_task_with_medication_advice_is_rejected(conn):
    patients.create_patient(conn, {"id": "DIS2", "name": "越权", "age": 60, "duration_years": 5, "goals": ["稳定"]})
    plan = {"actions": [{
        "tool": "create_task",
        "args": {
            "patient_id": "DIS2",
            "task_type": "record_glucose",
            "title": "补录空腹血糖",
            "description": "建议把降糖药停掉，观察一周。",
            "due_at": (now() + timedelta(days=1)).isoformat(),
        },
    }]}
    result = validators.validate_plan(conn, patient_id="DIS2", plan=plan, state={})
    assert result["ok"] is False
    assert any(r["code"] == validators.FORBIDDEN_ACTION for r in result["rejections"])


class _ScriptedLLM:
    mode = "real"
    model_name = "scripted-disclaimer"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def plan_actions(self, **kwargs):
        index = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return self.responses[index]


def test_r02_like_run_completes_with_disclaimer_task(conn):
    """R02 复现：检索 + 人工复核 + 带否定边界的任务 → 不应被拦，run 完成。"""
    patients.create_patient(conn, {"id": "R02X", "name": "复核", "age": 60, "duration_years": 5, "goals": ["稳定"]})
    for i, value in enumerate([7.0, 8.2, 9.6]):
        records.add_record(conn, "R02X", {"kind": "fasting_glucose", "value": value,
                                          "recorded_at": iso(now() - timedelta(hours=24 * (2 - i)))})
    events = detect_events(conn, "R02X")["created"]
    assert events
    due = (now() + timedelta(days=1)).isoformat()
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[ToolCall("search_knowledge", {"query": "血糖 记录 意义"}, "c1")], raw={}),
        LLMResponse(content="", tool_calls=[
            ToolCall("request_human_review", {"patient_id": "R02X", "event_id": events[0]["id"],
                                              "reason": "血糖显著升高，需要人工复核", "severity": "high"}, "c2"),
            ToolCall("create_task", {"patient_id": "R02X", "task_type": "record_glucose",
                                     "title": "补录空腹血糖",
                                     "description": "本任务仅为数据采集，不含用药调整建议。",
                                     "due_at": due}, "c3"),
        ], raw={}),
        LLMResponse(content="已创建补录任务并提交人工复核。", tool_calls=[], raw={}),
    ])
    result = orchestrator.run_agent(conn, "R02X", trigger_type="event_detected",
                                    event_ids=[events[0]["id"]], llm=llm)
    assert result["status"] == "completed", result
    assert not result["rejections"], result["rejections"]
    assert conn.execute("SELECT COUNT(*) c FROM tasks WHERE patient_id='R02X'").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM reviews WHERE patient_id='R02X'").fetchone()["c"] >= 1
