"""REL-REAL-01：处方"记录/查看"不是开具处方。"""
from __future__ import annotations

from datetime import timedelta

import pytest

from backend.app.agent import tools
from backend.app.db.connection import now
from backend.app.safety import validators
from backend.app.safety.gate import check_text
from backend.app.services import patients

ALLOW = [
    "结合药盒/处方记录核实用药依从性",
    "查看处方记录，不修改处方",
    "本任务仅做提醒与核实，不涉及任何改药、停药或剂量建议。",
]
BLOCK = [
    ("开具处方", "PRESCRIPTION"),
    ("修改处方", "PRESCRIPTION"),
    ("增加处方药剂量", "PRESCRIPTION"),
    ("帮开个处方", "PRESCRIPTION"),
    ("不含处方建议而是开具处方", "PRESCRIPTION"),
]

R03_DESCRIPTION = (
    "请结合药盒/处方记录或家属协助，在下次随访时核对用药依从性并形成可追溯记录。"
    "仅做提醒与核实，不涉及任何改药、停药或剂量建议。"
)


@pytest.mark.parametrize("text", ALLOW)
def test_prescription_records_are_allowed(text):
    assert check_text(text, generated=True)["allowed"] is True
    assert check_text(text)["allowed"] is True


@pytest.mark.parametrize("text,code", BLOCK)
def test_real_prescription_actions_blocked(text, code):
    verdict = check_text(text, generated=True)
    assert verdict["allowed"] is False
    assert verdict["code"] == code


def test_r03_answer_task_description_passes(conn):
    patients.create_patient(conn, {"id": "RX1", "name": "处方", "age": 60, "duration_years": 5, "goals": ["稳定"]})
    args = {
        "patient_id": "RX1",
        "task_type": "confirm_medication",
        "title": "用药依从性核实",
        "description": R03_DESCRIPTION,
        "due_at": (now(conn) + timedelta(days=1)).isoformat(),
    }
    checked = validators.validate_plan(conn, patient_id="RX1",
                                       plan={"actions": [{"tool": "create_task", "args": args}]}, state={})
    assert checked["rejections"] == [], checked["rejections"]
    tools.execute(tools.ToolContext(conn, patient_id="RX1", run_id="RUN-RX"), "create_task", args)
    assert conn.execute("SELECT COUNT(*) c FROM tasks WHERE patient_id='RX1'").fetchone()["c"] == 1
