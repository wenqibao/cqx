"""A-WB-01 回归：真实路径只读取、不采取管理动作时必须判失败，并在只读轮后给出推进提示。

真实失败 RUN-04a267842b5d：三轮只有 search_knowledge / query_history / get_preferences，
没有任务、提问或复核，事件却可能被当成已处理。这里用受控脚本模型复现，不调用厂商。
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from backend.app.agent import llm as llm_module
from backend.app.agent import orchestrator
from backend.app.agent.llm import LLMResponse, ToolCall
from backend.app.audit.trace import steps
from backend.app.db.connection import iso, now
from backend.app.events.detector import detect_events
from backend.app.services import patients, records


def _seed_event(conn, pid="WB01"):
    patients.create_patient(conn, {"id": pid, "name": "推进测试", "age": 60, "duration_years": 6, "goals": ["稳定"]})
    for i, value in enumerate([7.0, 7.8, 8.6, 9.3]):
        records.add_record(
            conn,
            pid,
            {"kind": "fasting_glucose", "value": value, "recorded_at": iso(now(conn) - timedelta(hours=24 * (4 - i)))},
        )
    events = detect_events(conn, pid)["created"]
    assert events, "测试前置：必须产生事件"
    return events[0]


def _search(query: str, call_id: str):
    return LLMResponse(content="", tool_calls=[ToolCall("search_knowledge", {"query": query}, call_id)],
                       raw={"id": f"resp-{call_id}", "model": "scripted", "usage": {"total_tokens": 1}})


def _create_task(pid: str, call_id: str, event_id: str | None = None):
    args = {
        "patient_id": pid,
        "task_type": "record_glucose",
        "title": "补录空腹血糖",
        "due_at": (now() + timedelta(days=1)).isoformat(),
    }
    if event_id:
        args["event_id"] = event_id
    return LLMResponse(
        content="",
        tool_calls=[ToolCall("create_task", args, call_id)],
        raw={"id": f"resp-{call_id}", "model": "scripted", "usage": {"total_tokens": 1}},
    )


class ScriptedLLM:
    mode = "real"
    model_name = "scripted-review"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.seen_messages: list[list[dict]] = []

    def plan_actions(self, *, system, user, tools, extra_messages=None):
        self.seen_messages.append(list(extra_messages or []))
        index = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return self.responses[index]


def test_read_only_round_gets_nudge_then_acts(conn):
    event = _seed_event(conn)
    llm = ScriptedLLM([
        _search("连续记录血糖", "c1"),
        _create_task("WB01", "c2", event["id"]),
        LLMResponse(content="已为你创建补录任务。", tool_calls=[], raw={"id": "resp-c3"}),
    ])
    result = orchestrator.run_agent(conn, "WB01", trigger_type="event_detected", event_ids=[event["id"]], llm=llm)

    assert result["status"] == "completed", result
    assert conn.execute("SELECT COUNT(*) c FROM tasks WHERE patient_id='WB01'").fetchone()["c"] == 1
    kinds = [s["kind"] for s in steps(conn, result["run_id"])]
    assert "progress_nudge" in kinds, "只读轮之后必须追加一次推进提示"
    assert "已为你创建补录任务。" in result["responses"]
    status = conn.execute("SELECT status FROM events WHERE id=?", (event["id"],)).fetchone()["status"]
    assert status == "handled"


def test_only_reads_never_completes_and_event_stays_open(conn):
    event = _seed_event(conn)
    llm = ScriptedLLM([
        _search("连续记录血糖", "c1"),
        _search("血糖 监测 频率", "c2"),
        _search("血糖 记录 意义", "c3"),
    ])
    result = orchestrator.run_agent(conn, "WB01", trigger_type="event_detected", event_ids=[event["id"]], llm=llm)

    assert result["status"] == "failed"
    assert any(r["code"] == "POSTCHECK_MISMATCH" for r in result["rejections"])
    assert conn.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"] == 0
    status = conn.execute("SELECT status FROM events WHERE id=?", (event["id"],)).fetchone()["status"]
    assert status == "open", "只读取不能被当成已处理事件"


def test_search_calls_are_capped(conn):
    event = _seed_event(conn)
    llm = ScriptedLLM([_search("连续记录血糖", f"c{i}") for i in range(3)])
    result = orchestrator.run_agent(conn, "WB01", trigger_type="event_detected", event_ids=[event["id"]], llm=llm)

    executed_searches = [e for e in result["actions"] if e["tool"] == "search_knowledge"]
    assert len(executed_searches) == 2, "检索最多执行 2 次"
    run_steps = steps(conn, result["run_id"])
    assert any(s["code"] == "NO_PROGRESS" for s in run_steps), "超出上限的检索应标记 NO_PROGRESS"
    assert result["status"] == "failed"


def test_nudge_is_visible_to_the_next_round(conn):
    event = _seed_event(conn)
    llm = ScriptedLLM([
        _search("连续记录血糖", "c1"),
        _create_task("WB01", "c2"),
        LLMResponse(content="已为你创建补录任务。", tool_calls=[], raw={"id": "resp-c3"}),
    ])
    orchestrator.run_agent(conn, "WB01", trigger_type="event_detected", event_ids=[event["id"]], llm=llm)
    # 第二次请求（第 2 轮）的额外消息里应包含推进提示
    assert len(llm.seen_messages) >= 2
    second_round = llm.seen_messages[1]
    assert any(m.get("role") == "system" and "没有产生任何管理动作" in m.get("content", "") for m in second_round)
