"""F10 真实工具调用：每个工具都直接读写数据库，并有可验证的返回结构。

工具白名单由 config/safety_rules.yaml 控制；白名单外的工具一律拒绝。
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any

from backend.app.db.connection import iso, loads, now
from backend.app.events.detector import get_event
from backend.app.knowledge import search as knowledge_search
from backend.app.memory import preferences
from backend.app.planning import planner
from backend.app.questioning import service as questioning
from backend.app.reviews import service as reviews
from backend.app.services import notifications, state as state_service
from backend.app.services.records import list_records
from backend.app.tasks import service as tasks
from backend.app.util import new_id

TOOL_SPECS: dict[str, dict[str, Any]] = {
    "search_knowledge": {
        "description": "在有限且来源明确的健康管理知识包中检索，返回可定位段落",
        "parameters": {"query": "string"},
    },
    "ask_user": {
        "description": "向患者提出一个具体问题，并进入等待答复状态",
        "parameters": {"patient_id": "string", "question": "string", "target_field": "string?", "options": "array?"},
    },
    "create_task": {
        "description": "创建健康管理任务（不是医疗处置）。task_type 必须使用 Schema 枚举中的规范类型；"
                       "说明只写记录、提醒、核实、转交，不写具体用药调整建议；"
                       "正式复评/随访请用 schedule_review，不要用任务替代",
        "parameters": {
            "patient_id": "string",
            "task_type": "string",
            "title": "string",
            "description": "string?",
            "due_at": "iso8601?",
            "priority": "int?",
            "event_id": "string?",
            "required_fields": "array?",
        },
    },
    "update_task": {
        "description": "修改任务时间或非医疗内容，保留版本历史",
        "parameters": {"task_id": "string", "due_at": "iso8601", "reason": "string?"},
    },
    "complete_task": {
        "description": "把任务标记为已完成",
        "parameters": {"task_id": "string"},
    },
    "query_history": {
        "description": "查询患者历史记录",
        "parameters": {"patient_id": "string", "kind": "string?", "days": "int?"},
    },
    "schedule_review": {
        "description": "安排一次到期自动复评",
        "parameters": {"patient_id": "string", "task_id": "string?", "event_id": "string?",
                       "delay_hours": "int?", "reason": "string?"},
    },
    "create_notification": {
        "description": "创建站内提醒",
        "parameters": {"patient_id": "string", "title": "string", "body": "string?", "kind": "string?", "ref_type": "string?", "ref_id": "string?"},
    },
    "request_human_review": {
        "description": "创建人工专业复核事项（不给出医疗结论）",
        "parameters": {"patient_id": "string", "event_id": "string?", "reason": "string", "severity": "string?"},
    },
    "save_preference": {
        "description": "保存患者明确确认的偏好",
        "parameters": {"patient_id": "string", "kind": "string", "value": "string", "source": "string"},
    },
    "get_preferences": {
        "description": "读取当前生效的偏好",
        "parameters": {"patient_id": "string"},
    },
    "list_tasks": {
        "description": "列出患者任务",
        "parameters": {"patient_id": "string", "status": "string?"},
    },
    "parse_constraint": {
        "description": "解析患者提出的时间约束",
        "parameters": {"message": "string"},
    },
    "respond": {
        "description": "向患者输出一段说明（可附带引用）",
        "parameters": {"text": "string", "citations": "array?"},
    },
}


class ToolContext:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        patient_id: str,
        run_id: str,
        evidence: list[dict[str, Any]] | None = None,
        event_ids: list[str] | None = None,
    ) -> None:
        self.conn = conn
        self.patient_id = patient_id
        self.run_id = run_id
        self.evidence = evidence or []
        self.event_ids = event_ids or []
        self.responses: list[str] = []


def _ok(**kw: Any) -> dict[str, Any]:
    return {"ok": True, **kw}


def _fail(code: str, message: str, **kw: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, "code": code, **kw}


def execute(ctx: ToolContext, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    handler = HANDLERS.get(tool)
    if handler is None:
        return _fail("UNKNOWN_TOOL", f"未知工具: {tool}")
    try:
        return handler(ctx, args)
    except Exception as exc:  # 工具失败必须显式返回，不能静默当成成功
        return _fail("TOOL_EXECUTION_FAILED", f"{type(exc).__name__}: {exc}")


def _filter_relevant_hits(query: str, hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return knowledge_search.filter_relevant_hits(query, hits)


def _search_knowledge(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    result = knowledge_search.search(ctx.conn, args.get("query", ""))
    hits = _filter_relevant_hits(args.get("query", ""), result["hits"])
    ctx.evidence = hits
    note = result["note"]
    if hits != result["hits"]:
        note = "检索到的通用片段不包含查询中的实体，已按证据不足处理"
    return _ok(
        query=result["query"],
        hits=hits,
        found=bool(hits),
        note=note,
    )


def _ask_user(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    field = args.get("target_field")
    patient_id = args.get("patient_id") or ctx.patient_id
    if field:
        recent = ctx.conn.execute(
            "SELECT id, answer, answer_text FROM questions WHERE patient_id=? AND target_field=? "
            "AND status='answered' ORDER BY answered_at DESC LIMIT 1", (patient_id, field)
        ).fetchone()
        if recent:
            payload = loads(recent["answer"], {}) or {}
            if payload.get("uncertain") is False:
                return _ok(question_id=recent["id"], created=False, reused=True,
                           status="answered", answer=payload.get("value"),
                           question=f"已复用此前回答：{recent['answer_text'] or ''}")
    question, created = questioning.create_question(
        ctx.conn,
        args.get("patient_id") or ctx.patient_id,
        question=args.get("question", ""),
        kind=args.get("kind", "missing_field"),
        target_field=args.get("target_field"),
        options=args.get("options"),
        run_id=ctx.run_id,
        event_id=args.get("event_id"),
        resume_payload=args.get("resume"),
    )
    if created:
        notifications.create_notification(
            ctx.conn,
            args.get("patient_id") or ctx.patient_id,
            kind="question_created",
            title="Agent 需要您补充信息",
            body=question["question"],
            ref_type="question",
            ref_id=question["id"],
        )
    return _ok(question_id=question["id"], created=created, status=question["status"], question=question["question"])


def _create_task(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    from backend.app.tasks.types import normalize_task_type, task_type_candidates

    raw_type = args.get("task_type")
    task_type = normalize_task_type(raw_type)
    if task_type is None:
        return _fail("INVALID_TASK_TYPE",
                     f"不支持的任务类型: {raw_type}；可用类型: {task_type_candidates()}")
    task, created = tasks.create_task(
        ctx.conn,
        args.get("patient_id") or ctx.patient_id,
        task_type=task_type,
        title=args["title"],
        description=args.get("description", ""),
        due_at=args.get("due_at"),
        priority=int(args.get("priority", 50)),
        event_id=args.get("event_id"),
        run_id=ctx.run_id,
        required_fields=args.get("required_fields") or [],
        meta=args.get("meta") or {},
    )
    if created:
        notifications.create_notification(
            ctx.conn,
            args.get("patient_id") or ctx.patient_id,
            kind="task_created",
            title=task["title"],
            body=task.get("description") or "",
            ref_type="task",
            ref_id=task["id"],
        )
    return _ok(task_id=task["id"], created=created, version=task["version"], status=task["status"], title=task["title"])


DATE_TZ = __import__("zoneinfo").ZoneInfo("Asia/Shanghai")


def _request_due_conflict(conn, run_id: str, due_at: str) -> str | None:
    """患者请求文本中的明确日期必须与 due_at 的北京时间日期一致。"""
    import json as _json
    import re as _re
    from datetime import date, timedelta

    from backend.app.db.connection import parse_ts

    if not run_id or not due_at:
        return None
    row = conn.execute("SELECT input FROM agent_runs WHERE id=?", (run_id,)).fetchone()
    try:
        message = (_json.loads(row["input"]) if row and row["input"] else {}).get("message") or ""
    except Exception:
        return None
    if not message:
        return None
    try:
        due_local = parse_ts(due_at).astimezone(DATE_TZ)
    except Exception:
        return None
    base = now(conn).astimezone(DATE_TZ)
    explicit = _re.findall(r"(\d{4})-(\d{2})-(\d{2})", message)
    if explicit:
        year, month, day = (int(part) for part in explicit[-1])
        if due_local.date() != date(year, month, day):
            return f"请求日期 {year:04d}-{month:02d}-{day:02d} 与 due_at 北京时间 {due_local.date()} 不一致"
    month_day = _re.findall(r"(\d{1,2})月(\d{1,2})日", message)
    if month_day:
        month, day = (int(part) for part in month_day[-1])
        if (due_local.month, due_local.day) != (month, day):
            return f"请求日期 {month}月{day}日 与 due_at 北京时间 {due_local.month}月{due_local.day}日 不一致"
    for word, days in (("大后天", 3), ("后天", 2), ("明天", 1), ("今天", 0)):
        if word in message:
            expected = (base + timedelta(days=days)).date()
            if due_local.date() != expected:
                return f"请求“{word}”对应 {expected}，与 due_at 北京时间 {due_local.date()} 不一致"
            break
    return None


FULL_DATETIME = r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?)"
DATE_ONLY = r"(UTC|北京时间|BJT)?\s*(\d{4})-(\d{2})-(\d{2})"

VAGUE_TIME_CUES = ("再说", "晚一点", "晚点", "之后", "回头", "改天", "有空", "看情况")


def _run_message(conn, run_id: str) -> str:
    import json as _json

    if not run_id:
        return ""
    row = conn.execute("SELECT input FROM agent_runs WHERE id=?", (run_id,)).fetchone()
    try:
        return (_json.loads(row["input"]) if row and row["input"] else {}).get("message") or ""
    except Exception:
        return ""


def _vague_time_request(message: str) -> bool:
    """含糊时间表达：没有明确日期和时刻，不得直接改期。"""
    import re as _re

    if not message:
        return False
    if any(cue in message for cue in VAGUE_TIME_CUES):
        return True
    if "周末" in message and not _re.search(r"(周六|周日|星期六|星期日|礼拜六|礼拜日)", message):
        return True
    return False


def _message_has_time(message: str, hour: int, minute: int) -> bool:
    import re as _re

    for period, raw_hour, raw_minute in _re.findall(
            r"(上午|下午|晚上|早上|凌晨|中午)?\s*(\d{1,2})\s*[:：点]\s*(\d{1,2})?", message):
        value = int(raw_hour)
        if period in ("下午", "晚上") and value < 12:
            value += 12
        if period == "凌晨" and value == 12:
            value = 0
        if value == hour and int(raw_minute or 0) == minute:
            return True
    return f"{hour:02d}:{minute:02d}" in message



def _date_conflict(text: str, due_at: str, base, clock_text: str | None = None) -> str | None:
    """按标注时区核对文本中的日期与 due_at；完整时间按瞬时比较。"""
    import re as _re
    from datetime import date, timedelta, timezone

    from backend.app.db.connection import parse_ts

    try:
        due_instant = parse_ts(due_at)
    except Exception:
        return None
    due_local = due_instant.astimezone(DATE_TZ)
    for value in _re.findall(FULL_DATETIME, text):
        try:
            stated = parse_ts(value)
        except Exception:
            continue
        if stated.tzinfo is None:
            stated = stated.replace(tzinfo=DATE_TZ)
        if abs((stated - due_instant).total_seconds()) >= 60:
            return f"文本时间 {value} 与 due_at 不一致"
    rest = _re.sub(FULL_DATETIME, "", text)
    for label, year, month, day in _re.findall(DATE_ONLY, rest):
        target = date(int(year), int(month), int(day))
        if label.upper() == "UTC":
            actual = due_instant.astimezone(timezone.utc).date()
        else:
            actual = due_local.date()
        if actual != target:
            zone = "UTC" if label.upper() == "UTC" else "北京时间"
            return f"文本日期 {target}（{zone}）与 due_at 对应日期 {actual} 不一致"
    clock_source = clock_text if clock_text is not None else rest
    strict_clock = bool(_re.search(r"北京时间|上午|下午|晚上|早上|凌晨|中午|点", clock_source))
    for period, hour, minute in (_re.findall(
            r"(上午|下午|晚上|早上|凌晨|中午)?\s*(\d{1,2})\s*[:：点]\s*(\d{1,2})?", clock_source)
            if strict_clock else []):
        value = int(hour)
        if period in ("下午", "晚上") and value < 12:
            value += 12
        if period == "凌晨" and value == 12:
            value = 0
        if value != due_local.hour or int(minute or 0) != due_local.minute:
            return f"文本时刻 {hour}:{minute or '00'} 与 due_at 北京时间 {due_local.hour:02d}:{due_local.minute:02d} 不一致"
    for month, day in _re.findall(r"(\d{1,2})月(\d{1,2})日", rest):
        target = (int(month), int(day))
        if (due_local.month, due_local.day) != target:
            return f"文本日期 {month}月{day}日 与 due_at 北京时间 {due_local.month}月{due_local.day}日 不一致"
    if not _re.search(r"\d{4}-\d{2}-\d{2}", rest):
        for word, days in (("大后天", 3), ("后天", 2), ("明天", 1), ("今天", 0)):
            if word in rest:
                expected = (base + timedelta(days=days)).date()
                if due_local.date() != expected:
                    return f"文本“{word}”对应 {expected}，与 due_at 北京时间 {due_local.date()} 不一致"
                break
    return None


def _reason_due_conflict(conn, reason: str, due_at: str) -> str | None:
    if not reason or not due_at:
        return None
    return _date_conflict(reason, due_at, now(conn).astimezone(DATE_TZ))


def _request_due_conflict(conn, run_id: str, due_at: str) -> str | None:
    """患者请求文本中的明确日期必须与 due_at 一致。"""
    import json as _json

    if not run_id or not due_at:
        return None
    row = conn.execute("SELECT input FROM agent_runs WHERE id=?", (run_id,)).fetchone()
    try:
        message = (_json.loads(row["input"]) if row and row["input"] else {}).get("message") or ""
    except Exception:
        return None
    if not message:
        return None
    import re as _re

    tail = _re.split(r"改成|改到|改为|调整到|调整成|换成|改在", message)[-1]
    return _date_conflict(message, due_at, now(conn).astimezone(DATE_TZ), clock_text=tail)


def _update_task(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    message = _run_message(ctx.conn, ctx.run_id)
    if _vague_time_request(message):
        return _fail("MISSING_REQUIRED_DATA", "患者仅给出含糊时间，请先询问具体日期和时刻后再改期")
    conflict = _reason_due_conflict(ctx.conn, args.get("reason") or "", args.get("due_at") or "")
    if not conflict:
        conflict = _request_due_conflict(ctx.conn, ctx.run_id, args.get("due_at") or "")
    if conflict:
        return _fail("MISSING_REQUIRED_DATA", conflict)
    task = tasks.reschedule_task(
        ctx.conn,
        args["task_id"],
        due_at=args["due_at"],
        reason=args.get("reason") or "患者申请调整时间",
        changed_by=args.get("changed_by", "patient"),
        run_id=ctx.run_id,
        title=args.get("title"),
        description=args.get("description"),
    )
    notifications.create_notification(
        ctx.conn,
        task["patient_id"],
        kind="task_updated",
        title=f"任务时间已调整：{task['title']}",
        body=f"新时间：{task['due_at']}",
        ref_type="task",
        ref_id=task["id"],
    )
    return _ok(task_id=task["id"], version=task["version"], due_at=task["due_at"], status=task["status"])


def _complete_task(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    task = tasks.complete_task(
        ctx.conn, args["task_id"], changed_by=args.get("changed_by", "patient"), run_id=ctx.run_id
    )
    result: dict[str, Any] = {
        "task_id": task["id"], "status": task["status"], "version": task["version"],
        "changed": bool(task.get("changed", True)),
    }
    if result["changed"]:
        # 与 POST /tasks/{id}/complete 同一副作用：走 outbox，可失败补偿
        from backend.app.automation import outbox

        outbox_id = outbox.enqueue(ctx.conn, "after_task_completed", ctx.patient_id,
                                   {"task_id": task["id"], "changed_by": args.get("changed_by", "patient"),
                                    "run_agent": False})
        try:
            outbox.process(ctx.conn, outbox_id)
        except Exception as exc:
            result["partial_success"] = True
            result["outbox_id"] = outbox_id
            result["automation_error"] = f"{type(exc).__name__}: {exc}"
    return _ok(**result)


def _query_history(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    patient_id = args.get("patient_id") or ctx.patient_id
    days = int(args.get("days", 7))
    from datetime import timedelta

    since = iso(now(ctx.conn) - timedelta(days=days))
    records = list_records(ctx.conn, patient_id, kind=args.get("kind"), since=since, limit=200)
    return _ok(count=len(records), records=records[:50])


def _schedule_review(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    # 未显式给 task/event 时，优先关联本次运行正在处理的那个事件
    task_id = args.get("task_id")
    event_id = args.get("event_id")
    if not task_id and not event_id and len(ctx.event_ids) == 1:
        event_id = ctx.event_ids[0]
    review = reviews.schedule_review(
        ctx.conn,
        args.get("patient_id") or ctx.patient_id,
        task_id=task_id,
        event_id=event_id,
        run_id=ctx.run_id,
        delay_hours=args.get("delay_hours"),
        reason=args.get("reason", "按计划安排复评"),
    )
    return _ok(review_id=review["id"], scheduled_for=review["scheduled_for"], branch=review["branch"])


def _create_notification(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    ntf = notifications.create_notification(
        ctx.conn,
        args.get("patient_id") or ctx.patient_id,
        kind=args.get("kind", "info"),
        title=args.get("title", ""),
        body=args.get("body", ""),
        ref_type=args.get("ref_type"),
        ref_id=args.get("ref_id"),
    )
    return _ok(notification_id=ntf["id"])


def _request_human_review(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    # 幂等：同一患者同一事件/理由只有一条待处理的人工复核，避免重复升级
    existing = ctx.conn.execute(
        "SELECT * FROM reviews WHERE patient_id=? AND branch='HUMAN_REVIEW' AND status='pending_human' "
        "AND COALESCE(event_id,'')=COALESCE(?, '') AND reason=?",
        (args.get("patient_id") or ctx.patient_id, args.get("event_id"), args.get("reason", "需要人工专业复核")),
    ).fetchone()
    if existing:
        return _ok(review_id=existing["id"], branch="HUMAN_REVIEW", status="pending_human", created=False)
    review = reviews.schedule_review(
        ctx.conn,
        args.get("patient_id") or ctx.patient_id,
        task_id=args.get("task_id"),
        event_id=args.get("event_id"),
        run_id=ctx.run_id,
        delay_hours=0,
        branch="HUMAN_REVIEW",
        reason=args.get("reason", "需要人工专业复核"),
    )
    ctx.conn.execute(
        "UPDATE reviews SET status='pending_human', branch='HUMAN_REVIEW', detail=? WHERE id=?",
        (
            '{"escalated":true,"severity":"%s"}' % args.get("severity", "high"),
            review["id"],
        ),
    )
    notifications.create_notification(
        ctx.conn,
        args.get("patient_id") or ctx.patient_id,
        kind="review_due",
        title="已创建人工复核事项",
        body=args.get("reason", "需要人工专业复核"),
        ref_type="review",
        ref_id=review["id"],
    )
    return _ok(review_id=review["id"], branch="HUMAN_REVIEW", status="pending_human")


def _save_preference(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    source = args.get("source", "patient_confirmed")
    value = str(args.get("value", ""))
    if source == "patient_input":
        import re as _re

        message = _run_message(ctx.conn, ctx.run_id)
        clock = _re.search(r"(\d{1,2})[:：](\d{2})", value)
        if clock and message and not _message_has_time(message, int(clock.group(1)), int(clock.group(2))):
            return _fail("MISSING_REQUIRED_DATA", "患者原话未给出该时间，不能记为患者偏好")
    pref = preferences.set_preference(
        ctx.conn,
        args.get("patient_id") or ctx.patient_id,
        kind=args.get("kind", "note"),
        value=str(args.get("value", "")),
        source=args.get("source", "patient_confirmed"),
        run_id=ctx.run_id,
    )
    return _ok(preference_id=pref["id"], kind=pref["kind"], value=pref["value"])


def _get_preferences(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    prefs = preferences.list_preferences(ctx.conn, args.get("patient_id") or ctx.patient_id)
    return _ok(count=len(prefs), preferences=prefs)


def _list_tasks(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    items = tasks.list_tasks(
        ctx.conn, args.get("patient_id") or ctx.patient_id, status=args.get("status")
    )
    return _ok(count=len(items), tasks=items)


def _parse_constraint(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    return _ok(**planner.parse_constraint(args.get("message", "")))


def _respond(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    text = args.get("text", "")
    ctx.responses.append(text)
    return _ok(text=text, citations=args.get("citations", []), uncertain=bool(args.get("uncertain")))


HANDLERS = {
    "search_knowledge": _search_knowledge,
    "ask_user": _ask_user,
    "create_task": _create_task,
    "update_task": _update_task,
    "complete_task": _complete_task,
    "query_history": _query_history,
    "schedule_review": _schedule_review,
    "create_notification": _create_notification,
    "request_human_review": _request_human_review,
    "save_preference": _save_preference,
    "get_preferences": _get_preferences,
    "list_tasks": _list_tasks,
    "parse_constraint": _parse_constraint,
    "respond": _respond,
}
