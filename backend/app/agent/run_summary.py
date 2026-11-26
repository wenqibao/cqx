"""O1：运行顶部业务结果摘要。

从已有运行、轨迹、问题、任务与复评生成稳定摘要，不新增表、不改状态机。
所有"已完成/已调整/已安排"必须有真实工具成功与数据库对象支持。
"""
from __future__ import annotations

import sqlite3
from typing import Any

from backend.app.db.connection import loads

TRIGGER_LABELS = {
    "record_created": "新增健康记录",
    "event_detected": "检测到健康事件",
    "review_due": "复评到期",
    "user_request": "患者主动请求",
    "answer_received": "患者回答问题",
    "scheduled_tick": "定时任务触发",
    "scan": "扫描触发",
}

GOAL_BY_INTENT = {
    "event_response": "核实并处理患者近期健康事件",
    "answer_received": "根据患者回答恢复管理流程",
    "knowledge_question": "回答患者健康问题",
    "negotiate_plan": "根据患者时间约束调整计划",
    "unsafe_request": "拦截越权请求并给出安全指引",
    "check_in": "跟进患者近期管理情况",
    "patient_request": "执行患者请求的健康管理动作",
}

TOOL_LABELS = {
    "create_task": "创建任务",
    "update_task": "调整任务",
    "complete_task": "完成任务",
    "schedule_review": "安排复评",
    "request_human_review": "提交人工复核",
    "ask_user": "向患者提问",
    "create_notification": "发送提醒",
    "save_preference": "保存偏好",
    "search_knowledge": "检索知识库",
    "query_history": "查询历史",
    "list_tasks": "查看任务",
}

MANAGEMENT_TOOLS = {"create_task", "update_task", "complete_task", "schedule_review",
                    "request_human_review", "ask_user", "create_notification", "save_preference"}


def _payload(step: dict[str, Any]) -> dict[str, Any]:
    value = step.get("payload")
    if isinstance(value, dict):
        return value
    return loads(value, {}) or {}


def _refs_from_result(result: dict[str, Any]) -> list[str]:
    refs = []
    for key in ("task_id", "review_id", "question_id", "notification_id", "preference_id"):
        value = result.get(key)
        if isinstance(value, str) and value:
            refs.append(value)
    return refs


def _verify_object(conn: sqlite3.Connection, patient_id: str, tool: str,
                   result: dict[str, Any]) -> tuple[bool, str | None]:
    """成功工具必须能在数据库中找到真实对象，且归属/状态与声明一致。"""
    if tool in ("create_task", "update_task", "complete_task"):
        task_id = result.get("task_id")
        row = conn.execute("SELECT patient_id,status,version FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not task_id or not row:
            return False, "任务不存在"
        if row["patient_id"] != patient_id:
            return False, "任务属于其他患者"
        if tool == "complete_task" and row["status"] != "done":
            return False, "任务未标记完成"
        if tool == "update_task" and result.get("version") is not None:
            if int(row["version"]) != int(result["version"]):
                return False, "任务版本与工具返回不一致"
        return True, None
    if tool in ("schedule_review", "request_human_review"):
        review_id = result.get("review_id")
        row = conn.execute("SELECT patient_id,status,branch FROM reviews WHERE id=?", (review_id,)).fetchone()
        if not review_id or not row:
            return False, "复评不存在"
        if row["patient_id"] != patient_id:
            return False, "复评属于其他患者"
        if tool == "request_human_review" and row["branch"] != "HUMAN_REVIEW":
            return False, "不是人工复核分支"
        if tool == "schedule_review" and row["status"] not in ("scheduled", "resolved"):
            return False, "复评状态异常"
        return True, None
    if tool == "ask_user":
        question_id = result.get("question_id")
        row = conn.execute("SELECT patient_id,status FROM questions WHERE id=?", (question_id,)).fetchone()
        if not question_id or not row:
            return False, "问题不存在"
        if row["patient_id"] != patient_id:
            return False, "问题属于其他患者"
        if row["status"] not in ("waiting", "answered", "expired"):
            return False, "问题状态异常"
        return True, None
    if tool == "create_notification":
        notification_id = result.get("notification_id")
        row = conn.execute("SELECT patient_id FROM notifications WHERE id=?", (notification_id,)).fetchone()
        if not notification_id or not row:
            return False, "通知不存在"
        if row["patient_id"] != patient_id:
            return False, "通知属于其他患者"
        return True, None
    if tool == "save_preference":
        preference_id = result.get("preference_id")
        row = conn.execute("SELECT patient_id,status FROM preferences WHERE id=?", (preference_id,)).fetchone()
        if not preference_id or not row:
            return False, "偏好不存在"
        if row["patient_id"] != patient_id or row["status"] != "active":
            return False, "偏好无效或属于其他患者"
        return True, None
    return True, None


PLAN_FIELDS = ("due_at", "title", "description", "status", "priority", "task_type")


def _plan_changes(conn: sqlite3.Connection, run_id: str) -> list[dict[str, Any]]:
    """O4：本次运行实际写入的任务版本与前一版本对照。"""
    rows = conn.execute(
        "SELECT task_id, version, snapshot, change_kind, reason, changed_by, created_at "
        "FROM task_versions WHERE run_id=? ORDER BY task_id, version", (run_id,)
    ).fetchall()
    changes: list[dict[str, Any]] = []
    for row in rows:
        after = loads(row["snapshot"], {}) or {}
        previous = conn.execute(
            "SELECT snapshot FROM task_versions WHERE task_id=? AND version<? ORDER BY version DESC LIMIT 1",
            (row["task_id"], row["version"]),
        ).fetchone()
        before = (loads(previous["snapshot"], {}) or {}) if previous else {}
        diff = {}
        for field in PLAN_FIELDS:
            if before.get(field) != after.get(field):
                diff[field] = {"before": before.get(field), "after": after.get(field)}
        changes.append({
            "task_id": row["task_id"],
            "title": after.get("title"),
            "change_kind": row["change_kind"],
            "version_before": before.get("version"),
            "version_after": after.get("version"),
            "changed_fields": diff,
            "reason": row["reason"],
            "changed_by": row["changed_by"],
            "result": "saved",
        })
    return changes


def build(conn: sqlite3.Connection, run: dict[str, Any], steps: list[dict[str, Any]],
          questions: list[dict[str, Any]], reviews: list[dict[str, Any]],
          tasks: list[dict[str, Any]]) -> dict[str, Any]:
    output = run.get("output") or {}
    plan = run.get("plan") or {}
    input_data = run.get("input") or {}
    intent = run.get("intent") or plan.get("intent") or ""

    event_ids = plan.get("events") or []
    goal = GOAL_BY_INTENT.get(intent)
    if not goal:
        message = (input_data.get("message") or "").strip()
        goal = message[:40] if message else "处理患者健康管理请求"

    trigger = {
        "type": run.get("trigger_type"),
        "label": TRIGGER_LABELS.get(run.get("trigger_type"), run.get("trigger_type")),
        "ref": run.get("trigger_ref"),
        "reason": (input_data.get("message") or "").strip()[:80] or None,
    }

    completed: list[dict[str, Any]] = []
    unfinished: list[dict[str, Any]] = []
    refs: set[str] = {run["id"]}
    refs.update(value for value in event_ids if isinstance(value, str))

    for step in steps:
        payload = _payload(step)
        tool = step.get("tool_name")
        if step.get("kind") == "tool_result" and step.get("status") == "ok" and tool in MANAGEMENT_TOOLS:
            result = payload.get("result") or {}
            verified, reason = _verify_object(conn, run["patient_id"], tool, result)
            if not verified:
                unfinished.append({"code": "TRACE_MISMATCH", "message": reason, "tool": tool})
                continue
            completed.append({
                "tool": tool,
                "label": TOOL_LABELS.get(tool, tool),
                "refs": _refs_from_result(result),
            })
            refs.update(_refs_from_result(result))
            if result.get("status") == "done":
                completed[-1]["detail"] = "任务已完成"
    for rejection in output.get("rejections") or []:
        unfinished.append({
            "code": rejection.get("code"),
            "message": rejection.get("message"),
            "tool": rejection.get("tool"),
        })
    for step in steps:
        if step.get("status") == "failed" and step.get("kind") in ("tool_result", "rejection"):
            entry = {"code": step.get("code"), "message": (_payload(step).get("post_check") or {}).get("message"),
                     "tool": step.get("tool_name")}
            if entry["code"] and all(item.get("code") != entry["code"] or item.get("tool") != entry["tool"]
                                     for item in unfinished):
                unfinished.append(entry)

    if run.get("status") in ("failed", "blocked") and run.get("error"):
        if not any(item.get("message") == run["error"] for item in unfinished):
            unfinished.append({"code": "RUN_ERROR", "message": run["error"], "tool": None})

    waiting_question = next((q for q in questions if q.get("status") == "waiting"), None)
    waiting_review = next((r for r in reviews if r.get("status") == "pending_human"), None)
    waiting = None
    next_owner = None
    if waiting_question:
        waiting = {"kind": "question", "id": waiting_question.get("id"),
                   "target_field": waiting_question.get("target_field"),
                   "text": waiting_question.get("question")}
        next_owner = {"role": "patient", "action": "回答待确认问题"}
    elif waiting_review:
        waiting = {"kind": "human_review", "id": waiting_review.get("id")}
        next_owner = {"role": "clinician", "action": "完成人工复核"}
    elif run.get("status") == "waiting_user":
        next_owner = {"role": "patient", "action": "补充必要信息"}
    elif run.get("status") in ("failed", "blocked"):
        next_owner = {"role": "agent", "action": "查看失败原因后重试或人工处理"}

    for task in tasks:
        refs.add(task["id"])
        if task.get("status") == "pending":
            refs.add(task["id"])
    for question in questions:
        refs.add(question["id"])
    for review in reviews:
        refs.add(review["id"])

    unresolved = [w for w in (output.get("warnings") or []) if not w.get("resolved", True)]
    partial_success = bool(completed) and (bool(unfinished) or bool(unresolved))
    return {
        "goal": goal,
        "trigger": trigger,
        "completed": completed,
        "unfinished": unfinished,
        "waiting": waiting,
        "next_owner": next_owner,
        "partial_success": partial_success,
        "warnings": output.get("warnings") or [],
        "plan_changes": _plan_changes(conn, run["id"]),
        "refs": sorted(refs),
    }
