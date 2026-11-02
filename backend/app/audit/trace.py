"""F14 决策解释与运行追踪：run_id、每一步的输入/工具/结果/错误，全部落库。"""
from __future__ import annotations

import sqlite3
from typing import Any

from backend.app.db.connection import dumps, iso, loads, now
from backend.app.util import new_id


def start_run(
    conn: sqlite3.Connection,
    patient_id: str,
    *,
    trigger_type: str,
    trigger_ref: str | None,
    llm_mode: str,
    model_name: str | None,
    intent: str | None = None,
    input_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_id = new_id("run")
    conn.execute(
        """INSERT INTO agent_runs(id,patient_id,trigger_type,trigger_ref,llm_mode,model_name,status,intent,input,started_at)
           VALUES(?,?,?,?,?,?,'running',?,?,?)""",
        (run_id, patient_id, trigger_type, trigger_ref, llm_mode, model_name, intent, dumps(input_payload or {}), iso(now(conn))),
    )
    return get_run(conn, run_id)  # type: ignore[return-value]


def get_run(conn: sqlite3.Connection, run_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM agent_runs WHERE id=?", (run_id,)).fetchone()
    if not row:
        return None
    data = dict(row)
    for field in ("input", "plan", "output"):
        data[field] = loads(data[field], {})
    return data


def list_runs(conn: sqlite3.Connection, patient_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM agent_runs WHERE patient_id=? ORDER BY started_at DESC LIMIT ?", (patient_id, limit)
    ).fetchall()
    out = []
    for r in rows:
        item = dict(r)
        item["output"] = loads(item["output"], {})
        out.append(item)
    return out


def add_step(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    phase: str,
    kind: str,
    tool_name: str | None = None,
    payload: dict[str, Any] | None = None,
    status: str = "ok",
    code: str | None = None,
) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(step_no),0) AS n FROM agent_steps WHERE run_id=?", (run_id,)
    ).fetchone()
    step_no = int(row["n"]) + 1
    conn.execute(
        """INSERT INTO agent_steps(run_id,step_no,phase,kind,tool_name,payload,status,code,created_at)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (run_id, step_no, phase, kind, tool_name, dumps(payload or {}), status, code, iso(now(conn))),
    )
    return step_no


def finish_run(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    status: str,
    plan: dict[str, Any] | None = None,
    output: dict[str, Any] | None = None,
    error: str | None = None,
    intent: str | None = None,
) -> dict[str, Any] | None:
    sets = ["status=?", "finished_at=?"]
    args: list[Any] = [status, iso(now(conn))]
    if plan is not None:
        sets.append("plan=?")
        args.append(dumps(plan))
    if output is not None:
        sets.append("output=?")
        args.append(dumps(output))
    if error:
        sets.append("error=?")
        args.append(error)
    if intent:
        sets.append("intent=?")
        args.append(intent)
    args.append(run_id)
    conn.execute(f"UPDATE agent_runs SET {', '.join(sets)} WHERE id=?", args)
    return get_run(conn, run_id)


def steps(conn: sqlite3.Connection, run_id: str) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM agent_steps WHERE run_id=? ORDER BY step_no", (run_id,)).fetchall()
    return [
        {
            "step_no": r["step_no"],
            "phase": r["phase"],
            "kind": r["kind"],
            "tool_name": r["tool_name"],
            "payload": loads(r["payload"], {}),
            "status": r["status"],
            "code": r["code"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


def trace(conn: sqlite3.Connection, run_id: str) -> dict[str, Any]:
    from backend.app.knowledge.search import evidence_for_run
    from backend.app.questioning.service import list_questions
    from backend.app.reviews.service import list_reviews
    from backend.app.tasks.service import list_tasks

    run = get_run(conn, run_id)
    if not run:
        raise KeyError(f"运行记录不存在: {run_id}")
    patient_id = run["patient_id"]
    tasks = [
        t
        for t in list_tasks(conn, patient_id, limit=200)
        if t.get("source_run_id") == run_id or run_id in (t.get("meta") or {}).get("run_ids", [])
    ]
    return {
        "run": run,
        "steps": steps(conn, run_id),
        "evidence": evidence_for_run(conn, run_id),
        "questions": [q for q in list_questions(conn, patient_id, limit=200) if q.get("run_id") == run_id],
        "reviews": [r for r in list_reviews(conn, patient_id, limit=200) if r.get("run_id") == run_id],
        "tasks": tasks,
    }
