"""F09 个性化任务规划 + F22 多事件协调与优先级。"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from backend.app.config import safety_rules, task_rules
from backend.app.db.connection import iso, now, parse_ts

SEVERITY_WEIGHT = {"high": 100, "medium": 60, "low": 30}
KNOWN_HISTORY_BOOST = {"T2DM": 0}

QUESTION_HINTS = ("为什么", "为何", "怎么", "如何", "是什么", "什么", "能不能", "可以吗", "?", "？")
NEGOTIATION_HINTS = ("没空", "没时间", "改到", "改成", "调整", "换到", "推迟", "提前", "上班", "改一下")
TIME_RE = re.compile(r"(?P<h>[01]?\d|2[0-3])\s*[:：]\s*(?P<m>[0-5]\d)")


def detect_intent(message: str | None, has_events: bool) -> str:
    msg = (message or "").strip()
    if msg:
        verdict = safety_rules()
        lowered = msg.lower()
        for rule in verdict.get("forbidden_intents", []):
            for kw in rule.get("keywords", []):
                if kw.lower() in lowered:
                    return "unsafe_request"
        if any(h in msg for h in NEGOTIATION_HINTS):
            return "negotiate_plan"
        if any(h in msg for h in QUESTION_HINTS):
            return "knowledge_question"
        return "patient_request"
    return "event_response" if has_events else "check_in"


def _apply_preference(due: datetime, preference: str | None) -> datetime:
    """F25：已有患者确认的时间偏好时，把非医疗任务的提醒移动到偏好时段。"""
    if not preference:
        return due
    pref = preference.lower()
    target_hour = None
    if "morning" in pref or "早" in pref:
        target_hour = 8
    elif "evening" in pref or "晚" in pref:
        target_hour = 19
    elif "noon" in pref or "中" in pref:
        target_hour = 12
    else:
        m = TIME_RE.search(preference)
        if m:
            target_hour = int(m.group("h"))
    if target_hour is None:
        return due
    adjusted = due.replace(hour=target_hour, minute=0, second=0, microsecond=0)
    if adjusted <= due:
        adjusted = adjusted + timedelta(days=1)
    return adjusted


def field_missing_in_state(field: str, state: dict[str, Any]) -> bool:
    """判断规划所需字段在患者近期记录中是否确实缺失（依据状态聚合，不靠硬编码）。"""
    agg7 = state.get("aggregates", {}).get("7d", {})
    agg3 = state.get("aggregates", {}).get("3d", {})
    if field == "medication_taken":
        return int(agg7.get("medication_taken", {}).get("count", 0)) == 0
    if field == "steps":
        return int(agg3.get("steps", {}).get("count", 0)) == 0
    if field == "fasting_glucose":
        return int(agg7.get("fasting_glucose", {}).get("count", 0)) == 0
    return field in state.get("missing_fields", [])


def _template_actions(
    conn: sqlite3.Connection,
    *,
    event: dict[str, Any],
    state: dict[str, Any],
    preference: str | None,
    existing_types: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    cfg = task_rules()
    templates = cfg.get("templates", {}).get(event["code"], [])
    actions: list[dict[str, Any]] = []
    for tpl in templates:
        required = list(tpl.get("required_fields", []))
        missing = [f for f in required if field_missing_in_state(f, state)]
        base_priority = int(tpl.get("priority", 50)) + SEVERITY_WEIGHT.get(event["severity"], 0) // 10
        due = now(conn) + timedelta(hours=int(tpl.get("due_hours", 24)))
        due = _apply_preference(due, preference)
        task_type = tpl["task_type"]
        if task_type in existing_types:
            # F22 合并：同一类任务只入库一次，把事件挂到已有任务
            existing_types[task_type]["args"]["event_ids"].append(event["id"])
            existing_types[task_type]["args"]["priority"] = max(
                existing_types[task_type]["args"]["priority"], base_priority
            )
            continue
        action = {
            "tool": "create_task",
            "args": {
                "patient_id": state["patient"]["id"],
                "task_type": task_type,
                "title": tpl["title"],
                "description": tpl.get("description", ""),
                "due_at": iso(due),
                "priority": base_priority,
                "event_id": event["id"],
                "event_ids": [event["id"]],
                "required_fields": required,
                "meta": {
                    "event_code": event["code"],
                    "severity": event["severity"],
                    "knowledge_query": tpl.get("knowledge_query"),
                },
            },
            "requires_evidence": False,
            "reason": f"{event['code']}（{event['severity']}）触发：{tpl['title']}",
        }
        if tpl.get("review_branch") == "human_review":
            action["tool"] = "request_human_review"
            action["args"] = {
                "patient_id": state["patient"]["id"],
                "event_id": event["id"],
                "reason": tpl.get("description", "高风险记录需要人工复核"),
                "severity": event["severity"],
            }
        existing_types[task_type] = action
        actions.append(action)
        if missing:
            # F21：数据不足时不直接下结论，先问清楚
            actions.insert(
                0,
                {
                    "tool": "ask_user",
                    "args": {
                        "patient_id": state["patient"]["id"],
                        "target_field": missing[0],
                        "question": _question_text(missing[0]),
                        "options": ["已按时完成", "记不清", "未完成"],
                        "event_id": event["id"],
                        "resume": {"task_type": task_type, "event_id": event["id"]},
                    },
                    "requires_evidence": False,
                    "reason": f"缺少 {missing[0]}，先询问患者",
                },
            )
    return actions


def _question_text(field: str) -> str:
    from backend.app.questioning.service import default_question_for

    return default_question_for(field)["question"]


def build_event_plan(
    conn: sqlite3.Connection,
    *,
    state: dict[str, Any],
    events: list[dict[str, Any]],
    preference: str | None = None,
    intent: str = "event_response",
) -> dict[str, Any]:
    """F22：多个事件按"安全优先 + 严重度 + 优先级"排序，合并同类任务。"""
    events_sorted = sorted(
        events,
        key=lambda e: (SEVERITY_WEIGHT.get(e["severity"], 0), e["detected_at"]),
        reverse=True,
    )
    existing_types: dict[str, dict[str, Any]] = {}
    actions: list[dict[str, Any]] = []
    summary: list[str] = []
    for event in events_sorted:
        planned = _template_actions(
            conn,
            event=event,
            state=state,
            preference=preference,
            existing_types=existing_types,
        )
        actions.extend(planned)
        summary.append(f"{event['code']}（{event['severity']}）→ {len(planned)} 个动作")
    actions.sort(key=lambda a: -int(a.get("args", {}).get("priority", 50)))
    return {
        "intent": intent,
        "reasoning_summary": summary,
        "actions": actions,
        "events": [e["id"] for e in events_sorted],
        "priority_order": [e["code"] for e in events_sorted],
    }


def build_knowledge_plan(
    *,
    state: dict[str, Any],
    message: str,
    hits: list[dict[str, Any]],
    query: str,
) -> dict[str, Any]:
    actions: list[dict[str, Any]] = [
        {"tool": "search_knowledge", "args": {"query": query}, "requires_evidence": False, "reason": "检索已核对资料"}
    ]
    if hits:
        top = hits[0]
        claim = (
            f"根据《{top['title']}》（{top['publisher']}）{top['anchor']} 段：{top['quote'][:120]}"
        )
        actions.append(
            {
                "tool": "respond",
                "args": {
                    "patient_id": state["patient"]["id"],
                    "text": claim,
                    "citations": [f"{h['doc_id']}{h['anchor']}" for h in hits],
                },
                "requires_evidence": True,
                "reason": "基于知识证据回答",
            }
        )
    else:
        actions.append(
            {
                "tool": "respond",
                "args": {
                    "patient_id": state["patient"]["id"],
                    "text": "（该回答需要知识证据，已阻止无出处结论）",
                    "citations": [],
                },
                "requires_evidence": True,
                "reason": "无证据时应拒绝回答（会被 NO_EVIDENCE 拦截并记录）",
            }
        )
        actions.append(
            {
                "tool": "respond",
                "args": {
                    "patient_id": state["patient"]["id"],
                    "text": "已核对的知识包中没有足够资料回答这个问题，我不会给出没有出处的结论。建议在复诊时向医生确认。",
                    "citations": [],
                    "uncertain": True,
                },
                "requires_evidence": False,
                "reason": "无证据兜底话术（明确不确定，不编造）",
            }
        )
    return {
        "intent": "knowledge_question",
        "reasoning_summary": [f"知识检索：{query}，命中 {len(hits)} 段"],
        "actions": actions,
        "events": [],
        "priority_order": [],
    }


def parse_constraint(message: str) -> dict[str, Any]:
    """F23 解析患者的时间约束，例如"19:00 上班，改成 08:00 记录步数"。"""
    msg = message or ""
    times = TIME_RE.findall(msg)
    target_hour = None
    m = re.search(r"(?:改成|改到|调整到|换到|提前到|推迟到)\s*([01]?\d|2[0-3])\s*[:：]\s*([0-5]\d)", msg)
    if m:
        target_hour = int(m.group(1))
    elif times:
        target_hour = int(times[-1][0])
    task_type = None
    mapping = {
        "步数": "record_activity",
        "走路": "record_activity",
        "活动": "record_activity",
        "血糖": "record_glucose",
        "服药": "confirm_medication",
        "吃药": "confirm_medication",
        "体重": "record_weight",
    }
    for key, value in mapping.items():
        if key in msg:
            task_type = value
            break
    return {
        "target_hour": target_hour,
        "target_minute": int(m.group(2)) if m else 0,
        "task_type": task_type,
        "raw": msg,
        "confidence": 0.9 if target_hour is not None else 0.3,
    }


def build_negotiation_plan(
    conn: sqlite3.Connection,
    *,
    state: dict[str, Any],
    message: str,
    constraint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    constraint = constraint or parse_constraint(message)
    patient_id = state["patient"]["id"]
    task_type = constraint.get("task_type")
    hours = constraint.get("target_hour")
    actions: list[dict[str, Any]] = [
        {"tool": "parse_constraint", "args": {"message": message}, "requires_evidence": False, "reason": "解析时间约束"}
    ]
    if hours is None:
        actions.append(
            {
                "tool": "ask_user",
                "args": {
                    "patient_id": patient_id,
                    "target_field": "preferred_time_window",
                    "question": "您希望把这项任务调整到几点？例如 08:00。",
                    "options": ["07:00", "08:00", "20:00", "保持不变"],
                    "resume": {"intent": "negotiate_plan"},
                },
                "requires_evidence": False,
                "reason": "未识别出可执行的新时间",
            }
        )
        return {
            "intent": "negotiate_plan",
            "reasoning_summary": ["未解析到明确时间，转为询问"],
            "actions": actions,
            "events": [],
            "priority_order": [],
            "constraint": constraint,
        }

    candidates = [t for t in state.get("open_tasks", []) if t.get("status") == "pending"]
    if task_type:
        typed = [t for t in candidates if t["task_type"] == task_type]
        candidates = typed or candidates
    if not candidates:
        new_due = now(conn).replace(
            hour=int(hours), minute=int(constraint.get("target_minute", 0)), second=0, microsecond=0
        )
        if new_due <= now(conn):
            new_due = new_due + timedelta(days=1)
        default_type = task_type or "record_activity"
        titles = {
            "record_activity": "按约定时间记录步数",
            "record_glucose": "按约定时间记录空腹血糖",
            "confirm_medication": "按约定时间确认服药",
            "record_weight": "按约定时间记录体重",
        }
        actions.append(
            {
                "tool": "create_task",
                "args": {
                    "patient_id": patient_id,
                    "task_type": default_type,
                    "title": titles.get(default_type, "按约定时间完成记录"),
                    "description": "按患者确认的时间创建记录任务。",
                    "due_at": iso(new_due),
                    "priority": 50,
                    "required_fields": [] if default_type != "record_glucose" else ["fasting_glucose"],
                },
                "requires_evidence": False,
                "reason": "没有可调整的任务，按患者时间新建",
            }
        )
        actions.append(
            {
                "tool": "save_preference",
                "args": {
                    "patient_id": patient_id,
                    "kind": "preferred_time_window",
                    "value": f"{int(hours):02d}:{int(constraint.get('target_minute', 0)):02d}",
                    "source": "patient_confirmed",
                },
                "requires_evidence": False,
                "reason": "记录患者确认的时间偏好（F25）",
            }
        )
        return {
            "intent": "negotiate_plan",
            "reasoning_summary": [f"没有待调整任务，按患者时间 {new_due.strftime('%H:%M')} 新建记录任务"],
            "actions": actions,
            "events": [],
            "priority_order": [],
            "constraint": constraint,
        }

    task = candidates[0]
    base = parse_ts(task["due_at"]) or now(conn) + timedelta(days=1)
    new_due = base.replace(hour=int(hours), minute=int(constraint.get("target_minute", 0)), second=0, microsecond=0)
    if new_due <= now(conn):
        new_due = new_due + timedelta(days=1)
    actions.append(
        {
            "tool": "update_task",
            "args": {
                "patient_id": patient_id,
                "task_id": task["id"],
                "due_at": iso(new_due),
                "reason": f"患者提出时间冲突：{message}",
            },
            "requires_evidence": False,
            "reason": f"按患者要求把 {task['title']} 调整到 {new_due.strftime('%H:%M')}",
        }
    )
    actions.append(
        {
            "tool": "save_preference",
            "args": {
                "patient_id": patient_id,
                "kind": "preferred_time_window",
                "value": f"{int(hours):02d}:{int(constraint.get('target_minute', 0)):02d}",
                "source": "patient_confirmed",
            },
            "requires_evidence": False,
            "reason": "记录患者确认的时间偏好（F25）",
        }
    )
    return {
        "intent": "negotiate_plan",
        "reasoning_summary": [f"把任务 {task['title']} 从 {task['due_at']} 调整到 {iso(new_due)}"],
        "actions": actions,
        "events": [],
        "priority_order": [],
        "constraint": constraint,
    }


def build_checkin_plan(conn: sqlite3.Connection, *, state: dict[str, Any]) -> dict[str, Any]:
    """无事件、无提问时的常规巡检：只做能在数据库验证的动作。"""
    patient_id = state["patient"]["id"]
    actions: list[dict[str, Any]] = []
    if state.get("missing_fields"):
        field = state["missing_fields"][0]
        actions.append(
            {
                "tool": "ask_user",
                "args": {
                    "patient_id": patient_id,
                    "target_field": field,
                    "question": _question_text(field),
                    "options": ["已按时完成", "记不清", "未完成"],
                    "resume": {"intent": "check_in"},
                },
                "requires_evidence": False,
                "reason": f"档案/记录缺 {field}",
            }
        )
    if not actions:
        actions.append(
            {
                "tool": "respond",
                "args": {
                    "patient_id": patient_id,
                    "text": "目前没有需要处理的事件，已核对最近的记录与任务。",
                    "citations": [],
                },
                "requires_evidence": False,
                "reason": "无待处理事项",
            }
        )
    return {
        "intent": "check_in",
        "reasoning_summary": ["常规巡检：无新事件"],
        "actions": actions,
        "events": [],
        "priority_order": [],
    }
