"""模型接入层（F08）。

两种模式，运行记录中必须如实标注：
- mock：确定性策略规划器（本机无模型调用，可离线复现）。运行记录 llm_mode=mock。
- real：OpenAI 兼容 /chat/completions 端点，支持原生 tool calling。运行记录 llm_mode=real。

禁止把 mock 结果伪装成真实模型输出：所有 run 都会写入 llm_mode，API/CLI/报告都会透出该字段。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

from backend.app.config import settings


class LLMConfigError(RuntimeError):
    """real 模式配置缺失时抛出，绝不静默降级为 mock。"""


class LLMRequestError(RuntimeError):
    pass


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    id: str = ""


@dataclass
class LLMResponse:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


class LLMClient:
    mode: str = "mock"
    model_name: str = "deterministic-planner"

    def plan_actions(
        self,
        *,
        system: str,
        user: str,
        tools: list[dict[str, Any]],
        extra_messages: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        raise NotImplementedError


class DeterministicPlannerLLM(LLMClient):
    """离线确定性策略：真正执行的是 planner 的规则推导，不冒充模型输出。"""

    mode = "mock"
    model_name = "deterministic-planner"

    def plan_actions(
        self,
        *,
        system: str,
        user: str,
        tools: list[dict[str, Any]],
        extra_messages: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        raise NotImplementedError("mock 模式由 orchestrator 直接调用 planning.planner，不经过模型")


class OpenAICompatLLM(LLMClient):
    mode = "real"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model
        self.timeout = timeout
        self.transport = transport

    def _payload(
        self, system: str, user: str, tools: list[dict[str, Any]], extra_messages: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        if extra_messages:
            messages.extend(extra_messages)
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": 0,
        }
        # DeepSeek 默认思考模式要求回传 reasoning_content；当前循环使用非思考协议。
        if urlparse(self.base_url).hostname == "api.deepseek.com":
            payload["thinking"] = {"type": "disabled"}
        if tools:
            payload["tools"] = [{"type": "function", "function": t} for t in tools]
            payload["tool_choice"] = "auto"
        return payload

    def plan_actions(
        self,
        *,
        system: str,
        user: str,
        tools: list[dict[str, Any]],
        extra_messages: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        # 厂商请求预算：在真正发出 HTTP 前预占，失败/超时同样计数
        from backend.app.agent import vendor_budget

        try:
            vendor_budget.reserve()
        except vendor_budget.VendorBudgetError as exc:
            raise LLMRequestError(f"厂商预算守卫拒绝: {exc}") from exc
        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                resp = client.post(url, headers=headers, json=self._payload(system, user, tools, extra_messages))
        except httpx.HTTPError as exc:
            raise LLMRequestError(f"模型请求失败: {str(exc).replace(self.api_key, '[REDACTED]')}") from exc
        if resp.status_code >= 400:
            detail = resp.text.replace(self.api_key, "[REDACTED]")
            raise LLMRequestError(f"模型返回 {resp.status_code}: {detail[:300]}")
        try:
            return self.parse_response(resp.json())
        except (ValueError, TypeError, AttributeError) as exc:
            raise LLMRequestError("模型响应不是有效的工具调用结构") from exc

    @staticmethod
    def parse_response(data: dict[str, Any]) -> LLMResponse:
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMRequestError(f"模型响应结构异常: {json.dumps(data)[:300]}") from exc
        calls: list[ToolCall] = []
        for item in message.get("tool_calls") or []:
            fn = item.get("function") or {}
            raw_args = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except (ValueError, TypeError):
                args = {"_raw": raw_args}
            calls.append(ToolCall(name=fn.get("name", ""), arguments=args, id=item.get("id", "")))
        return LLMResponse(content=message.get("content") or "", tool_calls=calls, raw=data)


def get_llm() -> LLMClient:
    cfg = settings()
    mode = (cfg.llm_mode or "mock").lower()
    if mode == "mock":
        return DeterministicPlannerLLM()
    if mode == "real":
        missing = [k for k, v in (("AGENT_LLM_BASE_URL", cfg.llm_base_url), ("AGENT_LLM_API_KEY", cfg.llm_api_key), ("AGENT_LLM_MODEL", cfg.llm_model)) if not v]
        if missing:
            raise LLMConfigError(
                "AGENT_LLM_MODE=real 但缺少配置: " + ", ".join(missing) + "。请补全 .env，或改回 mock 模式。"
            )
        return OpenAICompatLLM(cfg.llm_base_url, cfg.llm_api_key, cfg.llm_model)
    raise LLMConfigError(f"未知的 AGENT_LLM_MODE: {cfg.llm_mode}（仅支持 mock / real）")


def tool_schemas(only: set[str] | None = None) -> list[dict[str, Any]]:
    from backend.app.agent.tools import TOOL_SPECS

    schemas = []
    for name, spec in TOOL_SPECS.items():
        if only is not None and name not in only:
            continue
        props = {}
        required = []
        for param, ptype in spec["parameters"].items():
            optional = ptype.endswith("?")
            base = ptype.rstrip("?")
            jtype = {"string": "string", "int": "integer", "array": "array", "object": "object", "bool": "boolean"}.get(
                base, "string"
            )
            props[param] = {"type": jtype}
            if jtype == "array":
                props[param]["items"] = {"type": "string"}
            if not optional:
                required.append(param)
        if name == "save_preference":
            from backend.app.memory.preferences import ALLOWED_KINDS, ALLOWED_SOURCES

            props["kind"]["enum"] = sorted(ALLOWED_KINDS)
            props["kind"]["description"] = "偏好类型；时间偏好必须用 preferred_time_window，不要用 note"
            props["value"]["description"] = "preferred_time_window 用 24 小时制 HH:MM（例如 08:00）"
            props["source"]["enum"] = sorted(ALLOWED_SOURCES)
            props["source"]["description"] = "患者明确确认时用 patient_confirmed"
        schemas.append(
            {
                "name": name,
                "description": spec["description"],
                "parameters": {"type": "object", "properties": props, "required": required},
            }
        )
    return schemas
