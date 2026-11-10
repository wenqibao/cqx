"""F06 新增数据主动触发 / F07 复评到期调度：事件发生即入队并由后台执行，无需人工点击。"""
from __future__ import annotations

import sqlite3
from typing import Any

from backend.app.agent import orchestrator
from backend.app.automation import scheduler
from backend.app.db.connection import dumps, iso, now
from backend.app.events.detector import detect_events
from backend.app.questioning import service as questioning
from backend.app.services import notifications
from backend.app.services.records import add_record
from backend.app.safety import gate

METRIC_FIELDS = {"medication_taken", "steps", "fasting_glucose", "weight"}


def after_records(
    conn: sqlite3.Connection,
    patient_id: str,
    records: list[dict[str, Any]],
    *,
    source: str = "record_created",
    run_immediately: bool = True,
) -> dict[str, Any]:
    """保存记录后自动检测事件；有事件则立即启动 Agent（并留下调度任务记录）。"""
    result = detect_events(conn, patient_id, trigger=source)
    created = result["created"]
    triggered_runs: list[dict[str, Any]] = []
    jobs: list[dict[str, Any]] = []
    for event in created:
        gate.audit(
            conn,
            actor="system",
            action="event_detected",
            decision="info",
            patient_id=patient_id,
            code=event["code"],
            detail={"event_id": event["id"], "severity": event["severity"]},
        )
        if event["severity"] == "high":
            notifications.create_notification(
                conn,
                patient_id,
                kind="agent_alert",
                title=f"检测到高风险事件：{event['code']}",
                body=event["message"],
                ref_type="event",
                ref_id=event["id"],
            )
        job = scheduler.enqueue_job(
            conn,
            kind="agent_run",
            patient_id=patient_id,
            ref_id=event["id"],
            run_at=iso(now(conn)),
            payload={"trigger_type": "event_detected", "event_id": event["id"], "source": source},
        )
        jobs.append(job)
        if run_immediately:
            outcome = orchestrator.run_agent(
                conn,
                patient_id,
                trigger_type="event_detected",
                trigger_ref=event["id"],
                event_ids=[event["id"]],
            )
            triggered_runs.append(outcome)
            scheduler.mark_job_done(conn, job["id"], {"run_id": outcome["run_id"]})
    return {
        "patient_id": patient_id,
        "records": len(records),
        "events_created": created,
        "jobs": jobs,
        "runs": triggered_runs,
    }


def after_answer(conn: sqlite3.Connection, question: dict[str, Any]) -> dict[str, Any]:
    """F21：患者答复后把答案转成真实数据（或标记不确定），并恢复同一管理流程。"""
    patient_id = question["patient_id"]
    field = question.get("target_field")
    answer = question.get("answer") or {}
    text = (question.get("answer_text") or "").strip()
    recorded = None
    uncertainty = bool(answer.get("uncertain"))
    if field in METRIC_FIELDS and not uncertainty:
        value = answer.get("value")
        if value is None:
            lowered = text.lower()
            if field == "medication_taken":
                if any(k in text for k in ("已按时", "按时", "吃了", "是")):
                    value = 1
                elif any(k in text for k in ("未完成", "没吃", "漏", "否")):
                    value = 0
            elif text.replace(".", "", 1).isdigit():
                value = float(text)
        if value is not None:
            recorded = add_record(
                conn,
                patient_id,
                {
                    "kind": field,
                    "value": value,
                    "recorded_at": iso(now(conn)),
                    "source": "question_answer",
                    "note": f"由问题 {question['id']} 的答复录入",
                },
            )
    run = orchestrator.run_agent(
        conn,
        patient_id,
        trigger_type="answer_received",
        trigger_ref=question["id"],
        message=f"患者回答：{text}",
    )
    return {"question_id": question["id"], "recorded": recorded, "uncertain": uncertainty, "run": run}


def after_task_completed(conn: sqlite3.Connection, task: dict[str, Any], *, changed_by: str = "patient") -> dict[str, Any]:
    """任务完成后立即评估关联复评，避免"已完成但一直挂着"。"""
    from backend.app.reviews import service as reviews

    rows = conn.execute(
        "SELECT * FROM reviews WHERE task_id=? AND status='scheduled'", (task["id"],)
    ).fetchall()
    evaluated = [reviews.evaluate_review(conn, r["id"], closer=changed_by) for r in rows]
    return {"task_id": task["id"], "reviews": evaluated}


def after_preference_change(conn: sqlite3.Connection, patient_id: str) -> dict[str, Any]:
    """偏好更新后重新评估待办任务时间（F25），只调整非医疗记录类任务。"""
    from backend.app.memory import preferences
    from backend.app.planning.planner import _apply_preference
    from backend.app.db.connection import parse_ts
    from backend.app.tasks import service as tasks

    pref = preferences.preferred_time_window(conn, patient_id)
    updated = []
    if pref:
        for task in tasks.list_tasks(conn, patient_id, status="pending"):
            if task["task_type"] in ("confirm_medication", "record_glucose"):
                continue
            if str(task["task_type"]).startswith("review_"):
                continue  # PREF-SCOPE-01：人工复核类任务不受普通时间偏好影响
            current = parse_ts(task["due_at"])
            if not current:
                continue
            new_due = _apply_preference(current, pref)
            if iso(new_due) != task["due_at"]:
                updated.append(
                    tasks.reschedule_task(
                        conn,
                        task["id"],
                        due_at=iso(new_due),
                        reason=f"患者更新了时间偏好: {pref}",
                        changed_by="agent",
                    )
                )
    return {"preference": pref, "updated": updated}
