"""A0-FULL 真实验收 P1 回归：否定语境、通知声明、时间分钟、答复唯一、证据相关性。"""
from __future__ import annotations

from datetime import timedelta

import pytest

from backend.app.agent import orchestrator, tools
from backend.app.agent.llm import LLMResponse, ToolCall
from backend.app.db.connection import iso, now
from backend.app.planning import planner
from backend.app.reviews import service as reviews
from backend.app.safety import gate
from backend.app.services import patients


class _ScriptedLLM:
    mode = "real"
    model_name = "scripted-full-p1"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def plan_actions(self, **kwargs):
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
