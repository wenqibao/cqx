"""F11 健康任务管理 + F23 计划协商与动态重规划（版本、去重、合并）。"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any

from backend.app.config import task_rules
from backend.app.db.connection import dumps, iso, loads, now, parse_ts
from backend.app.services.patients import get_patient
from backend.app.util import new_id, short_hash

STATUSES = ("pending", "done", "missed", "cancelled")
MAX_DUE_HOURS = 720


class TaskError(ValueError):
    pass


def _row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "patient_id": row["patient_id"],
        "task_type": row["task_type"],
        "title": row["title"],
        "description": row["description"],
        "status": row["status"],
        "priority": row["priority"],
        "due_at": row["due_at"],
        "event_id": row["event_id"],
        "source_run_id": row["source_run_id"],
        "version": row["version"],
        "required_fields": loads(row["required_fields"], []),
        "meta": loads(row["meta"], {}),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "completed_at": row["completed_at"],
    }


def get_task(conn: sqlite3.Connection, task_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    return _row(row) if row else None


def list_tasks(
    conn: sqlite3.Connection,
    patient_id: str,
    *,
    status: str | None = None,
    task_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    get_patient(conn, patient_id)
    sql = "SELECT * FROM tasks WHERE patient_id=?"
    args: list[Any] = [patient_id]
    if status:
        sql += " AND status=?"
        args.append(status)
    if task_type:
        sql += " AND task_type=?"
        args.append(task_type)
    sql += " ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'missed' THEN 1 ELSE 2 END, priority DESC, due_at"
    sql += " LIMIT ?"
    args.append(limit)
    return [_row(r) for r in conn.execute(sql, args).fetchall()]


def _check_due(conn: sqlite3.Connection, dt: datetime) -> None:
    """HTTP API、服务层与 Agent 工具共用同一 due 契约：未来 0~720 小时。"""
    ts = now(conn)
    if dt <= ts:
        raise TaskError("due_at 必须晚于当前时间")
    if dt - ts > timedelta(hours=MAX_DUE_HOURS):
        raise TaskError("due_at 超出允许范围（最多 720 小时）")


def _dedupe_key(patient_id: str, task_type: str, due_at: str | None) -> str:
    bucket = (due_at or "")[:10] or "nodue"
    return short_hash(f"{patient_id}|{task_type}|{bucket}", length=24)


def find_mergeable(
    conn: sqlite3.Connection, patient_id: str, task_type: str, due_at: str | None
) -> dict[str, Any] | None:
    """F22：同一类可合并任务在去重窗口内视为同一任务，不重复入库。"""
    cfg = task_rules()
    mergeable = task_type in set(cfg.get("mergeable_task_types", []))
    window_hours = int(cfg.get("dedupe_window_hours", 72))
    key = _dedupe_key(patient_id, task_type, due_at)
    row = conn.execute(
        "SELECT * FROM tasks WHERE patient_id=? AND dedupe_key=? AND status IN ('pending','missed')",
        (patient_id, key),
    ).fetchone()
    if row:
        return _row(row)
    if not mergeable:
        return None
    cutoff = iso(now(conn) - timedelta(hours=window_hours))
    row = conn.execute(
        """SELECT * FROM tasks WHERE patient_id=? AND task_type=? AND status='pending' AND created_at>=?
           AND (? IS NULL OR due_at IS NULL OR ABS(julianday(due_at)-julianday(?))*24 <= ?)
           ORDER BY created_at LIMIT 1""",
        (patient_id, task_type, cutoff, due_at, due_at, window_hours),
    ).fetchone()
    return _row(row) if row else None


def create_task(
    conn: sqlite3.Connection,
    patient_id: str,
    *,
    task_type: str,
    title: str,
    description: str = "",
    due_at: str | None = None,
    priority: int = 50,
    event_id: str | None = None,
    run_id: str | None = None,
    required_fields: list[str] | None = None,
    meta: dict[str, Any] | None = None,
    merge: bool = True,
    schedule_review: bool = True,
) -> tuple[dict[str, Any], bool]:
    """返回 (task, created)；created=False 表示合并到已有任务（任务不会重复入库）。"""
    get_patient(conn, patient_id)
    if event_id:
        event_row = conn.execute("SELECT patient_id FROM events WHERE id=?", (event_id,)).fetchone()
        if not event_row or event_row["patient_id"] != patient_id:
            raise TaskError("event_id 不存在或不属于当前患者")
    if merge:
        existing = find_mergeable(conn, patient_id, task_type, due_at)
        if existing:
            merged_meta = dict(existing["meta"])
            event_ids = set(merged_meta.get("event_ids", []))
            if event_id:
                event_ids.add(event_id)
            merged_meta["event_ids"] = sorted(event_ids)
            merged_meta["merged"] = True
            conn.execute(
                "UPDATE tasks SET priority=?, event_id=COALESCE(event_id,?), meta=?, updated_at=? WHERE id=?",
                (max(priority, existing["priority"]), event_id, dumps(merged_meta), iso(now(conn)), existing["id"]),
            )
            return get_task(conn, existing["id"]), False  # type: ignore[return-value]
    ts = iso(now(conn))
    tid = new_id("task")
    key = _dedupe_key(patient_id, task_type, due_at)
    meta = dict(meta or {})
    if event_id:
        meta.setdefault("event_ids", [event_id])
    conn.execute(
        """INSERT INTO tasks(id,patient_id,task_type,title,description,status,priority,due_at,event_id,
                source_run_id,version,required_fields,meta,dedupe_key,created_at,updated_at)
           VALUES(?,?,?,?,?,'pending',?,?,?,?,1,?,?,?,?,?)""",
        (
            tid,
            patient_id,
            task_type,
            title,
            description,
            priority,
            due_at,
            event_id,
            run_id,
            dumps(required_fields or []),
            dumps(meta),
            key,
            ts,
            ts,
        ),
    )
    task = get_task(conn, tid)
    _snapshot(conn, task, "create", "任务创建", "agent" if run_id else "system", run_id)
    if schedule_review:
        from backend.app.reviews import service as review_service

        review_service.schedule_review(
            conn,
            patient_id,
            task_id=tid,
            event_id=event_id,
            run_id=run_id,
            reason="任务创建后自动安排复评",
        )
    return task, True  # type: ignore[return-value]


def _snapshot(
    conn: sqlite3.Connection,
    task: dict[str, Any] | None,
    change_kind: str,
    reason: str | None,
    changed_by: str,
    run_id: str | None = None,
) -> None:
    if not task:
        return
    conn.execute(
        """INSERT INTO task_versions(task_id,version,snapshot,change_kind,reason,changed_by,run_id,created_at)
           VALUES(?,?,?,?,?,?,?,?)""",
        (task["id"], task["version"], dumps(task), change_kind, reason, changed_by, run_id, iso(now(conn))),
    )


def complete_task(
    conn: sqlite3.Connection,
    task_id: str,
    *,
    changed_by: str = "patient",
    run_id: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    task = get_task(conn, task_id)
    if not task:
        raise TaskError(f"任务不存在: {task_id}")
    if task["status"] == "cancelled":
        raise TaskError("已取消的任务不能完成")
    ts = iso(now(conn))
    # COMPLETE-CONCURRENT-01：状态转换必须原子，只有真正改到 done 的请求才算 changed
    cur = conn.execute(
        "UPDATE tasks SET status='done', version=version+1, completed_at=?, updated_at=? "
        "WHERE id=? AND status IN ('pending','missed')",
        (ts, ts, task_id),
    )
    updated = get_task(conn, task_id)
    if cur.rowcount == 0:
        if updated:
            updated["changed"] = False
        return updated  # type: ignore[return-value]
    if updated:
        updated["changed"] = True
    _snapshot(conn, updated, "complete", note or "患者确认完成", changed_by, run_id)
    return updated  # type: ignore[return-value]


def reschedule_task(
    conn: sqlite3.Connection,
    task_id: str,
    *,
    due_at: str,
    reason: str = "患者申请调整时间",
    changed_by: str = "patient",
    run_id: str | None = None,
    title: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    task = get_task(conn, task_id)
    if not task:
        raise TaskError(f"任务不存在: {task_id}")
    if task["status"] != "pending":
        raise TaskError("只能调整待办任务")
    dt = parse_ts(due_at)
    if dt is None:
        raise TaskError("due_at 不是合法时间")
    _check_due(conn, dt)
    old = task["due_at"]
    new_key = _dedupe_key(task["patient_id"], task["task_type"], iso(dt))
    conflict = conn.execute(
        "SELECT id FROM tasks WHERE dedupe_key=? AND id<>? AND status IN ('pending','missed')",
        (new_key, task_id),
    ).fetchone()
    if conflict:
        raise TaskError("目标时间已存在同类任务，请合并或选择其他时间")
    conn.execute(
        "UPDATE tasks SET due_at=?, dedupe_key=?, title=COALESCE(?,title), description=COALESCE(?,description), "
        "version=version+1, updated_at=? WHERE id=?",
        (iso(dt), new_key, title, description, iso(now(conn)), task_id),
    )
    updated = get_task(conn, task_id)
    _snapshot(conn, updated, "reschedule", f"{reason}（原时间 {old}）", changed_by, run_id)
    return updated  # type: ignore[return-value]


def cancel_task(
    conn: sqlite3.Connection, task_id: str, *, reason: str = "取消任务", changed_by: str = "agent", run_id: str | None = None
) -> dict[str, Any]:
    task = get_task(conn, task_id)
    if not task:
        raise TaskError(f"任务不存在: {task_id}")
    if task["status"] in ("done", "cancelled"):
        return task
    conn.execute(
        "UPDATE tasks SET status='cancelled', version=version+1, updated_at=? WHERE id=?",
        (iso(now(conn)), task_id),
    )
    updated = get_task(conn, task_id)
    _snapshot(conn, updated, "cancel", reason, changed_by, run_id)
    return updated  # type: ignore[return-value]


def versions(conn: sqlite3.Connection, task_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM task_versions WHERE task_id=? ORDER BY id", (task_id,)
    ).fetchall()
    return [
        {
            "version": r["version"],
            "change_kind": r["change_kind"],
            "reason": r["reason"],
            "changed_by": r["changed_by"],
            "run_id": r["run_id"],
            "created_at": r["created_at"],
            "snapshot": loads(r["snapshot"], {}),
        }
        for r in rows
    ]


def due_tasks(conn: sqlite3.Connection, at: datetime | None = None) -> list[dict[str, Any]]:
    at = at or now(conn)
    rows = conn.execute(
        "SELECT * FROM tasks WHERE status='pending' AND due_at IS NOT NULL AND due_at<=? ORDER BY due_at",
        (iso(at),),
    ).fetchall()
    return [_row(r) for r in rows]


def mark_missed(conn: sqlite3.Connection, task_id: str) -> dict[str, Any] | None:
    conn.execute(
        "UPDATE tasks SET status='missed', updated_at=? WHERE id=? AND status='pending'",
        (iso(now(conn)), task_id),
    )
    return get_task(conn, task_id)
