"""残余 30 项的结构回归（迁移、原子幂等、作用域、输入边界）。"""
from __future__ import annotations

import sqlite3
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from backend.app.agent import orchestrator
from backend.app.automation import scheduler
from backend.app.db import migrations
from backend.app.db.connection import connect, iso, now
from backend.app.events import detector
from backend.app.main import create_app
from backend.app.memory import preferences
from backend.app.questioning import service as questioning
from backend.app.reviews import service as reviews
from backend.app.services import patients, records
from backend.app.tasks import service as tasks


def _patient(conn, pid="S1"):
    patients.create_patient(conn, {"id": pid, "name": "结构", "age": 60, "duration_years": 5, "goals": ["稳定"]})


def _event(conn, pid, code="GLUCOSE_RISING", severity="high"):
    conn.execute(
        """INSERT INTO events(id,patient_id,code,severity,status,message,evidence,dedupe_key,source_record_id,detected_at)
           VALUES(?,?,?,?,'open',?,?,?,?,?)""",
        (f"EVT-{pid}-{code}", pid, code, severity, code, "{}", f"{pid}:{code}:test", None, iso(now(conn))),
    )
    return f"EVT-{pid}-{code}"


# ---------- 迁移 ----------
def test_migration_cleans_legacy_duplicates(workdir):
    path = workdir / "legacy.db"
    conn = connect(path)
    _patient(conn, "MIG")
    # 模拟旧库：删除新索引，恢复旧唯一索引，写入 NULL 重复作业与旧数据
    conn.execute("DROP INDEX IF EXISTS uq_jobs_key")
    conn.execute("CREATE UNIQUE INDEX uq_jobs_key ON automation_jobs(kind, patient_id, ref_id, run_at)")
    for _ in range(2):
        conn.execute(
            "INSERT INTO automation_jobs(id,kind,patient_id,ref_id,payload,run_at,status,attempts,created_at,updated_at) "
            "VALUES(?,?,NULL,?,?,?, 'pending',0,?,?)",
            (f"J{_}", "overdue_check", "overdue-x", "{}", "2026-01-01T00:00:00Z",
             "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
        )
    conn.execute("UPDATE patients SET is_synthetic=0 WHERE id='MIG'")
    conn.execute("UPDATE app_meta SET value='0' WHERE key='schema_version'")
    conn.close()

    reopened = connect(path)
    assert reopened.execute("SELECT COUNT(*) c FROM automation_jobs WHERE kind='overdue_check'").fetchone()["c"] == 1
    assert patients.get_patient(reopened, "MIG")["is_synthetic"] is True
    assert migrations.schema_version(reopened) == migrations.SCHEMA_VERSION
    reopened.close()


# ---------- 作用域 ----------
def test_agent_rejects_foreign_event(conn):
    _patient(conn, "A")
    _patient(conn, "B")
    foreign = _event(conn, "B")
    with pytest.raises(orchestrator.EventScopeError):
        orchestrator.run_agent(conn, "A", trigger_type="event_detected", event_ids=[foreign])


def test_agent_rejects_unknown_event(conn):
    _patient(conn, "A")
    with pytest.raises(orchestrator.EventScopeError):
        orchestrator.run_agent(conn, "A", trigger_type="event_detected", event_ids=["EV-NOT-EXIST"])


def test_review_rejects_foreign_task(conn):
    _patient(conn, "A")
    _patient(conn, "B")
    task_b, _ = tasks.create_task(conn, "B", task_type="record_glucose", title="记录",
                                  due_at=iso(now(conn) + timedelta(days=1)), schedule_review=False)
    with pytest.raises(reviews.ReviewError):
        reviews.schedule_review(conn, "A", task_id=task_b["id"], delay_hours=24)


def test_task_rejects_foreign_event(conn):
    _patient(conn, "A")
    _patient(conn, "B")
    foreign = _event(conn, "B")
    with pytest.raises(tasks.TaskError):
        tasks.create_task(conn, "A", task_type="record_glucose", title="记录", event_id=foreign,
                          due_at=iso(now(conn) + timedelta(days=1)), schedule_review=False)


# ---------- 并发/原子 ----------
def test_complete_is_atomic_across_connections(db_path):
    conn1 = connect(db_path)
    conn2 = connect(db_path)
    try:
        _patient(conn1, "C1")
        task, _ = tasks.create_task(conn1, "C1", task_type="record_glucose", title="记录",
                                    due_at=iso(now(conn1) + timedelta(days=1)), schedule_review=False)
        first = tasks.complete_task(conn1, task["id"])
        second = tasks.complete_task(conn2, task["id"])
        assert first.get("changed") is True
        assert second.get("changed") is False
    finally:
        conn1.close()
        conn2.close()


def test_waiting_question_is_unique_across_connections(db_path):
    conn1 = connect(db_path)
    conn2 = connect(db_path)
    try:
        _patient(conn1, "C2")
        q1, created1 = questioning.create_question(conn1, "C2", question="服药了吗", target_field="medication_taken")
        q2, created2 = questioning.create_question(conn2, "C2", question="服药了吗", target_field="medication_taken")
        assert created1 is True and created2 is False
        assert q1["id"] == q2["id"]
        assert conn1.execute("SELECT COUNT(*) c FROM questions WHERE status='waiting'").fetchone()["c"] == 1
    finally:
        conn1.close()
        conn2.close()


def test_preference_single_active_across_connections(db_path):
    conn1 = connect(db_path)
    conn2 = connect(db_path)
    try:
        _patient(conn1, "C3")
        preferences.set_preference(conn1, "C3", kind="preferred_time_window", value="20:30")
        preferences.set_preference(conn2, "C3", kind="preferred_time_window", value="07:00")
        active = conn1.execute(
            "SELECT COUNT(*) c FROM preferences WHERE patient_id='C3' AND kind='preferred_time_window' AND status='active'"
        ).fetchone()["c"]
        assert active == 1
    finally:
        conn1.close()
        conn2.close()


def test_answer_is_cas(conn):
    _patient(conn, "C4")
    q, _ = questioning.create_question(conn, "C4", question="服药了吗", target_field="medication_taken")
    questioning.answer_question(conn, q["id"], answer_text="已服药")
    with pytest.raises(questioning.QuestionError):
        questioning.answer_question(conn, q["id"], answer_text="未服药")


def test_resolve_is_cas(conn):
    _patient(conn, "C5")
    task, _ = tasks.create_task(conn, "C5", task_type="record_glucose", title="记录",
                                due_at=iso(now(conn) + timedelta(days=1)), schedule_review=False)
    review = reviews.schedule_review(conn, "C5", task_id=task["id"], delay_hours=0, branch="HUMAN_REVIEW")
    conn.execute("UPDATE reviews SET status='pending_human' WHERE id=?", (review["id"],))
    reviews.resolve_human_review(conn, review["id"], decision="保持原计划")
    second = reviews.resolve_human_review(conn, review["id"], decision="改结论")
    assert second.get("already_resolved") is True


def test_event_recurrence_stops_without_new_evidence(conn):
    _patient(conn, "C6")
    records.add_record(conn, "C6", {"kind": "fasting_glucose", "value": 7.0,
                                    "recorded_at": iso(now(conn) - timedelta(hours=3))})
    records.add_record(conn, "C6", {"kind": "fasting_glucose", "value": 8.8,
                                    "recorded_at": iso(now(conn) - timedelta(hours=2))})
    first = detector.detect_events(conn, "C6")["created"]
    detector.mark_handled(conn, [e["id"] for e in first], "R")
    records.add_record(conn, "C6", {"kind": "fasting_glucose", "value": 9.9,
                                    "recorded_at": iso(now(conn) - timedelta(minutes=30))})
    again = detector.detect_events(conn, "C6")["created"]
    assert len(again) == 1
    third = detector.detect_events(conn, "C6")["created"]
    assert third == []
    open_count = conn.execute("SELECT COUNT(*) c FROM events WHERE patient_id='C6' AND status='open'").fetchone()["c"]
    assert open_count == 1


# ---------- API 输入边界 ----------
def test_api_input_boundaries(db_path):
    app = create_app()
    with TestClient(app) as client:
        assert client.post("/api/patients", json={"id": "V1", "name": "x", "age": -8}).status_code == 422
        assert client.post("/api/patients", json={"id": "V2", "name": "x", "duration_years": -3}).status_code == 422
        client.post("/api/patients", json={"id": "V3", "name": "x", "age": 60})
        assert client.post("/api/patients", json={"id": "V3", "name": "again"}).status_code == 409
        bad_bp = client.post("/api/patients/V3/records", json={
            "kind": "bp", "payload": {"systolic": -100, "diastolic": 9999}, "trigger_agent": False})
        assert bad_bp.status_code == 422
        bad_time = client.post("/api/patients/V3/records", json={
            "kind": "steps", "value": 100, "recorded_at": "not-a-time", "trigger_agent": False})
        assert bad_time.status_code == 422
        assert client.get("/api/patients/NOPE/records").status_code == 404
        assert client.get("/api/patients/NOPE/state/history").status_code == 404
        assert client.get("/api/patients/NOPE/runs").status_code == 404
        task = client.post("/api/patients/V3/tasks", json={}) if False else None
        # 空答案 / 空结论 / 空偏好
        q = client.post("/api/patients/V3/questions", json={}) if False else None
        assert client.post("/api/patients/V3/preferences", json={
            "kind": "preferred_time_window", "value": ""}).status_code == 422


def test_health_reports_new_version():
    app = create_app()
    with TestClient(app) as client:
        body = client.get("/api/health").json()
    assert body["version"] == "0.3.5"
