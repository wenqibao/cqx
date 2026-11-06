"""F05 健康事件检测：只使用配置中的固定规则，输出"需关注事项"，不做诊断。"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any

from backend.app.config import event_rules
from backend.app.db.connection import dumps, iso, loads, now
from backend.app.util import new_id

SEVERITY_ORDER = {"high": 3, "medium": 2, "low": 1}


def _rows(conn: sqlite3.Connection, patient_id: str, kind: str, since: datetime) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM health_records WHERE patient_id=? AND kind=? AND recorded_at>=? AND recorded_at<=? "
        "ORDER BY recorded_at",
        (patient_id, kind, iso(since), iso(now(conn))),
    ).fetchall()


def _eval_threshold(rule: dict[str, Any], rows: list[sqlite3.Row]) -> tuple[bool, dict[str, Any]]:
    vals = [r["value"] for r in rows if r["value"] is not None]
    if not vals:
        return False, {}
    op = rule.get("comparator", "gte")
    threshold = float(rule.get("threshold", 0))
    hits = [v for v in vals if (v >= threshold if op == "gte" else v <= threshold)]
    if not hits:
        return False, {}
    return True, {
        "matches": hits,
        "record_ids": [r["id"] for r in rows if r["value"] in hits],
        "threshold": threshold,
        "comparator": op,
        "window_days": rule.get("window_days"),
    }


def _eval_trend(rule: dict[str, Any], rows: list[sqlite3.Row]) -> tuple[bool, dict[str, Any]]:
    vals = [r["value"] for r in rows if r["value"] is not None]
    if len(vals) < int(rule.get("min_points", 2)):
        return False, {}
    delta = vals[-1] - vals[0]
    threshold = float(rule.get("delta_threshold", 0))
    if abs(delta) >= threshold:
        return True, {
            "first": vals[0],
            "last": vals[-1],
            "delta": round(delta, 2),
            "points": len(vals),
            "window_days": rule.get("window_days"),
        }
    daily_mean = rule.get("daily_mean_threshold")
    if daily_mean is not None:
        # 按自然日聚合后取日均，判断活动量是否偏低
        by_day: dict[str, list[float]] = {}
        for r in rows:
            if r["value"] is None:
                continue
            by_day.setdefault(str(r["recorded_at"])[:10], []).append(r["value"])
        means = [sum(v) / len(v) for v in by_day.values()]
        if means and sum(means) / len(means) < float(daily_mean):
            return True, {
                "daily_means": {k: round(sum(v) / len(v), 1) for k, v in by_day.items()},
                "threshold": daily_mean,
                "window_days": rule.get("window_days"),
            }
    return False, {}


def _eval_variability(rule: dict[str, Any], rows: list[sqlite3.Row]) -> tuple[bool, dict[str, Any]]:
    vals = [r["value"] for r in rows if r["value"] is not None]
    if len(vals) < int(rule.get("min_points", 3)):
        return False, {}
    span = max(vals) - min(vals)
    if span >= float(rule.get("range_threshold", 4.0)):
        return True, {"min": min(vals), "max": max(vals), "range": round(span, 2), "points": len(vals)}
    return False, {}


def _eval_adherence(rule: dict[str, Any], rows: list[sqlite3.Row]) -> tuple[bool, dict[str, Any]]:
    if not rows:
        return False, {}
    missed = [r for r in rows if (r["value"] or 0) <= 0]
    if len(missed) >= int(rule.get("missed_threshold", 2)):
        return True, {
            "missed_count": len(missed),
            "missed_record_ids": [r["id"] for r in missed],
            "window_days": rule.get("window_days"),
        }
    return False, {}


EVALUATORS = {
    "threshold": _eval_threshold,
    "trend": _eval_trend,
    "variability": _eval_variability,
    "adherence": _eval_adherence,
}


def detect_events(
    conn: sqlite3.Connection,
    patient_id: str,
    *,
    trigger: str = "record_created",
    codes: list[str] | None = None,
) -> dict[str, Any]:
    """运行全部（或指定）规则；返回新建/已存在事件列表。"""
    cfg = event_rules()
    ts = now(conn)
    bucket = iso(ts)[:13]  # 同一小时内同一规则只产生一个事件，保证幂等
    created: list[dict[str, Any]] = []
    existing: list[dict[str, Any]] = []
    for rule in cfg.get("rules", []):
        code = rule["code"]
        if codes and code not in codes:
            continue
        evaluator = EVALUATORS.get(rule.get("kind", ""))
        if evaluator is None:
            continue
        window = int(rule.get("window_days", cfg.get("window_days", 7)))
        rows = _rows(conn, patient_id, rule["metric"], ts - timedelta(days=window))
        hit, evidence = evaluator(rule, rows)
        if not hit:
            continue
        dedupe = f"{patient_id}:{code}:{bucket}"
        # EVENT-RECURRENCE-01：同小时事件已处理后又出现新异常，必须新建 open 事件
        prior = conn.execute("SELECT status FROM events WHERE dedupe_key=?", (dedupe,)).fetchone()
        if prior and prior["status"] != "open":
            dedupe = f"{dedupe}:{new_id('event')}"
        event_id = new_id("event")
        cur = conn.execute(
            """INSERT OR IGNORE INTO events(id,patient_id,code,severity,status,message,evidence,dedupe_key,
                    source_record_id,detected_at) VALUES(?,?,?,?,'open',?,?,?,?,?)""",
            (
                event_id,
                patient_id,
                code,
                rule.get("severity", "low"),
                rule.get("message", code),
                dumps({"trigger": trigger, **evidence}),
                dedupe,
                (evidence.get("record_ids") or [None])[0],
                iso(ts),
            ),
        )
        if cur.rowcount == 0:
            row = conn.execute("SELECT * FROM events WHERE dedupe_key=?", (dedupe,)).fetchone()
            if row:
                existing.append(row_to_event(row))
            continue
        row = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        created.append(row_to_event(row))
    created.sort(key=lambda e: SEVERITY_ORDER.get(e["severity"], 0), reverse=True)
    return {"created": created, "existing": existing}


def row_to_event(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "patient_id": row["patient_id"],
        "code": row["code"],
        "severity": row["severity"],
        "status": row["status"],
        "message": row["message"],
        "evidence": loads(row["evidence"], {}),
        "source_record_id": row["source_record_id"],
        "detected_at": row["detected_at"],
        "handled_at": row["handled_at"],
        "handled_by_run": row["handled_by_run"],
    }


def list_events(
    conn: sqlite3.Connection, patient_id: str, *, status: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM events WHERE patient_id=?"
    args: list[Any] = [patient_id]
    if status:
        sql += " AND status=?"
        args.append(status)
    sql += " ORDER BY detected_at DESC LIMIT ?"
    args.append(limit)
    return [row_to_event(r) for r in conn.execute(sql, args).fetchall()]


def get_event(conn: sqlite3.Connection, event_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    return row_to_event(row) if row else None


def mark_handled(conn: sqlite3.Connection, event_ids: list[str], run_id: str, status: str = "handled") -> None:
    ts = iso(now(conn))
    for event_id in event_ids:
        conn.execute(
            "UPDATE events SET status=?, handled_at=?, handled_by_run=? WHERE id=? AND status='open'",
            (status, ts, run_id, event_id),
        )
