"""F12 动态复评三分支：CLOSED / MISSING_DATA / HUMAN_REVIEW。"""
from __future__ import annotations

import sqlite3
from datetime import timedelta
from typing import Any

from backend.app.config import review_rules
from backend.app.db.connection import dumps, iso, loads, now, parse_ts
from backend.app.services.patients import get_patient
from backend.app.services.state import build_state
from backend.app.util import new_id

BRANCHES = ("CLOSED", "MISSING_DATA", "HUMAN_REVIEW")


def _row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "patient_id": row["patient_id"],
        "task_id": row["task_id"],
        "event_id": row["event_id"],
        "run_id": row["run_id"],
        "branch": row["branch"],
        "status": row["status"],
        "reason": row["reason"],
        "detail": loads(row["detail"], {}),
        "scheduled_for": row["scheduled_for"],
        "created_at": row["created_at"],
        "resolved_at": row["resolved_at"],
    }


def default_delay_hours() -> int:
    return int(review_rules().get("default_review_delay_hours", 48))


class ReviewError(ValueError):
    pass


def schedule_review(
    conn: sqlite3.Connection,
    patient_id: str,
    *,
    task_id: str | None = None,
    event_id: str | None = None,
    run_id: str | None = None,
    delay_hours: int | None = None,
    branch: str = "PENDING",
    reason: str = "任务完成后安排复评",
) -> dict[str, Any]:
    get_patient(conn, patient_id)
    # REVIEW-REF-SCOPE-01：服务层校验 task/event 归属，不能依赖 Agent validator
    if task_id:
        row = conn.execute("SELECT patient_id FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row or row["patient_id"] != patient_id:
            raise ReviewError("task_id 不存在或不属于当前患者")
    if event_id:
        row = conn.execute("SELECT patient_id FROM events WHERE id=?", (event_id,)).fetchone()
        if not row or row["patient_id"] != patient_id:
            raise ReviewError("event_id 不存在或不属于当前患者")
    if delay_hours is not None:
        if delay_hours < 0 or delay_hours > 720:
            raise ReviewError("delay_hours 必须在 0~720 小时之间")
        if delay_hours == 0 and branch != "HUMAN_REVIEW":
            raise ReviewError("delay_hours=0 只允许用于人工复核升级")
    due = now(conn) + timedelta(hours=delay_hours if delay_hours is not None else default_delay_hours())
    # A0-FULL-P2-02：同一患者、同一任务/事件、同一复评窗口只保留一条待复评，避免重复
    existing = conn.execute(
        """SELECT id FROM reviews WHERE patient_id=? AND status='scheduled'
           AND COALESCE(task_id,'')=? AND COALESCE(event_id,'')=?
           AND ABS((julianday(scheduled_for) - julianday(?)) * 24) <= 1
           ORDER BY created_at DESC LIMIT 1""",
        (patient_id, task_id or "", event_id or "", iso(due)),
    ).fetchone()
    if existing:
        review = get_review(conn, existing["id"])
        if review:
            review["duplicate"] = True
            return review
    rid = new_id("review")
    window_key = f"{patient_id}|{task_id or ''}|{event_id or ''}|{iso(due)[:13]}"
    conn.execute(
        """INSERT OR IGNORE INTO reviews(id,patient_id,task_id,event_id,run_id,branch,status,reason,detail,
                scheduled_for,created_at,review_key)
           VALUES(?,?,?,?,?,?,'scheduled',?,?,?,?,?)""",
        (
            rid,
            patient_id,
            task_id,
            event_id,
            run_id,
            branch,
            reason,
            dumps({"scheduled_by": run_id or "system"}),
            iso(due),
            iso(now(conn)),
            window_key,
        ),
    )
    row = conn.execute("SELECT id FROM reviews WHERE review_key=? AND status='scheduled'", (window_key,)).fetchone()
    if row and row["id"] != rid:
        duplicate = get_review(conn, row["id"])
        if duplicate:
            duplicate["duplicate"] = True
            return duplicate
    review = get_review(conn, rid)
    if review and review["status"] == "scheduled":
        from backend.app.automation import scheduler as _scheduler

        _scheduler.enqueue_job(
            conn,
            kind="review_due",
            patient_id=patient_id,
            ref_id=rid,
            run_at=review["scheduled_for"],
            payload={"branch": branch},
        )
    return review  # type: ignore[return-value]


def get_review(conn: sqlite3.Connection, review_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM reviews WHERE id=?", (review_id,)).fetchone()
    return _row(row) if row else None


def list_reviews(
    conn: sqlite3.Connection, patient_id: str, *, status: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    get_patient(conn, patient_id)
    sql = "SELECT * FROM reviews WHERE patient_id=?"
    args: list[Any] = [patient_id]
    if status:
        sql += " AND status=?"
        args.append(status)
    sql += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    return [_row(r) for r in conn.execute(sql, args).fetchall()]


def decide_branch(conn: sqlite3.Connection, review: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    """按规则判定分支，返回 (branch, reason, detail)。任何高风险一律 HUMAN_REVIEW。"""
    cfg = review_rules()
    state = build_state(conn, review["patient_id"])
    task = None
    if review["task_id"]:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (review["task_id"],)).fetchone()
        task = dict(row) if row else None
    event = None
    if review["event_id"]:
        row = conn.execute("SELECT * FROM events WHERE id=?", (review["event_id"],)).fetchone()
        event = dict(row) if row else None

    detail: dict[str, Any] = {
        "task_status": task["status"] if task else None,
        "task_type": task["task_type"] if task else None,
        "event_severity": event["severity"] if event else None,
        "event_code": event["code"] if event else None,
    }
    if event and event["severity"] == "high":
        return "HUMAN_REVIEW", "关联事件为高风险，需人工复核", detail
    if task and str(task["task_type"]).startswith("review_"):
        return "HUMAN_REVIEW", "任务本身属于人工复核类", detail

    sufficiency = cfg.get("data_sufficiency", {})
    glucose_points = int(state["aggregates"]["7d"].get("fasting_glucose", {}).get("count", 0))
    steps_points = int(state["aggregates"]["3d"].get("steps", {}).get("count", 0))
    detail.update({"glucose_points_7d": glucose_points, "steps_points_3d": steps_points})
    required = loads(task["required_fields"], []) if task else []
    missing_required = [f for f in required if f in state["missing_fields"]]
    detail["missing_required_fields"] = missing_required

    if missing_required:
        return "MISSING_DATA", f"仍缺少数据: {', '.join(missing_required)}", detail
    if glucose_points < int(sufficiency.get("glucose_min_points_7d", 2)) and task and task["task_type"] == "record_glucose":
        return "MISSING_DATA", "7 天空腹血糖记录点不足，需继续补录", detail
    if task and task["status"] == "done":
        return "CLOSED", "任务已完成且所需数据齐备", detail
    if task and task["status"] in ("pending", "missed"):
        return "MISSING_DATA", "任务到期仍未完成，需要补录或重新安排", detail
    return "CLOSED", "无未解决事项", detail


def evaluate_review(conn: sqlite3.Connection, review_id: str, *, closer: str = "system") -> dict[str, Any]:
    review = get_review(conn, review_id)
    if not review:
        raise KeyError(f"复评不存在: {review_id}")
    if review["status"] in ("completed", "pending_human"):
        return review
    branch, reason, detail = decide_branch(conn, review)
    ts = iso(now(conn))
    status = "pending_human" if branch == "HUMAN_REVIEW" else "completed"
    detail["closer"] = closer
    conn.execute(
        "UPDATE reviews SET branch=?, status=?, reason=?, detail=?, resolved_at=? WHERE id=?",
        (branch, status, reason, dumps(detail), ts if branch != "HUMAN_REVIEW" else None, review_id),
    )
    return get_review(conn, review_id)  # type: ignore[return-value]


def resolve_human_review(conn: sqlite3.Connection, review_id: str, *, decision: str, note: str = "") -> dict[str, Any]:
    review = get_review(conn, review_id)
    if not review:
        raise KeyError(f"复评不存在: {review_id}")
    if review["branch"] != "HUMAN_REVIEW":
        raise ValueError("只有 HUMAN_REVIEW 分支可以人工结案")
    ts = iso(now(conn))
    detail = dict(review["detail"])
    detail["human_decision"] = decision
    detail["human_note"] = note
    # REVIEW-RESOLVE-RACE-01：pending_human → completed 必须原子 CAS
    cur = conn.execute(
        "UPDATE reviews SET status='completed', detail=?, resolved_at=?, reason=? "
        "WHERE id=? AND status='pending_human'",
        (dumps(detail), ts, f"人工复核结论: {decision}", review_id),
    )
    if cur.rowcount == 0:
        current = get_review(conn, review_id)
        if current:
            return {**current, "already_resolved": True}
    return get_review(conn, review_id)  # type: ignore[return-value]


def due_reviews(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM reviews WHERE status='scheduled' AND scheduled_for IS NOT NULL AND scheduled_for<=? "
        "ORDER BY scheduled_for",
        (iso(now(conn)),),
    ).fetchall()
    return [_row(r) for r in rows]


def parse_scheduled(review: dict[str, Any]):
    return parse_ts(review["scheduled_for"])
