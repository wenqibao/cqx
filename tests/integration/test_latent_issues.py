"""B 历史潜伏问题（19 项）的结构级回归。"""
from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from backend.app.agent import orchestrator
from backend.app.agent.llm import LLMResponse, ToolCall
from backend.app.api.routes_agent import router  # noqa: F401  (确保路由已加载)
from backend.app.automation import scheduler, triggers
from backend.app.db.connection import connect, dumps, iso, now, parse_ts
from backend.app.events import detector
from backend.app.main import create_app
from backend.app.memory import preferences
from backend.app.questioning import service as questioning
from backend.app.reviews import service as reviews
from backend.app.services import patients, records, state
from backend.app.tasks import service as tasks


def _patient(conn, pid="L1"):
    return patients.create_patient(conn, {"id": pid, "name": "潜伏", "age": 60, "duration_years": 5, "goals": ["稳定"]})


# ---------- DATA-SYN-01 ----------
def test_synthetic_patient_is_forced(conn):
    p = patients.create_patient(conn, {"id": "SYN", "name": "合成", "is_synthetic": False})
    assert p["is_synthetic"] is True


def test_api_rejects_non_synthetic_patient(db_path):
    app = create_app()
    with TestClient(app) as client:
        resp = client.post("/api/patients", json={"id": "SYN2", "name": "非合成", "is_synthetic": False})
    assert resp.status_code == 422


# ---------- RECORD-TIME-01 ----------
def test_future_record_is_rejected(conn):
    _patient(conn)
    with pytest.raises(records.RecordValidationError):
        records.add_record(conn, "L1", {"kind": "fasting_glucose", "value": 3.1,
                                        "recorded_at": iso(now(conn) + timedelta(days=30))})


def test_future_record_does_not_enter_state_or_events(conn):
    _patient(conn)
    conn.execute(
        """INSERT INTO health_records(patient_id,kind,value,unit,recorded_at,source,note,payload,dedupe_key,created_at)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        ("L1", "fasting_glucose", 3.1, "mmol/L", iso(now(conn) + timedelta(days=30)), "manual", None, None,
         "future1", iso(now(conn))),
    )
    snap = state.build_state(conn, "L1")
    assert snap["aggregates"]["7d"]["fasting_glucose"]["count"] == 0
    result = detector.detect_events(conn, "L1")
    assert result["created"] == []


# ---------- REV-DEDUPE-01/02 / REVIEW-DUE-01 / REVIEW-RESOLVE-01 ----------
def test_review_window_is_symmetric(conn):
    _patient(conn)
    auto = reviews.schedule_review(conn, "L1", task_id="T1", delay_hours=48)
    same = reviews.schedule_review(conn, "L1", task_id="T1", delay_hours=48)
    assert same["id"] == auto["id"] and same["duplicate"] is True
    earlier = reviews.schedule_review(conn, "L1", task_id="T1", delay_hours=24)
    assert earlier["id"] != auto["id"]
    later = reviews.schedule_review(conn, "L1", task_id="T1", delay_hours=168)
    assert later["id"] != auto["id"]


@pytest.mark.parametrize("delay", [-24, 100000])
def test_review_delay_range_rejected(conn, delay):
    _patient(conn)
    with pytest.raises(reviews.ReviewError):
        reviews.schedule_review(conn, "L1", task_id="T1", delay_hours=delay)


def test_human_review_can_use_zero_delay(conn):
    _patient(conn)
    review = reviews.schedule_review(conn, "L1", task_id="T1", delay_hours=0, branch="HUMAN_REVIEW")
    assert review["scheduled_for"]


def test_human_review_resolve_is_idempotent(conn):
    _patient(conn)
    review = reviews.schedule_review(conn, "L1", task_id="T1", delay_hours=0, branch="HUMAN_REVIEW")
    first = reviews.resolve_human_review(conn, review["id"], decision="保持原计划")
    second = reviews.resolve_human_review(conn, review["id"], decision="改为其他结论")
    assert second.get("already_resolved") is True
    assert second["detail"]["human_decision"] == "保持原计划"
    assert first["detail"]["human_decision"] == "保持原计划"


# ---------- TASK-DEDUPE-01 / TASK-MERGE-01 / TASK-DUE-01 ----------
def test_reschedule_updates_dedupe_key(conn):
    _patient(conn)
    d1 = iso(now(conn) + timedelta(hours=24))
    d2 = iso(now(conn) + timedelta(days=3))
    task, created = tasks.create_task(conn, "L1", task_type="record_weight", title="称重", due_at=d1, schedule_review=False)
    tasks.reschedule_task(conn, task["id"], due_at=d2)
    again, created2 = tasks.create_task(conn, "L1", task_type="record_weight", title="称重", due_at=d1, schedule_review=False)
    assert created2 is True
    assert again["id"] != task["id"]
    assert again["due_at"].startswith(d1[:13])


def test_far_due_tasks_are_not_merged(conn):
    _patient(conn)
    near = iso(now(conn) + timedelta(days=1))
    far = iso(now(conn) + timedelta(days=30))
    first, _ = tasks.create_task(conn, "L1", task_type="record_activity", title="活动", due_at=near, schedule_review=False)
    second, created = tasks.create_task(conn, "L1", task_type="record_activity", title="活动", due_at=far, schedule_review=False)
    assert created is True
    assert second["id"] != first["id"]


def test_reschedule_rejects_past_and_too_far(conn):
    _patient(conn)
    task, _ = tasks.create_task(conn, "L1", task_type="record_steps", title="步数",
                                due_at=iso(now(conn) + timedelta(days=1)), schedule_review=False)
    with pytest.raises(tasks.TaskError):
        tasks.reschedule_task(conn, task["id"], due_at=iso(now(conn) - timedelta(days=1)))
    with pytest.raises(tasks.TaskError):
        tasks.reschedule_task(conn, task["id"], due_at=iso(now(conn) + timedelta(days=40)))


# ---------- QUESTION-EXP-01 / QUESTION-DEDUPE-01 ----------
def test_expired_answer_is_rejected(conn):
    _patient(conn)
    q, _ = questioning.create_question(conn, "L1", question="服药了吗", target_field="medication_taken", ttl_hours=1)
    conn.execute("UPDATE questions SET expires_at=? WHERE id=?", (iso(now(conn) - timedelta(hours=1)), q["id"]))
    with pytest.raises(questioning.QuestionExpired):
        questioning.answer_question(conn, q["id"], answer_text="已服药")
    assert questioning.get_question(conn, q["id"])["status"] == "expired"


def test_same_field_question_merges_events(conn):
    _patient(conn)
    q1, created1 = questioning.create_question(conn, "L1", question="服药了吗", target_field="medication_taken",
                                               event_id="EVT-A", resume_payload={"event_ids": ["EVT-A"]})
    q2, created2 = questioning.create_question(conn, "L1", question="服药了吗", target_field="medication_taken",
                                               event_id="EVT-B")
    assert created1 is True and created2 is False
    assert q2["id"] == q1["id"]
    assert q2["resume_payload"]["event_ids"] == ["EVT-A", "EVT-B"]


# ---------- JOB-DEDUPE-01 / JOB-RECOVERY-01 ----------
def test_system_job_is_deduped(conn):
    scheduler.enqueue_job(conn, kind="overdue_check", patient_id=None, ref_id="overdue-2026-01-01")
    scheduler.enqueue_job(conn, kind="overdue_check", patient_id=None, ref_id="overdue-2026-01-01")
    rows = conn.execute("SELECT COUNT(*) c FROM automation_jobs WHERE kind='overdue_check'").fetchone()["c"]
    assert rows == 1


def test_stale_running_job_is_recovered(conn):
    job = scheduler.enqueue_job(conn, kind="reminder", patient_id="L1", ref_id="R1",
                                payload={"title": "提醒"})
    conn.execute("UPDATE automation_jobs SET status='running', updated_at=? WHERE id=?",
                 (iso(now(conn) - timedelta(days=7)), job["id"]))
    assert scheduler.recover_stale_jobs(conn) == 1
    status = conn.execute("SELECT status FROM automation_jobs WHERE id=?", (job["id"],)).fetchone()["status"]
    assert status == "pending"


# ---------- COMPLETE-IDEMP-01 ----------
def test_duplicate_complete_does_not_trigger_agent(db_path):
    app = create_app()
    with TestClient(app) as client:
        client.post("/api/patients", json={"id": "CP1", "name": "完成", "age": 60, "duration_years": 5, "goals": ["稳定"]})
        conn = connect(db_path)
        try:
            task, _ = tasks.create_task(conn, "CP1", task_type="record_glucose", title="记录",
                                        due_at=iso(now(conn) + timedelta(days=1)), schedule_review=False)
        finally:
            conn.close()
        first = client.post(f"/api/tasks/{task['id']}/complete", json={"changed_by": "patient", "run_agent": True})
        second = client.post(f"/api/tasks/{task['id']}/complete", json={"changed_by": "patient", "run_agent": True})
    assert first.status_code == 200
    assert second.json().get("already_done") is True
    assert second.json().get("run") is None


# ---------- PREF-TIME-01 / PREF-SCOPE-01 ----------
def test_preference_keeps_minutes(conn):
    _patient(conn)
    preferences.set_preference(conn, "L1", kind="preferred_time_window", value="20:30",
                               source="patient_confirmed")
    task, _ = tasks.create_task(conn, "L1", task_type="record_activity", title="步数",
                                due_at=iso(now(conn) + timedelta(days=1)), schedule_review=False)
    triggers.after_preference_change(conn, "L1")
    updated = tasks.get_task(conn, task["id"])
    due = parse_ts(updated["due_at"])
    assert due and (due.hour, due.minute) == (20, 30)


def test_review_task_not_moved_by_preference(conn):
    _patient(conn)
    preferences.set_preference(conn, "L1", kind="preferred_time_window", value="20:30",
                               source="patient_confirmed")
    task, _ = tasks.create_task(conn, "L1", task_type="review_hypoglycemia", title="低血糖复核",
                                due_at=iso(now(conn) + timedelta(days=1)), schedule_review=False)
    before = task["due_at"]
    triggers.after_preference_change(conn, "L1")
    assert tasks.get_task(conn, task["id"])["due_at"] == before


# ---------- EVENT-RECURRENCE-01 / EVENT-FINALIZE-01 / STATE-LAST-01 ----------
def _glucose(conn, pid, value, when):
    records.add_record(conn, pid, {"kind": "fasting_glucose", "value": value, "recorded_at": iso(when)})


def test_handled_event_can_reopen_on_new_evidence(conn):
    _patient(conn)
    _glucose(conn, "L1", 7.0, now(conn) - timedelta(hours=2))
    _glucose(conn, "L1", 8.8, now(conn) - timedelta(hours=1))
    first = detector.detect_events(conn, "L1")["created"]
    assert first
    detector.mark_handled(conn, [e["id"] for e in first], "RUN-X")
    _glucose(conn, "L1", 9.9, now(conn) - timedelta(minutes=30))
    again = detector.detect_events(conn, "L1")["created"]
    assert again, "已处理事件后的新异常必须产生新的 open 事件"


def test_only_referenced_events_are_handled(conn):
    _patient(conn)
    ts = iso(now(conn))
    for code in ("GLUCOSE_RISING", "LOW_ACTIVITY"):
        conn.execute(
            """INSERT INTO events(id,patient_id,code,severity,status,message,evidence,dedupe_key,source_record_id,detected_at)
               VALUES(?,?,?,?,'open',?,?,?,?,?)""",
            (code, "L1", code, "high" if code == "GLUCOSE_RISING" else "medium", code, "{}", f"L1:{code}:{ts[:13]}", None, ts),
        )
    events = [detector.get_event(conn, "GLUCOSE_RISING"), detector.get_event(conn, "LOW_ACTIVITY")]
    first, second = events[0], events[1]
    executed = [{"tool": "create_task", "ok": True, "args": {"event_id": first["id"]}, "result": {}}]
    orchestrator._finalize_events(conn, "RUN-Y", events, False, executed)
    assert detector.get_event(conn, first["id"])["status"] == "handled"
    assert detector.get_event(conn, second["id"])["status"] == "open"


def test_last_at_belongs_to_same_metric(conn):
    _patient(conn)
    d1 = now(conn) - timedelta(days=2)
    d2 = now(conn) - timedelta(days=1)
    records.add_record(conn, "L1", {"kind": "fasting_glucose", "value": 6.6, "recorded_at": iso(d1)})
    records.add_record(conn, "L1", {"kind": "steps", "value": 6000, "recorded_at": iso(d2)})
    agg = state.build_state(conn, "L1")["aggregates"]["7d"]["fasting_glucose"]
    assert agg["last"] == 6.6
    assert parse_ts(agg["last_at"]) == parse_ts(iso(d1))
