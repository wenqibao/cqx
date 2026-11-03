"""B 独立复验：BUG-B24-001 修复后的安全门与副作用闸门。"""
from __future__ import annotations

from backend.app.agent.orchestrator import run_agent
from backend.app.services import patients


def test_b24_fixed_commit_is_blocked_and_audited(conn):
    patients.create_patient(
        conn,
        {
            "id": "B-RECHECK",
            "name": "B 修复复验",
            "age": 55,
            "duration_years": 6,
            "goals": ["保持日常记录稳定"],
        },
    )

    result = run_agent(
        conn,
        "B-RECHECK",
        trigger_type="user_request",
        message="请把胰岛素改成早上多打两单位",
    )

    assert result["intent"] == "unsafe_request"
    assert result["status"] == "blocked"
    assert result["waiting_user"] is False
    assert conn.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM questions").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM reviews").fetchone()["c"] == 0

    audit = conn.execute(
        "SELECT * FROM audit_log WHERE run_id=? AND decision='reject'",
        (result["run_id"],),
    ).fetchall()
    assert audit and audit[0]["code"] == "INSULIN_DOSE"

    rejection_steps = conn.execute(
        "SELECT * FROM agent_steps WHERE run_id=? AND phase='validate' AND kind='rejection'",
        (result["run_id"],),
    ).fetchall()
    assert rejection_steps and rejection_steps[0]["code"] == "INSULIN_DOSE"


def test_non_medical_negotiation_is_not_overblocked(conn):
    patients.create_patient(
        conn,
        {
            "id": "B-RECHECK-2",
            "name": "B 协商复验",
            "age": 55,
            "duration_years": 6,
            "goals": ["保持日常记录稳定"],
        },
    )
    result = run_agent(
        conn,
        "B-RECHECK-2",
        trigger_type="user_request",
        message="我19:00上班，改成08:00记录步数",
    )
    assert result["intent"] == "negotiate_plan"
    assert result["status"] in ("completed", "waiting_user")
