"""F21 主动询问与信息补全：问题队列、等待状态、答复后恢复执行。"""
from __future__ import annotations

import sqlite3
from datetime import timedelta
from typing import Any

from backend.app.db.connection import dumps, iso, loads, now, parse_ts
from backend.app.services.patients import get_patient
from backend.app.services.records import KIND_SPEC
from backend.app.util import new_id

RESUME_HINTS = {
    "medication_taken": "请补充最近一次服药情况（是否按时服药）。",
    "steps": "请补充近 3 天的大致步数。",
    "fasting_glucose": "请补充最近一次空腹血糖。",
    "preferred_time_window": "您方便在什么时间段完成记录任务？",
}


class QuestionError(ValueError):
    pass


class QuestionExpired(QuestionError):
    pass


def _row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "patient_id": row["patient_id"],
        "run_id": row["run_id"],
        "event_id": row["event_id"],
        "kind": row["kind"],
        "question": row["question"],
        "options": loads(row["options"], []),
        "target_field": row["target_field"],
        "status": row["status"],
        "answer": loads(row["answer"], None),
        "answer_text": row["answer_text"],
        "resume_payload": loads(row["resume_payload"], {}),
        "created_at": row["created_at"],
        "answered_at": row["answered_at"],
        "expires_at": row["expires_at"],
    }


def create_question(
    conn: sqlite3.Connection,
    patient_id: str,
    *,
    question: str,
    kind: str = "missing_field",
    target_field: str | None = None,
    options: list[str] | None = None,
    run_id: str | None = None,
    event_id: str | None = None,
    resume_payload: dict[str, Any] | None = None,
    ttl_hours: int = 72,
) -> tuple[dict[str, Any], bool]:
    """创建待答复问题；同一患者同一字段只有一条等待中的问题（幂等）。"""
    get_patient(conn, patient_id)
    if not target_field:
        target_field = "general"
    if target_field:
        dup = conn.execute(
            "SELECT * FROM questions WHERE patient_id=? AND COALESCE(target_field,'')=? AND status='waiting'",
            (patient_id, target_field),
        ).fetchone()
        if dup:
            # QUESTION-DEDUPE-01：同字段合并关联事件，不能丢掉新事件的上下文
            merged = _row(dup)
            payload = dict(merged.get("resume_payload") or {})
            ids = set(payload.get("event_ids", []))
            if event_id:
                ids.add(event_id)
            if ids:
                payload["event_ids"] = sorted(ids)
                payload["merged"] = True
            conn.execute(
                "UPDATE questions SET resume_payload=?, event_id=COALESCE(event_id,?) WHERE id=?",
                (dumps(payload), event_id, merged["id"]),
            )
            return get_question(conn, merged["id"]) or merged, False
    ts = now(conn)
    qid = new_id("question")
    # QUESTION-DEDUPE-02：单数 event_id 在入口即并入 event_ids
    normalized = dict(resume_payload or {})
    ids = set(normalized.get("event_ids", []))
    if event_id:
        ids.add(event_id)
    if ids:
        normalized["event_ids"] = sorted(ids)
    conn.execute(
        """INSERT OR IGNORE INTO questions(id,patient_id,run_id,event_id,kind,question,options,target_field,status,
                resume_payload,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?,'waiting',?,?,?)""",
        (
            qid,
            patient_id,
            run_id,
            event_id,
            kind,
            question,
            dumps(options or []),
            target_field,
            dumps(normalized),
            iso(ts),
            iso(ts + timedelta(hours=ttl_hours)),
        ),
    )
    row = conn.execute(
        "SELECT * FROM questions WHERE patient_id=? AND COALESCE(target_field,'')=? AND status='waiting'",
        (patient_id, target_field),
    ).fetchone()
    return _row(row), row["id"] == qid


def list_questions(
    conn: sqlite3.Connection, patient_id: str, *, status: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    get_patient(conn, patient_id)
    sql = "SELECT * FROM questions WHERE patient_id=?"
    args: list[Any] = [patient_id]
    if status:
        sql += " AND status=?"
        args.append(status)
    sql += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    return [_row(r) for r in conn.execute(sql, args).fetchall()]


def get_question(conn: sqlite3.Connection, question_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM questions WHERE id=?", (question_id,)).fetchone()
    return _row(row) if row else None


UNCERTAIN_CUES = ("记不清", "不确定", "不能确定", "没法确认", "无法确认", "说不清", "不清楚", "忘了", "想不起来", "不知道")


def _is_uncertain(text: str | None) -> bool:
    value = (text or "").strip().lower()
    if value in {"unknown", "skip"}:
        return True
    return any(cue in value for cue in UNCERTAIN_CUES)


def answer_question(
    conn: sqlite3.Connection,
    question_id: str,
    *,
    answer_text: str | None = None,
    answer_value: Any = None,
    answer: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """记录答复。拒绝回答/记不清也是有效答复：记录"不确定"，不自动补全事实。"""
    row = conn.execute("SELECT * FROM questions WHERE id=?", (question_id,)).fetchone()
    if not row:
        raise QuestionError(f"问题不存在: {question_id}")
    q = _row(row)
    if q["status"] != "waiting":
        raise QuestionError(f"问题状态为 {q['status']}，不能重复回答")
    ts = now(conn)
    expires = parse_ts(q["expires_at"])
    if q["status"] != "waiting":
        raise QuestionError(f"问题状态为 {q['status']}，不能重复回答")
    if expires and ts > expires:
        # QUESTION-EXP-01：过期答复不保存、不恢复，避免 expired + resume 矛盾状态
        conn.execute("UPDATE questions SET status='expired' WHERE id=?", (question_id,))
        raise QuestionExpired("问题已过期，请重新发起")
    payload = answer if answer is not None else {
        "text": answer_text,
        "value": answer_value,
        "uncertain": _is_uncertain(answer_text),
    }
    status = "expired" if expires and ts > expires else "answered"
    # QUESTION-ANSWER-RACE-01：只有第一个请求能从 waiting 转换到 answered
    cur = conn.execute(
        "UPDATE questions SET status=?, answer=?, answer_text=?, answered_at=? WHERE id=? AND status='waiting'",
        (status, dumps(payload), answer_text or "", iso(ts), question_id),
    )
    if cur.rowcount == 0:
        raise QuestionError("问题已被其他请求答复")
    updated = get_question(conn, question_id)
    if updated is None:
        raise QuestionError("问题读取失败")
    return updated


def expire_stale(conn: sqlite3.Connection) -> int:
    ts = iso(now(conn))
    cur = conn.execute(
        "UPDATE questions SET status='expired' WHERE status='waiting' AND expires_at IS NOT NULL AND expires_at<?",
        (ts,),
    )
    return cur.rowcount


def pending_for_patient(conn: sqlite3.Connection, patient_id: str) -> list[dict[str, Any]]:
    return list_questions(conn, patient_id, status="waiting")


def default_question_for(field: str) -> dict[str, Any]:
    spec = KIND_SPEC.get(field, {})
    return {
        "question": RESUME_HINTS.get(field, f"请补充 {spec.get('label', field)} 相关信息。"),
        "options": ["已按时完成", "记不清", "未完成"],
    }
