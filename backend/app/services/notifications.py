"""F16 站内待办提醒（后端数据与接口；页面由 C 实现）。"""
from __future__ import annotations

import sqlite3
from typing import Any

from backend.app.db.connection import iso, now
from backend.app.util import new_id


def create_notification(
    conn: sqlite3.Connection,
    patient_id: str,
    *,
    kind: str,
    title: str,
    body: str = "",
    ref_type: str | None = None,
    ref_id: str | None = None,
) -> dict[str, Any]:
    nid = new_id("notification")
    conn.execute(
        """INSERT INTO notifications(id,patient_id,kind,title,body,status,ref_type,ref_id,created_at)
           VALUES(?,?,?,?,?,'unread',?,?,?)""",
        (nid, patient_id, kind, title, body, ref_type, ref_id, iso(now(conn))),
    )
    return get_notification(conn, nid)


def get_notification(conn: sqlite3.Connection, notification_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM notifications WHERE id=?", (notification_id,)).fetchone()
    return dict(row) if row else None


def list_notifications(
    conn: sqlite3.Connection, patient_id: str, *, status: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM notifications WHERE patient_id=?"
    args: list[Any] = [patient_id]
    if status:
        sql += " AND status=?"
        args.append(status)
    sql += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def mark_read(conn: sqlite3.Connection, notification_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM notifications WHERE id=?", (notification_id,)).fetchone()
    if not row:
        return None
    conn.execute(
        "UPDATE notifications SET status='read', read_at=? WHERE id=?", (iso(now(conn)), notification_id)
    )
    return get_notification(conn, notification_id)


def mark_all_read(conn: sqlite3.Connection, patient_id: str) -> int:
    cur = conn.execute(
        "UPDATE notifications SET status='read', read_at=? WHERE patient_id=? AND status='unread'",
        (iso(now(conn)), patient_id),
    )
    return cur.rowcount
