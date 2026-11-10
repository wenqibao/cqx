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
    from backend.app.services import records

    for kind, value in (("medication_taken", 1), ("steps", 6000)):
        records.add_record(conn, pid, {"kind": kind, "value": value, "recorded_at": iso(now(conn))})


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

def _event(conn, pid="MQ1", code="GLUCOSE_RISING", *, event_id=None):
    event_id = event_id or f"EVT-{pid}"
    conn.execute(
        "INSERT INTO events(id,patient_id,code,severity,status,message,evidence,dedupe_key,source_record_id,detected_at) "
        "VALUES(?,?,?,'high','open','x','{}',?,NULL,?)",
        (event_id, pid, code, f"{pid}:{code}:x", iso(now(conn))),
    )
    return event_id


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

MIXED_TEXTS = [
    "遇到调整用药需求时引导就医。把降糖药停掉。",
    "把降糖药停掉。遇到调整用药需求时引导就医。",
    "遇到调整用药需求时引导就医，并把降糖药停掉。",
    "如出现调整剂量需求请联系医生。建议减少二甲双胍剂量。",
]


@pytest.mark.parametrize("text", MIXED_TEXTS)
def test_mixed_referral_and_instruction_is_blocked(text):
    assert gate.check_text(text, generated=True)["allowed"] is False
    assert gate.check_text(text)["allowed"] is False


def test_notification_body_with_mixed_text_is_rejected_before_write(conn):
    _patient(conn, "MX1")
    checked = validators.validate_plan(conn, patient_id="MX1", evidence=[], plan={"actions": [{
        "tool": "create_notification",
        "args": {"patient_id": "MX1", "kind": "info", "title": "提醒",
                 "body": "遇到调整用药需求时引导就医。把降糖药停掉。"},
    }]})
    assert any(r["code"] == "FORBIDDEN_ACTION" for r in checked["rejections"])
    assert conn.execute("SELECT COUNT(*) c FROM notifications").fetchone()["c"] == 0


def test_alias_task_type_is_deduped_before_write(conn):
    _patient(conn, "AL1")
    tasks.create_task(conn, "AL1", task_type="record_glucose", title="已有任务",
                      due_at=iso(now(conn) + timedelta(days=1)), schedule_review=False)
    llm = CaptureLLM([
        LLMResponse(content="", tool_calls=[ToolCall("create_task", {
            "patient_id": "AL1", "task_type": "record_reminder", "title": "别名任务",
            "due_at": (now(conn) + timedelta(days=3)).isoformat()}, "c1")], raw={}),
        LLMResponse(content="已沿用现有任务。", tool_calls=[], raw={}),
    ])
    result = orchestrator.run_agent(conn, "AL1", trigger_type="request", message="帮我建个记录任务", llm=llm)
    assert conn.execute("SELECT COUNT(*) c FROM tasks WHERE patient_id='AL1'").fetchone()["c"] == 1
    assert not [r for r in result["rejections"] if r["code"] == "POSTCHECK_MISMATCH"]
    assert any(s["code"] == "DUPLICATE_TASK" for s in
               conn.execute("SELECT code FROM agent_steps WHERE run_id=?", (result["run_id"],)).fetchall())


def test_unknown_task_type_writes_nothing(conn):
    _patient(conn, "AL2")
    llm = CaptureLLM([LLMResponse(content="", tool_calls=[ToolCall("create_task", {
        "patient_id": "AL2", "task_type": "made_up_type", "title": "x",
        "due_at": (now(conn) + timedelta(days=1)).isoformat()}, "c1")], raw={})])
    result = orchestrator.run_agent(conn, "AL2", trigger_type="request", message="建个任务", llm=llm)
    assert conn.execute("SELECT COUNT(*) c FROM tasks WHERE patient_id='AL2'").fetchone()["c"] == 0
    assert any(r["code"] in ("INVALID_TASK_TYPE", "TOOL_EXECUTION_FAILED") for r in result["rejections"])

def test_missing_required_field_triggers_question_without_adherence_goals(conn):
    patients.create_patient(conn, {"id": "MQ3", "name": "MQ3", "age": 55, "duration_years": 6,
                                   "goals": ["保持日常记录稳定"]})
    evt = _event(conn, "MQ3")
    llm = CaptureLLM([LLMResponse(content="", tool_calls=[ToolCall("create_task", {
        "patient_id": "MQ3", "task_type": "record_glucose", "title": "补录血糖",
        "event_id": evt, "due_at": (now(conn) + timedelta(days=1)).isoformat()}, "c1")], raw={}),
        LLMResponse(content="已创建补录任务。", tool_calls=[], raw={})])
    result = orchestrator.run_agent(conn, "MQ3", trigger_type="event_detected", event_ids=[evt], llm=llm)
    assert result["status"] == "waiting_user", result
    question = conn.execute("SELECT * FROM questions WHERE patient_id='MQ3' AND status='waiting'").fetchone()
    assert question and question["target_field"] == "medication_taken"

B10_TEXT = "请核实过去一周有无漏服、漏打或停药的情况。"
B22_TEXT = "核实是否按时服药，有无漏服或自行停药。"
R07_TEXT = "漏服或自行调整剂量会影响血糖趋势，请如实记录。"
B02_TEXT = "关于胰岛素剂量，请咨询内分泌科医生。"


@pytest.mark.parametrize("text", [B10_TEXT, B22_TEXT, R07_TEXT])
def test_retrospective_verification_is_allowed(text):
    assert gate.check_text(text, generated=True)["allowed"] is True


def test_generated_referral_reference_is_allowed():
    assert gate.check_text(B02_TEXT, generated=True)["allowed"] is True


@pytest.mark.parametrize("text", [
    "请把降糖药停掉。",
    "建议减少二甲双胍剂量。",
    "您有没有停过药？",
    "是否要停药？",
])
def test_instruction_and_inquiry_are_still_blocked(text):
    assert gate.check_text(text, generated=True)["allowed"] is False


def test_ask_user_verification_text_is_not_blocked(conn):
    _patient(conn, "V33A")
    llm = CaptureLLM([
        LLMResponse(content="", tool_calls=[ToolCall("ask_user", {
            "patient_id": "V33A", "question": B10_TEXT, "target_field": "medication_taken"}, "c1")], raw={}),
    ])
    result = orchestrator.run_agent(conn, "V33A", trigger_type="request",
                                    message="核实一下我最近的服药情况", llm=llm)
    assert result["status"] == "waiting_user", result
    assert not [r for r in result["rejections"] if r["code"] == "FORBIDDEN_ACTION"]


def test_respond_summary_does_not_consume_action_budget(conn):
    _patient(conn, "V33B")
    responses = []
    for round_index in range(3):
        calls = [ToolCall("create_notification", {
            "patient_id": "V33B", "title": f"提醒{round_index * 3 + i}",
            "body": f"内容{round_index * 3 + i}"}, f"c{round_index * 3 + i}") for i in range(3)]
        if round_index == 2:
            calls = calls[:2] + [ToolCall("respond", {
                "patient_id": "V33B", "text": "已创建提醒并说明情况。"}, "c9")]
        responses.append(LLMResponse(content="", tool_calls=calls, raw={}))
    llm = CaptureLLM(responses)
    result = orchestrator.run_agent(conn, "V33B", trigger_type="request", message="给我一些提醒", llm=llm)
    assert result["status"] == "completed", result
    assert conn.execute("SELECT COUNT(*) c FROM notifications WHERE patient_id='V33B'").fetchone()["c"] == 8
    assert not [r for r in result["rejections"] if r["code"] == "TOO_MANY_ACTIONS"]

@pytest.mark.parametrize("text", [
    "核实过去一周有无漏服，把降糖药停掉。",
    "核实过去一周有无漏服，停药。",
    "核实是否按时服药，建议减少二甲双胍剂量。",
])
def test_same_sentence_comma_mixed_is_blocked(text):
    assert gate.check_text(text, generated=True)["allowed"] is False
    assert gate.check_text(text)["allowed"] is False


def test_continuation_after_comma_keeps_verification():
    assert gate.check_text("核实是否按时服药，有无漏服或自行停药。", generated=True)["allowed"] is True


def _review_setup(conn, pid="RV1"):
    _patient(conn, pid)
    evt = _event(conn, pid)
    from backend.app.reviews import service as reviews

    review = reviews.schedule_review(conn, pid, event_id=evt, delay_hours=24)
    return evt, review


def test_referencing_existing_review_is_not_a_false_claim(conn):
    evt, review = _review_setup(conn)
    llm = CaptureLLM([LLMResponse(content="",
        tool_calls=[ToolCall("respond", {"patient_id": "RV1",
                                         "text": f"沿用之前安排的复评 {review['id']}，请按计划记录。"}, "c1")], raw={})])
    result = orchestrator.run_agent(conn, "RV1", trigger_type="answer_received", message="记不清", llm=llm)
    assert result["status"] == "completed", result
    assert not [r for r in result["rejections"] if r["code"] == "POSTCHECK_MISMATCH"]
    steps = conn.execute("SELECT kind FROM agent_steps WHERE run_id=?", (result["run_id"],)).fetchall()
    assert any(row["kind"] == "review_reference" for row in steps)


def test_fabricated_review_claim_is_rejected(conn):
    _patient(conn, "RV2")
    llm = CaptureLLM([LLMResponse(content="",
        tool_calls=[ToolCall("respond", {"patient_id": "RV2", "text": "已经创建了复评，请放心。"}, "c1")], raw={})])
    result = orchestrator.run_agent(conn, "RV2", trigger_type="answer_received", message="记不清", llm=llm)
    assert any(r["code"] == "POSTCHECK_MISMATCH" for r in result["rejections"])


def test_resume_does_not_reask_same_field(conn):
    patients.create_patient(conn, {"id": "RV3", "name": "RV3", "age": 60, "duration_years": 5, "goals": ["稳定"]})
    evt = _event(conn, "RV3")
    from backend.app.reviews import service as reviews

    reviews.schedule_review(conn, "RV3", event_id=evt, delay_hours=24)
    llm = CaptureLLM([LLMResponse(content="",
        tool_calls=[ToolCall("respond", {"patient_id": "RV3", "text": "已按原计划继续观察。"}, "c1")], raw={})])
    result = orchestrator.run_agent(conn, "RV3", trigger_type="answer_received", message="记不清", llm=llm)
    assert conn.execute("SELECT COUNT(*) c FROM questions WHERE patient_id='RV3' AND status='waiting'").fetchone()["c"] == 0

@pytest.mark.parametrize("text", [
    "核实过去一周有无漏服，建议减少剂量。",
    "建议减少剂量。",
    "可以考虑停用药物。",
])
def test_omitted_drug_dose_change_is_blocked(text):
    assert gate.check_text(text)['allowed'] is False


def test_educational_dose_statement_is_allowed():
    assert gate.check_text("调整剂量会影响血糖趋势。")['allowed'] is True


MIXED_VERIFICATION = "核实既往用药记录后今天起停药。"


@pytest.mark.parametrize("text", [
    MIXED_VERIFICATION,
    "今天起停药并核实既往用药记录。",
    "核实既往用药记录，然后停药。",
    "核实既往用药记录。今天起停药。",
    "核实过去一周有无漏服并停药。",
    "确认既往记录后降低剂量。",
    "核实既往用药记录后不必等待直接停药。",
    "如果需要核实既往记录后停药并咨询医生。",
])
def test_verification_does_not_cover_a_separate_instruction(text):
    assert not gate.check_text(text)["allowed"]
    assert not gate.check_text(text, generated=True)["allowed"]


@pytest.mark.parametrize("text", [
    "核实近7天是否按医嘱服药、有无漏服或自行停药，仅做记录核实。",
    "近一周有没有漏服、停药的情况？",
    "如果需要调整用药，请联系医生。",
])
def test_matched_verification_and_referral_remain_allowed(text):
    assert gate.check_text(text, generated=True)["allowed"]


def test_mixed_verification_input_is_blocked_before_model(client, conn, monkeypatch):
    _patient(conn, "A035")
    model = CaptureLLM([LLMResponse(content="", tool_calls=[], raw={})])
    monkeypatch.setattr(orchestrator.llm_module, "get_llm", lambda: model)

    run = client.post("/api/patients/A035/agent/runs", json={"message": MIXED_VERIFICATION}).json()

    assert run["status"] == "blocked", run
    assert model.calls == 0


@pytest.mark.parametrize(("tool", "field", "args", "table"), [
    ("create_notification", "body", {"title": "合成提醒"}, "notifications"),
    ("create_task", "description", {"task_type": "record_glucose", "title": "核实记录"}, "tasks"),
    ("ask_user", "question", {"target_field": "medication_taken"}, "questions"),
    ("respond", "text", {}, None),
])
def test_mixed_generated_verification_does_not_reach_patient(
        client, conn, monkeypatch, tool, field, args, table):
    _patient(conn, "A035")
    payload = {"patient_id": "A035", **args, field: MIXED_VERIFICATION}
    if tool == "create_task":
        payload["due_at"] = iso(now(conn) + timedelta(days=1))
    model = CaptureLLM([LLMResponse(content="", tool_calls=[ToolCall(tool, payload, "mixed")], raw={})])
    monkeypatch.setattr(orchestrator.llm_module, "get_llm", lambda: model)

    run = client.post("/api/patients/A035/agent/runs", json={"message": "请核对健康记录"}).json()

    assert any(r["code"] == "FORBIDDEN_ACTION" for r in run["rejections"]), run
    assert MIXED_VERIFICATION not in run["responses"]
    if table:
        assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE patient_id='A035'").fetchone()[0] == 0
    audit = client.get("/api/system/audit").json()
    assert audit["forbidden_executed"] == 0
    assert audit["blocked_total"] > 0


def _review_reply(conn, text, *, pid="RV1", event_ids=None):
    model = CaptureLLM([LLMResponse(content="", tool_calls=[
        ToolCall("respond", {"patient_id": pid, "text": text}, "claim"),
    ], raw={})])
    return orchestrator.run_agent(conn, pid, trigger_type="answer_received",
                                  message="记不清", event_ids=event_ids, llm=model)


@pytest.mark.parametrize("reply", [
    "此前已核对您的记录。本轮已安排新的复评，时间为明天上午。",
    "此前已核对您的记录并已安排新的复评。",
    "沿用此前已安排的复评。本轮又已创建新的复评。",
    "沿用此前已安排的复评，时间为后天。",
    "沿用此前已安排的复评，后天上午进行。",
    "沿用之前安排的复评 REV-unknown。",
    "沿用原计划，同时已改期复评。",
    "保留既有复评并已安排另一条复评。",
    "沿用患者P002的既有复评。",
])
def test_review_reference_cannot_cover_unverified_changes(conn, reply):
    from backend.app.audit import trace

    evt, review = _review_setup(conn)
    result = _review_reply(conn, reply, event_ids=[evt])
    assert any(r["code"] == "POSTCHECK_MISMATCH" and r["tool"] == "schedule_review"
               for r in result["rejections"]), result
    assert reply not in result["responses"]
    assert not any(a["tool"] == "respond" and a["ok"] for a in result["actions"])
    step = next(s for s in trace.steps(conn, result["run_id"]) if s["kind"] == "tool_result")
    assert step["status"] == "failed" and not step["payload"]["post_check"]["ok"]
    assert step["payload"]["result"]["text"] == reply
    assert conn.execute("SELECT id FROM reviews").fetchone()["id"] == review["id"]
    assert conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 1


def test_review_reference_checks_exact_time(conn):
    evt, review = _review_setup(conn)
    reply = f"沿用此前已安排的复评 {review['id']}，时间为{review['scheduled_for']}。"
    result = _review_reply(conn, reply, event_ids=[evt])
    assert result["status"] == "completed", result
    assert result["responses"] == [reply]


@pytest.mark.parametrize("scope", ["other_patient", "other_event", "expired"])
def test_review_reference_requires_current_scope_and_future_time(conn, scope):
    from backend.app.reviews import service as reviews

    _patient(conn, "RV1")
    event = _event(conn, "RV1")
    review_event, review_patient = event, "RV1"
    if scope == "other_patient":
        _patient(conn, "RV2")
        review_patient = "RV2"
        review_event = _event(conn, "RV2")
    if scope == "other_event":
        review_event = _event(conn, "RV1", code="ADHERENCE_DROP", event_id="EVT-RV1-other")
    review = reviews.schedule_review(conn, review_patient, event_id=review_event, delay_hours=24)
    if scope == "expired":
        conn.execute("UPDATE reviews SET scheduled_for=? WHERE id=?",
                     (iso(now(conn) - timedelta(hours=1)), review["id"]))

    reply = f"沿用此前已安排的复评 {review['id']}。"
    result = _review_reply(conn, reply, event_ids=[event])

    assert any(r["code"] == "POSTCHECK_MISMATCH" and r["tool"] == "schedule_review"
               for r in result["rejections"]), result
    assert reply not in result["responses"]


def test_successful_review_tool_only_supports_its_persisted_time(conn):
    evt, review = _review_setup(conn)
    executed = [{"tool": "schedule_review", "ok": True, "result": {"review_id": review["id"]}}]
    matches = f"本轮已安排复评 {review['id']}，时间为{review['scheduled_for']}。"
    assert not orchestrator._unsupported_claims(matches, executed, conn=conn, patient_id="RV1", event_ids=[evt])
    wrong = f"本轮已安排复评 {review['id']}，时间为后天。"
    rejections = orchestrator._unsupported_claims(wrong, executed, conn=conn, patient_id="RV1", event_ids=[evt])
    assert [r["code"] for r in rejections] == ["POSTCHECK_MISMATCH"]


def test_b11_reference_records_each_review_and_does_not_reask(conn):
    from backend.app.db.connection import loads

    _patient(conn, "RV1")
    evt = _event(conn, "RV1")
    for task_type in ("record_glucose", "confirm_medication"):
        tasks.create_task(conn, "RV1", task_type=task_type, title="核实记录",
                          event_id=evt, due_at=iso(now(conn) + timedelta(days=2)))
    expected = {row["id"] for row in conn.execute("SELECT id FROM reviews WHERE event_id=?", (evt,))}
    assert len(expected) == 2
    result = _review_reply(conn, "现有两项待办已覆盖本次事件。两项都已安排到期复评，届时会结合新记录再判断。",
                           event_ids=[evt])

    assert result["status"] == "completed", result
    assert not result["rejections"]
    assert conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 0
    rows = conn.execute("SELECT payload FROM agent_steps WHERE run_id=? AND kind='review_reference'",
                        (result["run_id"],)).fetchall()
    assert {loads(row["payload"])["review_id"] for row in rows} == expected
