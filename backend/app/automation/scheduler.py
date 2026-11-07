"""F07 后台自动调度：到期复评、到期提醒、事件扫描都由调度器执行，且可重复执行而不重复生效。"""
from __future__ import annotations

import sqlite3
import threading
import time
from datetime import timedelta
from typing import Any

from backend.app.db.connection import dumps, iso, loads, now, parse_ts
from backend.app.util import new_id

TERMINAL = ("done", "skipped", "failed")


def enqueue_job(
    conn: sqlite3.Connection,
    *,
    kind: str,
    patient_id: str | None,
    ref_id: str | None = None,
    run_at: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ts = now(conn)
    run_at = run_at or iso(ts)
    job_id = new_id("job")
    conn.execute(
        """INSERT OR IGNORE INTO automation_jobs(id,kind,patient_id,ref_id,payload,run_at,status,attempts,created_at,updated_at)
           VALUES(?,?,?,?,?,?,'pending',0,?,?)""",
        (job_id, kind, patient_id, ref_id, dumps(payload or {}), run_at, iso(ts), iso(ts)),
    )
    row = conn.execute(
        "SELECT * FROM automation_jobs WHERE kind=? AND patient_id IS ? AND ref_id IS ? AND run_at=?",
        (kind, patient_id, ref_id, run_at),
    ).fetchone()
    return dict(row) if row else {"id": job_id, "kind": kind, "status": "pending"}


def mark_job_done(conn: sqlite3.Connection, job_id: str, result: dict[str, Any] | None = None) -> None:
    conn.execute(
        "UPDATE automation_jobs SET status='done', payload=?, updated_at=? WHERE id=?",
        (dumps(result or {}), iso(now(conn)), job_id),
    )


def due_jobs(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM automation_jobs WHERE status='pending' AND run_at<=? ORDER BY run_at LIMIT ?",
        (iso(now(conn)), limit),
    ).fetchall()
    return [dict(r) for r in rows]


def _claim(conn: sqlite3.Connection, job_id: str) -> bool:
    cur = conn.execute(
        "UPDATE automation_jobs SET status='running', attempts=attempts+1, updated_at=? WHERE id=? AND status='pending'",
        (iso(now(conn)), job_id),
    )
    return cur.rowcount == 1


def recover_stale_jobs(conn: sqlite3.Connection, *, stale_minutes: int = 30) -> int:
    """JOB-RECOVERY-01：进程在 claim 后中断，running 作业超时后重新入队。"""
    cutoff = iso(now(conn) - timedelta(minutes=stale_minutes))
    cur = conn.execute(
        "UPDATE automation_jobs SET status='pending', last_error='stale running recovered', updated_at=? "
        "WHERE status='running' AND updated_at<?",
        (iso(now(conn)), cutoff),
    )
    return cur.rowcount


def _finish(conn: sqlite3.Connection, job_id: str, status: str, detail: dict[str, Any], error: str | None = None) -> None:
    conn.execute(
        "UPDATE automation_jobs SET status=?, payload=?, last_error=?, updated_at=? WHERE id=?",
        (status, dumps(detail), error, iso(now(conn)), job_id),
    )


def tick(conn: sqlite3.Connection, *, limit: int = 50) -> dict[str, Any]:
    """执行所有到期任务；每条作业只被领取一次，重复调用不会重复执行。"""
    from backend.app.agent import orchestrator
    from backend.app.automation import triggers
    from backend.app.events.detector import detect_events
    from backend.app.questioning import service as questioning
    from backend.app.reviews import service as reviews
    from backend.app.services import notifications
    from backend.app.tasks import service as tasks

    processed: list[dict[str, Any]] = []
    from backend.app.automation import outbox

    outbox_result = outbox.process_pending(conn)
    recovered_jobs = recover_stale_jobs(conn)
    expired_questions = questioning.expire_stale(conn)
    # 每日一次到期扫描：把超期未完成的任务标记为 missed 并提醒（幂等，按天去重）
    day_key = iso(now(conn))[:10]
    enqueue_job(
        conn,
        kind="overdue_check",
        patient_id=None,
        ref_id=f"overdue-{day_key}",
        run_at=iso(now(conn).replace(hour=0, minute=0, second=0, microsecond=0)),
        payload={"day": day_key},
    )
    for job in due_jobs(conn, limit=limit):
        if not _claim(conn, job["id"]):
            continue
        payload = loads(job["payload"], {})
        try:
            if job["kind"] == "agent_run":
                outcome = orchestrator.run_agent(
                    conn,
                    job["patient_id"],
                    trigger_type=payload.get("trigger_type", "scheduled_tick"),
                    trigger_ref=job["ref_id"],
                    event_ids=[payload["event_id"]] if payload.get("event_id") else None,
                )
                _finish(conn, job["id"], "done", {"run_id": outcome["run_id"], "status": outcome["status"]})
                processed.append({"job": job["id"], "kind": job["kind"], "run_id": outcome["run_id"]})
            elif job["kind"] == "review_due":
                review = reviews.get_review(conn, job["ref_id"]) if job["ref_id"] else None
                if not review:
                    _finish(conn, job["id"], "skipped", {"reason": "复评记录不存在"})
                    continue
                if review["status"] != "scheduled":
                    _finish(conn, job["id"], "skipped", {"reason": f"复评状态为 {review['status']}，无需自动评估"})
                    continue
                evaluated = reviews.evaluate_review(conn, review["id"], closer="scheduler")
                notifications.create_notification(
                    conn,
                    review["patient_id"],
                    kind="review_due",
                    title=f"复评完成：{evaluated['branch']}",
                    body=evaluated.get("reason") or "",
                    ref_type="review",
                    ref_id=review["id"],
                )
                if evaluated["branch"] == "MISSING_DATA":
                    follow = orchestrator.run_agent(
                        conn,
                        review["patient_id"],
                        trigger_type="review_due",
                        trigger_ref=review["id"],
                    )
                    _finish(conn, job["id"], "done", {"review": evaluated, "followup_run": follow["run_id"]})
                else:
                    _finish(conn, job["id"], "done", {"review": evaluated})
                processed.append({"job": job["id"], "kind": job["kind"], "review_id": review["id"]})
            elif job["kind"] == "event_scan":
                result = detect_events(conn, job["patient_id"], trigger="scheduled_scan")
                _finish(conn, job["id"], "done", {"events": [e["code"] for e in result["created"]]})
                processed.append({"job": job["id"], "kind": job["kind"], "events": len(result["created"])})
            elif job["kind"] == "overdue_check":
                overdue = tasks.due_tasks(conn)
                touched = []
                for task in overdue:
                    tasks.mark_missed(conn, task["id"])
                    notifications.create_notification(
                        conn,
                        task["patient_id"],
                        kind="task_overdue",
                        title=f"任务已到期未完成：{task['title']}",
                        body="可以补录数据，或申请调整时间。",
                        ref_type="task",
                        ref_id=task["id"],
                    )
                    touched.append(task["id"])
                _finish(conn, job["id"], "done", {"overdue": touched})
                processed.append({"job": job["id"], "kind": job["kind"], "overdue": len(touched)})
            elif job["kind"] == "reminder":
                notifications.create_notification(
                    conn,
                    job["patient_id"],
                    kind=payload.get("kind", "reminder"),
                    title=payload.get("title", "提醒"),
                    body=payload.get("body", ""),
                    ref_type=payload.get("ref_type"),
                    ref_id=job["ref_id"],
                )
                _finish(conn, job["id"], "done", {})
                processed.append({"job": job["id"], "kind": job["kind"]})
            else:
                _finish(conn, job["id"], "skipped", {"reason": f"未知作业类型 {job['kind']}"})
        except Exception as exc:  # 调度失败要记录并允许重试，不能吞掉
            attempts = int(job.get("attempts", 0)) + 1
            if attempts >= 3:
                _finish(conn, job["id"], "failed", {}, f"{type(exc).__name__}: {exc}")
            else:
                retry_at = iso(now(conn) + timedelta(seconds=60 * attempts))
                conn.execute(
                    "UPDATE automation_jobs SET status='pending', run_at=?, last_error=?, updated_at=? WHERE id=?",
                    (retry_at, f"{type(exc).__name__}: {exc}", iso(now(conn)), job["id"]),
                )
    return {
        "at": iso(now(conn)),
        "processed": processed,
        "expired_questions": expired_questions,
        "recovered_jobs": recovered_jobs,
        "outbox": outbox_result,
        "pending_jobs": conn.execute(
            "SELECT COUNT(*) AS c FROM automation_jobs WHERE status='pending'"
        ).fetchone()["c"],
    }


def schedule_review_job(conn: sqlite3.Connection, review: dict[str, Any]) -> dict[str, Any]:
    return enqueue_job(
        conn,
        kind="review_due",
        patient_id=review["patient_id"],
        ref_id=review["id"],
        run_at=review["scheduled_for"],
        payload={"branch": review["branch"]},
    )


class AutomationLoop(threading.Thread):
    """uvicorn 启动后可选的轮询线程；测试与 CLI 演示使用显式 tick 更可控。"""

    def __init__(self, db_path: str | None = None, interval: int = 30) -> None:
        super().__init__(daemon=True, name="automation-loop")
        self.db_path = db_path
        self.interval = max(1, interval)
        self._stop = threading.Event()

    def run(self) -> None:  # pragma: no cover - 后台线程
        from backend.app.db.connection import connect

        while not self._stop.wait(self.interval):
            try:
                conn = connect(self.db_path)
                try:
                    tick(conn)
                finally:
                    conn.close()
            except Exception:
                time.sleep(1)

    def stop(self) -> None:
        self._stop.set()
