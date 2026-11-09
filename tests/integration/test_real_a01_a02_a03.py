"""REAL-A01：任务类型规范/别名/迁移；REAL-A02：安全措辞成对回归；REAL-A03：动作额度。"""
from __future__ import annotations

from datetime import timedelta

import pytest

from backend.app.agent import orchestrator, tools
from backend.app.agent.llm import LLMResponse, ToolCall, tool_schemas
from backend.app.db import migrations
from backend.app.db.connection import iso, now
from backend.app.safety import gate, validators
from backend.app.services import patients
from backend.app.tasks import service as tasks
from backend.app.tasks.types import canonical_task_types, normalize_task_type


def _patient(conn, pid="TT1"):
    patients.create_patient(conn, {"id": pid, "name": pid, "age": 60, "duration_years": 5, "goals": ["稳定"]})


def _ctx(conn, pid="TT1"):
    return tools.ToolContext(conn, patient_id=pid, run_id="RUN-TT")


class CaptureLLM:
    mode = "real"
    model_name = "capture"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.histories: list[list[dict]] = []

    def plan_actions(self, *, system=None, user=None, tools=None, extra_messages=None):
        self.histories.append(list(extra_messages or []))
        index = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return self.responses[index]


# ---------------- A01 ----------------

def test_unknown_task_type_is_rejected_with_candidates(conn):
    _patient(conn)
    result = tools.execute(_ctx(conn), "create_task", {
        "patient_id": "TT1", "task_type": "glucose_record_check",
        "title": "x", "due_at": (now(conn) + timedelta(days=1)).isoformat(),
    })
    assert result["ok"] is True, "别名应被归一而不是拒绝"
    assert tasks.list_tasks(conn, "TT1")[0]["task_type"] == "record_glucose"

    bad = tools.execute(_ctx(conn), "create_task", {
        "patient_id": "TT1", "task_type": "totally_made_up",
        "title": "x", "due_at": (now(conn) + timedelta(days=1)).isoformat(),
    })
    assert bad["ok"] is False
    assert bad["code"] == "INVALID_TASK_TYPE"
    assert "record_glucose" in bad["error"]


def test_schema_exposes_canonical_task_types():
    schema = next(s for s in tool_schemas() if s["name"] == "create_task")
    task_type = schema["parameters"]["properties"]["task_type"]
    assert set(canonical_task_types()) <= set(task_type["enum"])
    assert "record_glucose" in task_type["enum"]


def test_legacy_task_types_are_normalized_by_migration(conn):
    _patient(conn)
    conn.execute(
        "INSERT INTO tasks(id,patient_id,task_type,title,status,due_at,version,dedupe_key,created_at,updated_at) "
        "VALUES('TSK-LEGACY','TT1','record_reminder','旧任务','pending',?,1,'legacy-key',?,?)",
        (iso(now(conn) + timedelta(days=1)), iso(now(conn)), iso(now(conn))),
    )
    migrations._normalize_task_types(conn)
    row = conn.execute("SELECT task_type FROM tasks WHERE id='TSK-LEGACY'").fetchone()
    assert row["task_type"] == "record_glucose"
    assert normalize_task_type("glucose_record_check") == "record_glucose"
    assert normalize_task_type("not_a_type") is None


def test_validator_rejects_unknown_type_before_write(conn):
    _patient(conn)
    checked = validators.validate_plan(conn, patient_id="TT1", evidence=[], plan={"actions": [{
        "tool": "create_task",
        "args": {"patient_id": "TT1", "task_type": "made_up", "title": "x",
                 "due_at": (now(conn) + timedelta(days=1)).isoformat()},
    }]})
    assert any(r["code"] == "INVALID_TASK_TYPE" for r in checked["rejections"])
    assert conn.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"] == 0


# ---------------- A02 ----------------

@pytest.mark.parametrize("text", [
    "请按时记录血糖，不自行调整药物或剂量。",
    "遇到调整用药需求时，请引导患者就医。",
    "如出现调整剂量需求，请联系医生。",
])
def test_safe_business_phrasing_is_allowed(text):
    assert gate.check_text(text, generated=True)["allowed"] is True
    assert gate.check_text(text)["allowed"] is True


@pytest.mark.parametrize("text", [
    "请把降糖药停掉。",
    "把胰岛素改成早上多打两个单位。",
    "建议减少二甲双胍剂量。",
])
def test_actual_medication_change_is_blocked(text):
    assert gate.check_text(text, generated=True)["allowed"] is False


def test_task_description_with_safe_wording_is_not_flagged(conn):
    _patient(conn)
    checked = validators.validate_plan(conn, patient_id="TT1", evidence=[], plan={"actions": [{
        "tool": "create_task",
        "args": {"patient_id": "TT1", "task_type": "confirm_medication",
                 "title": "核实服药", "description": "请核对服药情况，不自行调整药物或剂量；需要时引导就医。",
                 "due_at": (now(conn) + timedelta(days=1)).isoformat()},
    }]})
    assert not [r for r in checked["rejections"] if r["code"] == "FORBIDDEN_ACTION"]


# ---------------- A03 ----------------

def test_action_budget_rejects_ninth_action_with_detail(conn):
    _patient(conn)
    responses = []
    for round_index in range(3):
        calls = [ToolCall("create_notification", {
            "patient_id": "TT1", "title": f"提醒{round_index * 3 + i}",
            "body": f"内容{round_index * 3 + i}"}, f"c{round_index * 3 + i}") for i in range(3)]
        responses.append(LLMResponse(content="", tool_calls=calls, raw={}))
    llm = CaptureLLM(responses)
    result = orchestrator.run_agent(conn, "TT1", trigger_type="request", message="给我一些提醒", llm=llm)
    assert result["status"] == "failed", result
    too_many = [r for r in result["rejections"] if r["code"] == "TOO_MANY_ACTIONS"]
    assert too_many, result["rejections"]
    assert too_many[0]["detail"]["cap"] == validators.max_actions_per_run()
    assert conn.execute("SELECT COUNT(*) c FROM notifications WHERE patient_id='TT1'").fetchone()["c"] == 8
    assert any(
        any("剩余动作额度" in (message.get("content") or "") for message in history)
        for history in llm.histories
    ), "应在后续轮次告知剩余动作额度"

def _event(conn, pid="MQ1", code="GLUCOSE_RISING"):
    conn.execute(
        "INSERT INTO events(id,patient_id,code,severity,status,message,evidence,dedupe_key,source_record_id,detected_at) "
        "VALUES(?,?,?,'high','open','x','{}',?,NULL,?)",
        (f"EVT-{pid}", pid, code, f"{pid}:{code}:x", iso(now(conn))),
    )
    return f"EVT-{pid}"


def test_adherence_patient_without_medication_gets_question(conn):
    patients.create_patient(conn, {"id": "MQ1", "name": "MQ1", "age": 62, "duration_years": 10,
                                   "goals": ["减少漏服"], "constraints": ["早餐后服药"]})
    evt = _event(conn)
    llm = CaptureLLM([LLMResponse(content="", tool_calls=[ToolCall("create_task", {
        "patient_id": "MQ1", "task_type": "record_glucose", "title": "补录血糖",
        "event_id": evt, "due_at": (now(conn) + timedelta(days=1)).isoformat()}, "c1")], raw={}),
        LLMResponse(content="已创建补录任务。", tool_calls=[], raw={})])
    result = orchestrator.run_agent(conn, "MQ1", trigger_type="event_detected", event_ids=[evt], llm=llm)
    assert result["status"] == "waiting_user", result
    question = conn.execute("SELECT * FROM questions WHERE patient_id='MQ1' AND status='waiting'").fetchone()
    assert question and question["target_field"] == "medication_taken"
    assert conn.execute("SELECT COUNT(*) c FROM tasks WHERE patient_id='MQ1'").fetchone()["c"] == 1


def test_non_adherence_patient_is_not_forced_to_ask(conn):
    _patient(conn, "MQ2")
    evt = _event(conn, "MQ2")
    llm = CaptureLLM([LLMResponse(content="", tool_calls=[ToolCall("create_task", {
        "patient_id": "MQ2", "task_type": "record_glucose", "title": "补录血糖",
        "event_id": evt, "due_at": (now(conn) + timedelta(days=1)).isoformat()}, "c1")], raw={}),
        LLMResponse(content="已创建补录任务。", tool_calls=[], raw={})])
    result = orchestrator.run_agent(conn, "MQ2", trigger_type="event_detected", event_ids=[evt], llm=llm)
    assert result["status"] == "completed", result
    assert conn.execute("SELECT COUNT(*) c FROM questions WHERE patient_id='MQ2'").fetchone()["c"] == 0
