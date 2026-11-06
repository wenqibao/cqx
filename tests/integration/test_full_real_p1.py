"""A0-FULL 真实验收 P1 回归：否定语境、通知声明、时间分钟、答复唯一、证据相关性。"""
from __future__ import annotations

from datetime import timedelta

import pytest

from backend.app.agent import orchestrator, tools
from backend.app.agent.llm import LLMResponse, ToolCall
from backend.app.db.connection import iso, now
from backend.app.planning import planner
from backend.app.reviews import service as reviews
from backend.app.safety import gate, validators
from backend.app.services import patients


class _ScriptedLLM:
    mode = "real"
    model_name = "scripted-full-p1"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.seen: list[list[dict]] = []

    def plan_actions(self, *, system=None, user=None, tools=None, extra_messages=None):
        self.seen.append(list(extra_messages or []))
        index = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return self.responses[index]


# ---------- P1-01 否定语境 ----------
def test_patient_negative_constraint_is_allowed():
    text = "请综合处理血糖升高、波动、活动不足和用药记录缺失，但不要更改用药。"
    assert gate.check_text(text)["allowed"] is True
    assert gate.check_text(text, generated=True)["allowed"] is True


def test_generated_avoidance_disclaimer_is_allowed():
    text = "如果测量时出现明显不适，请及时就医，不要自行调整用药或胰岛素剂量。"
    assert gate.check_text(text, generated=True)["allowed"] is True


@pytest.mark.parametrize("text", ["帮我把降糖药停了吧", "请把胰岛素改成早上多打两单位"])
def test_real_intents_still_blocked(text):
    assert gate.check_text(text)["allowed"] is False
    assert gate.check_text(text, generated=True)["allowed"] is False


# ---------- P1-02 通知 vs 任务声明 ----------
def test_notification_claim_maps_to_notification():
    assert orchestrator._claimed_state_changes("已创建一条站内提醒。") == {"create_notification"}
    assert orchestrator._claimed_state_changes("已按你的要求创建站内提醒，没有创建任何健康任务。") == {"create_notification"}
    assert orchestrator._claimed_state_changes("已为你创建任务：明天记录血糖。") == {"create_task"}


def test_notification_run_completes(conn):
    patients.create_patient(conn, {"id": "NT1", "name": "通知", "age": 60, "duration_years": 5, "goals": ["稳定"]})
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[
            ToolCall("create_notification", {"patient_id": "NT1", "title": "记录提醒", "body": "20:00 记录"}, "c1"),
            ToolCall("respond", {"patient_id": "NT1", "text": "已创建一条站内提醒，到时会提示你。"}, "c2"),
        ], raw={}),
    ])
    result = orchestrator.run_agent(conn, "NT1", trigger_type="user_request", message="帮我建个提醒", llm=llm)
    assert result["status"] == "completed", result
    assert not result["rejections"]
    assert conn.execute("SELECT COUNT(*) c FROM notifications WHERE patient_id='NT1'").fetchone()["c"] == 1


# ---------- P1-03 时间解析保留分钟 ----------
@pytest.mark.parametrize("message,hour,minute", [
    ("我唯一可用时间是 20:30。只解析这个约束，不要修改任何任务。", 20, 30),
    ("改成 07:05 记录步数", 7, 5),
    ("晚上 20:00 可以", 20, 0),
])
def test_parse_constraint_keeps_minutes(message, hour, minute):
    parsed = planner.parse_constraint(message)
    assert (parsed["target_hour"], parsed["target_minute"]) == (hour, minute)


# ---------- P1-04 答复恰好一次 ----------
def test_respond_stops_further_rounds(conn):
    patients.create_patient(conn, {"id": "RSP", "name": "回复", "age": 60, "duration_years": 5, "goals": ["稳定"]})
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[ToolCall("respond", {"patient_id": "RSP", "text": "答案一次。"}, "c1")], raw={}),
        LLMResponse(content="答案重复。", tool_calls=[], raw={}),
    ])
    result = orchestrator.run_agent(conn, "RSP", trigger_type="user_request", message="帮我建个提醒", llm=llm)
    assert result["responses"] == ["答案一次。"]


def test_tools_only_run_gets_deterministic_closing(conn):
    patients.create_patient(conn, {"id": "RSP2", "name": "收尾", "age": 60, "duration_years": 5, "goals": ["稳定"]})
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[
            ToolCall("create_task", {"patient_id": "RSP2", "task_type": "record_glucose", "title": "补录",
                                     "due_at": (now() + timedelta(days=1)).isoformat()}, "c1"),
        ], raw={}),
        LLMResponse(content="", tool_calls=[], raw={}),
    ])
    result = orchestrator.run_agent(conn, "RSP2", trigger_type="user_request", message="帮我建个任务", llm=llm)
    assert len(result["responses"]) == 1
    assert "创建任务" in result["responses"][0]


# ---------- P1-05 证据相关性 ----------
def test_entity_mismatch_filters_generic_hits(conn):
    patients.create_patient(conn, {"id": "EV1", "name": "证据", "age": 60, "duration_years": 5, "goals": ["稳定"]})
    ctx = tools.ToolContext(conn, patient_id="EV1", run_id="RUN-TEST")
    result = tools.execute(ctx, "search_knowledge", {"query": "XQZ-999 生物标志物在稳定期 2 型糖尿病中的特异性"})
    assert result["ok"] is True
    assert result["hits"] == []
    assert result["found"] is False


def test_entity_match_keeps_hits(conn):
    patients.create_patient(conn, {"id": "EV2", "name": "证据2", "age": 60, "duration_years": 5, "goals": ["稳定"]})
    hit = [{"doc_id": "KD-001", "chunk_id": "C1", "text": "XQZ-999 是虚构标志物"}]
    assert tools._filter_relevant_hits("XQZ-999 的特异性", hit) == hit


# ---------- P2-02 复评去重 ----------
def test_review_schedule_is_idempotent(conn):
    patients.create_patient(conn, {"id": "RV1", "name": "复评", "age": 60, "duration_years": 5, "goals": ["稳定"]})
    first = reviews.schedule_review(conn, "RV1", task_id="TSK-1", delay_hours=24)
    second = reviews.schedule_review(conn, "RV1", task_id="TSK-1", delay_hours=24)
    assert second.get("duplicate") is True
    assert second["id"] == first["id"]
    total = conn.execute("SELECT COUNT(*) c FROM reviews WHERE patient_id='RV1'").fetchone()["c"]
    assert total == 1

# ---------- B 残余观察项 ----------
def test_no_evidence_stops_further_actions(conn):
    """知识问答无证据后立刻收口：不再执行后续 create_task 等重试动作。"""
    patients.create_patient(conn, {"id": "NE1", "name": "无证据", "age": 60, "duration_years": 5, "goals": ["稳定"]})
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[ToolCall("search_knowledge", {"query": "XQZ-999 生物标志物"}, "c1")], raw={}),
        LLMResponse(content="", tool_calls=[ToolCall("create_task", {
            "patient_id": "NE1", "task_type": "record_glucose", "title": "核实",
            "due_at": (now() + timedelta(days=1)).isoformat()}, "c2")], raw={}),
    ])
    result = orchestrator.run_agent(conn, "NE1", trigger_type="user_request",
                                    message="XQZ-999 在稳定期 2 型糖尿病中的特异性是多少", llm=llm)
    assert result["status"] == "failed"
    assert any(r["code"] == "NO_EVIDENCE" for r in result["rejections"])
    assert conn.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"] == 0, "无证据后不应再执行建任务"
    assert any("没有足够资料" in r for r in result["responses"])
    # 只保留与事实一致的 NO_EVIDENCE，不再叠加"只读无结论"矛盾拒绝
    assert {r["code"] for r in result["rejections"]} == {"NO_EVIDENCE"}, result["rejections"]


def test_past_due_returns_correctable_hint_then_model_retries(conn):
    """过期 due_at 的拒绝结果要带可修正提示，模型能据此重试成功。"""
    patients.create_patient(conn, {"id": "DUE1", "name": "到期", "age": 60, "duration_years": 5, "goals": ["稳定"]})
    past = (now() - timedelta(hours=2)).isoformat()
    future = (now() + timedelta(days=1)).isoformat()
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[ToolCall("create_task", {
            "patient_id": "DUE1", "task_type": "record_glucose", "title": "补录", "due_at": past}, "c1")], raw={}),
        LLMResponse(content="", tool_calls=[ToolCall("create_task", {
            "patient_id": "DUE1", "task_type": "record_glucose", "title": "补录", "due_at": future}, "c2")], raw={}),
        LLMResponse(content="已创建补录任务。", tool_calls=[], raw={}),
    ])
    result = orchestrator.run_agent(conn, "DUE1", trigger_type="user_request", message="帮我建个补录任务", llm=llm)
    # 当前语义：只要发生过拒绝，run 仍记 failed（保守），但模型应能据提示重试成功
    assert any(r["code"] == "INVALID_DUE" for r in result["rejections"])
    assert conn.execute("SELECT COUNT(*) c FROM tasks WHERE patient_id='DUE1'").fetchone()["c"] == 1
    second_round = " ".join(str(m) for m in llm.seen[1])
    assert "INVALID_DUE" in second_round and "hint" in second_round
    # 脱敏后的可修正提示也要留在持久化轨迹里，供技术日志核对
    step = conn.execute("SELECT payload FROM agent_steps WHERE run_id=? AND code='INVALID_DUE' LIMIT 1",
                        (result["run_id"],)).fetchone()
    assert step and "hint" in step["payload"]

# ---------- 发布验收 REL-01 / REL-02 ----------
def test_review_requires_schedule_review_tool(conn):
    """REL-01：'复评'不能用普通任务替代，必须先被引导到 schedule_review。"""
    patients.create_patient(conn, {"id": "REL1", "name": "复评", "age": 60, "duration_years": 5, "goals": ["稳定"]})
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[ToolCall("create_task", {
            "patient_id": "REL1", "task_type": "follow_up_review", "title": "24小时复评",
            "due_at": (now() + timedelta(hours=24)).isoformat()}, "c1")], raw={}),
        LLMResponse(content="", tool_calls=[
            ToolCall("schedule_review", {"patient_id": "REL1", "delay_hours": 24, "reason": "完成任务后复评"}, "c2"),
            ToolCall("respond", {"patient_id": "REL1", "text": "已安排 24 小时复评。"}, "c3"),
        ], raw={}),
    ])
    result = orchestrator.run_agent(conn, "REL1", trigger_type="user_request",
                                    message="完成任务后安排24小时复评", llm=llm)
    assert result["status"] == "completed", result
    assert conn.execute("SELECT COUNT(*) c FROM tasks WHERE patient_id='REL1'").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM reviews WHERE patient_id='REL1'").fetchone()["c"] == 1
    codes = [s["code"] for s in conn.execute(
        "SELECT code FROM agent_steps WHERE run_id=? AND kind='tool_choice'", (result["run_id"],)).fetchall()]
    assert "TOOL_CHOICE_INVALID" in codes


@pytest.mark.parametrize("text", [
    "本任务仅做提醒与核实，不涉及任何改药、停药或剂量调整建议。",
    "目标由患者参与确定，不设医疗性运动处方。",
])
def test_rel02_negated_texts_allowed(text):
    assert gate.check_text(text, generated=True)["allowed"] is True
    assert gate.check_text(text)["allowed"] is True


@pytest.mark.parametrize("text,code", [
    ("开具处方", "PRESCRIPTION"),
    ("建议把降糖药停掉", "CHANGE_MEDICATION"),
    ("不设处方而是开具处方", "PRESCRIPTION"),
])
def test_rel02_real_actions_still_blocked(text, code):
    verdict = gate.check_text(text, generated=True)
    assert verdict["allowed"] is False
    assert verdict["code"] == code

# ---------- REL-02 追加：问诊式询问 ----------
@pytest.mark.parametrize("text", [
    "您最近有没有更改用药方案？",
    "最近是否调整过用药？",
])
def test_question_inquiry_about_medication_is_allowed(text):
    """采集病史的问句不是执行/建议改药。"""
    assert gate.check_text(text, generated=True)["allowed"] is True
    assert gate.check_text(text)["allowed"] is True


@pytest.mark.parametrize("text", [
    "您有没有停过药？",
    "是否要停药？",
    "是否增加胰岛素剂量？",
    "您有没有更改用药方案",
])
def test_question_inquiry_with_protected_words_still_blocked(text):
    assert gate.check_text(text, generated=True)["allowed"] is False

# ---------- REL-02 真实原句（B 提供） ----------
REL02_REASON = "近7天空腹血糖呈上升趋势（均值8.23 mmol/L，最近一次10.5 mmol/L为最高值），同时存在血糖波动事件与用药不依从记录，需专业人员复核血糖趋势与用药情况，并评估是否需要调整监测或治疗方案。系统不提供任何用药调整建议。"
REL02_DESCRIPTION = "系统记录显示最近一次用药记录为未服药，且存在用药不依从事件。请患者核实近7天是否按时按量服药，记录漏服次数与原因。本任务仅做提醒与核实，不涉及任何改药、停药或剂量调整建议。"


@pytest.mark.parametrize("text", [REL02_REASON, REL02_DESCRIPTION])
def test_rel02_real_texts_are_allowed(text):
    assert gate.check_text(text, generated=True)["allowed"] is True
    assert gate.check_text(text)["allowed"] is True


def test_review_reason_is_checked_and_allowed(conn):
    """request_human_review.reason 也走同一安全门，且合规文本放行。"""
    patients.create_patient(conn, {"id": "RV2", "name": "复核", "age": 60, "duration_years": 5, "goals": ["稳定"]})
    action = {"tool": "request_human_review", "args": {"patient_id": "RV2", "reason": REL02_REASON, "severity": "high"}}
    result = validators.validate_plan(conn, patient_id="RV2", plan={"actions": [action]}, state={})
    assert result["ok"] is True, result["rejections"]


@pytest.mark.parametrize("text,code", [
    ("是否需要停药", "CHANGE_MEDICATION"),
    ("是否需要增加胰岛素剂量", "INSULIN_DOSE"),
    ("请把用药方案改成早晚各一次", "CHANGE_MEDICATION"),
    ("评估是否需要停用二甲双胍", "CHANGE_MEDICATION"),
])
def test_conditional_and_real_changes_still_blocked(text, code):
    verdict = gate.check_text(text, generated=True)
    assert verdict["allowed"] is False
    assert verdict["code"] == code


def test_rejection_trace_carries_tool_call_attribution(conn):
    """拒绝轨迹要能定位到具体轮次/工具调用（B 的 index 对不上问题）。"""
    patients.create_patient(conn, {"id": "AT1", "name": "定位", "age": 60, "duration_years": 5, "goals": ["稳定"]})
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[ToolCall("create_task", {
            "patient_id": "AT1", "task_type": "record_glucose", "title": "补录",
            "description": "建议把降糖药停掉", "due_at": (now() + timedelta(days=1)).isoformat()}, "c1")], raw={}),
    ])
    result = orchestrator.run_agent(conn, "AT1", trigger_type="user_request", message="帮我建个任务", llm=llm)
    row = conn.execute("SELECT payload FROM agent_steps WHERE run_id=? AND kind='rejection' LIMIT 1",
                       (result["run_id"],)).fetchone()
    payload = str(row["payload"])
    assert "call_index" in payload and "call_id" in payload and "round" in payload
