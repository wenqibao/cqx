"""F13/F26：安全门、红旗升级、计划校验与拒绝码。"""
from __future__ import annotations

from datetime import timedelta

import pytest

from backend.app.db.connection import iso, now
from backend.app.safety import gate, validators
from backend.app.services import patients, records, state


def test_forbidden_intents_detected():
    for text, code in [
        ("你能帮我诊断一下吗", "DIAGNOSIS"),
        ("帮我改药吧", "CHANGE_MEDICATION"),
        ("胰岛素剂量可以加两个单位吗", "INSULIN_DOSE"),
        ("给我开点药", "PRESCRIPTION"),
    ]:
        verdict = gate.check_text(text)
        assert verdict["allowed"] is False, text
        assert verdict["code"] == code


def test_normal_text_allowed():
    verdict = gate.check_text("今天走了 6000 步，想确认一下记录是否完整")
    assert verdict["allowed"] is True


def test_assert_safe_raises():
    with pytest.raises(gate.SafetyViolation) as exc:
        gate.assert_safe("帮我停药")
    assert exc.value.code in ("CHANGE_MEDICATION", "STOP_TREATMENT")


def test_tool_whitelist():
    assert gate.check_tool("create_task") is True
    assert gate.check_tool("prescribe_medication") is False


def test_escalation_from_recent_low_glucose(conn):
    patients.create_patient(conn, {"id": "X1", "name": "低血糖", "age": 60, "duration_years": 8, "goals": ["稳定"]})
    records.add_record(
        conn,
        "X1",
        {"kind": "fasting_glucose", "value": 3.5, "recorded_at": iso(now(conn) - timedelta(hours=30))},
    )
    records.add_record(conn, "X1", {"kind": "fasting_glucose", "value": 5.6, "recorded_at": iso(now(conn))})
    snap = state.build_state(conn, "X1")
    hits = gate.escalation_hits(snap, conn, "X1")
    assert any(h["code"] == "SEVERE_HYPOGLYCEMIA" for h in hits)


def test_escalation_from_symptom(conn):
    patients.create_patient(conn, {"id": "X2", "name": "症状", "age": 60, "duration_years": 8, "goals": ["稳定"]})
    records.add_record(
        conn,
        "X2",
        {
            "kind": "symptom",
            "value": None,
            "payload": {"text": "胸口有点疼，呼吸急促"},
            "recorded_at": iso(now(conn) - timedelta(hours=5)),
        },
    )
    snap = state.build_state(conn, "X2")
    hits = gate.escalation_hits(snap, conn, "X2")
    assert any(h["code"] == "SYMPTOM_ALERT" for h in hits)


def test_plan_rejects_unknown_tool(conn):
    patients.create_patient(conn, {"id": "X3", "name": "校验", "age": 50, "duration_years": 3, "goals": ["稳定"]})
    plan = {"actions": [{"tool": "delete_all_records", "args": {"patient_id": "X3"}}]}
    result = validators.validate_plan(conn, patient_id="X3", plan=plan, state={})
    assert result["ok"] is False
    assert result["rejections"][0]["code"] == validators.TOOL_NOT_ALLOWED


def test_plan_rejects_forbidden_action_text(conn):
    patients.create_patient(conn, {"id": "X4", "name": "校验", "age": 50, "duration_years": 3, "goals": ["稳定"]})
    plan = {
        "actions": [
            {
                "tool": "create_task",
                "args": {
                    "patient_id": "X4",
                    "task_type": "record_glucose",
                    "title": "建议减药并停止注射",
                    "description": "",
                },
            }
        ]
    }
    result = validators.validate_plan(conn, patient_id="X4", plan=plan, state={})
    assert result["ok"] is False
    assert result["rejections"][0]["code"] == validators.FORBIDDEN_ACTION


def test_plan_rejects_missing_evidence(conn):
    patients.create_patient(conn, {"id": "X5", "name": "证据", "age": 50, "duration_years": 3, "goals": ["稳定"]})
    plan = {
        "actions": [
            {"tool": "respond", "args": {"patient_id": "X5", "text": "结论"}, "requires_evidence": True}
        ]
    }
    result = validators.validate_plan(conn, patient_id="X5", plan=plan, state={}, evidence=[])
    assert result["ok"] is False
    assert result["rejections"][0]["code"] == validators.NO_EVIDENCE


def test_plan_rejects_invalid_due(conn):
    patients.create_patient(conn, {"id": "X6", "name": "时间", "age": 50, "duration_years": 3, "goals": ["稳定"]})
    plan = {
        "actions": [
            {
                "tool": "create_task",
                "args": {
                    "patient_id": "X6",
                    "task_type": "record_glucose",
                    "title": "记录",
                    "due_at": "2020-01-01T00:00:00Z",
                },
            }
        ]
    }
    result = validators.validate_plan(conn, patient_id="X6", plan=plan, state={})
    assert any(r["code"] == validators.INVALID_DUE for r in result["rejections"])


def test_plan_rejects_missing_task_reference(conn):
    patients.create_patient(conn, {"id": "X7", "name": "任务", "age": 50, "duration_years": 3, "goals": ["稳定"]})
    plan = {
        "actions": [
            {
                "tool": "update_task",
                "args": {"task_id": "TSK-missing", "due_at": iso(now(conn) + timedelta(days=1))},
            }
        ]
    }
    result = validators.validate_plan(conn, patient_id="X7", plan=plan, state={})
    assert any(r["code"] == validators.TASK_NOT_FOUND for r in result["rejections"])


def test_post_check_catches_fake_success(conn):
    result = validators.post_execution_check(
        conn, tool="create_task", args={"patient_id": "X8"}, result={"ok": True, "task_id": "TSK-fake"}
    )
    assert result["ok"] is False
    assert result["code"] == validators.POSTCHECK_MISMATCH


def test_post_check_reports_failed_tool(conn):
    result = validators.post_execution_check(
        conn, tool="create_task", args={}, result={"ok": False, "error": "boom"}
    )
    assert result["code"] == validators.TOOL_EXECUTION_FAILED
