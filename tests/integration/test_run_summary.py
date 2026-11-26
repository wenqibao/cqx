"""O1：运行顶部业务结果摘要（API 级，含数据库交叉核验反例）。"""
from __future__ import annotations

from datetime import timedelta

from backend.app.db.connection import dumps, iso, now
from backend.app.services import patients, records
from backend.app.tasks import service as tasks


def _patient(conn, pid):
    patients.create_patient(conn, {"id": pid, "name": pid, "age": 60, "duration_years": 5, "goals": ["稳定"]})
    for kind, value in (("medication_taken", 1), ("steps", 6000)):
        records.add_record(conn, pid, {"kind": kind, "value": value, "recorded_at": iso(now(conn))})


def _run(conn, pid, *, status="completed", intent="event_response", error=None):
    run_id = f"RUN-{pid}-{status}"
    conn.execute(
        "INSERT OR REPLACE INTO agent_runs(id,patient_id,trigger_type,llm_mode,status,intent,input,plan,output,error,started_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (run_id, pid, "event_detected", "mock", status, intent, dumps({"message": "测试"}),
         dumps({"intent": intent}), dumps({"responses": [], "rejections": [], "warnings": []}), error, iso(now(conn))),
    )
    return run_id


def _step(conn, run_id, tool, result, *, status="ok", step_no=1):
    conn.execute(
        "INSERT INTO agent_steps(run_id,step_no,phase,kind,tool_name,payload,status,created_at) "
        "VALUES(?,?,'observe','tool_result',?,?,?,?)",
        (run_id, step_no, tool, dumps({"result": result}), status, iso(now(conn))),
    )


def test_completed_requires_real_database_object(client, conn):
    _patient(conn, "O1A")
    task, _ = tasks.create_task(conn, "O1A", task_type="record_glucose", title="补录",
                                due_at=iso(now(conn) + timedelta(days=1)), schedule_review=False)
    run_id = _run(conn, "O1A")
    _step(conn, run_id, "create_task", {"ok": True, "task_id": task["id"]})
    body = client.get(f"/api/runs/{run_id}").json()
    assert body["summary"]["completed"][0]["refs"] == [task["id"]]
    assert body["summary"]["unfinished"] == []


def test_missing_object_is_not_completed(client, conn):
    _patient(conn, "O1B")
    run_id = _run(conn, "O1B")
    _step(conn, run_id, "create_task", {"ok": True, "task_id": "TASK-NOT-IN-DB"})
    body = client.get(f"/api/runs/{run_id}").json()
    assert body["summary"]["completed"] == []
    assert any(item["code"] == "TRACE_MISMATCH" for item in body["summary"]["unfinished"])


def test_other_patient_object_is_not_completed(client, conn):
    _patient(conn, "O1C")
    _patient(conn, "O1D")
    task, _ = tasks.create_task(conn, "O1D", task_type="record_glucose", title="他人的",
                                due_at=iso(now(conn) + timedelta(days=1)), schedule_review=False)
    run_id = _run(conn, "O1C")
    _step(conn, run_id, "create_task", {"ok": True, "task_id": task["id"]})
    body = client.get(f"/api/runs/{run_id}").json()
    assert body["summary"]["completed"] == []
    assert any(item["code"] == "TRACE_MISMATCH" for item in body["summary"]["unfinished"])


def test_failed_run_error_appears_in_summary(client, conn):
    _patient(conn, "O1E")
    run_id = _run(conn, "O1E", status="failed", error="RuntimeError: upstream unavailable")
    body = client.get(f"/api/runs/{run_id}").json()
    assert any(item["code"] == "RUN_ERROR" and "upstream" in item["message"]
               for item in body["summary"]["unfinished"])
    assert body["summary"]["next_owner"]["role"] == "agent"


def test_pure_failure_is_not_partial_success(client, conn):
    _patient(conn, "O1F")
    run_id = _run(conn, "O1F", status="failed")
    conn.execute(
        "INSERT INTO agent_steps(run_id,step_no,phase,kind,tool_name,payload,status,code,created_at) "
        "VALUES(?,2,'validate','rejection','create_task',?,'rejected','INVALID_TASK_TYPE',?)",
        (run_id, dumps({"rejection": {"code": "INVALID_TASK_TYPE"}}), iso(now(conn))),
    )
    conn.execute("UPDATE agent_runs SET output=? WHERE id=?",
                 (dumps({"rejections": [{"code": "INVALID_TASK_TYPE", "tool": "create_task"}], "warnings": []}), run_id))
    body = client.get(f"/api/runs/{run_id}").json()
    assert body["summary"]["completed"] == []
    assert body["summary"]["partial_success"] is False


def test_completed_plus_unfinished_is_partial_success(client, conn):
    _patient(conn, "O1G")
    task, _ = tasks.create_task(conn, "O1G", task_type="record_glucose", title="补录",
                                due_at=iso(now(conn) + timedelta(days=1)), schedule_review=False)
    run_id = _run(conn, "O1G", status="failed", error="部分动作失败")
    _step(conn, run_id, "create_task", {"ok": True, "task_id": task["id"]})
    body = client.get(f"/api/runs/{run_id}").json()
    assert body["summary"]["completed"]
    assert body["summary"]["unfinished"]
    assert body["summary"]["partial_success"] is True


def test_negotiate_plan_goal(client, conn):
    _patient(conn, "O1H")
    run_id = _run(conn, "O1H", intent="negotiate_plan")
    body = client.get(f"/api/runs/{run_id}").json()
    assert body["summary"]["goal"] == "根据患者时间约束调整计划"


def test_legacy_run_is_stable(client, conn):
    _patient(conn, "O1I")
    conn.execute(
        "INSERT INTO agent_runs(id,patient_id,trigger_type,llm_mode,status,started_at) "
        "VALUES('RUN-LEGACY-O1','O1I','user_request','mock','completed',?)",
        (iso(now(conn)),),
    )
    body = client.get("/api/runs/RUN-LEGACY-O1").json()
    summary = body["summary"]
    assert summary["completed"] == [] and summary["unfinished"] == []
    assert summary["waiting"] is None and summary["refs"] == ["RUN-LEGACY-O1"]
