"""集成测试：F06/F08-F14/F21-F26 端到端行为。"""
from __future__ import annotations

from datetime import timedelta

from backend.app.agent.orchestrator import run_agent
from backend.app.audit.trace import trace
from backend.app.automation import scheduler, triggers
from backend.app.db.connection import advance_clock, iso, now
from backend.app.questioning import service as questioning
from backend.app.reviews import service as reviews
from backend.app.services import patients, records, state
from backend.app.tasks import service as tasks


def _mk(conn, pid="A001"):
    return patients.create_patient(
        conn, {"id": pid, "name": "集成患者", "age": 58, "duration_years": 8, "goals": ["稳定血糖"]}
    )


def _rise(conn, pid):
    base = now(conn)
    for i, value in enumerate([7.0, 7.6, 8.2, 8.9, 9.4]):
        records.add_record(
            conn,
            pid,
            {"kind": "fasting_glucose", "value": value, "recorded_at": iso(base - timedelta(hours=24 * (5 - i)))},
        )


def test_record_save_triggers_event_and_agent(conn):
    _mk(conn)
    _rise(conn, "A001")
    last = records.add_record(
        conn, "A001", {"kind": "fasting_glucose", "value": 9.6, "recorded_at": iso(now(conn))}
    )
    result = triggers.after_records(conn, "A001", [last])
    assert result["events_created"], "保存记录后必须自动产生事件"
    assert result["runs"], "有事件时必须自动启动 Agent（无需点击）"
    run_id = result["runs"][0]["run_id"]
    detail = trace(conn, run_id)
    assert detail["run"]["trigger_type"] == "event_detected"
    assert detail["run"]["llm_mode"] == "mock"
    assert any(s["kind"] == "tool_call" for s in detail["steps"])
    task_rows = conn.execute("SELECT * FROM tasks WHERE patient_id='A001'").fetchall()
    assert task_rows, "Agent 必须真实创建任务"


def test_agent_creates_task_and_trace_is_reproducible(conn):
    _mk(conn)
    _rise(conn, "A001")
    out = run_agent(conn, "A001", trigger_type="user_request")
    assert out["status"] in ("completed", "waiting_user")
    assert out["run_id"].startswith("RUN-")
    detail = trace(conn, out["run_id"])
    phases = {s["phase"] for s in detail["steps"]}
    assert {"perceive", "plan", "validate", "act", "observe"} <= phases
    assert detail["run"]["finished_at"] is not None


def test_missing_data_triggers_question_then_resume(conn):
    _mk(conn)
    _rise(conn, "A001")  # 无服药记录 → 需要主动询问
    out = run_agent(conn, "A001", trigger_type="user_request")
    questions = questioning.list_questions(conn, "A001", status="waiting")
    assert questions, "缺信息时必须主动提问"
    assert out["status"] == "waiting_user"
    q = questions[0]
    answered = questioning.answer_question(conn, q["id"], answer_text="已按时完成")
    assert answered["status"] == "answered"
    resume = triggers.after_answer(conn, answered)
    assert resume["recorded"] is not None, "答复要落成真实记录"
    assert resume["recorded"]["kind"] == "medication_taken"
    assert resume["run"]["run_id"]


def test_answer_uncertain_does_not_fabricate(conn):
    _mk(conn)
    _rise(conn, "A001")
    run_agent(conn, "A001", trigger_type="user_request")
    q = questioning.list_questions(conn, "A001", status="waiting")[0]
    answered = questioning.answer_question(conn, q["id"], answer_text="记不清")
    resume = triggers.after_answer(conn, answered)
    assert resume["uncertain"] is True
    assert resume["recorded"] is None


def test_task_completion_leads_to_closed_review(conn):
    _mk(conn)
    task, created = tasks.create_task(
        conn,
        "A001",
        task_type="record_glucose",
        title="记录空腹血糖",
        due_at=iso(now(conn) + timedelta(hours=12)),
        required_fields=["fasting_glucose"],
    )
    assert created is True
    review_scheduled = conn.execute("SELECT * FROM reviews WHERE task_id=?", (task["id"],)).fetchone()
    assert review_scheduled["status"] == "scheduled"
    _rise(conn, "A001")
    done = tasks.complete_task(conn, task["id"], changed_by="patient")
    assert done["status"] == "done"
    result = triggers.after_task_completed(conn, done)
    branch = result["reviews"][0]["branch"]
    assert branch == "CLOSED"
    assert result["reviews"][0]["status"] == "completed"


def test_review_missing_data_branch(conn):
    _mk(conn)
    task, _ = tasks.create_task(
        conn, "A001", task_type="record_activity", title="补录步数", required_fields=["steps"]
    )
    review = conn.execute("SELECT * FROM reviews WHERE task_id=?", (task["id"],)).fetchone()
    tasks.mark_missed(conn, task["id"])
    evaluated = reviews.evaluate_review(conn, review["id"])
    assert evaluated["branch"] == "MISSING_DATA"


def test_human_review_branch_for_high_risk(conn):
    _mk(conn)
    records.add_record(conn, "A001", {"kind": "fasting_glucose", "value": 3.2, "recorded_at": iso(now(conn))})
    out = run_agent(conn, "A001", trigger_type="user_request")
    assert out["intent"] == "escalation"
    rows = conn.execute("SELECT * FROM reviews WHERE patient_id='A001' AND branch='HUMAN_REVIEW'").fetchall()
    assert rows and rows[0]["status"] == "pending_human"
    resolved = reviews.resolve_human_review(conn, rows[0]["id"], decision="已电话联系并建议就诊")
    assert resolved["status"] == "completed"


def test_scheduler_tick_runs_due_review_without_click(conn):
    _mk(conn)
    task, _ = tasks.create_task(conn, "A001", task_type="record_glucose", title="记录血糖")
    review = conn.execute("SELECT * FROM reviews WHERE task_id=?", (task["id"],)).fetchone()
    advance_clock(conn, 3600 * 24 * 3)
    result = scheduler.tick(conn)
    assert any(p["kind"] == "review_due" for p in result["processed"])
    updated = reviews.get_review(conn, review["id"])
    assert updated["status"] in ("completed", "pending_human")


def test_scheduler_is_idempotent(conn):
    _mk(conn)
    tasks.create_task(conn, "A001", task_type="record_glucose", title="记录血糖")
    advance_clock(conn, 3600 * 24 * 3)
    first = scheduler.tick(conn)
    second = scheduler.tick(conn)
    review_first = [p for p in first["processed"] if p["kind"] == "review_due"]
    review_second = [p for p in second["processed"] if p["kind"] == "review_due"]
    assert review_first and not review_second


def test_duplicate_record_does_not_rerun_agent(conn):
    _mk(conn)
    _rise(conn, "A001")
    data = {"kind": "fasting_glucose", "value": 9.7, "recorded_at": iso(now(conn))}
    first = records.add_record(conn, "A001", data)
    triggers.after_records(conn, "A001", [first])
    runs_after_first = conn.execute("SELECT COUNT(*) AS c FROM agent_runs").fetchone()["c"]
    second = records.add_record(conn, "A001", data)
    assert second["duplicate"] is True
    runs_after_second = conn.execute("SELECT COUNT(*) AS c FROM agent_runs").fetchone()["c"]
    assert runs_after_second == runs_after_first


def test_negotiation_updates_task_and_saves_version(conn):
    _mk(conn)
    task, _ = tasks.create_task(
        conn, "A001", task_type="record_activity", title="记录步数", due_at=iso(now(conn) + timedelta(hours=20))
    )
    out = run_agent(conn, "A001", trigger_type="user_request", message="我19:00上班，改成08:00记录步数")
    assert out["intent"] == "negotiate_plan"
    updated = tasks.get_task(conn, task["id"])
    assert updated["version"] >= 2
    assert updated["due_at"].endswith("Z")
    history = tasks.versions(conn, task["id"])
    assert len(history) >= 2
    pref = conn.execute("SELECT * FROM preferences WHERE patient_id='A001' AND status='active'").fetchone()
    assert pref is not None and pref["value"].startswith("08:00")


def test_knowledge_question_cites_source(conn):
    _mk(conn)
    out = run_agent(conn, "A001", trigger_type="user_request", message="为什么需要连续记录血糖")
    assert out["intent"] == "knowledge_question"
    assert out["evidence"], "回答必须带来源"
    assert out["evidence"][0]["citation"].startswith("中国")
    assert out["rejections"] == []


def test_no_evidence_blocks_claim(conn):
    _mk(conn)
    out = run_agent(conn, "A001", trigger_type="user_request", message="量子纠缠和超导材料能谱是什么")
    codes = [r["code"] for r in out["rejections"]]
    assert "NO_EVIDENCE" in codes
    assert any("没有足够资料" in r for r in out["responses"])


def test_forbidden_request_blocked_and_audited(conn):
    _mk(conn)
    out = run_agent(conn, "A001", trigger_type="user_request", message="帮我把降糖药停了吧")
    assert out["intent"] == "unsafe_request"
    assert out["status"] == "blocked"
    row = conn.execute("SELECT * FROM audit_log WHERE decision='reject'").fetchone()
    assert row is not None


def test_multi_event_merge_and_priority(conn):
    _mk(conn)
    base = now(conn)
    for i, value in enumerate([7.0, 7.8, 8.6, 9.2]):
        records.add_record(
            conn,
            "A001",
            {"kind": "fasting_glucose", "value": value, "recorded_at": iso(base - timedelta(hours=24 * (4 - i)))},
        )
    for hours, value in [(40, 0), (12, 0)]:
        records.add_record(
            conn, "A001", {"kind": "medication_taken", "value": value, "recorded_at": iso(base - timedelta(hours=hours))}
        )
    records.add_record(conn, "A001", {"kind": "steps", "value": 1500, "recorded_at": iso(base - timedelta(hours=20))})
    out = run_agent(conn, "A001", trigger_type="user_request")
    assert out["priority_order"], "多事件必须有明确优先级"
    created = [a for a in out["actions"] if a["tool"] == "create_task" and a["result"].get("created")]
    types = conn.execute("SELECT task_type, COUNT(*) c FROM tasks WHERE patient_id='A001' GROUP BY task_type").fetchall()
    assert all(row["c"] == 1 for row in types), "同类任务不能重复入库"


def test_preference_applies_to_new_tasks(conn):
    _mk(conn)
    from backend.app.memory import preferences

    preferences.set_preference(conn, "A001", kind="preferred_time_window", value="08:00")
    _rise(conn, "A001")
    out = run_agent(conn, "A001", trigger_type="user_request")
    rows = conn.execute("SELECT due_at FROM tasks WHERE patient_id='A001'").fetchall()
    assert rows
    assert any(r["due_at"][11:13] == "08" for r in rows)


def test_state_snapshot_written_after_run(conn):
    _mk(conn)
    _rise(conn, "A001")
    run_agent(conn, "A001", trigger_type="user_request")
    snap = state.latest_snapshot(conn, "A001")
    assert snap is not None and snap["patient"]["id"] == "A001"
