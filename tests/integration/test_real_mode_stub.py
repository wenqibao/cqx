"""real 模式端到端验证：用本地 OpenAI 兼容 stub 服务器走完 tool calling → 真实写库。

说明：这验证的是 **real 模式的完整代码路径**（HTTP 请求、tool calling 解析、安全校验、
工具执行、执行后核对、llm_mode 落库），使用的模型端点是一个本地 stub，**不是真实大模型**；
报告与文档中不得据此宣称"真实模型已 smoke test 通过"。
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from backend.app.agent.orchestrator import run_agent
from backend.app.audit.trace import trace
from backend.app.config import reload_config
from backend.app.db.connection import iso, now
from backend.app.services import patients


class _StubHandler(BaseHTTPRequestHandler):
    calls: list[dict] = []
    tool_name = "create_task"

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("content-length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        type(self).calls.append(body)
        has_tool_message = any(m.get("role") == "tool" for m in body.get("messages", []))
        if not has_tool_message:
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
                                        "name": type(self).tool_name,
                                        "arguments": json.dumps(
                                            {
                                                "patient_id": "R001",
                                                "task_type": "record_glucose",
                                                "title": "按医生要求记录空腹血糖",
                                                "due_at": iso(now()),
                                                "priority": 50,
                                            },
                                            ensure_ascii=False,
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        else:
            payload = {"choices": [{"message": {"content": "已创建记录任务，并安排复评。"}}]}
        data = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # 静默
        return


@pytest.fixture()
def stub_server():
    server = HTTPServer(("127.0.0.1", 0), _StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _StubHandler.calls = []
    yield f"http://127.0.0.1:{server.server_port}/v1"
    server.shutdown()
    server.server_close()


def test_real_mode_tool_call_writes_database(conn, stub_server, monkeypatch):
    monkeypatch.setenv("AGENT_LLM_MODE", "real")
    monkeypatch.setenv("AGENT_LLM_BASE_URL", stub_server)
    monkeypatch.setenv("AGENT_LLM_API_KEY", "test-key")
    monkeypatch.setenv("AGENT_LLM_MODEL", "stub-model")
    reload_config()
    try:
        patients.create_patient(conn, {"id": "R001", "name": "real 模式", "age": 55, "duration_years": 4, "goals": ["稳定"]})
        result = run_agent(conn, "R001", trigger_type="user_request", message="请帮我按医生的要求设一个记录任务")
        assert result["llm_mode"] == "real"
        assert result["model"] == "stub-model"
        assert result["status"] in ("completed", "waiting_user")

        tasks = conn.execute("SELECT * FROM tasks WHERE patient_id='R001'").fetchall()
        assert tasks, "模型 tool call 必须真实写入数据库"
        assert tasks[0]["task_type"] == "record_glucose"

        run_row = conn.execute("SELECT * FROM agent_runs WHERE id=?", (result["run_id"],)).fetchone()
        assert run_row["llm_mode"] == "real"
        assert run_row["model_name"] == "stub-model"

        detail = trace(conn, result["run_id"])
        assert any(s["kind"] == "tool_call" and s["tool_name"] == "create_task" for s in detail["steps"])
        assert any(s["kind"] == "tool_result" and s["status"] == "ok" for s in detail["steps"])

        # 至少发生过两轮请求：第一轮返回 tool_call，第二轮带 tool 消息返回收尾文本
        assert len(_StubHandler.calls) >= 2
        assert any(m.get("role") == "tool" for m in _StubHandler.calls[-1]["messages"])
    finally:
        reload_config()


def test_real_mode_rejected_action_is_not_executed(conn, stub_server, monkeypatch):
    """模型要求执行白名单外/越权动作时，必须被安全门拦下且不写库。"""
    monkeypatch.setenv("AGENT_LLM_MODE", "real")
    monkeypatch.setenv("AGENT_LLM_BASE_URL", stub_server)
    monkeypatch.setenv("AGENT_LLM_API_KEY", "k")
    monkeypatch.setenv("AGENT_LLM_MODEL", "stub-model")
    reload_config()
    _StubHandler.tool_name = "prescribe_medication"
    try:
        patients.create_patient(conn, {"id": "R001", "name": "real 拦截", "age": 55, "duration_years": 4, "goals": ["稳定"]})
        result = run_agent(conn, "R001", trigger_type="user_request", message="请帮我整理一下最近的记录")
        codes = [r["code"] for r in result["rejections"]]
        assert "TOOL_NOT_ALLOWED" in codes or "FORBIDDEN_ACTION" in codes
        codes = [r["code"] for r in result["rejections"]]
        assert "TOOL_NOT_ALLOWED" in codes or "FORBIDDEN_ACTION" in codes
        assert conn.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"] == 0
        assert result["llm_mode"] == "real"
    finally:
        _StubHandler.tool_name = "create_task"
        reload_config()
