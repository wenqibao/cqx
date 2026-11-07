"""副作用 outbox：业务写入成功后，自动化失败可重试补偿。"""
from __future__ import annotations

import sqlite3
from typing import Any

from backend.app.db.connection import dumps, iso, loads, now
from backend.app.util import new_id

MAX_ATTEMPTS = 3


def enqueue(conn: sqlite3.Connection, kind: str, patient_id: str, payload: dict[str, Any]) -> str:
    oid = new_id("outbox")
    ts = iso(now(conn))
    conn.execute(
        "INSERT INTO automation_outbox(id,kind,patient_id,payload,status,attempts,created_at,updated_at) "
        "VALUES(?,?,?,?,'pending',0,?,?)",
        (oid, kind, patient_id, dumps(payload), ts, ts),
    )
    return oid


def pending(conn: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM automation_outbox WHERE status='pending' ORDER BY created_at LIMIT ?", (limit,)
    ).fetchall()
    return [dict(row) for row in rows]


def _dispatch(conn: sqlite3.Connection, kind: str, patient_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from backend.app.agent import orchestrator
    from backend.app.automation import triggers
    from backend.app.events import detector

    if kind == "after_records":
        return triggers.after_records(conn, patient_id, payload.get("records") or [], source=payload.get("source", "record_created"))
    if kind == "after_preference":
        return triggers.after_preference_change(conn, patient_id)
    if kind == "after_task_completed":
        from backend.app.tasks import service as tasks

        task = tasks.get_task(conn, payload["task_id"])
        if not task:
            return {"skipped": "task_not_found"}
        result = triggers.after_task_completed(conn, task, changed_by=payload.get("changed_by", "patient"))
        if payload.get("run_agent"):
            result["run"] = orchestrator.run_agent(
                conn, patient_id, trigger_type="task_completed", trigger_ref=payload["task_id"]
            )
        return result
    if kind == "scan_later":
        return detector.detect_events(conn, patient_id, trigger="scheduled_scan")
    raise ValueError(f"未知 outbox 类型: {kind}")


def process(conn: sqlite3.Connection, outbox_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM automation_outbox WHERE id=?", (outbox_id,)).fetchone()
    if not row:
        raise KeyError(outbox_id)
    payload = loads(row["payload"], {}) or {}
    try:
        result = _dispatch(conn, row["kind"], row["patient_id"], payload)
    except Exception as exc:
        attempts = int(row["attempts"]) + 1
        status = "failed" if attempts >= MAX_ATTEMPTS else "pending"
        conn.execute(
            "UPDATE automation_outbox SET attempts=?, status=?, last_error=?, updated_at=? WHERE id=?",
            (attempts, status, f"{type(exc).__name__}: {exc}", iso(now(conn)), outbox_id),
        )
        raise
    conn.execute(
        "UPDATE automation_outbox SET status='done', attempts=attempts+1, last_error=NULL, updated_at=? WHERE id=?",
        (iso(now(conn)), outbox_id),
    )
    return result


def process_pending(conn: sqlite3.Connection, limit: int = 20) -> dict[str, Any]:
    done, failed = 0, 0
    for row in pending(conn, limit):
        try:
            process(conn, row["id"])
            done += 1
        except Exception:
            failed += 1
    return {"done": done, "failed": failed}
