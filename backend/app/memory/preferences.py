"""F25 长期偏好记忆：只保存患者明确确认的偏好，可覆盖、可清除，且不得绕过安全门。"""
from __future__ import annotations

import sqlite3
from typing import Any

from backend.app.db.connection import iso, now
from backend.app.services.patients import get_patient
from backend.app.util import new_id

ALLOWED_SOURCES = {"patient_confirmed", "patient_input", "import"}
ALLOWED_KINDS = {
    "preferred_time_window",   # 例如 morning / evening / 08:00-10:00
    "task_obstacle",           # 例如 早上要上班
    "contact_window",
    "reminder_channel",
    "note",
}


class PreferenceError(ValueError):
    pass


def set_preference(
    conn: sqlite3.Connection,
    patient_id: str,
    *,
    kind: str,
    value: str,
    source: str = "patient_confirmed",
    run_id: str | None = None,
) -> dict[str, Any]:
    get_patient(conn, patient_id)
    if kind not in ALLOWED_KINDS:
        raise PreferenceError(f"不支持的偏好类型: {kind}")
    if source not in ALLOWED_SOURCES:
        raise PreferenceError("偏好来源必须是患者明确确认，Agent 不得推断未提供的事实")
    ts = iso(now(conn))
    conn.execute("BEGIN IMMEDIATE")
    old = conn.execute(
        "SELECT id FROM preferences WHERE patient_id=? AND kind=? AND status='active'", (patient_id, kind)
    ).fetchone()
    pid = new_id("pref")
    if old and old["id"]:
        conn.execute(
            "UPDATE preferences SET status='superseded', valid_until=?, superseded_by=? WHERE id=?",
            (ts, pid, old["id"]),
        )
    conn.execute(
        """INSERT INTO preferences(id,patient_id,kind,value,source,status,valid_from,created_at)
           VALUES(?,?,?,?,?,'active',?,?)""",
        (pid, patient_id, kind, value, source, ts, ts),
    )
    conn.execute("COMMIT")
    row = conn.execute("SELECT * FROM preferences WHERE id=?", (pid,)).fetchone()
    return dict(row)


def list_preferences(conn: sqlite3.Connection, patient_id: str, *, include_history: bool = False) -> list[dict[str, Any]]:
    get_patient(conn, patient_id)
    sql = "SELECT * FROM preferences WHERE patient_id=?"
    if not include_history:
        sql += " AND status='active'"
    sql += " ORDER BY kind, created_at DESC"
    return [dict(r) for r in conn.execute(sql, (patient_id,)).fetchall()]


def get_preference(conn: sqlite3.Connection, patient_id: str, kind: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM preferences WHERE patient_id=? AND kind=? AND status='active' ORDER BY created_at DESC LIMIT 1",
        (patient_id, kind),
    ).fetchone()
    return dict(row) if row else None


def clear_preference(conn: sqlite3.Connection, patient_id: str, kind: str) -> dict[str, Any]:
    ts = iso(now(conn))
    row = conn.execute(
        "SELECT id FROM preferences WHERE patient_id=? AND kind=? AND status='active'", (patient_id, kind)
    ).fetchone()
    if not row:
        return {"cleared": False, "kind": kind}
    conn.execute(
        "UPDATE preferences SET status='cleared', valid_until=? WHERE id=?", (ts, row["id"])
    )
    return {"cleared": True, "kind": kind, "cleared_at": ts}


def preferred_time_window(conn: sqlite3.Connection, patient_id: str) -> str | None:
    pref = get_preference(conn, patient_id, "preferred_time_window")
    return pref["value"] if pref else None
