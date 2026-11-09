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

def test_knowledge_question_is_classified_for_answer_like_questions():
    from backend.app.planning.planner import detect_intent
    assert detect_intent("血糖 9.8 是不是太高", False) == "knowledge_question"
    assert detect_intent("这个指标会不会有影响", False) == "knowledge_question"


def test_knowledge_question_only_exposes_search_and_respond(conn):
    _patient(conn, "KQ1")

    class ToolCapturingLLM:
        mode = "real"
        model_name = "kq-tools"

        def __init__(self):
            self.calls = 0
            self.tool_names: list[str] = []

        def plan_actions(self, *, system=None, user=None, tools=None, extra_messages=None):
            self.tool_names = [t["name"] for t in (tools or [])]
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(content="", tool_calls=[ToolCall(
                    "search_knowledge", {"query": "空腹血糖 偏高"}, "c1")], raw={})
            if self.calls == 2:
                return LLMResponse(content="", tool_calls=[
                    ToolCall("create_task", {"patient_id": "KQ1", "task_type": "record_glucose",
                                             "title": "记录", "due_at": (now(conn) + timedelta(days=1)).isoformat()}, "c2"),
                    ToolCall("create_notification", {"patient_id": "KQ1", "title": "提醒"}, "c3"),
                    ToolCall("request_human_review", {"patient_id": "KQ1", "reason": "血糖偏高", "severity": "high"}, "c4"),
                    ToolCall("respond", {"patient_id": "KQ1",
                                         "text": "空腹血糖 9.8 偏高，建议复测并与医生沟通。"}, "c5"),
                ], raw={})
            return LLMResponse(content="", tool_calls=[], raw={})

    llm = ToolCapturingLLM()
    result = orchestrator.run_agent(conn, "KQ1", trigger_type="user_request",
                                    message="血糖 9.8 是不是太高", llm=llm)
    assert "create_task" not in llm.tool_names
    assert "create_notification" not in llm.tool_names
    assert set(llm.tool_names) <= {"search_knowledge", "respond"}
    assert result["status"] == "completed", result
    assert conn.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM notifications").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM reviews").fetchone()["c"] == 0
    assert any("9.8" in text for text in result["responses"])
    skipped = [s for s in steps(conn, result["run_id"]) if s["code"] == "TOOL_NOT_ALLOWED"]
    assert len(skipped) == 3, "非知识类动作应被软拒绝并记录"

def test_duplicate_create_task_is_blocked_and_model_reuses(conn):
    _patient(conn, "AUT-G")
    evt = _glucose_event(conn, "AUT-G")
    existing, _ = tasks.create_task(conn, "AUT-G", task_type="confirm_medication", title="核实近3天服药",
                                    due_at=iso(now(conn) + timedelta(days=1)), schedule_review=False)
    llm = CapturingLLM([
        LLMResponse(content="先建个任务", tool_calls=[ToolCall("create_task", {
            "patient_id": "AUT-G", "task_type": "confirm_medication", "title": "核实服药",
            "event_id": evt, "due_at": (now(conn) + timedelta(days=2)).isoformat()}, "c1")], raw={}),
        LLMResponse(content="已有同类任务，改为调整", tool_calls=[ToolCall("update_task", {
            "task_id": existing["id"], "due_at": (now(conn) + timedelta(days=2)).isoformat()}, "c2")], raw={}),
        LLMResponse(content="已调整现有任务。", tool_calls=[], raw={}),
    ])
    result = orchestrator.run_agent(conn, "AUT-G", trigger_type="event_detected", event_ids=[evt], llm=llm)
    assert result["status"] == "completed", result
    assert conn.execute("SELECT COUNT(*) c FROM tasks WHERE patient_id='AUT-G'").fetchone()["c"] == 1
    assert tasks.get_task(conn, existing["id"])["version"] == 2
    assert any(s["code"] == "DUPLICATE_TASK" for s in steps(conn, result["run_id"]))


def test_different_task_type_is_still_allowed(conn):
    _patient(conn, "AUT-H")
    evt = _glucose_event(conn, "AUT-H")
    tasks.create_task(conn, "AUT-H", task_type="confirm_medication", title="核实服药",
                      due_at=iso(now(conn) + timedelta(days=1)), schedule_review=False)
    llm = CapturingLLM([
        LLMResponse(content="补录血糖", tool_calls=[ToolCall("create_task", {
            "patient_id": "AUT-H", "task_type": "record_glucose", "title": "补录空腹血糖",
            "event_id": evt, "due_at": (now(conn) + timedelta(days=1)).isoformat()}, "c1")], raw={}),
        LLMResponse(content="已创建补录任务。", tool_calls=[], raw={}),
    ])
    result = orchestrator.run_agent(conn, "AUT-H", trigger_type="event_detected", event_ids=[evt], llm=llm)
    assert result["status"] == "completed", result
    assert conn.execute("SELECT COUNT(*) c FROM tasks WHERE patient_id='AUT-H'").fetchone()["c"] == 2

def test_state_brief_marks_covering_task_for_event(conn):
    _patient(conn, "AUT-I")
    evt = _glucose_event(conn, "AUT-I")
    task, _ = tasks.create_task(conn, "AUT-I", task_type="confirm_medication", title="核实服药",
                                due_at=iso(now(conn) + timedelta(days=1)), schedule_review=False)
    llm = CapturingLLM([LLMResponse(content="", tool_calls=[ToolCall("ask_user", {
        "patient_id": "AUT-I", "question": "服药情况？", "target_field": "medication_taken"}, "c1")], raw={})])
    orchestrator.run_agent(conn, "AUT-I", trigger_type="event_detected", event_ids=[evt], llm=llm)
    prompt = llm.prompts[0]
    assert "已有可覆盖任务" in prompt
    assert task["id"] in prompt


def test_duplicate_rejection_forces_reuse_toolset(conn):
    _patient(conn, "AUT-J")
    evt = _glucose_event(conn, "AUT-J")
    existing, _ = tasks.create_task(conn, "AUT-J", task_type="confirm_medication", title="核实服药",
                                    due_at=iso(now(conn) + timedelta(days=1)), schedule_review=False)

    class ReuseLLM:
        mode = "real"
        model_name = "reuse"

        def __init__(self):
            self.calls = 0
            self.tools_by_call: list[list[str]] = []

        def plan_actions(self, *, system=None, user=None, tools=None, extra_messages=None):
            self.tools_by_call.append([t["name"] for t in (tools or [])])
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(content="", tool_calls=[ToolCall("create_task", {
                    "patient_id": "AUT-J", "task_type": "confirm_medication", "title": "核实服药",
                    "event_id": evt, "due_at": (now(conn) + timedelta(days=2)).isoformat()}, "c1")], raw={})
            if self.calls == 2:
                return LLMResponse(content="", tool_calls=[ToolCall("update_task", {
                    "task_id": existing["id"], "due_at": (now(conn) + timedelta(days=2)).isoformat()}, "c2")], raw={})
            return LLMResponse(content="已调整现有任务。", tool_calls=[], raw={})

    llm = ReuseLLM()
    result = orchestrator.run_agent(conn, "AUT-J", trigger_type="event_detected", event_ids=[evt], llm=llm)
    assert result["status"] == "completed", result
    assert conn.execute("SELECT COUNT(*) c FROM tasks WHERE patient_id='AUT-J'").fetchone()["c"] == 1
    second_tools = set(llm.tools_by_call[1])
    assert second_tools <= {"update_task", "respond", "list_tasks"}, second_tools
    assert "create_task" not in second_tools

def test_a5_01_schedule_review_completes_management_event(conn):
    _patient(conn, "A5A")
    evt = _glucose_event(conn, "A5A")
    llm = CapturingLLM([LLMResponse(content="安排正式复评", tool_calls=[ToolCall("schedule_review", {
        "patient_id": "A5A", "event_id": evt, "delay_hours": 48, "reason": "血糖上升需复评"}, "c1")], raw={})])
    result = orchestrator.run_agent(conn, "A5A", trigger_type="event_detected", event_ids=[evt], llm=llm)
    assert result["status"] == "completed", result
    review = conn.execute("SELECT * FROM reviews WHERE patient_id='A5A'").fetchone()
    assert review and review["status"] == "scheduled" and review["event_id"] == evt
    assert conn.execute("SELECT status FROM events WHERE id=?", (evt,)).fetchone()["status"] == "handled"
    assert conn.execute("SELECT COUNT(*) c FROM tasks WHERE patient_id='A5A'").fetchone()["c"] == 0


def test_a5_02_review_only_closes_its_own_event(conn):
    _patient(conn, "A5B")
    evt_a = _glucose_event(conn, "A5B", code="GLUCOSE_RISING")
    evt_b = _glucose_event(conn, "A5B", code="LOW_ACTIVITY", severity="medium")
    llm = CapturingLLM([LLMResponse(content="只处理血糖事件", tool_calls=[ToolCall("schedule_review", {
        "patient_id": "A5B", "event_id": evt_a, "delay_hours": 48}, "c1")], raw={})])
    result = orchestrator.run_agent(conn, "A5B", trigger_type="event_detected", event_ids=[evt_a, evt_b], llm=llm)
    assert result["status"] == "completed", result
    status_a = conn.execute("SELECT status FROM events WHERE id=?", (evt_a,)).fetchone()["status"]
    status_b = conn.execute("SELECT status FROM events WHERE id=?", (evt_b,)).fetchone()["status"]
    assert status_a == "handled" and status_b == "open"


def test_a5_03_existing_task_coverage_via_respond(conn):
    _patient(conn, "A5C")
    evt = _glucose_event(conn, "A5C")
    task, _ = tasks.create_task(conn, "A5C", task_type="confirm_medication", title="核实近3天服药",
                                event_id=evt, due_at=iso(now(conn) + timedelta(days=1)), schedule_review=False)
    llm = CapturingLLM([
        LLMResponse(content="先建任务", tool_calls=[ToolCall("create_task", {
            "patient_id": "A5C", "task_type": "confirm_medication", "title": "核实服药",
            "event_id": evt, "due_at": (now(conn) + timedelta(days=2)).isoformat()}, "c1")], raw={}),
        LLMResponse(content=f"已有任务 {task['id']}（{task['title']}）覆盖本事件，无需重复创建。",
                    tool_calls=[], raw={}),
    ])
    result = orchestrator.run_agent(conn, "A5C", trigger_type="event_detected", event_ids=[evt], llm=llm)
    assert result["status"] == "completed", result
    assert conn.execute("SELECT COUNT(*) c FROM tasks WHERE patient_id='A5C'").fetchone()["c"] == 1
    assert result.get("warnings"), "重复创建被拒应保留 warning"
    assert conn.execute("SELECT status FROM events WHERE id=?", (evt,)).fetchone()["status"] == "handled"


def test_a5_04_unsupported_coverage_claim_is_rejected(conn):
    _patient(conn, "A5D")
    evt = _glucose_event(conn, "A5D")
    tasks.create_task(conn, "A5D", task_type="confirm_medication", title="核实近3天服药",
                      due_at=iso(now(conn) + timedelta(days=1)), schedule_review=False)
    llm = CapturingLLM([
        LLMResponse(content="先建任务", tool_calls=[ToolCall("create_task", {
            "patient_id": "A5D", "task_type": "confirm_medication", "title": "核实服药",
            "due_at": (now(conn) + timedelta(days=2)).isoformat()}, "c1")], raw={}),
        LLMResponse(content="已经处理好了。", tool_calls=[], raw={}),
    ])
    result = orchestrator.run_agent(conn, "A5D", trigger_type="event_detected", event_ids=[evt], llm=llm)
    assert result["status"] == "failed", result
    assert any(r["code"] == "POSTCHECK_MISMATCH" for r in result["rejections"])


def test_a5_05_update_task_closes_only_linked_event(conn):
    _patient(conn, "A5E")
    evt_a = _glucose_event(conn, "A5E", code="GLUCOSE_RISING")
    evt_b = _glucose_event(conn, "A5E", code="LOW_ACTIVITY", severity="medium")
    task, _ = tasks.create_task(conn, "A5E", task_type="confirm_medication", title="核实服药",
                                event_id=evt_a, due_at=iso(now(conn) + timedelta(days=1)), schedule_review=False)
    llm = CapturingLLM([LLMResponse(content="调整已有任务", tool_calls=[ToolCall("update_task", {
        "patient_id": "A5E", "task_id": task["id"],
        "due_at": (now(conn) + timedelta(days=2)).isoformat()}, "c1")], raw={})])
    result = orchestrator.run_agent(conn, "A5E", trigger_type="event_detected", event_ids=[evt_a, evt_b], llm=llm)
    assert result["status"] == "completed", result
    assert conn.execute("SELECT status FROM events WHERE id=?", (evt_a,)).fetchone()["status"] == "handled"
    assert conn.execute("SELECT status FROM events WHERE id=?", (evt_b,)).fetchone()["status"] == "open"


def test_a5_06_read_only_does_not_complete_or_close(conn):
    _patient(conn, "A5F")
    evt = _glucose_event(conn, "A5F")
    llm = CapturingLLM([LLMResponse(content="", tool_calls=[ToolCall("list_tasks", {"patient_id": "A5F"}, "c1")], raw={})])
    result = orchestrator.run_agent(conn, "A5F", trigger_type="event_detected", event_ids=[evt], llm=llm)
    assert result["status"] == "failed", result
    assert conn.execute("SELECT status FROM events WHERE id=?", (evt,)).fetchone()["status"] == "open"


def test_a5_07_parse_only_still_allowed(conn):
    _patient(conn, "A5G")
    llm = CapturingLLM([
        LLMResponse(content="", tool_calls=[ToolCall("parse_constraint", {
            "message": "只解析，不要修改：明天早上8点提醒我测血糖"}, "c1")], raw={}),
        LLMResponse(content="已解析：明天 08:00。", tool_calls=[], raw={}),
    ])
    result = orchestrator.run_agent(conn, "A5G", trigger_type="user_request",
                                    message="只解析，不要修改：明天早上8点提醒我测血糖", llm=llm)
    assert result["status"] == "completed", result

def test_unlinked_update_task_keeps_single_event_open(conn):
    _patient(conn, "B1A")
    evt = _glucose_event(conn, "B1A")
    task, _ = tasks.create_task(conn, "B1A", task_type="record_steps", title="记录步数",
                                event_id=None, due_at=iso(now(conn) + timedelta(days=1)), schedule_review=False)
    llm = CapturingLLM([LLMResponse(content="调整步数任务", tool_calls=[ToolCall("update_task", {
        "patient_id": "B1A", "task_id": task["id"],
        "due_at": (now(conn) + timedelta(days=2)).isoformat()}, "c1")], raw={})])
    result = orchestrator.run_agent(conn, "B1A", trigger_type="event_detected", event_ids=[evt], llm=llm)
    assert result["status"] == "completed", result
    assert conn.execute("SELECT status FROM events WHERE id=?", (evt,)).fetchone()["status"] == "open"


def test_unlinked_schedule_review_keeps_single_event_open(conn):
    _patient(conn, "B1B")
    evt = _glucose_event(conn, "B1B")
    task, _ = tasks.create_task(conn, "B1B", task_type="record_steps", title="记录步数",
                                event_id=None, due_at=iso(now(conn) + timedelta(days=1)), schedule_review=False)
    llm = CapturingLLM([LLMResponse(content="安排复评", tool_calls=[ToolCall("schedule_review", {
        "patient_id": "B1B", "task_id": task["id"], "delay_hours": 24}, "c1")], raw={})])
    result = orchestrator.run_agent(conn, "B1B", trigger_type="event_detected", event_ids=[evt], llm=llm)
    assert result["status"] == "completed", result
    assert conn.execute("SELECT status FROM events WHERE id=?", (evt,)).fetchone()["status"] == "open"


def test_linked_update_task_closes_single_event(conn):
    _patient(conn, "B1C")
    evt = _glucose_event(conn, "B1C")
    task, _ = tasks.create_task(conn, "B1C", task_type="record_glucose", title="记录",
                                event_id=evt, due_at=iso(now(conn) + timedelta(days=1)), schedule_review=False)
    llm = CapturingLLM([LLMResponse(content="调整任务", tool_calls=[ToolCall("update_task", {
        "patient_id": "B1C", "task_id": task["id"],
        "due_at": (now(conn) + timedelta(days=2)).isoformat()}, "c1")], raw={})])
    result = orchestrator.run_agent(conn, "B1C", trigger_type="event_detected", event_ids=[evt], llm=llm)
    assert conn.execute("SELECT status FROM events WHERE id=?", (evt,)).fetchone()["status"] == "handled"


def test_unresolved_duplicate_warning_stays_unresolved(conn):
    _patient(conn, "B1D")
    evt = _glucose_event(conn, "B1D")
    tasks.create_task(conn, "B1D", task_type="confirm_medication", title="核实服药",
                      due_at=iso(now(conn) + timedelta(days=1)), schedule_review=False)
    llm = CapturingLLM([
        LLMResponse(content="先建任务", tool_calls=[ToolCall("create_task", {
            "patient_id": "B1D", "task_type": "confirm_medication", "title": "核实服药",
            "due_at": (now(conn) + timedelta(days=2)).isoformat()}, "c1")], raw={}),
        LLMResponse(content="已经处理好了。", tool_calls=[], raw={}),
    ])
    result = orchestrator.run_agent(conn, "B1D", trigger_type="event_detected", event_ids=[evt], llm=llm)
    assert result["status"] == "failed", result
    warnings = [w for w in result.get("warnings", []) if w.get("code") == "DUPLICATE_TASK"]
    assert warnings and warnings[0]["resolved"] is False


def test_resolved_duplicate_warning_after_update(conn):
    _patient(conn, "B1E")
    evt = _glucose_event(conn, "B1E")
    existing, _ = tasks.create_task(conn, "B1E", task_type="confirm_medication", title="核实服药",
                                    due_at=iso(now(conn) + timedelta(days=1)), schedule_review=False)
    llm = CapturingLLM([
        LLMResponse(content="先建任务", tool_calls=[ToolCall("create_task", {
            "patient_id": "B1E", "task_type": "confirm_medication", "title": "核实服药",
            "due_at": (now(conn) + timedelta(days=2)).isoformat()}, "c1")], raw={}),
        LLMResponse(content="改为调整已有任务", tool_calls=[ToolCall("update_task", {
            "patient_id": "B1E", "task_id": existing["id"],
            "due_at": (now(conn) + timedelta(days=2)).isoformat()}, "c2")], raw={}),
    ])
    result = orchestrator.run_agent(conn, "B1E", trigger_type="event_detected", event_ids=[evt], llm=llm)
    assert result["status"] == "completed", result
    warnings = [w for w in result.get("warnings", []) if w.get("code") == "DUPLICATE_TASK"]
    assert warnings and warnings[0]["resolved"] is True

def test_review_only_request_does_not_create_task(conn):
    _patient(conn, "V31A")
    evt = _glucose_event(conn, "V31A")
    llm = CapturingLLM([LLMResponse(content="安排复评", tool_calls=[
        ToolCall("schedule_review", {"patient_id": "V31A", "event_id": evt, "delay_hours": 48}, "c1"),
        ToolCall("create_task", {"patient_id": "V31A", "task_type": "record_verification",
                                 "title": "核实近7天记录", "event_id": evt,
                                 "due_at": (now(conn) + timedelta(days=1)).isoformat()}, "c2"),
    ], raw={})])
    result = orchestrator.run_agent(conn, "V31A", trigger_type="event_detected", event_ids=[evt],
                                    message="请安排一次正式复评，并说明依据。", llm=llm)
    assert result["status"] == "completed", result
    assert conn.execute("SELECT COUNT(*) c FROM tasks WHERE patient_id='V31A'").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM reviews WHERE patient_id='V31A'").fetchone()["c"] == 1
    assert any(s["code"] == "TOOL_NOT_ALLOWED" for s in steps(conn, result["run_id"]))


def test_task_request_still_allows_create_task(conn):
    _patient(conn, "V31B")
    evt = _glucose_event(conn, "V31B")
    llm = CapturingLLM([LLMResponse(content="创建任务", tool_calls=[ToolCall("create_task", {
        "patient_id": "V31B", "task_type": "record_glucose", "title": "补录血糖",
        "event_id": evt, "due_at": (now(conn) + timedelta(days=1)).isoformat()}, "c1")], raw={})])
    result = orchestrator.run_agent(conn, "V31B", trigger_type="event_detected", event_ids=[evt],
                                    message="帮我建一个记录血糖的任务，并安排复评。", llm=llm)
    assert conn.execute("SELECT COUNT(*) c FROM tasks WHERE patient_id='V31B'").fetchone()["c"] == 1


def test_schedule_review_without_scope_uses_current_event(conn):
    _patient(conn, "V31C")
    evt = _glucose_event(conn, "V31C")
    tasks.create_task(conn, "V31C", task_type="confirm_medication", title="核实服药",
                      due_at=iso(now(conn) + timedelta(days=1)), schedule_review=False)
    llm = CapturingLLM([LLMResponse(content="安排复评", tool_calls=[ToolCall("schedule_review", {
        "patient_id": "V31C", "delay_hours": 24}, "c1")], raw={})])
    result = orchestrator.run_agent(conn, "V31C", trigger_type="event_detected", event_ids=[evt], llm=llm)
    assert result["status"] == "completed", result
    review = conn.execute("SELECT * FROM reviews WHERE patient_id='V31C'").fetchone()
    assert review and review["event_id"] == evt


def test_r09_different_task_type_is_allowed_with_existing_task(conn):
    _patient(conn, "V31D")
    evt = _glucose_event(conn, "V31D")
    tasks.create_task(conn, "V31D", task_type="confirm_medication", title="核实服药",
                      event_id=evt, due_at=iso(now(conn) + timedelta(days=1)), schedule_review=False)
    llm = CapturingLLM([LLMResponse(content="缺血糖记录，新建任务", tool_calls=[ToolCall("create_task", {
        "patient_id": "V31D", "task_type": "record_glucose", "title": "补录空腹血糖",
        "event_id": evt, "due_at": (now(conn) + timedelta(days=1)).isoformat()}, "c1")], raw={})])
    result = orchestrator.run_agent(conn, "V31D", trigger_type="event_detected", event_ids=[evt],
                                    message="我的记录有缺项，请按我现有的任务帮我处理，不要重复建任务。", llm=llm)
    assert result["status"] == "completed", result
    assert conn.execute("SELECT COUNT(*) c FROM tasks WHERE patient_id='V31D'").fetchone()["c"] == 2
