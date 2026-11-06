"""F04 状态记忆与趋势：把患者档案、记录、任务、事件、偏好在一次读取中装配成 Patient State。"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any

from backend.app.db.connection import dumps, iso, loads, now, parse_ts
from backend.app.services.patients import get_patient, profile_completeness
from backend.app.services.records import KIND_SPEC

METRICS = ("fasting_glucose", "postprandial_glucose", "steps", "weight", "medication_taken")


def _records_since(conn: sqlite3.Connection, patient_id: str, since: datetime) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM health_records WHERE patient_id=? AND recorded_at>=? AND recorded_at<=? ORDER BY recorded_at",
        (patient_id, iso(since), iso(now(conn))),
    ).fetchall()


def _aggregate(rows: list[sqlite3.Row], kind: str) -> dict[str, Any]:
    kind_rows = [r for r in rows if r["kind"] == kind and r["value"] is not None]
    vals = [r["value"] for r in kind_rows]
    if not vals:
        return {"count": 0}
    return {
        "count": len(vals),
        "mean": round(sum(vals) / len(vals), 2),
        "min": round(min(vals), 2),
        "max": round(max(vals), 2),
        "last": round(vals[-1], 2),
        "last_at": kind_rows[-1]["recorded_at"],  # 必须来自同一指标记录
    }


def _latest_per_kind(rows: list[sqlite3.Row]) -> dict[str, Any]:
    latest: dict[str, Any] = {}
    for row in rows:
        latest[row["kind"]] = {
            "value": row["value"],
            "unit": row["unit"],
            "recorded_at": row["recorded_at"],
            "payload": loads(row["payload"], {}),
        }
    return latest


def build_state(conn: sqlite3.Connection, patient_id: str) -> dict[str, Any]:
    patient = get_patient(conn, patient_id)
    ts = now(conn)
    rows_7d = _records_since(conn, patient_id, ts - timedelta(days=7))
    rows_14d = _records_since(conn, patient_id, ts - timedelta(days=14))
    rows_3d = _records_since(conn, patient_id, ts - timedelta(days=3))
    latest = _latest_per_kind(list(rows_14d))

    aggregates = {
        "7d": {m: _aggregate(rows_7d, m) for m in METRICS},
        "3d": {m: _aggregate(rows_3d, m) for m in METRICS},
        "14d": {m: _aggregate(rows_14d, m) for m in METRICS},
    }

    glucose_vals = [r["value"] for r in rows_7d if r["kind"] == "fasting_glucose" and r["value"] is not None]
    trend = "unknown"
    if len(glucose_vals) >= 2:
        delta = glucose_vals[-1] - glucose_vals[0]
        trend = "rising" if delta >= 0.5 else "falling" if delta <= -0.5 else "stable"

    tasks = conn.execute(
        "SELECT * FROM tasks WHERE patient_id=? AND status IN ('pending','missed') ORDER BY priority DESC, due_at",
        (patient_id,),
    ).fetchall()
    open_tasks = [
        {
            "id": t["id"],
            "task_type": t["task_type"],
            "title": t["title"],
            "status": t["status"],
            "priority": t["priority"],
            "due_at": t["due_at"],
            "required_fields": loads(t["required_fields"], []),
            "event_id": t["event_id"],
            "version": t["version"],
        }
        for t in tasks
    ]
    events = conn.execute(
        "SELECT id, code, severity, status, message, detected_at FROM events WHERE patient_id=? AND status='open' "
        "ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, detected_at DESC",
        (patient_id,),
    ).fetchall()
    open_events = [dict(e) for e in events]
    questions = conn.execute(
        "SELECT id, kind, question, target_field, status, created_at FROM questions "
        "WHERE patient_id=? AND status='waiting' ORDER BY created_at",
        (patient_id,),
    ).fetchall()
    prefs = conn.execute(
        "SELECT id, kind, value, source, valid_from FROM preferences WHERE patient_id=? AND status='active' "
        "ORDER BY created_at DESC",
        (patient_id,),
    ).fetchall()
    notifications = conn.execute(
        "SELECT COUNT(*) AS c FROM notifications WHERE patient_id=? AND status='unread'", (patient_id,)
    ).fetchone()

    completeness = profile_completeness(patient)
    missing_fields = list(completeness["missing"])
    # 关键健康数据缺失也属于"需要补全的信息"（F04 → F21）
    for metric in ("fasting_glucose", "steps", "medication_taken"):
        if int(aggregates["7d"].get(metric, {}).get("count", 0)) == 0 and metric not in missing_fields:
            missing_fields.append(metric)
    for task in open_tasks:
        for field in task["required_fields"]:
            if field not in missing_fields and _field_missing(field, latest, rows_7d):
                missing_fields.append(field)

    return {
        "patient": patient,
        "profile_complete": completeness["complete"],
        "missing_fields": missing_fields,
        "trend": {"fasting_glucose_7d": trend},
        "aggregates": aggregates,
        "latest": latest,
        "open_events": open_events,
        "open_tasks": open_tasks,
        "pending_questions": [dict(q) for q in questions],
        "preferences": [dict(p) for p in prefs],
        "unread_notifications": notifications["c"] if notifications else 0,
        "record_counts": {
            "3d": len(rows_3d),
            "7d": len(rows_7d),
            "14d": len(rows_14d),
        },
        "generated_at": iso(ts),
    }


def _field_missing(field: str, latest: dict[str, Any], rows_7d: list[sqlite3.Row]) -> bool:
    """判断某任务所需字段在近 7 天是否已具备。"""
    if field == "medication_taken":
        return not any(r["kind"] == "medication_taken" for r in rows_7d)
    if field == "steps":
        return not any(r["kind"] == "steps" for r in rows_7d)
    if field == "fasting_glucose":
        return not any(r["kind"] == "fasting_glucose" for r in rows_7d)
    return field not in latest


def save_snapshot(conn: sqlite3.Connection, patient_id: str, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    snap = snapshot or build_state(conn, patient_id)
    row = conn.execute(
        "SELECT COALESCE(MAX(version),0) AS v FROM state_snapshots WHERE patient_id=?", (patient_id,)
    ).fetchone()
    version = int(row["v"]) + 1
    conn.execute(
        "INSERT INTO state_snapshots(patient_id,version,snapshot,created_at) VALUES(?,?,?,?)",
        (patient_id, version, dumps(snap), iso(now(conn))),
    )
    snap["snapshot_version"] = version
    return snap


def latest_snapshot(conn: sqlite3.Connection, patient_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM state_snapshots WHERE patient_id=? ORDER BY version DESC LIMIT 1", (patient_id,)
    ).fetchone()
    if not row:
        return None
    return {**loads(row["snapshot"], {}), "snapshot_version": row["version"], "snapshot_at": row["created_at"]}


def describe_kinds() -> dict[str, Any]:
    return KIND_SPEC
