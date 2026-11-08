"""A3：执行后核验必须与 SQLite 交叉核对，禁止工具"报成功但库无变化"。"""
from __future__ import annotations

from datetime import timedelta

from backend.app.agent import tools
from backend.app.db.connection import iso, now
from backend.app.safety import validators
from backend.app.services import patients


def _patient(conn, pid="VER1"):
    patients.create_patient(conn, {"id": pid, "name": pid, "age": 60, "duration_years": 5, "goals": ["稳定"]})


def test_fake_task_success_is_rejected(conn):
    check = validators.post_execution_check(
        conn, tool="create_task", args={"patient_id": "VER1", "task_type": "record_glucose"},
        result={"ok": True, "task_id": "TSK-NOT-EXIST"},
    )
    assert check["ok"] is False
    assert check["code"] == validators.POSTCHECK_MISMATCH


def test_fake_review_success_is_rejected(conn):
    check = validators.post_execution_check(
        conn, tool="schedule_review", args={"patient_id": "VER1"}, result={"ok": True, "review_id": "REV-NOT-EXIST"},
    )
    assert check["ok"] is False


def test_fake_human_review_success_is_rejected(conn):
    check = validators.post_execution_check(
        conn, tool="request_human_review", args={"patient_id": "VER1"}, result={"ok": True, "review_id": "REV-NOT-EXIST"},
    )
    assert check["ok"] is False


def test_fake_question_success_is_rejected(conn):
    check = validators.post_execution_check(
        conn, tool="ask_user", args={"patient_id": "VER1", "target_field": "steps"},
        result={"ok": True, "question_id": "Q-NOT-EXIST"},
    )
    assert check["ok"] is False


def test_fake_notification_success_is_rejected(conn):
    check = validators.post_execution_check(
        conn, tool="create_notification", args={"patient_id": "VER1"},
        result={"ok": True, "notification_id": "NTF-NOT-EXIST"},
    )
    assert check["ok"] is False


def test_real_task_passes_postcheck(conn):
    _patient(conn)
    result = tools.execute(tools.ToolContext(conn, patient_id="VER1", run_id="RUN-VER"), "create_task", {
        "patient_id": "VER1", "task_type": "record_glucose", "title": "记录",
        "due_at": (now(conn) + timedelta(days=1)).isoformat(),
    })
    assert result["ok"] is True
    check = validators.post_execution_check(
        conn, tool="create_task", args={"patient_id": "VER1", "task_type": "record_glucose"}, result=result,
    )
    assert check["ok"] is True, check


def test_task_event_association_is_verified(conn):
    _patient(conn)
    conn.execute(
        """INSERT INTO events(id,patient_id,code,severity,status,message,evidence,dedupe_key,source_record_id,detected_at)
           VALUES('EVT-VER','VER1','GLUCOSE_RISING','high','open','x','{}','VER1:x',NULL,?)""",
        (iso(now(conn)),),
    )
    result = tools.execute(tools.ToolContext(conn, patient_id="VER1", run_id="RUN-VER"), "create_task", {
        "patient_id": "VER1", "task_type": "record_glucose", "title": "记录", "event_id": "EVT-VER",
        "due_at": (now(conn) + timedelta(days=1)).isoformat(),
    })
    assert result["ok"] is True
    check = validators.post_execution_check(
        conn, tool="create_task",
        args={"patient_id": "VER1", "task_type": "record_glucose", "event_id": "EVT-OTHER"}, result=result,
    )
    assert check["ok"] is False, "关联事件不一致必须被核验发现"


def test_wrong_patient_is_rejected(conn):
    _patient(conn)
    _patient(conn, "VER2")
    result = tools.execute(tools.ToolContext(conn, patient_id="VER1", run_id="RUN-VER"), "create_task", {
        "patient_id": "VER1", "task_type": "record_glucose", "title": "记录",
        "due_at": (now(conn) + timedelta(days=1)).isoformat(),
    })
    check = validators.post_execution_check(
        conn, tool="create_task", args={"patient_id": "VER2", "task_type": "record_glucose"}, result=result,
    )
    assert check["ok"] is False
