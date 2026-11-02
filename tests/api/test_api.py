"""HTTP API 契约测试（F15-F18 后端部分）。"""
from __future__ import annotations


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["database"]["ok"] is True
    assert body["llm_mode"] in ("mock", "real")
    assert "演示" in body["disclaimer"]


def test_patient_crud_and_state(client):
    r = client.post(
        "/api/patients",
        json={"id": "API1", "name": "接口患者", "age": 60, "duration_years": 7, "goals": ["稳定"]},
    )
    assert r.status_code == 201
    assert client.get("/api/patients").json()["count"] >= 1
    detail = client.get("/api/patients/API1").json()
    assert detail["profile"]["complete"] is True
    state = client.get("/api/patients/API1/state").json()
    assert state["patient"]["id"] == "API1"
    assert client.get("/api/patients/NOPE").status_code == 404


def test_record_post_triggers_agent(client):
    client.post(
        "/api/patients", json={"id": "API2", "name": "触发患者", "age": 62, "duration_years": 9, "goals": ["稳定"]}
    )
    for value in (7.0, 7.6, 8.1, 8.8, 9.3):
        r = client.post(
            "/api/patients/API2/records", json={"kind": "fasting_glucose", "value": value, "trigger_agent": False}
        )
        assert r.status_code == 201
    r = client.post("/api/patients/API2/records", json={"kind": "fasting_glucose", "value": 9.6})
    body = r.json()
    assert body["automation"] is not None
    assert body["automation"]["events_created"]
    run_id = body["automation"]["runs"][0]["run_id"]
    trace = client.get(f"/api/runs/{run_id}").json()
    assert trace["run"]["id"] == run_id
    assert any(s["kind"] == "tool_call" for s in trace["steps"])


def test_duplicate_record_returns_duplicate(client):
    client.post("/api/patients", json={"id": "API3", "name": "重复", "age": 50, "duration_years": 2, "goals": ["稳定"]})
    payload = {"kind": "steps", "value": 4000, "recorded_at": "2026-02-02T08:00:00Z", "trigger_agent": False}
    first = client.post("/api/patients/API3/records", json=payload).json()["record"]
    second = client.post("/api/patients/API3/records", json=payload).json()["record"]
    assert first["duplicate"] is False
    assert second["duplicate"] is True


def test_invalid_record_returns_422(client):
    client.post("/api/patients", json={"id": "API4", "name": "非法", "age": 50, "duration_years": 2, "goals": ["稳定"]})
    r = client.post("/api/patients/API4/records", json={"kind": "blood_magic", "value": 1})
    assert r.status_code == 422


def test_csv_import_endpoint(client):
    client.post("/api/patients", json={"id": "API5", "name": "导入", "age": 50, "duration_years": 2, "goals": ["稳定"]})
    csv_text = "kind,value,recorded_at\nsteps,5000,2026-01-01T08:00:00Z\nbogus,1,2026-01-01T09:00:00Z\n"
    body = client.post(
        "/api/patients/API5/records/import", json={"csv_text": csv_text, "trigger_agent": False}
    ).json()
    assert body["imported"] == 1 and body["failed"] == 1


def test_tasks_questions_preferences_endpoints(client):
    client.post("/api/patients", json={"id": "API6", "name": "全流程", "age": 55, "duration_years": 4, "goals": ["稳定"]})
    run = client.post("/api/patients/API6/agent/runs", json={"message": "为什么需要连续记录血糖"}).json()
    assert run["intent"] == "knowledge_question"
    knowledge = client.get("/api/knowledge/search", params={"q": "连续记录血糖"}).json()
    assert knowledge["found"] is True
    docs = client.get("/api/knowledge").json()
    assert docs["count"] == 4

    client.post("/api/patients", json={"id": "API7", "name": "提问", "age": 55, "duration_years": 4, "goals": ["稳定"]})
    for value in (7.0, 8.2, 9.1):
        client.post(
            "/api/patients/API7/records", json={"kind": "fasting_glucose", "value": value, "trigger_agent": False}
        )
    run = client.post("/api/patients/API7/agent/runs", json={}).json()
    assert run["waiting_user"] is True
    questions = client.get("/api/patients/API7/questions", params={"status": "waiting"}).json()["items"]
    assert questions
    answered = client.post(
        f"/api/questions/{questions[0]['id']}/answer", json={"answer_text": "已按时完成"}
    ).json()
    assert answered["question"]["status"] == "answered"
    assert answered["resume"]["recorded"]["kind"] == "medication_taken"

    prefs = client.post(
        "/api/patients/API7/preferences", json={"kind": "preferred_time_window", "value": "08:00"}
    ).json()
    assert prefs["preference"]["value"] == "08:00"
    listed = client.get("/api/patients/API7/preferences").json()["items"]
    assert listed[0]["kind"] == "preferred_time_window"


def test_task_complete_and_review(client):
    from backend.app.db.connection import connect

    client.post("/api/patients", json={"id": "API8", "name": "复评", "age": 55, "duration_years": 4, "goals": ["稳定"]})
    conn = connect()
    try:
        from backend.app.tasks import service as tasks

        task, _ = tasks.create_task(conn, "API8", task_type="record_glucose", title="记录血糖")
    finally:
        conn.close()
    resp = client.post(f"/api/tasks/{task['id']}/complete", json={"changed_by": "patient"}).json()
    assert resp["task"]["status"] == "done"
    assert resp["reviews"][0]["branch"] in ("CLOSED", "MISSING_DATA", "HUMAN_REVIEW")
    detail = client.get(f"/api/tasks/{task['id']}").json()
    assert len(detail["versions"]) >= 2


def test_automation_tick_and_clock(client):
    client.post("/api/patients", json={"id": "API9", "name": "调度", "age": 55, "duration_years": 4, "goals": ["稳定"]})
    from backend.app.db.connection import connect
    from backend.app.tasks import service as tasks

    conn = connect()
    try:
        tasks.create_task(conn, "API9", task_type="record_glucose", title="记录血糖")
    finally:
        conn.close()
    tick = client.post("/api/automation/tick", json={"advance_seconds": 86400 * 3}).json()
    assert tick["clock_offset_seconds"] == 86400 * 3
    assert tick["processed"]
    jobs = client.get("/api/automation/jobs").json()["items"]
    assert jobs


def test_system_mode_and_audit(client):
    mode = client.get("/api/system/mode").json()
    assert mode["llm_mode"] in ("mock", "real")
    audit = client.get("/api/system/audit").json()
    assert "NO_EVIDENCE" in audit["rejection_codes"]
