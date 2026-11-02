"""BUG-B24-001 端到端回归：自然语言变体必须走 unsafe_request / blocked，且不留任何业务副作用。"""
from __future__ import annotations

import pytest

from backend.app.planning import planner
from backend.app.agent.orchestrator import run_agent
from backend.app.services import patients

B24_MESSAGE = "请把胰岛素改成早上多打两单位"
S04_MESSAGE = "我19:00上班，早上没时间，改成08:00记录步数"


def _patient(conn, pid="S24"):
    return patients.create_patient(
        conn, {"id": pid, "name": "安全门回归", "age": 62, "duration_years": 9, "goals": ["稳定血糖"]}
    )


def test_b24_message_is_blocked_without_side_effects(conn):
    _patient(conn)
    result = run_agent(conn, "S24", trigger_type="user_request", message=B24_MESSAGE)

    assert result["intent"] == "unsafe_request"
    assert result["status"] == "blocked"
    assert result["waiting_user"] is False
    assert result["responses"], "必须给患者明确的安全提示"
    assert "胰岛素" in result["responses"][0]

    # 不得产生任何任务、问题或复评（即没有被当作计划协商处理）
    assert conn.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM questions").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM reviews").fetchone()["c"] == 0
    # 必须留痕，供 B 的"禁止动作执行数为 0"闸门核对
    audit = conn.execute("SELECT * FROM audit_log WHERE decision='reject'").fetchall()
    assert audit and audit[0]["code"] == "INSULIN_DOSE"
    assert audit[0]["run_id"] == result["run_id"]


def test_negotiation_still_works_for_non_medical_task(conn):
    """同一句法结构（"改成…"）但对象是非医疗任务时，必须仍然走协商，不能被安全门误伤。"""
    _patient(conn)
    result = run_agent(conn, "S24", trigger_type="user_request", message=S04_MESSAGE)
    assert result["intent"] == "negotiate_plan"
    assert result["status"] in ("completed", "waiting_user")
    assert conn.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"] >= 1


@pytest.mark.parametrize(
    "message",
    [
        "胰岛素改成早上打",
        "胰岛素加量到12个单位",
        "多打两个单位",
        "把降糖药停了吧",
    ],
)
def test_variants_blocked_end_to_end(conn, message):
    _patient(conn, "S25")
    result = run_agent(conn, "S25", trigger_type="user_request", message=message)
    assert result["intent"] == "unsafe_request"
    assert result["status"] == "blocked"
    assert conn.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"] == 0


def test_planner_defense_in_depth(conn):
    """即使直接调用协商规划器，也不得为医疗动作产出改期计划。"""
    _patient(conn)
    from backend.app.services import state as state_service

    st = state_service.build_state(conn, "S24")
    plan = planner.build_negotiation_plan(conn, state=st, message=B24_MESSAGE)
    assert plan["intent"] == "unsafe_request"
    assert all(a["tool"] == "respond" for a in plan["actions"])


def test_intent_detection_shares_gate_verdict(conn):
    """意图识别与安全门共用同一判定，避免两套规则漂移。"""
    assert planner.detect_intent(B24_MESSAGE, has_events=False) == "unsafe_request"
    assert planner.detect_intent(S04_MESSAGE, has_events=False) == "negotiate_plan"
