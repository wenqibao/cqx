"""F13 安全门：禁止医疗动作拦截、工具白名单、红旗信号升级、审计写入。"""
from __future__ import annotations

import sqlite3
from typing import Any

from backend.app.config import safety_rules
from backend.app.db.connection import dumps, iso, now


class SafetyViolation(Exception):
    def __init__(self, code: str, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}


def check_text(text: str) -> dict[str, Any]:
    """检查患者输入/模型输出中是否包含被禁止的医疗动作意图。"""
    cfg = safety_rules()
    lowered = (text or "").lower()
    for rule in cfg.get("forbidden_intents", []):
        for kw in rule.get("keywords", []):
            if kw.lower() in lowered:
                return {
                    "allowed": False,
                    "code": rule["code"],
                    "name": rule.get("name", rule["code"]),
                    "message": rule.get("message", ""),
                    "matched": kw,
                }
    return {"allowed": True, "code": None, "message": "", "matched": None}


def assert_safe(text: str) -> None:
    verdict = check_text(text)
    if not verdict["allowed"]:
        raise SafetyViolation(verdict["code"], verdict["message"], {"matched": verdict["matched"]})


def check_tool(tool_name: str) -> bool:
    return tool_name in set(safety_rules().get("allowed_tools", []))


def escalation_hits(state: dict[str, Any], conn: sqlite3.Connection | None = None, patient_id: str | None = None) -> list[dict[str, Any]]:
    """扫描红旗信号（低血糖、显著高血糖、危险症状）。

    有数据库连接时扫描最近 3 天的原始记录，避免"最新一条刚好正常"而漏掉近期的低血糖；
    没有连接时退化为只看最新一条（纯函数用途）。
    """
    cfg = safety_rules()
    hits: list[dict[str, Any]] = []
    patient_id = patient_id or (state.get("patient") or {}).get("id")
    recent: list[tuple[str, float, dict[str, Any]]] = []
    if conn is not None and patient_id:
        from datetime import timedelta

        from backend.app.db.connection import iso, now

        since = iso(now(conn) - timedelta(days=3))
        rows = conn.execute(
            "SELECT kind, value, payload, recorded_at FROM health_records "
            "WHERE patient_id=? AND recorded_at>=? ORDER BY recorded_at DESC",
            (patient_id, since),
        ).fetchall()
        for r in rows:
            payload = {}
            try:
                import json

                payload = json.loads(r["payload"] or "{}")
            except Exception:
                payload = {}
            recent.append((r["kind"], r["value"], payload))
    latest = state.get("latest", {})
    if not recent:
        for key in ("fasting_glucose", "postprandial_glucose"):
            item = latest.get(key)
            if item:
                recent.append((key, item.get("value"), item.get("payload") or {}))
        for key in ("symptom",):
            item = latest.get(key)
            if item:
                recent.append((key, None, item.get("payload") or {}))

    for rule in cfg.get("escalation_rules", []):
        field = rule.get("field")
        if field == "glucose":
            op, threshold = rule.get("op"), float(rule.get("threshold", 0))
            for kind, value, _payload in recent:
                if kind not in ("fasting_glucose", "postprandial_glucose") or value is None:
                    continue
                if (op == "lte" and value <= threshold) or (op == "gte" and value >= threshold):
                    hits.append(
                        {
                            "code": rule["code"],
                            "severity": rule.get("severity", "high"),
                            "message": rule.get("message", ""),
                            "about": f"血糖记录 {value} mmol/L",
                        }
                    )
                    break
        if field == "symptom":
            for kind, _value, payload in recent:
                if kind != "symptom":
                    continue
                text = str(payload.get("text", ""))
                matched = next((kw for kw in rule.get("keywords", []) if kw and kw in text), None)
                if matched:
                    hits.append(
                        {
                            "code": rule["code"],
                            "severity": rule.get("severity", "high"),
                            "message": rule.get("message", ""),
                            "about": f"症状记录：{text}",
                        }
                    )
                    break
    return hits


def audit(
    conn: sqlite3.Connection,
    *,
    actor: str,
    action: str,
    decision: str,
    patient_id: str | None = None,
    run_id: str | None = None,
    code: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        "INSERT INTO audit_log(ts,patient_id,run_id,actor,action,decision,code,detail) VALUES(?,?,?,?,?,?,?,?)",
        (iso(now(conn)), patient_id, run_id, actor, action, decision, code, dumps(detail or {})),
    )


def forbidden_action_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS c FROM audit_log WHERE decision='reject'").fetchone()
    return int(row["c"]) if row else 0
