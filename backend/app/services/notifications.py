"""F16 站内待办提醒（后端数据与接口；页面由 C 实现）。"""
from __future__ import annotations

import sqlite3
from datetime import timedelta
from typing import Any

from backend.app.db.connection import iso, now
from backend.app.util import new_id


def _duplicate_notification(conn, patient_id, *, kind, title, body, ref_type, ref_id):
    """同一引用或 5 分钟内完全相同的文案只保留一条。"""
    if ref_type and ref_id:
        row = conn.execute(
            "SELECT * FROM notifications WHERE patient_id=? AND ref_type=? AND ref_id=? AND kind=? "
            "ORDER BY created_at DESC LIMIT 1",
            (patient_id, ref_type, ref_id, kind),
        ).fetchone()
        if row:
            return dict(row)
    row = conn.execute(
        "SELECT * FROM notifications WHERE patient_id=? AND kind=? AND title=? AND COALESCE(body,'')=? "
        "AND created_at>=? ORDER BY created_at DESC LIMIT 1",
        (patient_id, kind, title, body or "", iso(now(conn) - timedelta(minutes=5))),
    ).fetchone()
    return dict(row) if row else None


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
    duplicate = _duplicate_notification(conn, patient_id, kind=kind, title=title, body=body,
                                        ref_type=ref_type, ref_id=ref_id)
    if duplicate:
        duplicate["duplicate"] = True
        return duplicate
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
