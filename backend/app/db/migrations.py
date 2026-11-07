"""数据库结构迁移。

原则：
- 版本号记录在 app_meta.schema_version；
- 迁移只在版本落后时执行一次，普通 connect() 不做破坏性 DDL；
- 旧数据先清理/规范化，再建唯一索引，保证旧库可升级；
- 每一步都在事务内，失败整体回滚。
"""
from __future__ import annotations

import sqlite3
from typing import Any

from backend.app.db.connection import dumps, get_meta, iso, loads, set_meta
from backend.app.util import short_hash

SCHEMA_VERSION = 2


def schema_version(conn: sqlite3.Connection) -> int:
    try:
        return int(get_meta(conn, "schema_version", "0") or "0")
    except ValueError:
        return 0


def _dedupe_jobs(conn: sqlite3.Connection) -> None:
    """旧唯一索引允许 NULL 重复；按业务键只保留最早一行。"""
    conn.execute(
        """DELETE FROM automation_jobs WHERE rowid NOT IN (
               SELECT MIN(rowid) FROM automation_jobs
               GROUP BY kind, COALESCE(patient_id,''), COALESCE(ref_id,''), run_at)"""
    )


def _dedupe_task_keys(conn: sqlite3.Connection) -> None:
    """重算 pending/missed 任务的 dedupe_key；冲突时保留最早，其余加后缀并标记。"""
    rows = conn.execute(
        "SELECT id, patient_id, task_type, due_at FROM tasks WHERE status IN ('pending','missed') ORDER BY created_at"
    ).fetchall()
    seen: dict[str, str] = {}
    for row in rows:
        key = short_hash(f"{row['patient_id']}|{row['task_type']}|{(row['due_at'] or '')[:10] or 'nodue'}", length=24)
        if key in seen:
            key = f"{key}-{row['id'][-6:]}"
        seen[key] = row["id"]
        conn.execute("UPDATE tasks SET dedupe_key=? WHERE id=?", (key, row["id"]))


def _normalize_patients(conn: sqlite3.Connection) -> None:
    """硬边界：历史演示患者一律规范为合成数据。"""
    conn.execute("UPDATE patients SET is_synthetic=1 WHERE is_synthetic<>1")


def _normalize_questions(conn: sqlite3.Connection) -> None:
    """补齐 event_ids，并把同字段多余的 waiting 置为 expired。"""
    for row in conn.execute("SELECT id, event_id, resume_payload FROM questions").fetchall():
        payload = loads(row["resume_payload"], {}) or {}
        ids = set(payload.get("event_ids", []))
        if row["event_id"]:
            ids.add(row["event_id"])
        if ids:
            payload["event_ids"] = sorted(ids)
            conn.execute("UPDATE questions SET resume_payload=? WHERE id=?", (dumps(payload), row["id"]))
    conn.execute(
        """UPDATE questions SET status='expired' WHERE status='waiting' AND rowid NOT IN (
               SELECT MIN(rowid) FROM questions WHERE status='waiting'
               GROUP BY patient_id, COALESCE(target_field,''))"""
    )


def _normalize_reviews(conn: sqlite3.Connection) -> None:
    """为复评建立窗口键；同键只保留最早一条 scheduled。"""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(reviews)").fetchall()}
    if "review_key" not in cols:
        conn.execute("ALTER TABLE reviews ADD COLUMN review_key TEXT")
    rows = conn.execute(
        "SELECT id, patient_id, task_id, event_id, scheduled_for, status FROM reviews ORDER BY created_at"
    ).fetchall()
    seen: dict[str, str] = {}
    for row in rows:
        scheduled = row["scheduled_for"] or ""
        bucket = scheduled[:13]  # 小时窗口，与 ±1h 去重语义一致
        key = f"{row['patient_id']}|{row['task_id'] or ''}|{row['event_id'] or ''}|{bucket}"
        conflict = key in seen
        if not conflict:
            seen[key] = row["id"]
        conn.execute(
            "UPDATE reviews SET review_key=?, status=? WHERE id=?",
            (key, "superseded" if conflict and row["status"] == "scheduled" else row["status"], row["id"]),
        )


def _normalize_preferences(conn: sqlite3.Connection) -> None:
    """同患者同类型只保留一条 active。"""
    conn.execute(
        """UPDATE preferences SET status='superseded' WHERE status='active' AND rowid NOT IN (
               SELECT MAX(rowid) FROM preferences WHERE status='active' GROUP BY patient_id, kind)"""
    )


def _create_indexes(conn: sqlite3.Connection) -> None:
    conn.execute("DROP INDEX IF EXISTS uq_jobs_key")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_jobs_key ON automation_jobs("
        "kind, COALESCE(patient_id,''), COALESCE(ref_id,''), run_at)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_questions_waiting ON questions(patient_id, target_field) "
        "WHERE status='waiting'"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_reviews_window ON reviews(review_key) "
        "WHERE status='scheduled'"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_prefs_active ON preferences(patient_id, kind) "
        "WHERE status='active'"
    )


def migrate(conn: sqlite3.Connection) -> int:
    current = schema_version(conn)
    if current >= SCHEMA_VERSION:
        return current
    conn.execute("BEGIN IMMEDIATE")
    try:
        _dedupe_jobs(conn)
        _normalize_patients(conn)
        _dedupe_task_keys(conn)
        _normalize_questions(conn)
        _normalize_reviews(conn)
        _normalize_preferences(conn)
        _create_indexes(conn)
        set_meta(conn, "schema_version", str(SCHEMA_VERSION))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return SCHEMA_VERSION
