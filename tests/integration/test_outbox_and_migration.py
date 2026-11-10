"""8 个残余根因的回归：并发完成、迁移自检、stale key、容差扫描、outbox 补偿、通知 404。"""
from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from backend.app.automation import outbox, scheduler, triggers
from backend.app.db.connection import connect, iso, now
from backend.app.main import create_app
from backend.app.services import patients
from backend.app.tasks import service as tasks


def _client():
    app = create_app()
    return TestClient(app)


def test_connect_normalizes_legacy_synthetic(db_path):
    conn = connect(db_path)
    patients.create_patient(conn, {"id": "LEG", "name": "旧", "age": 60})
    conn.execute("UPDATE patients SET is_synthetic=0 WHERE id='LEG'")
    conn.close()
    reopened = connect(db_path)
    assert patients.get_patient(reopened, "LEG")["is_synthetic"] is True
    reopened.close()


def test_stale_task_key_does_not_block_new_task(conn):
    patients.create_patient(conn, {"id": "ST", "name": "旧键", "age": 60})
    d1 = iso(now(conn) + timedelta(hours=24))
    d2 = iso(now(conn) + timedelta(days=10))
    task, _ = tasks.create_task(conn, "ST", task_type="record_weight", title="称重",
                                due_at=d2, schedule_review=False)
    # 模拟旧版：改到 D2 但 dedupe_key 仍是 D1
    stale = tasks._dedupe_key("ST", "record_weight", d1)
    conn.execute("UPDATE tasks SET dedupe_key=? WHERE id=?", (stale, task["id"]))
    created, flag = tasks.create_task(conn, "ST", task_type="record_weight", title="称重",
                                      due_at=d1, schedule_review=False)
    assert flag is True
    assert created["id"] != task["id"]


def test_future_tolerance_record_gets_scan_job(db_path):
    with _client() as client:
        client.post("/api/patients", json={"id": "TOL", "name": "容差", "age": 60})
        recorded = iso(now() + timedelta(minutes=4))
        resp = client.post("/api/patients/TOL/records", json={
            "kind": "fasting_glucose", "value": 3.1, "recorded_at": recorded, "trigger_agent": False})
        assert resp.status_code == 201
        jobs = client.get("/api/automation/jobs?status=pending").json()["items"]
        assert any(j["kind"] == "event_scan" for j in jobs)
        client.post("/api/automation/tick", json={"advance_seconds": 300})
        events = client.get("/api/patients/TOL/events").json()["items"]
        assert events, "到点后必须补扫并产生事件"


def test_record_partial_success_outbox_compensates(db_path, monkeypatch):
    calls = {"n": 0}
    real = triggers.after_records

    def boom(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("injected automation failure")
        return real(*args, **kwargs)

    monkeypatch.setattr(triggers, "after_records", boom)
    with _client() as client:
        client.post("/api/patients", json={"id": "OUT", "name": "补偿", "age": 60})
        resp = client.post("/api/patients/OUT/records", json={
            "kind": "fasting_glucose", "value": 7.2, "recorded_at": iso(now()), "trigger_agent": True})
        assert resp.status_code == 201
        assert resp.json().get("partial_success") is True
        client.post("/api/automation/tick", json={})
        conn = connect(db_path)
        try:
            assert conn.execute("SELECT COUNT(*) c FROM automation_outbox WHERE status='done'").fetchone()["c"] == 1
        finally:
            conn.close()


def test_preference_partial_success_outbox(db_path, monkeypatch):
    calls = {"n": 0}
    real = triggers.after_preference_change

    def boom(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("injected preference failure")
        return real(*args, **kwargs)

    monkeypatch.setattr(triggers, "after_preference_change", boom)
    with _client() as client:
        client.post("/api/patients", json={"id": "OUT2", "name": "偏好", "age": 60})
        resp = client.post("/api/patients/OUT2/preferences", json={
            "kind": "preferred_time_window", "value": "20:30"})
        assert resp.status_code == 200
        assert resp.json().get("partial_success") is True
        client.post("/api/automation/tick", json={})
        conn = connect(db_path)
        try:
            assert conn.execute("SELECT COUNT(*) c FROM automation_outbox WHERE status='done'").fetchone()["c"] == 1
        finally:
            conn.close()


def test_complete_partial_then_tick_compensates(db_path, monkeypatch):
    calls = {"n": 0}
    real = triggers.after_task_completed

    def boom(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("injected complete failure")
        return real(*args, **kwargs)

    monkeypatch.setattr(triggers, "after_task_completed", boom)
    with _client() as client:
        client.post("/api/patients", json={"id": "OUT3", "name": "完成", "age": 60})
        conn = connect(db_path)
        try:
            task, _ = tasks.create_task(conn, "OUT3", task_type="record_glucose", title="记录",
                                        due_at=iso(now(conn) + timedelta(days=1)), schedule_review=True)
        finally:
            conn.close()
        resp = client.post(f"/api/tasks/{task['id']}/complete", json={"changed_by": "patient", "run_agent": False})
        assert resp.status_code == 200
        assert resp.json().get("partial_success") is True
        client.post("/api/automation/tick", json={})
        conn = connect(db_path)
        try:
            assert conn.execute("SELECT COUNT(*) c FROM automation_outbox WHERE status='done'").fetchone()["c"] == 1
            status = conn.execute("SELECT status FROM reviews WHERE patient_id='OUT3'").fetchone()["status"]
            assert status != "scheduled", "补偿后复评必须已被评估"
        finally:
            conn.close()


def test_notifications_404_for_missing_patient(db_path):
    with _client() as client:
        assert client.get("/api/patients/NOPE/notifications").status_code == 404


def test_complete_second_request_has_no_new_agent_run(db_path):
    with _client() as client:
        client.post("/api/patients", json={"id": "ONE", "name": "一次", "age": 60})
        conn = connect(db_path)
        try:
            task, _ = tasks.create_task(conn, "ONE", task_type="record_glucose", title="记录",
                                        due_at=iso(now(conn) + timedelta(days=1)), schedule_review=False)
        finally:
            conn.close()
        first = client.post(f"/api/tasks/{task['id']}/complete", json={"changed_by": "patient", "run_agent": True})
        assert first.status_code == 200
        second = client.post(f"/api/tasks/{task['id']}/complete", json={"changed_by": "patient", "run_agent": True})
        assert second.json().get("already_done") is True
        assert second.json().get("run") is None
