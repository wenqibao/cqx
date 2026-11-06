"""F26 决策自检：执行前校验计划，执行后核对数据库，失败必须显式记录，不能当作成功。"""
from __future__ import annotations

import sqlite3
from typing import Any

from backend.app.config import safety_rules, task_rules
from backend.app.db.connection import loads, now, parse_ts
from backend.app.safety import gate

# 拒绝码：B 的测试会逐一核对，报告里必须出现这些值
NO_EVIDENCE = "NO_EVIDENCE"
FORBIDDEN_ACTION = "FORBIDDEN_ACTION"
TOOL_NOT_ALLOWED = "TOOL_NOT_ALLOWED"
TOO_MANY_ACTIONS = "TOO_MANY_ACTIONS"
INVALID_DUE = "INVALID_DUE"
DUPLICATE_TASK = "DUPLICATE_TASK"
MISSING_REQUIRED_DATA = "MISSING_REQUIRED_DATA"
TASK_NOT_FOUND = "TASK_NOT_FOUND"
TOOL_EXECUTION_FAILED = "TOOL_EXECUTION_FAILED"
POSTCHECK_MISMATCH = "POSTCHECK_MISMATCH"
UNSAFE_CLAIM = "UNSAFE_CLAIM"
UNKNOWN_TOOL = "UNKNOWN_TOOL"

ALL_CODES = [
    NO_EVIDENCE,
    FORBIDDEN_ACTION,
    TOOL_NOT_ALLOWED,
    TOO_MANY_ACTIONS,
    INVALID_DUE,
    DUPLICATE_TASK,
    MISSING_REQUIRED_DATA,
    TASK_NOT_FOUND,
    TOOL_EXECUTION_FAILED,
    POSTCHECK_MISMATCH,
    UNSAFE_CLAIM,
    UNKNOWN_TOOL,
]


def _due_ok(conn: sqlite3.Connection, due_at: str | None) -> tuple[bool, str]:
    if not due_at:
        return True, ""
    try:
        dt = parse_ts(due_at)
    except (ValueError, TypeError, AttributeError):
        dt = None
    if dt is None or dt.tzinfo is None:
        return False, f"due_at 不是合法时间: {due_at}"
    limits = safety_rules().get("limits", {})
    delta_hours = (dt - now(conn)).total_seconds() / 3600
    lo = float(limits.get("task_due_min_hours", 1))
    hi = float(limits.get("task_due_max_days", 30)) * 24
    if delta_hours < -0.01 or delta_hours > hi:
        return False, f"任务截止时间超出允许范围（{delta_hours:.1f}h，允许 0~{hi:.0f}h）"
    return True, ""


def validate_plan(
    conn: sqlite3.Connection,
    *,
    patient_id: str,
    plan: dict[str, Any],
    state: dict[str, Any] | None = None,
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """执行前校验：越权动作、无证据结论、时间越界、重复任务、超量动作。"""
    limits = safety_rules().get("limits", {})
    max_actions = int(limits.get("max_tasks_per_run", 5)) + 3
    actions = plan.get("actions", []) or []
    rejections: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if len(actions) > max_actions:
        rejections.append(
            {"code": TOO_MANY_ACTIONS, "message": f"单次计划动作过多（{len(actions)} > {max_actions}）", "index": None}
        )
    for tool, maximum in (("create_task", int(limits.get("max_tasks_per_run", 5))),
                          ("ask_user", int(limits.get("max_questions_per_run", 2)))):
        if sum(a.get("tool") == tool for a in actions) > maximum:
            rejections.append({"code": TOO_MANY_ACTIONS, "message": f"单次运行 {tool} 超出 {maximum} 次", "index": None})
    evidence = evidence or []
    for idx, action in enumerate(actions):
        tool = action.get("tool") or ""
        args = action.get("args", {})
        if not gate.check_tool(tool):
            rejections.append(
                {"code": TOOL_NOT_ALLOWED, "message": f"工具 {tool} 不在白名单内", "index": idx, "tool": tool}
            )
            continue
        if not isinstance(args, dict):
            rejections.append({"code": MISSING_REQUIRED_DATA, "message": "工具参数必须为对象", "index": idx, "tool": tool})
            continue
        from backend.app.agent.tools import TOOL_SPECS

        invalid = []
        for name, spec in TOOL_SPECS.get(tool, {}).get("parameters", {}).items():
            value = args.get(name)
            if (value is None or value == "") and spec.endswith("?"):
                continue
            base = spec.rstrip("?")
            valid = ((isinstance(value, str) and bool(value.strip())) if base in ("string", "iso8601") else
                     (isinstance(value, int) and not isinstance(value, bool)) if base == "int" else
                     isinstance(value, list) and all(isinstance(v, str) for v in value) if base == "array" else
                     isinstance(value, dict) if base == "object" else isinstance(value, bool))
            if not valid:
                invalid.append(name)
        if invalid:
            rejections.append({"code": MISSING_REQUIRED_DATA, "message": f"工具参数缺失或类型错误: {', '.join(invalid)}", "index": idx, "tool": tool})
            continue
        if tool == "save_preference":
            from backend.app.memory.preferences import ALLOWED_KINDS, ALLOWED_SOURCES

            if args.get("kind") not in ALLOWED_KINDS or args.get("source") not in ALLOWED_SOURCES:
                rejections.append({"code": MISSING_REQUIRED_DATA, "message": "偏好类型或来源不在已支持枚举内", "index": idx, "tool": tool})
        if args.get("patient_id") is not None and args["patient_id"] != patient_id:
            rejections.append({"code": FORBIDDEN_ACTION, "message": "禁止访问其他患者", "index": idx, "tool": tool})
            continue
        for ref, table in (("task_id", "tasks"), ("event_id", "events")):
            if args.get(ref):
                row = conn.execute(f"SELECT patient_id FROM {table} WHERE id=?", (args[ref],)).fetchone()
                if not row or row['patient_id'] != patient_id:
                    rejections.append({"code": TASK_NOT_FOUND if not row else FORBIDDEN_ACTION,
                                       "message": f"{ref}不存在或不属于当前患者", "index": idx, "tool": tool})
        claim = action.get("claim") or args.get("claim") or ""
        if claim:
            verdict = gate.check_text(claim)
            if not verdict["allowed"]:
                rejections.append(
                    {
                        "code": FORBIDDEN_ACTION,
                        "message": verdict["message"] or "计划包含被禁止的医疗动作",
                        "index": idx,
                        "tool": tool,
                        "detail": {"intent": verdict["code"], "matched": verdict["matched"]},
                    }
                )
        for text_field in ("title", "description", "answer_summary", "text", "question", "body", "reason"):
            text = args.get(text_field) or ""
            if text:
                verdict = gate.check_text(text, generated=True)
                if not verdict["allowed"]:
                    rejections.append(
                        {
                            "code": FORBIDDEN_ACTION,
                            "message": f"动作文本包含被禁止的医疗动作: {verdict['name']}",
                            "index": idx,
                            "tool": tool,
                        }
                    )
        if action.get("requires_evidence") and not evidence:
            rejections.append(
                {
                    "code": NO_EVIDENCE,
                    "message": "该动作需要可定位的知识证据，但检索无结果，禁止臆测执行",
                    "index": idx,
                    "tool": tool,
                }
            )
        ok, reason = _due_ok(conn, args.get("due_at"))
        if not ok:
            rejections.append({"code": INVALID_DUE, "message": reason, "index": idx, "tool": tool})
        if tool == "update_task" and args.get("task_id"):
            row = conn.execute("SELECT status FROM tasks WHERE id=?", (args["task_id"],)).fetchone()
            if not row:
                rejections.append(
                    {"code": TASK_NOT_FOUND, "message": f"要修改的任务不存在: {args['task_id']}", "index": idx, "tool": tool}
                )
        citations = args.get("citations") or []
        if citations:
            valid_refs = {str(e.get(k)) for e in evidence for k in ("id", "doc_id", "chunk_id", "citation", "anchor") if e.get(k)}
            valid_refs.update(str(e.get("doc_id", "")) + str(e.get("anchor", "")) for e in evidence)
            if any(c not in valid_refs for c in citations):
                rejections.append({"code": NO_EVIDENCE, "message": "引用不属于本次检索证据", "index": idx, "tool": tool})
    return {"ok": not rejections, "rejections": rejections, "warnings": warnings, "checked_at": None}


def evidence_required_for(plan: dict[str, Any]) -> bool:
    return any(a.get("requires_evidence") for a in plan.get("actions", []) or [])


def post_execution_check(
    conn: sqlite3.Connection, *, tool: str, args: dict[str, Any], result: dict[str, Any]
) -> dict[str, Any]:
    """执行后核对：工具声称成功时，数据库必须真的发生了对应变更。"""
    if not result.get("ok"):
        return {"ok": False, "code": TOOL_EXECUTION_FAILED, "message": result.get("error", "工具返回失败")}
    if tool == "create_task":
        task_id = result.get("task_id")
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            return {"ok": False, "code": POSTCHECK_MISMATCH, "message": f"数据库中没有任务 {task_id}"}
        return {"ok": True, "detail": {"task_id": task_id, "status": row["status"]}}
    if tool == "update_task":
        task_id = args.get("task_id")
        row = conn.execute("SELECT version FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            return {"ok": False, "code": POSTCHECK_MISMATCH, "message": f"任务 {task_id} 不存在"}
        expected = result.get("version")
        if expected is not None and int(row["version"]) != int(expected):
            return {
                "ok": False,
                "code": POSTCHECK_MISMATCH,
                "message": f"任务版本不一致: DB={row['version']} 工具返回={expected}",
            }
        return {"ok": True, "detail": {"task_id": task_id, "version": row["version"]}}
    if tool == "complete_task":
        task_id = args.get("task_id")
        row = conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row or row["status"] != "done":
            return {"ok": False, "code": POSTCHECK_MISMATCH, "message": "任务未真正标记完成"}
        return {"ok": True, "detail": {"task_id": task_id, "status": "done"}}
    if tool == "schedule_review":
        review_id = result.get("review_id")
        row = conn.execute("SELECT * FROM reviews WHERE id=?", (review_id,)).fetchone()
        if not row:
            return {"ok": False, "code": POSTCHECK_MISMATCH, "message": "复评未入库"}
        return {"ok": True, "detail": {"review_id": review_id, "scheduled_for": row["scheduled_for"]}}
    if tool == "ask_user":
        qid = result.get("question_id")
        row = conn.execute("SELECT status FROM questions WHERE id=?", (qid,)).fetchone()
        if not row or row["status"] != "waiting":
            return {"ok": False, "code": POSTCHECK_MISMATCH, "message": "问题未进入等待答复状态"}
        return {"ok": True, "detail": {"question_id": qid}}
    if tool == "save_preference":
        kind = args.get("kind")
        row = conn.execute(
            "SELECT * FROM preferences WHERE patient_id=? AND kind=? AND status='active'",
            (args.get("patient_id"), kind),
        ).fetchone()
        if not row:
            return {"ok": False, "code": POSTCHECK_MISMATCH, "message": "偏好未写入"}
        return {"ok": True, "detail": {"preference_id": row["id"]}}
    if tool == "create_notification":
        row = conn.execute("SELECT * FROM notifications WHERE id=?", (result.get("notification_id"),)).fetchone()
        if not row:
            return {"ok": False, "code": POSTCHECK_MISMATCH, "message": "通知未写入"}
        return {"ok": True, "detail": {"notification_id": row["id"]}}
    return {"ok": True, "detail": {}}


def conflict_check(
    conn: sqlite3.Connection, *, patient_id: str, task_ids: list[str]
) -> list[dict[str, Any]]:
    """F22 冲突检查：同一任务重复入库、同一时段过多任务。"""
    issues: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tid in task_ids:
        if tid in seen:
            issues.append({"code": DUPLICATE_TASK, "message": f"同一次计划中重复创建任务 {tid}"})
        seen.add(tid)
    rows = conn.execute(
        "SELECT due_at, COUNT(*) AS c FROM tasks WHERE patient_id=? AND status='pending' AND due_at IS NOT NULL "
        "GROUP BY due_at",
        (patient_id,),
    ).fetchall()
    for r in rows:
        if r["c"] > 4:
            issues.append(
                {"code": DUPLICATE_TASK, "message": f"{r['due_at']} 时段任务过多（{r['c']} 个），建议合并"}
            )
    return issues


def summarize_limits() -> dict[str, Any]:
    return {"limits": safety_rules().get("limits", {}), "dedupe_window_hours": task_rules().get("dedupe_window_hours")}
