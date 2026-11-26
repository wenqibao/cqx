"""O1：运行顶部业务结果摘要。"""
from __future__ import annotations

from datetime import timedelta

from backend.app.agent import orchestrator
from backend.app.agent.llm import LLMResponse, ToolCall
from backend.app.audit import trace as trace_mod
from backend.app.db.connection import iso, now
from backend.app.services import patients, records


class _LLM:
    mode = "real"
    model_name = "scripted-o1"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def plan_actions(self, **kwargs):
        index = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return self.responses[index]


def _patient(conn, pid):
    patients.create_patient(conn, {"id": pid, "name": pid, "age": 60, "duration_years": 5, "goals": ["稳定"]})
    for kind, value in (("medication_taken", 1), ("steps", 6000)):
        records.add_record(conn, pid, {"kind": kind, "value": value, "recorded_at": iso(now(conn))})


def _event(conn, pid):
    eid = f"EVT-{pid}"
    conn.execute(
        "INSERT INTO events(id,patient_id,code,severity,status,message,evidence,dedupe_key,source_record_id,detected_at) "
        "VALUES(?,?,'GLUCOSE_RISING','high','open','x','{}',?,NULL,?)",
        (eid, pid, f"{pid}:x", iso(now(conn))),
    )
    return eid


def test_summary_for_completed_action(conn):
    _patient(conn, "S1")
    evt = _event(conn, "S1")
    llm = _LLM([LLMResponse(content="", tool_calls=[ToolCall("create_task", {
        "patient_id": "S1", "task_type": "record_glucose", "title": "补录血糖",
        "event_id": evt, "due_at": (now(conn) + timedelta(days=1)).isoformat()}, "c1")], raw={})])
    result = orchestrator.run_agent(conn, "S1", trigger_type="event_detected", event_ids=[evt], llm=llm)
    summary = trace_mod.trace(conn, result["run_id"])["summary"]
    assert summary["goal"]
    assert summary["trigger"]["type"] == "event_detected"
    assert any(item["tool"] == "create_task" and item["refs"] for item in summary["completed"])
    assert summary["waiting"] is None
    assert summary["next_owner"] is None
    assert summary["partial_success"] is False


def test_summary_for_waiting_question(conn):
    _patient(conn, "S2")
    evt = _event(conn, "S2")
    llm = _LLM([LLMResponse(content="", tool_calls=[ToolCall("ask_user", {
        "patient_id": "S2", "question": "近7天是否按时服药？", "target_field": "medication_taken"}, "c1")], raw={})])
    result = orchestrator.run_agent(conn, "S2", trigger_type="event_detected", event_ids=[evt], llm=llm)
    summary = trace_mod.trace(conn, result["run_id"])["summary"]
    assert summary["waiting"]["kind"] == "question"
    assert summary["waiting"]["target_field"] == "medication_taken"
    assert summary["next_owner"]["role"] == "patient"


def test_summary_for_failed_action(conn):
    _patient(conn, "S3")
    evt = _event(conn, "S3")
    llm = _LLM([LLMResponse(content="", tool_calls=[ToolCall("create_task", {
        "patient_id": "S3", "task_type": "made_up", "title": "x",
        "event_id": evt, "due_at": (now(conn) + timedelta(days=1)).isoformat()}, "c1")], raw={})])
    result = orchestrator.run_agent(conn, "S3", trigger_type="event_detected", event_ids=[evt], llm=llm)
    summary = trace_mod.trace(conn, result["run_id"])["summary"]
    assert summary["unfinished"]
    assert summary["next_owner"]["role"] in ("agent", "patient")


def test_summary_tolerates_legacy_run(conn):
    _patient(conn, "S4")
    conn.execute(
        "INSERT INTO agent_runs(id,patient_id,trigger_type,llm_mode,status,started_at) "
        "VALUES('RUN-LEGACY','S4','user_request','mock','completed',?)",
        (iso(now(conn)),),
    )
    summary = trace_mod.trace(conn, "RUN-LEGACY")["summary"]
    assert summary["completed"] == []
    assert summary["unfinished"] == []
    assert summary["waiting"] is None
    assert summary["refs"] == ["RUN-LEGACY"]
