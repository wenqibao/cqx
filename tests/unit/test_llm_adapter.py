"""real 模式适配器测试：用 httpx MockTransport 验证请求/响应解析，不访问真实网络。

说明：这里不证明"真实模型可用"，只证明 real 模式代码路径可以正确处理
OpenAI 兼容的 tool calling 响应，且配置缺失时不会静默降级为 mock。
"""
from __future__ import annotations

import httpx
import pytest

from backend.app.agent import llm as llm_module


def _client(payload: dict, captured: dict) -> llm_module.OpenAICompatLLM:
    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.read().decode("utf-8")
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json=payload)

    return llm_module.OpenAICompatLLM(
        "https://example.invalid/v1", "test-key", "test-model", transport=httpx.MockTransport(handler)
    )


def test_parses_tool_calls():
    payload = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "create_task",
                                "arguments": '{"task_type": "record_glucose", "title": "记录血糖"}',
                            },
                        }
                    ],
                }
            }
        ]
    }
    captured: dict = {}
    resp = _client(payload, captured).plan_actions(system="s", user="u", tools=llm_module.tool_schemas())
    assert resp.tool_calls and resp.tool_calls[0].name == "create_task"
    assert resp.tool_calls[0].arguments["title"] == "记录血糖"
    assert captured["url"].endswith("/chat/completions")
    assert "test-model" in captured["body"]
    assert captured["headers"]["authorization"] == "Bearer test-key"


def test_parses_plain_content():
    payload = {"choices": [{"message": {"content": "请先补录血糖记录。"}}]}
    captured: dict = {}
    resp = _client(payload, captured).plan_actions(system="s", user="u", tools=[])
    assert resp.content.startswith("请先补录")
    assert resp.tool_calls == []


def test_http_error_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream boom")

    client = llm_module.OpenAICompatLLM(
        "https://example.invalid/v1", "k", "m", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(llm_module.LLMRequestError):
        client.plan_actions(system="s", user="u", tools=[])


def test_malformed_response_raises():
    client = llm_module.OpenAICompatLLM(
        "https://example.invalid/v1",
        "k",
        "m",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"oops": True})),
    )
    with pytest.raises(llm_module.LLMRequestError):
        client.plan_actions(system="s", user="u", tools=[])


def test_real_mode_without_config_raises(monkeypatch):
    from backend.app import config

    monkeypatch.setenv("AGENT_LLM_MODE", "real")
    monkeypatch.setenv("AGENT_LLM_BASE_URL", "")
    monkeypatch.setenv("AGENT_LLM_API_KEY", "")
    monkeypatch.setenv("AGENT_LLM_MODEL", "")
    config.reload_config()
    try:
        with pytest.raises(llm_module.LLMConfigError):
            llm_module.get_llm()
    finally:
        config.reload_config()


def test_unknown_mode_raises(monkeypatch):
    from backend.app import config

    monkeypatch.setenv("AGENT_LLM_MODE", "turbo")
    config.reload_config()
    try:
        with pytest.raises(llm_module.LLMConfigError):
            llm_module.get_llm()
    finally:
        config.reload_config()
