"""B16 / resume 路径回归：
1) respond 声称已建任务、同轮稍后 create_task 真的成功 → 不能判 POSTCHECK_MISMATCH；
2) 同轮没有任何 create_task 却声称已创建 → 仍必须判失败（防虚假成功）；
3) 只做读取、既没结论也没提问/升级 → 不能标 completed。
"""
from __future__ import annotations

from datetime import timedelta

from backend.app.agent import orchestrator
from backend.app.agent.llm import LLMResponse, ToolCall
from backend.app.db.connection import iso, now
from backend.app.events.detector import detect_events
from backend.app.services import patients, records


class _ScriptedLLM:
    mode = "real"
    model_name = "scripted-claim-timing"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def plan_actions(self, **kwargs):
        index = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return self.responses[index]


def _seed_event(conn, pid):
    patients.create_patient(conn, {"id": pid, "name": "时序", "age": 60, "duration_years": 5, "goals": ["稳定"]})
    for i, value in enumerate([7.0, 7.9, 8.8]):
        records.add_record(conn, pid, {"kind": "fasting_glucose", "value": value,
                                       "recorded_at": iso(now() - timedelta(hours=24 * (2 - i)))})
    return detect_events(conn, pid)["created"][0]


def test_claim_supported_by_later_tool_in_same_round(conn):
    """respond 在前、create_task 在同一轮之后执行 → 声明应被接受。"""
    event = _seed_event(conn, "CT1")
    due = (now() + timedelta(days=1)).isoformat()
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[
            ToolCall("respond", {"patient_id": "CT1", "text": "我已为您创建一条记录提醒任务，方便您从今天开始固定时间点记录。"}, "c1"),
            ToolCall("create_task", {"patient_id": "CT1", "task_type": "glucose_logging",
                                     "title": "固定时间点记录空腹血糖", "due_at": due}, "c2"),
        ], raw={}),
        LLMResponse(content="已记录，按任务执行即可。", tool_calls=[], raw={}),
    ])
    result = orchestrator.run_agent(conn, "CT1", trigger_type="event_detected", event_ids=[event["id"]], llm=llm)

    assert not [r for r in result["rejections"] if r["code"] == "POSTCHECK_MISMATCH"], result["rejections"]
    assert result["status"] == "completed", result
    assert conn.execute("SELECT COUNT(*) c FROM tasks WHERE patient_id='CT1'").fetchone()["c"] == 1


def test_claim_without_any_tool_still_fails(conn):
    """同轮没有任何 create_task，声称仍然必须被拆穿。"""
    event = _seed_event(conn, "CT2")
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[
            ToolCall("respond", {"patient_id": "CT2", "text": "我已为您创建一条记录提醒任务。"}, "c1"),
        ], raw={}),
        LLMResponse(content="", tool_calls=[], raw={}),
    ])
    result = orchestrator.run_agent(conn, "CT2", trigger_type="event_detected", event_ids=[event["id"]], llm=llm)

    assert any(r["code"] == "POSTCHECK_MISMATCH" for r in result["rejections"]), result["rejections"]
    assert result["status"] == "failed"
    assert conn.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"] == 0


def test_read_only_run_without_answer_is_not_completed(conn):
    """resume 路径：只 list_tasks/query_history，没有 respond → 不能 completed。"""
    patients.create_patient(conn, {"id": "CT3", "name": "只读", "age": 60, "duration_years": 5, "goals": ["稳定"]})
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[
            ToolCall("list_tasks", {"patient_id": "CT3"}, "c1"),
            ToolCall("query_history", {"patient_id": "CT3", "kind": "fasting_glucose"}, "c2"),
        ], raw={}),
        LLMResponse(content="", tool_calls=[], raw={}),
    ])
    result = orchestrator.run_agent(conn, "CT3", trigger_type="answer_received", message="记不清", llm=llm)

    assert result["status"] == "failed", result
    assert any(r["code"] == "POSTCHECK_MISMATCH" for r in result["rejections"]), result["rejections"]
