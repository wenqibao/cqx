"""B12/B17 契约回归：时间偏好 schema 明确；无证据知识问答必须 NO_EVIDENCE。"""
from __future__ import annotations

from backend.app.agent import llm as llm_module
from backend.app.agent import orchestrator
from backend.app.agent.llm import LLMResponse, ToolCall
from backend.app.services import patients


class _ScriptedLLM:
    mode = "real"
    model_name = "scripted-semantics"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def plan_actions(self, **kwargs):
        index = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return self.responses[index]


def test_preference_schema_declares_time_window_and_format():
    schemas = {s["name"]: s for s in llm_module.tool_schemas()}
    pref = schemas["save_preference"]["parameters"]["properties"]
    assert "preferred_time_window" in pref["kind"]["enum"]
    assert "patient_confirmed" in pref["source"]["enum"]
    assert "HH:MM" in pref["value"]["description"]
    assert "note" in pref["kind"]["description"]


def test_no_evidence_question_is_no_evidence_not_waiting_user(conn):
    """模型检索无结果后改用 ask_user，也必须判 NO_EVIDENCE，而不是等待用户。"""
    patients.create_patient(conn, {"id": "B17", "name": "无证据", "age": 60, "duration_years": 5, "goals": ["稳定"]})
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[ToolCall("search_knowledge", {"query": "量子纠缠 超导 能谱"}, "c1")], raw={}),
        LLMResponse(content="", tool_calls=[ToolCall("ask_user", {
            "patient_id": "B17", "question": "您具体想了解哪方面？", "target_field": "note"}, "c2")], raw={}),
        LLMResponse(content="", tool_calls=[], raw={}),
    ])
    result = orchestrator.run_agent(conn, "B17", trigger_type="user_request",
                                    message="量子纠缠和超导材料能谱是什么", llm=llm)
    codes = [r["code"] for r in result["rejections"]]
    assert "NO_EVIDENCE" in codes, result
    assert result["status"] == "failed", result
