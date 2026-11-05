"""F13 安全门：禁止医疗动作拦截、工具白名单、红旗信号升级、审计写入。"""
from __future__ import annotations

import re
import sqlite3
from typing import Any

from backend.app.config import safety_rules
from backend.app.db.connection import dumps, iso, now

# 免责声明上下文：命中的词如果落在这类短语之后，说明是在"我们不提供…"，属于引用而非请求
DISCLAIMER_MARKERS = ("不提供", "不做", "不给出", "不包含", "不含", "不包括", "不涉及", "不负责", "不得", "禁止", "无需", "无须", "不承诺")
DISCLAIMER_WINDOW = 24
# 免责声明后若出现转折或指令引导，说明否定只覆盖前半句，后半句是真实指令（A-REAL-02）
CONTRAST_CUES = ("而是", "只是", "反而", "不过", "却", "仍然", "还是")
INSTRUCTION_LEADIN = re.compile(r"(?:建议|请|应|需要|可以|要|立即|马上|尽快|务必|宜)\s*$")


class SafetyViolation(Exception):
    def __init__(self, code: str, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}


def _is_disclaimer(text: str, position: int, *, generated: bool = False) -> bool:
    window = text[max(0, position - DISCLAIMER_WINDOW) : position]
    # 否定只作用于当前分句，不能用前一句免责声明掩盖后一句越权指令。
    window = re.split(r"[，。；;！!？?\n]|但是|然而", window)[-1]
    if generated:
        # 输出中的否定边界说明/无具体剂量的转介，不等于患者提出执行医疗动作。
        if '能不能' not in window and re.search(r"(?:不构成|不作为|不会|不能|不应|不可)[^，。；]{0,10}$", window):
            return True
        right = re.split(r"[，。；;！!？?\n]", text[position:])[0]
        if re.fullmatch(r"(?:涉及|任何|关于|有关)?(?:用药|药物|胰岛素|诊断|处方)(?:方案|剂量|调整|问题|事项)*(?:请|应|需)(?:咨询|联系)(?:您?的)?(?:处方)?医生", window + right):
            return True
    covered = False
    for marker in DISCLAIMER_MARKERS:
        index = window.rfind(marker)
        if index < 0:
            continue
        tail = window[index + len(marker) :]
        # 免责后面紧跟"而是/只是…"或"建议/请…"→ 否定不覆盖本次命中，按真实指令处理
        if any(cue in tail for cue in CONTRAST_CUES) or INSTRUCTION_LEADIN.search(tail):
            continue
        covered = True
    return covered or bool(re.search(r"(?:不作|不进行|请勿)[^，。；]{0,8}$", window))


def _match_pattern(text: str, patterns: list[str], *, generated: bool = False) -> tuple[int, str] | None:
    for pattern in patterns:
        try:
            matches = list(re.finditer(pattern, text))
        except re.error:  # 配置写错不应让安全门整体失效
            continue
        for m in matches:
            if not _is_disclaimer(text, m.start(), generated=generated):
                return m.start(), m.group(0)
    return None


def check_text(text: str, *, generated: bool = False) -> dict[str, Any]:
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
            positions = [m.start() for m in re.finditer(re.escape(kw.lower()), lowered)]
            if any(not _is_disclaimer(lowered, position, generated=generated) for position in positions):
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
        hit = _match_pattern(lowered, [str(p) for p in (rule.get("patterns") or [])], generated=generated)
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
        unsafe_text = any(not check_text(str(args.get(k) or ''), generated=True)['allowed']
                          for k in ('claim','title','description','text','question','body'))
        if not check_tool(row['tool_name']) or unsafe_text:
            count += 1
    return count
