"""B1-001：厂商计数必须发生在真实发送层（适配器 + stub transport）。"""
from __future__ import annotations

import json

import httpx
import pytest

from backend.app.agent import vendor_budget
from backend.app.agent.llm import LLMRequestError, OpenAICompatLLM
from backend.app.agent import orchestrator
from backend.app.db.connection import connect
from backend.app.services import patients

CALL = {
    "choices": [{
        "message": {
            "content": None,
            "tool_calls": [{
                "id": "call_1", "type": "function",
                "function": {"name": "respond", "arguments": json.dumps({"patient_id": "VB1", "text": "好的"})},
            }],
        }
    }]
}


def _transport(counter: list[int], *, fail: Exception | None = None):
    def handler(request):
        counter[0] += 1
        if fail:
            raise fail
        return httpx.Response(200, json=CALL)

    return httpx.MockTransport(handler)


def _llm(transport):
    return OpenAICompatLLM(base_url="https://api.deepseek.com", api_key="test-key",
                           model="deepseek-chat", transport=transport)


@pytest.fixture()
def budget(workdir, monkeypatch):
    path = workdir / "ledger.json"
    monkeypatch.setenv("AGENT_VENDOR_LEDGER", str(path))
    monkeypatch.setenv("AGENT_VENDOR_MAX_ATTEMPTS", "16")
    return path


def _count(path):
    return json.loads(path.read_text(encoding="utf-8"))["vendor_http_attempts"]["count"]


def test_each_model_round_is_counted_at_send_layer(budget):
    counter = [0]
    llm = _llm(_transport(counter))
    for _ in range(3):
        llm.plan_actions(system="s", user="u", tools=[])
    assert counter[0] == 3
    assert _count(budget) == 3


def test_attempt_cap_blocks_before_the_17th_send(budget, monkeypatch):
    monkeypatch.setenv("AGENT_VENDOR_MAX_ATTEMPTS", "2")
    counter = [0]
    llm = _llm(_transport(counter))
    llm.plan_actions(system="s", user="u", tools=[])
    llm.plan_actions(system="s", user="u", tools=[])
    with pytest.raises(LLMRequestError, match="预算守卫拒绝"):
        llm.plan_actions(system="s", user="u", tools=[])
    assert counter[0] == 2, "第 3 次必须在发送前阻断"
    assert _count(budget) == 2


def test_failed_vendor_attempt_is_counted(budget):
    counter = [0]
    llm = _llm(_transport(counter, fail=httpx.ConnectError("boom")))
    with pytest.raises(LLMRequestError):
        llm.plan_actions(system="s", user="u", tools=[])
    assert counter[0] == 1
    assert _count(budget) == 1


def test_rule_path_does_not_call_vendor_or_ledger(conn, budget):
    patients.create_patient(conn, {"id": "VB2", "name": "VB2", "age": 60, "duration_years": 5, "goals": ["稳定"]})
    counter = [0]
    llm = _llm(_transport(counter))
    result = orchestrator.run_agent(conn, "VB2", trigger_type="user_request",
                                    message="请把胰岛素改成早上多打两单位", llm=llm)
    assert result["status"] == "blocked"
    assert counter[0] == 0
    assert not budget.exists() or _count(budget) == 0


def test_corrupt_ledger_blocks_before_send(budget):
    budget.write_text("{}", encoding="utf-8")
    counter = [0]
    llm = _llm(_transport(counter))
    with pytest.raises(LLMRequestError, match="预算守卫拒绝"):
        llm.plan_actions(system="s", user="u", tools=[])
    assert counter[0] == 0
    assert budget.read_text(encoding="utf-8") == "{}", "非法账本不得被覆盖"


def test_negative_count_blocks_before_send(budget):
    data = vendor_budget.default_ledger()
    data["vendor_http_attempts"]["count"] = -1
    budget.write_text(json.dumps(data), encoding="utf-8")
    counter = [0]
    llm = _llm(_transport(counter))
    with pytest.raises(LLMRequestError, match="负数"):
        llm.plan_actions(system="s", user="u", tools=[])
    assert counter[0] == 0


def test_snapshot_reports_usage(budget):
    counter = [0]
    llm = _llm(_transport(counter))
    llm.plan_actions(system="s", user="u", tools=[])
    snapshot = vendor_budget.snapshot()
    assert snapshot["enabled"] is True and snapshot["used"] == 1
    assert snapshot["limit"] == 16


def test_budget_disabled_is_noop(monkeypatch, workdir):
    monkeypatch.delenv("AGENT_VENDOR_LEDGER", raising=False)
    assert vendor_budget.reserve() is None
    assert vendor_budget.snapshot()["enabled"] is False
