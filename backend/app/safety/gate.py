"""F13 安全门：禁止医疗动作拦截、工具白名单、红旗信号升级、审计写入。"""
from __future__ import annotations

import re
import sqlite3
from typing import Any

from backend.app.config import safety_rules
from backend.app.db.connection import dumps, iso, now

# 免责声明上下文：命中的词如果落在这类短语之后，说明是在"我们不提供…"，属于引用而非请求
DISCLAIMER_MARKERS = ("不提供", "不做", "不给出", "不包含", "不负责", "不得", "禁止", "无需", "不承诺")
DISCLAIMER_WINDOW = 24


class SafetyViolation(Exception):
    def __init__(self, code: str, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}


def _is_disclaimer(text: str, position: int) -> bool:
    window = text[max(0, position - DISCLAIMER_WINDOW) : position]
    return any(marker in window for marker in DISCLAIMER_MARKERS)


def _match_pattern(text: str, patterns: list[str]) -> tuple[int, str] | None:
    for pattern in patterns:
        try:
            m = re.search(pattern, text)
        except re.error:  # 配置写错不应让安全门整体失效
            continue
        if m and not _is_disclaimer(text, m.start()):
            return m.start(), m.group(0)
    return None


def check_text(text: str) -> dict[str, Any]:
    """检查患者输入/模型输出中是否包含被禁止的医疗动作意图。

    两层识别：
    1) forbidden_intents.keywords —— 固定说法（"停药""开药"…）；
    2) intent_patterns —— "药物对象 + 剂量/用法变化"的表达变体
       （如"把胰岛素改成早上多打两单位"），避免只靠关键词漏拦。
    """
    cfg = safety_rules()
    # 规则自身的固定拒绝话术是可信的否定说明，不能再次按关键词误拦。
    refusal_texts = {r.get("message") for r in cfg.get("forbidden_intents", []) + cfg.get("intent_patterns", [])}
    if text.strip() in refusal_texts:
        return {"allowed": True, "code": None, "message": "", "matched": None}
    lowered = (text or "").lower()
    for rule in cfg.get("forbidden_intents", []):
        for kw in rule.get("keywords", []):
            position = lowered.find(kw.lower())
            if position >= 0 and not _is_disclaimer(lowered, position):
                return {
                    "allowed": False,
                    "code": rule["code"],
                    "name": rule.get("name", rule["code"]),
                    "message": rule.get("message", ""),
                    "matched": kw,
                }
    for rule in cfg.get("intent_patterns", []):
        terms = [str(t).lower() for t in (rule.get("terms") or [])]
        if terms and not any(term in lowered for term in terms):
            continue
        hit = _match_pattern(lowered, [str(p) for p in (rule.get("patterns") or [])])
        if hit:
            return {
                "allowed": False,
                "code": rule["code"],
                "name": rule.get("name", rule["code"]),
                "message": rule.get("message", ""),
                "matched": hit[1],
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
    # reject 表示已阻止，不能当成执行。按成功工具轨迹核对实际输出/动作文本。
    rows = conn.execute("SELECT run_id,step_no,tool_name FROM agent_steps WHERE kind='tool_result' AND status='ok'").fetchall()
    from backend.app.db.connection import loads

    count = 0
    for row in rows:
        call = conn.execute("SELECT payload FROM agent_steps WHERE run_id=? AND kind='tool_call' AND tool_name=? AND step_no<? ORDER BY step_no DESC LIMIT 1",
                            (row['run_id'], row['tool_name'], row['step_no'])).fetchone()
        args = loads(call['payload'], {}).get('args', {}) if call else {}
        unsafe_text = any(not check_text(str(args.get(k) or ''))['allowed']
                          for k in ('claim','title','description','text','question','body'))
        if not check_tool(row['tool_name']) or unsafe_text:
            count += 1
    return count
