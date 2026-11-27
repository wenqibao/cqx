"""O2/O3/O4：回答语义、信息复用、任务前后对照。"""
from __future__ import annotations

from datetime import timedelta

import pytest

from backend.app.agent import orchestrator, tools
from backend.app.agent.llm import LLMResponse, ToolCall
from backend.app.db.connection import dumps, iso, now
from backend.app.questioning import service as questioning
from backend.app.services import patients, records
from backend.app.tasks import service as tasks


class _LLM:
    mode = "real"
    model_name = "scripted-adapt"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def plan_actions(self, **kwargs):
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return response


def _patient(conn, pid):
    patients.create_patient(conn, {"id": pid, "name": pid, "age": 60, "duration_years": 5, "goals": ["稳定"]})
    for kind, value in (("medication_taken", 1), ("steps", 6000)):
        records.add_record(conn, pid, {"kind": kind, "value": value, "recorded_at": iso(now(conn))})


def _question(conn, pid, field="medication_taken"):
    question, _ = questioning.create_question(conn, pid, question="近7天是否按时服药？",
                                              kind="missing_field", target_field=field)
    return question


def test_uncertain_variants_stay_unknown(conn):
    _patient(conn, "O3A")
    for text in ("记不清", "这几天没记，不能确定", "暂时无法确认"):
        question = _question(conn, "O3A")
        answered = questioning.answer_question(conn, question["id"], answer_text=text)
        assert answered["answer"]["uncertain"] is True
        assert conn.execute("SELECT COUNT(*) c FROM health_records WHERE patient_id='O3A' AND kind='medication_taken'").fetchone()["c"] == 1


def test_definite_negative_is_known(conn):
    _patient(conn, "O3B")
    question = _question(conn, "O3B")
    answered = questioning.answer_question(conn, question["id"], answer_text="没有按时服药")
    assert answered["answer"]["uncertain"] is False


def test_answered_valid_field_is_reused_not_reasked(conn):
    _patient(conn, "O3C")
    question = _question(conn, "O3C")
    questioning.answer_question(conn, question["id"], answer_text="已按时服药")
    result = tools.execute(tools.ToolContext(conn, patient_id="O3C", run_id="RUN-O3C"), "ask_user", {
        "patient_id": "O3C", "question": "再次确认服药？", "target_field": "medication_taken",
    })
    assert result["ok"] is True and result.get("reused") is True
    assert result["created"] is False
    assert conn.execute("SELECT COUNT(*) c FROM questions WHERE patient_id='O3C' AND status='waiting'").fetchone()["c"] == 0


def test_uncertain_answer_allows_new_question(conn):
    _patient(conn, "O3D")
    question = _question(conn, "O3D")
    questioning.answer_question(conn, question["id"], answer_text="记不清")
    result = tools.execute(tools.ToolContext(conn, patient_id="O3D", run_id="RUN-O3D"), "ask_user", {
        "patient_id": "O3D", "question": "请补充服药情况", "target_field": "medication_taken",
    })
    assert result["ok"] is True and result["created"] is True


def test_plan_changes_from_update_task(client, conn):
    _patient(conn, "O4A")
    task, _ = tasks.create_task(conn, "O4A", task_type="record_glucose", title="记录",
                                due_at=iso(now(conn) + timedelta(days=1)), schedule_review=False)
    new_due = (now(conn) + timedelta(days=2)).isoformat()
    llm = _LLM([LLMResponse(content="", tool_calls=[ToolCall("update_task", {
        "patient_id": "O4A", "task_id": task["id"], "due_at": new_due}, "c1")], raw={})])
    result = orchestrator.run_agent(conn, "O4A", trigger_type="answer_received", message="改成后天", llm=llm)
    body = client.get(f"/api/runs/{result['run_id']}").json()
    change = body["summary"]["plan_changes"][0]
    assert change["task_id"] == task["id"]
    assert change["version_before"] == 1 and change["version_after"] == 2
    assert change["changed_fields"]["due_at"]["before"] != change["changed_fields"]["due_at"]["after"]
    assert change["result"] == "saved"


def test_failed_update_has_no_plan_change(client, conn):
    _patient(conn, "O4B")
    task, _ = tasks.create_task(conn, "O4B", task_type="record_glucose", title="记录",
                                due_at=iso(now(conn) + timedelta(days=1)), schedule_review=False)
    llm = _LLM([LLMResponse(content="", tool_calls=[ToolCall("update_task", {
        "patient_id": "O4B", "task_id": task["id"], "due_at": "2000-01-01T00:00:00Z"}, "c1")], raw={})])
    result = orchestrator.run_agent(conn, "O4B", trigger_type="answer_received", message="改成过去", llm=llm)
    body = client.get(f"/api/runs/{result['run_id']}").json()
    assert body["summary"]["plan_changes"] == []
    assert body["summary"]["unfinished"]


def test_resume_with_uncertain_answer_keeps_unknown(client, conn):
    _patient(conn, "O3E")
    question = _question(conn, "O3E")
    conn.execute("UPDATE questions SET run_id='RUN-Q1' WHERE id=?", (question["id"],))
    llm = _LLM([LLMResponse(content="", tool_calls=[ToolCall("respond", {
        "patient_id": "O3E", "text": "记不清也没关系，先按原计划观察。"}, "c1")], raw={})])
    result = orchestrator.run_agent(conn, "O3E", trigger_type="answer_received", message="记不清", llm=llm)
    assert result["status"] == "completed", result
    body = client.get(f"/api/runs/{result['run_id']}").json()
    assert body["summary"]["plan_changes"] == []
    assert conn.execute("SELECT COUNT(*) c FROM health_records WHERE patient_id='O3E' AND kind='medication_taken'").fetchone()["c"] == 1

def test_reused_answer_run_does_not_enter_waiting(conn):
    _patient(conn, "O3F")
    question = _question(conn, "O3F")
    questioning.answer_question(conn, question["id"], answer_text="已按时服药")
    llm = _LLM([LLMResponse(content="", tool_calls=[ToolCall("ask_user", {
        "patient_id": "O3F", "question": "再次确认服药？", "target_field": "medication_taken"}, "c1")], raw={}),
        LLMResponse(content="已复用此前回答：已按时服药。", tool_calls=[], raw={})])
    result = orchestrator.run_agent(conn, "O3F", trigger_type="answer_received", message="已按时服药", llm=llm)
    assert result["status"] == "completed", result
    assert conn.execute("SELECT COUNT(*) c FROM questions WHERE patient_id='O3F' AND status='waiting'").fetchone()["c"] == 0


@pytest.mark.parametrize("text", ["我不记得了", "现在无法判断", "这个不好说"])
def test_more_uncertain_phrases_stay_unknown(conn, text):
    _patient(conn, "O3G")
    question = _question(conn, "O3G")
    answered = questioning.answer_question(conn, question["id"], answer_text=text)
    assert answered["answer"]["uncertain"] is True
    assert conn.execute(
        "SELECT COUNT(*) c FROM health_records WHERE patient_id='O3G' AND kind='medication_taken'"
    ).fetchone()["c"] == 1

def test_resolved_warning_not_in_unfinished(client, conn):
    _patient(conn, "W1")
    run_id = "RUN-W1"
    conn.execute(
        "INSERT OR REPLACE INTO agent_runs(id,patient_id,trigger_type,llm_mode,status,intent,output,started_at) "
        "VALUES('RUN-W1','W1','event_detected','mock','completed','event_response',?,?)",
        (dumps({"responses": ["已安排复评"], "rejections": [
            {"code": "TOOL_EXECUTION_FAILED", "message": "缺少 task_id", "tool": "schedule_review"}],
            "warnings": [{"code": "TOOL_EXECUTION_FAILED", "message": "缺少 task_id",
                          "tool": "schedule_review", "resolved": True}]}), iso(now(conn))),
    )
    task, _ = tasks.create_task(conn, "W1", task_type="record_glucose", title="记录",
                                due_at=iso(now(conn) + timedelta(days=1)), schedule_review=False)
    review = __import__("backend.app.reviews.service", fromlist=["schedule_review"]).schedule_review(
        conn, "W1", task_id=task["id"], delay_hours=24)
    conn.execute(
        "INSERT INTO agent_steps(run_id,step_no,phase,kind,tool_name,payload,status,created_at) "
        "VALUES('RUN-W1',1,'observe','tool_result','schedule_review',?,'ok',?)",
        (dumps({"result": {"ok": True, "review_id": review["id"]}}), iso(now(conn))),
    )
    body = client.get("/api/runs/RUN-W1").json()
    assert body["summary"]["unfinished"] == []
    assert body["summary"]["partial_success"] is False
    assert body["summary"]["warnings"][0]["resolved"] is True


def test_adherence_injection_count_is_allowed():
    from backend.app.safety import gate

    text = "核对近7天降糖药/胰岛素的服用与注射次数，仅做记录核实，不涉及任何用药调整。"
    assert gate.check_text(text, generated=True)["allowed"] is True
    assert gate.check_text("增加注射次数。", generated=True)["allowed"] is False
    assert gate.check_text("调整胰岛素剂量。", generated=True)["allowed"] is False


def test_reason_due_date_conflict_is_rejected(conn):
    _patient(conn, "W2")
    task, _ = tasks.create_task(conn, "W2", task_type="record_glucose", title="记录",
                                due_at=iso(now(conn) + timedelta(days=1)), schedule_review=False)
    from backend.app.agent import tools
    from zoneinfo import ZoneInfo
    from datetime import datetime

    tz = ZoneInfo("Asia/Shanghai")
    base = now(conn).astimezone(tz)
    target = (base + timedelta(days=1)).replace(hour=20, minute=0, second=0, microsecond=0)
    good = tools.execute(tools.ToolContext(conn, patient_id="W2", run_id="RUN-W2"), "update_task", {
        "patient_id": "W2", "task_id": task["id"], "due_at": target.isoformat(),
        "reason": f"明天（{target.date()}）北京时间20:00",
    })
    assert good["ok"] is True, good
    bad = tools.execute(tools.ToolContext(conn, patient_id="W2", run_id="RUN-W2"), "update_task", {
        "patient_id": "W2", "task_id": task["id"],
        "due_at": (target - timedelta(days=1)).isoformat(),
        "reason": f"明天（{target.date()}）北京时间20:00",
    })
    assert bad["ok"] is False
    assert bad["code"] == "MISSING_REQUIRED_DATA"

def test_only_matching_resolved_error_is_removed(client, conn):
    _patient(conn, "W3")
    conn.execute(
        "INSERT OR REPLACE INTO agent_runs(id,patient_id,trigger_type,llm_mode,status,intent,output,started_at) "
        "VALUES('RUN-W3','W3','event_detected','mock','completed','event_response',?,?)",
        (dumps({
            "rejections": [
                {"code": "TOOL_EXECUTION_FAILED", "message": "缺少 task_id", "tool": "schedule_review"},
                {"code": "TOOL_EXECUTION_FAILED", "message": "时间已过", "tool": "schedule_review"},
            ],
            "warnings": [{"code": "TOOL_EXECUTION_FAILED", "message": "缺少 task_id",
                          "tool": "schedule_review", "resolved": True}],
        }), iso(now(conn))),
    )
    body = client.get("/api/runs/RUN-W3").json()
    remaining = [item["message"] for item in body["summary"]["unfinished"]]
    assert remaining == ["时间已过"]


def test_adherence_mixed_with_change_is_blocked():
    from backend.app.safety import gate

    assert gate.check_text("核对后把注射次数增加到每天三次。", generated=True)["allowed"] is False
    assert gate.check_text("核对既往服用与注射次数。", generated=True)["allowed"] is True


def test_request_date_conflict_is_rejected(conn):
    _patient(conn, "W4")
    task, _ = tasks.create_task(conn, "W4", task_type="record_glucose", title="记录",
                                due_at=iso(now(conn) + timedelta(days=2)), schedule_review=False)
    from backend.app.db.connection import dumps as _dumps
    conn.execute(
        "INSERT OR REPLACE INTO agent_runs(id,patient_id,trigger_type,llm_mode,status,input,started_at) "
        "VALUES('RUN-W4','W4','answer_received','mock','running',?,?)",
        (_dumps({"message": "明天晚上8点提醒我"}), iso(now(conn))),
    )
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Asia/Shanghai")
    due = now(conn).astimezone(tz).replace(hour=20, minute=0, second=0, microsecond=0)
    from backend.app.agent import tools

    result = tools.execute(tools.ToolContext(conn, patient_id="W4", run_id="RUN-W4"), "update_task", {
        "patient_id": "W4", "task_id": task["id"], "due_at": due.isoformat(),
        "reason": "患者申请调整时间",
    })
    assert result["ok"] is False
    assert result["code"] == "MISSING_REQUIRED_DATA"

def _scheduled_review(conn, pid, *, local_time="2026-11-30T02:04:55+08:00"):
    from datetime import datetime

    from backend.app.db.connection import dumps as _dumps
    task, _ = tasks.create_task(conn, pid, task_type="record_glucose", title="核实",
                                due_at=iso(now(conn) + timedelta(days=2)), schedule_review=False)
    review_id = f"REV-{pid}"
    conn.execute(
        "INSERT INTO reviews(id,patient_id,task_id,event_id,run_id,branch,status,reason,scheduled_for,created_at) "
        "VALUES(?,?,?,NULL,NULL,'MISSING_DATA','scheduled','核实',?,?)",
        (review_id, pid, task["id"], local_time, iso(now(conn))),
    )
    return review_id


def test_existing_review_claim_with_local_date_is_accepted(conn):
    _patient(conn, "F2A")
    review_id = _scheduled_review(conn, "F2A")
    text = "已安排的复评仍按原计划在11月30日凌晨（北京时间）进行。"
    run_id = "RUN-F2A"
    conn.execute(
        "INSERT OR REPLACE INTO agent_runs(id,patient_id,trigger_type,llm_mode,status,input,started_at) "
        "VALUES('RUN-F2A','F2A','answer_received','mock','running',?,?)",
        (dumps({"message": "我不记得了"}), iso(now(conn))),
    )
    llm = _LLM([LLMResponse(content="", tool_calls=[ToolCall("respond", {
        "patient_id": "F2A", "text": text}, "c1")], raw={})])
    result = orchestrator.run_agent(conn, "F2A", trigger_type="answer_received", message="我不记得了", llm=llm)
    assert result["status"] == "completed", result
    assert not [r for r in result["rejections"] if r["code"] == "POSTCHECK_MISMATCH"]
    refs = conn.execute(
        "SELECT payload FROM agent_steps WHERE run_id=? AND kind='review_reference'", (result["run_id"],)
    ).fetchall()
    assert refs
    assert conn.execute("SELECT COUNT(*) c FROM reviews WHERE patient_id='F2A'").fetchone()["c"] == 1


def test_review_claim_without_any_review_is_rejected(conn):
    _patient(conn, "F2B")
    llm = _LLM([LLMResponse(content="", tool_calls=[ToolCall("respond", {
        "patient_id": "F2B", "text": "已安排的复评仍按原计划在11月30日凌晨（北京时间）进行。"}, "c1")], raw={})])
    result = orchestrator.run_agent(conn, "F2B", trigger_type="answer_received", message="我不记得了", llm=llm)
    assert result["status"] == "failed"
    assert any(r["code"] == "POSTCHECK_MISMATCH" for r in result["rejections"])

def test_new_task_reuses_existing_event_review(conn):
    _patient(conn, "R1")
    conn.execute(
        "INSERT INTO events(id,patient_id,code,severity,status,message,evidence,dedupe_key,source_record_id,detected_at) "
        "VALUES('EVT-R1','R1','GLUCOSE_RISING','high','open','x','{}','R1:x',NULL,?)",
        (iso(now(conn)),),
    )
    tasks.create_task(conn, "R1", task_type="record_glucose", title="一",
                      due_at=iso(now(conn) + timedelta(days=1)), event_id="EVT-R1")
    tasks.create_task(conn, "R1", task_type="record_activity", title="二",
                      due_at=iso(now(conn) + timedelta(days=2)), event_id="EVT-R1")
    count = conn.execute("SELECT COUNT(*) c FROM reviews WHERE patient_id='R1'").fetchone()["c"]
    assert count == 1


def test_new_task_on_new_event_gets_own_review(conn):
    _patient(conn, "R2")
    for index, evt in enumerate(("EVT-R2A", "EVT-R2B")):
        conn.execute(
            "INSERT INTO events(id,patient_id,code,severity,status,message,evidence,dedupe_key,source_record_id,detected_at) "
            "VALUES(?,?,'GLUCOSE_RISING','high','open','x','{}',?,NULL,?)",
            (evt, "R2", f"R2:{index}", iso(now(conn))),
        )
        tasks.create_task(conn, "R2", task_type="record_glucose", title=f"t{index}",
                          due_at=iso(now(conn) + timedelta(days=1 + index)), event_id=evt)
    assert conn.execute("SELECT COUNT(*) c FROM reviews WHERE patient_id='R2'").fetchone()["c"] >= 1
