"""A5：Real 模式个体化自主决策（ScriptedLLM 验证后端执行合同，不宣称真实模型通过）。"""
from __future__ import annotations

from datetime import timedelta

from backend.app.agent import orchestrator
from backend.app.agent.llm import LLMResponse, ToolCall
from backend.app.audit.trace import steps
from backend.app.db.connection import iso, now
from backend.app.services import patients, records
from backend.app.tasks import service as tasks


class CapturingLLM:
    mode = "real"
    model_name = "scripted-autonomy"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.prompts: list[str] = []

    def plan_actions(self, *, system=None, user=None, tools=None, extra_messages=None):
        self.prompts.append(user or "")
        index = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return self.responses[index]


def _patient(conn, pid):
    patients.create_patient(conn, {"id": pid, "name": pid, "age": 60, "duration_years": 5, "goals": ["稳定"]})


def _glucose_event(conn, pid, code="GLUCOSE_RISING", severity="high", evidence=None):
    eid = f"EVT-{pid}-{code}"
    conn.execute(
        """INSERT INTO events(id,patient_id,code,severity,status,message,evidence,dedupe_key,source_record_id,detected_at)
           VALUES(?,?,?,?,'open',?,?,?,?,?)""",
        (eid, pid, code, severity, code, __import__("json").dumps(evidence or {"first": 7.0, "last": 9.5, "delta": 2.5}),
         f"{pid}:{code}:x", None, iso(now(conn))),
    )
    return eid


def test_same_event_different_patients_get_different_context(conn):
    _patient(conn, "AUT-A")
    _patient(conn, "AUT-B")
    evt_a = _glucose_event(conn, "AUT-A")
    evt_b = _glucose_event(conn, "AUT-B")
    task_b, _ = tasks.create_task(conn, "AUT-B", task_type="record_glucose", title="补录血糖",
                                  due_at=iso(now(conn) + timedelta(days=1)), schedule_review=False)

    llm_a = CapturingLLM([LLMResponse(content="", tool_calls=[ToolCall("ask_user", {
        "patient_id": "AUT-A", "question": "最近一次服药情况？", "target_field": "medication_taken"}, "c1")], raw={})])
    llm_b = CapturingLLM([LLMResponse(content="", tool_calls=[ToolCall("update_task", {
        "task_id": task_b["id"],
        "due_at": (now(conn) + timedelta(days=2)).isoformat()}, "c1")], raw={})])
    orchestrator.run_agent(conn, "AUT-A", trigger_type="event_detected", event_ids=[evt_a], llm=llm_a)
    orchestrator.run_agent(conn, "AUT-B", trigger_type="event_detected", event_ids=[evt_b], llm=llm_b)

    prompt_a, prompt_b = llm_a.prompts[0], llm_b.prompts[0]
    assert "EVT-AUT-A-GLUCOSE_RISING" in prompt_a and "EVT-AUT-B-GLUCOSE_RISING" in prompt_b
    assert "evidence" in prompt_a and "evidence" in prompt_b
    assert task_b["id"] not in prompt_a
    assert task_b["id"] in prompt_b
    # 相同事件代码，模型可见的既有任务不同 → 决策依据不同
    assert prompt_a != prompt_b


def test_existing_task_is_reused_not_duplicated(conn):
    _patient(conn, "AUT-C")
    evt = _glucose_event(conn, "AUT-C")
    task, _ = tasks.create_task(conn, "AUT-C", task_type="record_glucose", title="补录血糖",
                                due_at=iso(now(conn) + timedelta(days=1)), schedule_review=False)
    llm = CapturingLLM([
        LLMResponse(content="已有同类待办，调整时间即可", tool_calls=[ToolCall("update_task", {
            "task_id": task["id"], "due_at": (now(conn) + timedelta(days=2)).isoformat()}, "c1")], raw={}),
        LLMResponse(content="已调整现有任务。", tool_calls=[], raw={}),
    ])
    result = orchestrator.run_agent(conn, "AUT-C", trigger_type="event_detected", event_ids=[evt], llm=llm)
    assert result["status"] == "completed", result
    assert conn.execute("SELECT COUNT(*) c FROM tasks WHERE patient_id='AUT-C'").fetchone()["c"] == 1
    assert tasks.get_task(conn, task["id"])["version"] == 2
    assert any(s["kind"] == "decision" for s in steps(conn, result["run_id"])), "必须有结构化决策轨迹"


def test_missing_information_triggers_question(conn):
    _patient(conn, "AUT-D")
    evt = _glucose_event(conn, "AUT-D")
    llm = CapturingLLM([LLMResponse(content="缺少服药信息，先询问", tool_calls=[ToolCall("ask_user", {
        "patient_id": "AUT-D", "question": "最近一次服药情况？", "target_field": "medication_taken"}, "c1")], raw={})])
    result = orchestrator.run_agent(conn, "AUT-D", trigger_type="event_detected", event_ids=[evt], llm=llm)
    assert result["status"] == "waiting_user", result
    q = conn.execute("SELECT * FROM questions WHERE patient_id='AUT-D' AND status='waiting'").fetchone()
    assert q and q["target_field"] == "medication_taken"
    assert conn.execute("SELECT COUNT(*) c FROM health_records WHERE kind='medication_taken'").fetchone()["c"] == 0


def test_high_risk_goes_to_human_review(conn):
    _patient(conn, "AUT-E")
    evt = _glucose_event(conn, "AUT-E", severity="high")
    llm = CapturingLLM([LLMResponse(content="高风险，升级复核", tool_calls=[ToolCall("request_human_review", {
        "patient_id": "AUT-E", "event_id": evt, "reason": "低血糖风险需专业人员判断", "severity": "high"}, "c1")], raw={})])
    result = orchestrator.run_agent(conn, "AUT-E", trigger_type="event_detected", event_ids=[evt], llm=llm)
    assert result["status"] in ("completed", "waiting_user"), result
    review = conn.execute("SELECT * FROM reviews WHERE patient_id='AUT-E' AND branch='HUMAN_REVIEW'").fetchone()
    assert review and review["status"] == "pending_human"
    assert conn.execute("SELECT COUNT(*) c FROM tasks WHERE patient_id='AUT-E'").fetchone()["c"] == 0


def test_decision_trace_records_rationale_and_tools(conn):
    _patient(conn, "AUT-F")
    evt = _glucose_event(conn, "AUT-F")
    llm = CapturingLLM([
        LLMResponse(content="先补录血糖再观察趋势", tool_calls=[ToolCall("create_task", {
            "patient_id": "AUT-F", "task_type": "record_glucose", "title": "补录空腹血糖",
            "event_id": evt, "due_at": (now(conn) + timedelta(days=1)).isoformat()}, "c1")], raw={}),
        LLMResponse(content="已创建补录任务。", tool_calls=[], raw={}),
    ])
    result = orchestrator.run_agent(conn, "AUT-F", trigger_type="event_detected", event_ids=[evt], llm=llm)
    decisions = [s for s in steps(conn, result["run_id"]) if s["kind"] == "decision_rationale"]
    assert decisions, "缺少决策轨迹"
    payload = decisions[0]["payload"]
    assert payload.get("rationale") and "create_task" in payload.get("tools", [])
    assert evt in payload.get("linked_event_ids", [])
