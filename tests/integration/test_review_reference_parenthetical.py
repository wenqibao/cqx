"""A-035 补充：带 ID/日期的既有复评引用。"""
from __future__ import annotations

from datetime import timedelta

from backend.app.agent import orchestrator
from backend.app.agent.llm import LLMResponse, ToolCall
from backend.app.db.connection import iso, now
from backend.app.reviews import service as reviews
from backend.app.services import patients
from backend.app.services import records


class _LLM:
    mode = "real"
    model_name = "scripted-review-ref"

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


def test_parenthetical_review_reference_is_recognized(conn):
    _patient(conn, "PR1")
    evt = _event(conn, "PR1")
    review = reviews.schedule_review(conn, "PR1", event_id=evt, delay_hours=48)
    day = str(review["scheduled_for"])[:10]
    text = f"该任务对应的复评（{review['id']}，{day}）沿用原计划，不重复安排。"
    llm = _LLM([LLMResponse(content="", tool_calls=[ToolCall("respond", {"patient_id": "PR1", "text": text}, "c1")], raw={})])
    result = orchestrator.run_agent(conn, "PR1", trigger_type="answer_received", message="记不清", llm=llm)
    assert result["status"] == "completed", result
    assert not [r for r in result["rejections"] if r["code"] == "POSTCHECK_MISMATCH"]
    steps = conn.execute("SELECT kind, payload FROM agent_steps WHERE run_id=?", (result["run_id"],)).fetchall()
    assert any(row["kind"] == "review_reference" for row in steps)


def test_wrong_date_parenthetical_reference_is_rejected(conn):
    _patient(conn, "PR2")
    evt = _event(conn, "PR2")
    review = reviews.schedule_review(conn, "PR2", event_id=evt, delay_hours=48)
    text = f"该任务对应的复评（{review['id']}，2020-01-01）沿用原计划。"
    llm = _LLM([LLMResponse(content="", tool_calls=[ToolCall("respond", {"patient_id": "PR2", "text": text}, "c1")], raw={})])
    result = orchestrator.run_agent(conn, "PR2", trigger_type="answer_received", message="记不清", llm=llm)
    assert any(r["code"] == "POSTCHECK_MISMATCH" for r in result["rejections"])

def test_date_summary_covers_multiple_reviews(conn):
    _patient(conn, "PR3")
    evt = _event(conn, "PR3")
    first = reviews.schedule_review(conn, "PR3", event_id=evt, delay_hours=24)
    from backend.app.tasks import service as tasks
    from backend.app.db.connection import iso, now
    from datetime import timedelta

    task, _ = tasks.create_task(conn, "PR3", task_type="record_glucose", title="补录",
                                due_at=iso(now(conn) + timedelta(days=1)), schedule_review=False)
    second = reviews.schedule_review(conn, "PR3", task_id=task["id"], delay_hours=48)
    task2, _ = tasks.create_task(conn, "PR3", task_type="record_activity", title="活动",
                                 due_at=iso(now(conn) + timedelta(days=2)), schedule_review=False)
    third = reviews.schedule_review(conn, "PR3", task_id=task2["id"], delay_hours=48)
    day1 = str(first["scheduled_for"])[:10]
    day2 = str(second["scheduled_for"])[:10]
    text = f"两项任务都已安排复评（{day1}、{day2}），沿用原计划。"
    llm = _LLM([LLMResponse(content="", tool_calls=[ToolCall("respond", {"patient_id": "PR3", "text": text}, "c1")], raw={})])
    result = orchestrator.run_agent(conn, "PR3", trigger_type="answer_received", message="记不清", llm=llm)
    assert result["status"] == "completed", result
    assert not [r for r in result["rejections"] if r["code"] == "POSTCHECK_MISMATCH"]
    import json as _json
    refs = conn.execute("SELECT payload FROM agent_steps WHERE run_id=? AND kind='review_reference'", (result["run_id"],)).fetchall()
    assert refs and len(_json.loads(refs[0]["payload"])["review_ids"]) >= 2
