"""A3：执行后核验必须与 SQLite 交叉核对，禁止工具"报成功但库无变化"。"""
from __future__ import annotations

from datetime import timedelta

from backend.app.agent import tools
from backend.app.db.connection import iso, now
from backend.app.safety import validators
from backend.app.services import patients


def _patient(conn, pid="VER1"):
    patients.create_patient(conn, {"id": pid, "name": pid, "age": 60, "duration_years": 5, "goals": ["稳定"]})


def _ctx(conn):
    return tools.ToolContext(conn, patient_id="VER1", run_id="RUN-VER")


def _task(conn):
    from backend.app.tasks import service as tasks

    return tasks.create_task(conn, "VER1", task_type="record_glucose", title="记录",
                             due_at=iso(now(conn) + timedelta(days=1)), schedule_review=False)


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

def _event(conn, pid="VER1", eid="EVT-VER-A", code="GLUCOSE_RISING"):
    conn.execute(
        """INSERT OR REPLACE INTO events(id,patient_id,code,severity,status,message,evidence,dedupe_key,
                                          source_record_id,detected_at)
           VALUES(?,?,?, 'high','open','x','{}',?,NULL,?)""",
        (eid, pid, code, f"{pid}:{code}:x", iso(now(conn))),
    )
    return eid


def test_update_task_due_mismatch_is_rejected_with_reason(conn):
    _patient(conn)
    task, _ = _task(conn)
    new_due = (now(conn) + timedelta(days=3)).isoformat()
    result = tools.execute(_ctx(conn), "update_task", {"patient_id": "VER1", "task_id": task["id"], "due_at": new_due})
    assert result["ok"] is True, result
    check = validators.post_execution_check(
        conn, tool="update_task",
        args={"patient_id": "VER1", "task_id": task["id"], "due_at": (now(conn) + timedelta(days=5)).isoformat()},
        result=result,
    )
    assert check["ok"] is False
    assert "截止时间" in check["message"]


def test_update_task_other_patient_is_rejected_with_reason(conn):
    _patient(conn)
    _patient(conn, "VER2")
    task, _ = _task(conn)
    result = tools.execute(_ctx(conn), "update_task", {
        "patient_id": "VER1", "task_id": task["id"], "due_at": (now(conn) + timedelta(days=3)).isoformat(),
    })
    check = validators.post_execution_check(
        conn, tool="update_task", args={"patient_id": "VER2", "task_id": task["id"]}, result=result,
    )
    assert check["ok"] is False
    assert "不属于当前患者" in check["message"]


def test_schedule_review_event_mismatch_is_rejected_with_reason(conn):
    _patient(conn)
    _event(conn)
    result = tools.execute(_ctx(conn), "schedule_review", {
        "patient_id": "VER1", "event_id": "EVT-VER-A", "delay_hours": 24,
    })
    assert result["ok"] is True, result
    check = validators.post_execution_check(
        conn, tool="schedule_review",
        args={"patient_id": "VER1", "event_id": "EVT-OTHER"}, result=result,
    )
    assert check["ok"] is False
    assert "未关联指定事件" in check["message"]


def test_human_review_state_mismatch_is_rejected_with_reason(conn):
    _patient(conn)
    _event(conn)
    result = tools.execute(_ctx(conn), "request_human_review", {
        "patient_id": "VER1", "event_id": "EVT-VER-A", "reason": "需专业判断", "severity": "high",
    })
    assert result["ok"] is True, result
    conn.execute("UPDATE reviews SET status='resolved' WHERE id=?", (result["review_id"],))
    check = validators.post_execution_check(
        conn, tool="request_human_review", args={"patient_id": "VER1"}, result=result,
    )
    assert check["ok"] is False
    assert "状态异常" in check["message"]


def test_preference_value_mismatch_is_rejected_with_reason(conn):
    _patient(conn)
    result = tools.execute(_ctx(conn), "save_preference", {
        "patient_id": "VER1", "kind": "preferred_time_window", "value": "08:00-10:00", "source": "patient_confirmed",
    })
    assert result["ok"] is True, result
    check = validators.post_execution_check(
        conn, tool="save_preference",
        args={"patient_id": "VER1", "kind": "preferred_time_window", "value": "09:00-10:00"}, result=result,
    )
    assert check["ok"] is False
    assert "偏好值" in check["message"]


def test_notification_reference_mismatch_is_rejected_with_reason(conn):
    _patient(conn)
    result = tools.execute(_ctx(conn), "create_notification", {
        "patient_id": "VER1", "kind": "review_created", "title": "复核已创建", "body": "等待医生",
        "ref_type": "review", "ref_id": "REV-1",
    })
    assert result["ok"] is True, result
    check = validators.post_execution_check(
        conn, tool="create_notification",
        args={"patient_id": "VER1", "kind": "review_created", "ref_type": "review", "ref_id": "REV-2"},
        result=result,
    )
    assert check["ok"] is False
    assert "引用对象" in check["message"]


def test_valid_flows_pass_content_level_checks(conn):
    _patient(conn)
    due = (now(conn) + timedelta(days=2)).isoformat()
    created = tools.execute(_ctx(conn), "create_task", {
        "patient_id": "VER1", "task_type": "record_glucose", "title": "记录", "due_at": due,
    })
    updated = tools.execute(_ctx(conn), "update_task", {"patient_id": "VER1", "task_id": created["task_id"], "due_at": due})
    assert validators.post_execution_check(
        conn, tool="update_task", args={"patient_id": "VER1", "task_id": created["task_id"], "due_at": due}, result=updated,
    )["ok"] is True
    _event(conn)
    review = tools.execute(_ctx(conn), "schedule_review", {"patient_id": "VER1", "event_id": "EVT-VER-A", "delay_hours": 24})
    assert validators.post_execution_check(
        conn, tool="schedule_review", args={"patient_id": "VER1", "event_id": "EVT-VER-A"}, result=review,
    )["ok"] is True
    human = tools.execute(_ctx(conn), "request_human_review", {
        "patient_id": "VER1", "event_id": "EVT-VER-A", "reason": "需专业判断", "severity": "high",
    })
    assert validators.post_execution_check(
        conn, tool="request_human_review", args={"patient_id": "VER1", "event_id": "EVT-VER-A"}, result=human,
    )["ok"] is True
    pref = tools.execute(_ctx(conn), "save_preference", {
        "patient_id": "VER1", "kind": "preferred_time_window", "value": "08:00-10:00", "source": "patient_confirmed",
    })
    assert validators.post_execution_check(
        conn, tool="save_preference", args={"patient_id": "VER1", "kind": "preferred_time_window", "value": "08:00-10:00"}, result=pref,
    )["ok"] is True
    ntf = tools.execute(_ctx(conn), "create_notification", {
        "patient_id": "VER1", "kind": "info", "title": "提醒", "body": "记录血糖",
    })
    assert validators.post_execution_check(
        conn, tool="create_notification", args={"patient_id": "VER1", "kind": "info"}, result=ntf,
    )["ok"] is True
