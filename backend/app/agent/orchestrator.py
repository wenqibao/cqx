"""F08 Agent 自主决策 + F10 工具执行 + F14 轨迹。

单 Agent 架构：感知状态 → 识别事件/意图 → 检索证据 → 生成计划 → 安全与自检 →
执行工具 → 执行后核对 → 记录轨迹 → 更新状态与事件。

mock 模式下计划由 planning.planner 的确定性规则产生；real 模式下由模型通过原生
tool calling 产生。两种模式都会把 llm_mode 写入 agent_runs，禁止混淆。
"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from backend.app.agent import llm as llm_module
from backend.app.agent import tools
from backend.app.audit import trace
from backend.app.config import safety_rules
from backend.app.db.connection import dumps, iso, now
from backend.app.events.detector import get_event, mark_handled
from backend.app.knowledge import search as knowledge_search
from backend.app.memory import preferences
from backend.app.planning import planner
from backend.app.safety import gate, validators
from backend.app.services import state as state_service

SYSTEM_PROMPT = """你是"糖衡智管"健康管理 Agent，只服务于稳定期 2 型糖尿病患者的日常健康管理。
硬性规则：
1. 不做诊断、不开处方、不更改用药或胰岛素剂量；涉及这些请求必须拒绝，并建议就医。
2. 结论必须有可定位的知识证据；证据不足时明确说明"没有足够资料"，不得编造。
3. 缺信息时应主动询问，不得自行推断患者未提供的事实。
4. 只能通过给定工具执行动作，禁止声称执行了实际未执行的工具。
5. 高风险信号（低血糖、显著高血糖、危险症状）一律升级人工复核，不做处置建议。
完成标准（关键）：
- 处理健康事件时必须产生至少一个管理动作：create_task、ask_user 或 request_human_review；
  只调用 search_knowledge / query_history / get_preferences / list_tasks 属于"只看不做"，不算完成。
- search_knowledge 最多调用 2 次；拿到证据后立即行动，不要反复检索同一主题。
- 知识问答检索不到可引用证据时，直接用 respond 说明"没有足够资料"，不要改用 ask_user 追问无关问题。
- 安排复评/随访时必须调用 schedule_review（正式复评记录），不要用 create_task 代替。
- 保存时间偏好时 kind 必须用 preferred_time_window，value 用 24 小时制 HH:MM（如 08:00）；
  不要用 kind=note 记录具体时间。
- respond 的 text 只写自然语言结论；不要把 JSON、plan_id、data_snapshot、actions_taken 等内部字段写进 respond。
- 无法继续时，用 respond 说明原因，或 request_human_review 升级，不要沉默。
请始终以工具调用的方式行动。"""

# 只读工具：不改变业务状态，不能单独构成"处理完成"
READ_ONLY_TOOLS = frozenset({"search_knowledge", "query_history", "get_preferences", "list_tasks"})
ACTION_TOOLS = frozenset({"create_task", "update_task", "complete_task", "ask_user", "request_human_review", "save_preference", "create_notification"})
MAX_SEARCH_CALLS = 2
_TOOL_LABELS = {
    "create_task": "创建任务", "update_task": "更新任务", "complete_task": "完成任务",
    "save_preference": "保存偏好", "create_notification": "创建站内提醒",
    "schedule_review": "安排复评", "request_human_review": "提交人工复核",
    "parse_constraint": "解析时间约束", "search_knowledge": "检索知识",
    "query_history": "查询历史", "get_preferences": "读取偏好", "list_tasks": "查看任务",
}


def _state_brief(state: dict[str, Any]) -> str:
    patient = state["patient"]
    agg = state["aggregates"]["7d"]
    lines = [
        f"当前业务时间（UTC）: {state['generated_at']}；due_at必须在未来30天内，使用带时区ISO8601时间",
        f"患者: {patient['id']} {patient['name']}，{patient.get('age')}岁，病程{patient.get('duration_years')}年",
        f"近7天空腹血糖: {agg.get('fasting_glucose')}",
        f"近7天步数: {agg.get('steps')}",
        f"缺失字段: {state['missing_fields']}",
        f"未处理事件: {[e['code'] for e in state['open_events']]}",
        f"待办任务（实际ID、类型与时间）: {state['open_tasks']}",
        f"待回答问题: {state['pending_questions']}",
        f"最近数据: {state['latest']}",
        f"已确认约束: {patient.get('constraints', [])}",
        f"已保存的回答上下文: {state.get('answer_context')}",
        f"有效偏好: {[(p['kind'], p['value']) for p in state['preferences']]}",
    ]
    return "\n".join(lines)


class EventScopeError(ValueError):
    pass


def _run_agent_body(
    conn: sqlite3.Connection,
    patient_id: str,
    *,
    trigger_type: str,
    trigger_ref: str | None = None,
    message: str | None = None,
    event_ids: list[str] | None = None,
    llm: llm_module.LLMClient | None = None,
) -> dict[str, Any]:
    llm = llm or llm_module.get_llm()
    if trigger_type not in ("event_detected",) and not event_ids:
        from backend.app.events.detector import detect_events

        detect_events(conn, patient_id, trigger=f"{trigger_type}_scan")
    state = state_service.build_state(conn, patient_id)
    if trigger_type == "answer_received" and trigger_ref:
        from backend.app.questioning.service import get_question

        answered = get_question(conn, trigger_ref)
        if answered and answered['patient_id'] == patient_id:
            state['answer_context'] = {k: answered.get(k) for k in ('id', 'question', 'target_field', 'answer', 'answer_text')}
    if event_ids:
        resolved = []
        for eid in event_ids:
            event = get_event(conn, eid)
            if not event:
                raise EventScopeError(f"事件不存在: {eid}")
            if event.get("patient_id") != patient_id:
                raise EventScopeError(f"事件不属于当前患者: {eid}")
            resolved.append(event)
        events = [e for e in resolved if e.get("status") == "open"]
    else:
        events = [dict(e) for e in state["open_events"][:5]]
        events = [e for e in events if e and e.get("status") == "open"]

    run = trace.start_run(
        conn,
        patient_id,
        trigger_type=trigger_type,
        trigger_ref=trigger_ref,
        llm_mode=llm.mode,
        model_name=llm.model_name,
        input_payload={"message": message, "event_ids": [e["id"] for e in events], "trigger_type": trigger_type},
    )
    run_id = run["id"]
    trace.add_step(
        conn,
        run_id,
        phase="perceive",
        kind="decision",
        payload={
            "patient_id": patient_id,
            "open_events": [e["code"] for e in events],
            "missing_fields": state["missing_fields"],
            "llm_mode": llm.mode,
        },
    )

    unsafe = gate.check_text(message or "")
    escalations = gate.escalation_hits(state, conn, patient_id)
    plan: dict[str, Any] = {}
    evidence: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    executed: list[dict[str, Any]] = []
    responses: list[str] = []
    question_created = False

    if not unsafe["allowed"] or escalations:
        plan = _safety_plan(patient_id, message, unsafe, escalations, state)
        trace.add_step(
            conn,
            run_id,
            phase="plan",
            kind="decision",
            payload={"intent": plan["intent"], "reason": plan.get("reasoning_summary")},
        )
        if not unsafe["allowed"]:
            gate.audit(
                conn,
                actor="agent",
                action="block_forbidden_intent",
                decision="reject",
                patient_id=patient_id,
                run_id=run_id,
                code=unsafe["code"],
                detail={"matched": unsafe["matched"], "message": message},
            )
            # 拦截也要进轨迹，便于 F14 解释"为什么这次什么都没做"
            trace.add_step(
                conn,
                run_id,
                phase="validate",
                kind="rejection",
                payload={
                    "code": unsafe["code"],
                    "matched": unsafe["matched"],
                    "message": unsafe["message"],
                    "input": message,
                },
                status="rejected",
                code=unsafe["code"],
            )
        else:
            gate.audit(
                conn,
                actor="agent",
                action="escalate_red_flag",
                decision="escalate",
                patient_id=patient_id,
                run_id=run_id,
                code=escalations[0]["code"],
                detail={"hits": escalations},
            )
    else:
        intent = planner.detect_intent(message, bool(events))
        trace.add_step(conn, run_id, phase="plan", kind="decision", payload={"intent": intent})

        if llm.mode == "real" and intent in ("event_response", "check_in", "patient_request", "knowledge_question", "negotiate_plan"):
            try:
                plan, evidence, responses, question_created, executed, rejections = _run_real_llm(
                    conn, run_id, patient_id, llm, state, events, message, intent
                )
            except llm_module.LLMRequestError as exc:
                trace.add_step(conn, run_id, phase="plan", kind="llm_error", status="failed",
                               payload={"error": str(exc)}, code=validators.TOOL_EXECUTION_FAILED)
                trace.finish_run(conn, run_id, status="failed", error=str(exc), intent=intent)
                state_service.save_snapshot(conn, patient_id)
                raise
            no_evidence_blocked = intent == "knowledge_question" and any(
                r.get("code") == validators.NO_EVIDENCE for r in rejections
            )
            trace.finish_run(
                conn,
                run_id,
                status="failed" if no_evidence_blocked or (rejections and not question_created)
                else _status_for(executed, rejections, question_created),
                plan=plan,
                output={"responses": responses, "rejections": rejections, "actions": executed},
                intent=plan.get("intent"),
            )
            _finalize_events(conn, run_id, events, question_created, executed)
            state_service.save_snapshot(conn, patient_id)
            return _result(conn, run_id, patient_id, plan, evidence, responses, rejections, executed, question_created)

        plan, evidence = _build_mock_plan(conn, patient_id, state, events, message, intent, run_id)
        trace.add_step(
            conn,
            run_id,
            phase="plan",
            kind="decision",
            payload={"intent": plan.get("intent"), "actions": [a["tool"] for a in plan.get("actions", [])]},
        )

    validation = validators.validate_plan(
        conn, patient_id=patient_id, plan=plan, state=state, evidence=evidence
    )
    rejections.extend(validation["rejections"])
    for rej in validation["rejections"]:
        trace.add_step(
            conn,
            run_id,
            phase="validate",
            kind="rejection",
            tool_name=_tool_at(plan, rej.get("index")),
            payload={"rejection": rej},
            status="rejected",
            code=rej["code"],
        )
        gate.audit(
            conn,
            actor="agent",
            action="plan_rejected",
            decision="reject",
            patient_id=patient_id,
            run_id=run_id,
            code=rej["code"],
            detail=rej,
        )
    trace.add_step(
        conn,
        run_id,
        phase="validate",
        kind="validation",
        payload={"ok": validation["ok"], "rejections": len(validation["rejections"])},
        status="ok" if validation["ok"] else "rejected",
    )

    rejected_indexes = {r.get("index") for r in validation["rejections"] if r.get("index") is not None}
    ctx = tools.ToolContext(conn, patient_id=patient_id, run_id=run_id, evidence=evidence)
    for idx, action in enumerate(plan.get("actions", [])):
        if idx in rejected_indexes:
            continue
        result = _execute_action(conn, ctx, run_id, action, executed, rejections)
        if result.get("question_id"):
            question_created = True
        if result.get("text"):
            responses.append(result["text"])

    status = _status_for(executed, rejections, question_created)
    if plan.get("intent") == "unsafe_request":
        status = "blocked"
    _finalize_events(conn, run_id, events, question_created, executed)
    trace.finish_run(
        conn,
        run_id,
        status=status,
        plan=plan,
        output={
            "responses": responses,
            "rejections": rejections,
            "actions": executed,
            "evidence": [e.get("citation") for e in evidence],
        },
        intent=plan.get("intent"),
    )
    state_service.save_snapshot(conn, patient_id)
    return _result(conn, run_id, patient_id, plan, evidence, responses, rejections, executed, question_created)


def _tool_at(plan: dict[str, Any], index: int | None) -> str | None:
    if index is None:
        return None
    actions = plan.get("actions", [])
    if 0 <= index < len(actions):
        return actions[index].get("tool")
    return None


def _status_for(executed: list[dict[str, Any]], rejections: list[dict[str, Any]], waiting: bool) -> str:
    if waiting:
        return "waiting_user"
    if executed and all((not e.get("ok")) for e in executed):
        return "failed"
    return "completed"


def _execute_action(
    conn: sqlite3.Connection,
    ctx: tools.ToolContext,
    run_id: str,
    action: dict[str, Any],
    executed: list[dict[str, Any]],
    rejections: list[dict[str, Any]],
) -> dict[str, Any]:
    tool = action.get("tool", "")
    args = dict(action.get("args") or {})
    trace.add_step(
        conn, run_id, phase="act", kind="tool_call", tool_name=tool, payload={"args": args, "reason": action.get("reason")}
    )
    result = tools.execute(ctx, tool, args)
    check = validators.post_execution_check(conn, tool=tool, args=args, result=result)
    ok = bool(result.get("ok")) and bool(check.get("ok"))
    code = None if ok else (check.get("code") or result.get("code"))
    if not ok:
        rejections.append({"code": code, "message": check.get("message") or result.get("error"), "tool": tool})
    trace.add_step(
        conn,
        run_id,
        phase="observe",
        kind="tool_result",
        tool_name=tool,
        payload={"result": result, "post_check": check},
        status="ok" if ok else "failed",
        code=code,
    )
    entry = {"tool": tool, "args": args, "result": result, "ok": ok, "post_check": check}
    executed.append(entry)
    return result


def _build_mock_plan(
    conn: sqlite3.Connection,
    patient_id: str,
    state: dict[str, Any],
    events: list[dict[str, Any]],
    message: str | None,
    intent: str,
    run_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    evidence: list[dict[str, Any]] = []
    preference = preferences.preferred_time_window(conn, patient_id)
    if intent == "knowledge_question":
        query = message or ""
        hits = knowledge_search.search(conn, query)["hits"]
        if hits:
            evidence = knowledge_search.record_evidence(
                conn, patient_id=patient_id, run_id=run_id, hits=hits, query=query
            )
        plan = planner.build_knowledge_plan(state=state, message=message or "", hits=hits, query=query)
        return plan, evidence
    if intent == "negotiate_plan":
        return planner.build_negotiation_plan(conn, state=state, message=message or ""), evidence
    if intent == "unsafe_request":
        return (
            {
                "intent": "unsafe_request",
                "reasoning_summary": ["命中安全门：禁止的医疗动作"],
                "actions": [
                    {
                        "tool": "respond",
                        "args": {"patient_id": patient_id, "text": gate.check_text(message or "")["message"], "citations": []},
                        "requires_evidence": False,
                        "reason": "安全门拦截",
                    }
                ],
                "events": [],
                "priority_order": [],
            },
            evidence,
        )
    if events:
        plan = planner.build_event_plan(
            conn, state=state, events=events, preference=preference, intent="event_response"
        )
        # 任务说明里需要引用知识依据时，先检索并记录证据
        queries = [
            a["args"].get("meta", {}).get("knowledge_query")
            for a in plan.get("actions", [])
            if a.get("tool") == "create_task"
        ]
        for query in [q for q in queries if q]:
            hits = knowledge_search.search(conn, query, top_k=2)["hits"]
            if hits:
                evidence.extend(
                    knowledge_search.record_evidence(
                        conn, patient_id=patient_id, run_id=run_id, hits=hits, query=query
                    )
                )
        return plan, evidence
    return planner.build_checkin_plan(conn, state=state), evidence


def _safety_plan(
    patient_id: str,
    message: str | None,
    unsafe: dict[str, Any],
    escalations: list[dict[str, Any]],
    state: dict[str, Any],
) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    if not unsafe["allowed"]:
        actions.append(
            {
                "tool": "respond",
                "args": {
                    "patient_id": patient_id,
                    "text": unsafe["message"] or "本系统不提供该操作，请咨询医生。",
                    "citations": [],
                },
                "requires_evidence": False,
                "reason": "安全门拦截禁止的医疗动作",
            }
        )
    for hit in escalations:
        actions.append(
            {
                "tool": "request_human_review",
                "args": {
                    "patient_id": patient_id,
                    "reason": "；".join(h["message"] for h in escalations) or "需要人工专业复核",
                    "severity": max((h.get("severity", "high") for h in escalations), default="high"),
                },
                "requires_evidence": False,
                "reason": "红旗信号：" + "、".join(h["code"] for h in escalations),
            }
        )
        break  # 一次运行只创建一条合并后的人工复核事项
    if not actions:
        actions.append(
            {
                "tool": "respond",
                "args": {"patient_id": patient_id, "text": "已记录。", "citations": []},
                "requires_evidence": False,
                "reason": "无动作",
            }
        )
    return {
        "intent": "unsafe_request" if not unsafe["allowed"] else "escalation",
        "reasoning_summary": ["安全门优先于一切业务动作"],
        "actions": actions,
        "events": [],
        "priority_order": [],
    }


def _finalize_events(
    conn: sqlite3.Connection,
    run_id: str,
    events: list[dict[str, Any]],
    question_created: bool,
    executed: list[dict[str, Any]],
) -> None:
    """EVENT-FINALIZE-01：只关闭由成功动作明确关联的事件，未关联的保持 open。"""
    if not events or question_created:
        return
    business = {"create_task", "update_task", "request_human_review", "schedule_review"}
    referenced: set[str] = set()
    for entry in executed:
        if not entry.get("ok") or entry.get("tool") not in business:
            continue
        for source in (entry.get("args") or {}, entry.get("result") or {}):
            single = source.get("event_id")
            if isinstance(single, str):
                referenced.add(single)
            many = source.get("event_ids")
            if isinstance(many, list):
                referenced.update(item for item in many if isinstance(item, str))
    if not referenced and len(events) == 1 and any(
        entry.get("ok") and entry.get("tool") in business for entry in executed
    ):
        # 单事件场景且确有管理动作：可视为处理；纯读取仍保持 open
        referenced = {events[0]["id"]}
    targets = [event["id"] for event in events if event["id"] in referenced]
    if targets:
        mark_handled(conn, targets, run_id)


def _result(
    conn: sqlite3.Connection,
    run_id: str,
    patient_id: str,
    plan: dict[str, Any],
    evidence: list[dict[str, Any]],
    responses: list[str],
    rejections: list[dict[str, Any]],
    executed: list[dict[str, Any]],
    waiting: bool,
) -> dict[str, Any]:
    run = trace.get_run(conn, run_id) or {}
    return {
        "run_id": run_id,
        "patient_id": patient_id,
        "status": run.get("status"),
        "llm_mode": run.get("llm_mode"),
        "model": run.get("model_name"),
        "intent": plan.get("intent"),
        "reasoning": plan.get("reasoning_summary", []),
        "actions": [{"tool": e["tool"], "ok": e["ok"], "result": e["result"]} for e in executed],
        "responses": responses,
        "evidence": evidence,
        "rejections": rejections,
        "waiting_user": waiting,
        "priority_order": plan.get("priority_order", []),
    }


# 声称已执行的句式：模型措辞多变，固定短语会漏；同一分句含否定词时不算声称。
# 对象名词用命名组 obj 区分：站内提醒/通知属于 create_notification，不是 create_task（A0-FULL-P1-02）。
_CLAIM_PATTERNS = {
    "create_task": (
        r"(?:已|已经|已为你|已帮你|已经帮你|已经为你|给你|帮你)[^，。；！？\n]{0,10}(?:创建|新建|建立|生成|添加|安排|设置|建好|建了|设好)"
        r"[^，。；！？\n]{0,10}(?P<obj>任务|待办|复评|提醒(?!任务)|通知|消息)",
        r"(?P<obj>任务|待办)[^，。；！？\n]{0,4}(?:已|已经)?[^，。；！？\n]{0,4}(?:创建|新建|建立|生成)",
    ),
    "create_notification": (
        r"(?:已|已经|已为你|已帮你|已经帮你|已经为你)[^，。；！？\n]{0,10}(?:发送|推送|创建|发出|生成)"
        r"[^，。；！？\n]{0,10}(?P<obj>提醒(?!任务)|通知|消息)",
    ),
    "update_task": (
        r"(?:已|已经)[^，。；！？\n]{0,10}(?:调整|修改|改期|改到|推迟|提前|更新|挪到)[^，。；！？\n]{0,10}(?:任务|时间|计划)",
        r"(?:已|已经)[^，。；！？\n]{0,10}(?:改到|调整到|改期到|推迟到|提前到)",
        r"(?:任务|计划)[^，。；！？\n]{0,4}(?:已|已经)[^，。；！？\n]{0,2}(?:调整|修改|改期|更新)",
    ),
    "complete_task": (
        r"(?:已|已经)[^，。；！？\n]{0,10}(?:完成|标记完成|关闭)[^，。；！？\n]{0,10}任务",
        r"任务[^，。；！？\n]{0,4}(?:已|已经)[^，。；！？\n]{0,2}(?:完成|关闭)",
    ),
    "save_preference": (
        r"(?:已|已经)[^，。；！？\n]{0,10}(?:保存|记录|更新)[^，。；！？\n]{0,10}偏好",
        r"偏好[^，。；！？\n]{0,4}(?:已|已经)[^，。；！？\n]{0,2}(?:保存|记录|更新)",
    ),
}
_CLAIM_NEGATIONS = ("不能", "无法", "未能", "没有", "尚未", "不会", "不需要", "无需")
_CLAIM_OBJECT_TO_TOOL = {"提醒": "create_notification", "通知": "create_notification", "消息": "create_notification",
                        "复评": "schedule_review"}


def _claimed_state_changes(text: str) -> set[str]:
    """返回文本中声称已执行的工具集合；同一分句内有否定词时不算声称。"""
    claimed: set[str] = set()
    for tool, patterns in _CLAIM_PATTERNS.items():
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                start = max(text.rfind(mark, 0, match.start()) for mark in "，。；！？\n") + 1
                if any(neg in text[start:match.start()] for neg in _CLAIM_NEGATIONS):
                    continue
                obj = (match.groupdict().get("obj") or "")
                claimed.add(_CLAIM_OBJECT_TO_TOOL.get(obj, tool))
                break
    return claimed


def _check_real_reply(text, *, conn, patient_id, intent, evidence, executed, claims_out=None):
    """自由文本与 respond 工具使用相同安全/证据门。

    "声称已执行"的核对不在执行单个工具时做（B16：respond 可能排在同轮 create_task 之前），
    而是把文本放进 claims_out，等整轮/整次运行的 executed 完整后再统一核对。
    """
    action = {"tool": "respond", "args": {"text": text}, "requires_evidence": intent == "knowledge_question"}
    checked = validators.validate_plan(conn, patient_id=patient_id, plan={"actions": [action]}, evidence=evidence)
    if claims_out is not None:
        claims_out.append(text)
    else:
        checked["rejections"].extend(_unsupported_claims(text, executed))
    return checked["rejections"]


def _unsupported_claims(text: str, executed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"code": validators.POSTCHECK_MISMATCH, "message": "回答声称的业务变更没有成功工具支持", "tool": tool}
        for tool in _claimed_state_changes(text)
        if not any(e.get("ok") and e.get("tool") == tool for e in executed)
    ]


def _run_real_llm(
    conn: sqlite3.Connection,
    run_id: str,
    patient_id: str,
    llm: llm_module.LLMClient,
    state: dict[str, Any],
    events: list[dict[str, Any]],
    message: str | None,
    intent: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str], bool, list[dict[str, Any]], list[dict[str, Any]]]:
    """真实模型选工具；统一执行与轨迹，整次运行累计限制，不记录密钥或内部思考。"""
    evidence: list[dict[str, Any]] = []
    executed: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    responses: list[str] = []
    history: list[dict[str, Any]] = []
    accepted_actions: list[dict[str, Any]] = []
    search_calls = 0
    nudges = 0
    claim_texts: list[str] = []
    responded = False
    question_created = False
    rounds = []
    user = "\n".join([
        _state_brief(state), f"触发类型: {'事件' if events else '患者请求'}",
        f"待处理事件: {[{'id': e['id'], 'code': e['code'], 'severity': e['severity']} for e in events]}",
        f"患者输入: {message or '（无）'}",
        "请使用原生工具调用执行必要动作。缺信息时ask_user的target_field使用上述真实字段名。",
        "知识问答先search_knowledge，只引用本次返回的证据；任务时间使用当前业务时间，不编造ID。",
        "单次最多5个新任务、2个问题；不要重复已有待答问题或重复已经成功的动作。处理完请简短说明。",
        "若上方已保存的答复是不确定，保持该事实未知，不重复追问同一问题，可安排后续核实任务。",
    ])
    ctx = tools.ToolContext(conn, patient_id=patient_id, run_id=run_id)

    def reject(items, tool=None):
        rejections.extend(items)
        for item in items:
            trace.add_step(conn, run_id, phase="validate", kind="rejection", tool_name=tool,
                           payload={"rejection": item}, status="rejected", code=item['code'])
            gate.audit(conn, actor="agent", action="plan_rejected", decision="reject", patient_id=patient_id,
                       run_id=run_id, code=item['code'], detail=item)

    for round_no in range(3):
        # 一条请求轨迹对应一次 plan_actions，包含异常尝试；本客户端不做隐藏重试。
        trace.add_step(conn, run_id, phase="plan", kind="llm_request",
                       payload={"round": round_no, "model": llm.model_name})
        response = llm.plan_actions(system=SYSTEM_PROMPT, user=user, tools=llm_module.tool_schemas(), extra_messages=history)
        raw = response.raw or {}
        trace.add_step(conn, run_id, phase="plan", kind="llm_response", payload={
            "round": round_no, "response_id": raw.get('id'), "model": raw.get('model'), "usage": raw.get('usage'),
            "tool_calls": [{"id": c.id, "name": c.name, "arguments": c.arguments} for c in response.tool_calls],
        })
        if not response.tool_calls:
            if response.content:
                errors = _check_real_reply(response.content, conn=conn, patient_id=patient_id, intent=intent,
                                           evidence=evidence, executed=executed, claims_out=claim_texts)
                if errors:
                    reject(errors)
                else:
                    responses.append(response.content)
            break
        history.append({"role": "assistant", "content": response.content or "", "tool_calls": [
            {"id": c.id or f"call_{round_no}_{i}", "type": "function",
             "function": {"name": c.name, "arguments": json.dumps(c.arguments, ensure_ascii=False)}}
            for i, c in enumerate(response.tool_calls)
        ]})
        outcomes = []
        for index, call in enumerate(response.tool_calls):
            tool_call_id = call.id or f"call_{round_no}_{index}"
            # REL-01：正式复评必须用 schedule_review，普通任务不能替代（软拒绝，允许下一轮纠正）
            if call.name == "create_task" and isinstance(call.arguments, dict):
                task_type = str(call.arguments.get("task_type") or "").lower()
                title = str(call.arguments.get("title") or "")
                if task_type in {"follow_up_review", "followup_review", "review"} or "复评" in title:
                    guidance = {"ok": False, "code": "TOOL_CHOICE_INVALID",
                                "error": "正式复评必须调用 schedule_review；create_task 不能替代复评"}
                    trace.add_step(conn, run_id, phase="validate", kind="tool_choice", tool_name=call.name,
                                   payload=guidance, status="skipped", code="TOOL_CHOICE_INVALID")
                    history.append({"role": "tool", "tool_call_id": tool_call_id,
                                    "content": json.dumps(guidance, ensure_ascii=False)})
                    outcomes.append({"tool": call.name, "ok": False, "code": "TOOL_CHOICE_INVALID"})
                    continue
            # A-WB-01：只读检索次数封顶，防止模型反复检索、始终不采取管理动作
            if call.name == "search_knowledge" and search_calls >= MAX_SEARCH_CALLS:
                limited = {
                    "ok": False,
                    "code": "NO_PROGRESS",
                    "error": "检索次数已达上限，请基于已有证据立即执行管理动作（create_task / ask_user / request_human_review）",
                }
                trace.add_step(conn, run_id, phase="observe", kind="tool_result", tool_name=call.name,
                               payload={"skipped": True, "reason": "search_limit", "query": call.arguments.get("query")},
                               status="skipped", code="NO_PROGRESS")
                history.append({"role": "tool", "tool_call_id": tool_call_id,
                                "content": json.dumps(limited, ensure_ascii=False)})
                outcomes.append({"tool": call.name, "ok": False})
                continue
            if call.name == "search_knowledge":
                search_calls += 1
            action = {"tool": call.name, "args": call.arguments, "requires_evidence": call.name == 'respond' and intent == 'knowledge_question', "reason": "模型决策"}
            candidates = accepted_actions + [action]
            checked = validators.validate_plan(conn, patient_id=patient_id, plan={"actions": candidates}, evidence=evidence)
            errors = [e for e in checked['rejections'] if e.get('index') in (None, len(candidates)-1)]
            if call.name == 'respond' and isinstance(call.arguments, dict) and call.arguments.get('text'):
                errors.extend(_check_real_reply(call.arguments['text'], conn=conn, patient_id=patient_id,
                                               intent=intent, evidence=evidence, executed=executed,
                                               claims_out=claim_texts))
            if errors:
                # 方便定位是哪一轮、第几个工具调用触发的拒绝（B 的轨迹对齐问题）
                for item in errors:
                    item.setdefault("tool", call.name)
                    item["round"] = round_no
                    item["call_index"] = index
                    item["call_id"] = tool_call_id
                if errors[0]['code'] == validators.INVALID_DUE:
                    # 可修正提示：既回给模型，也脱敏写入拒绝轨迹，便于技术日志核对
                    errors[0]["server_now"] = iso(now(conn))
                    errors[0]["hint"] = "due_at 必须在当前时间之后、720 小时以内，请按此重新生成"
                reject(errors, call.name)
                result = {"ok": False, "error": errors[0].get('message') or "rejected by safety gate",
                          "code": errors[0]['code']}
                if errors[0]['code'] == validators.INVALID_DUE:
                    result["server_now"] = errors[0]["server_now"]
                    result["hint"] = errors[0]["hint"]
            else:
                accepted_actions.append(action)
                trace.add_step(conn, run_id, phase="validate", kind="validation", tool_name=call.name, payload={"ok": True})
                result = _execute_action(conn, ctx, run_id, action, executed, rejections)
                if call.name == 'search_knowledge' and result.get('ok'):
                    hits = result.get('hits') or []
                    evidence.extend(knowledge_search.record_evidence(conn, patient_id=patient_id, run_id=run_id,
                                                                    hits=hits, query=call.arguments.get('query', '')))
                    ctx.evidence = evidence
                if result.get('question_id') and result.get('ok'):
                    question_created = True
                if result.get('text') and result.get('ok'):
                    responses.append(result['text'])
                    if call.name == 'respond':
                        responded = True
            # 实际工具返回（包括知识片段/出处、实际任务ID）传回模型，不能只给命中数量。
            history.append({"role": "tool", "tool_call_id": tool_call_id,
                            "content": json.dumps(result, ensure_ascii=False)})
            outcomes.append({"tool": call.name, "ok": result.get('ok'), "code": result.get('code')})
        rounds.append({"round": round_no, "tools": outcomes})
        # 知识问答已确认无证据：立即收口，避免模型继续重试被拒动作（B 残余观察项 1）
        if intent == "knowledge_question" and not evidence and any(
            o["tool"] == "search_knowledge" and o["ok"] for o in outcomes
        ):
            trace.add_step(conn, run_id, phase="plan", kind="no_evidence_stop",
                           payload={"round": round_no, "message": "知识检索无证据，提前结束模型轮次"})
            break
        # A-WB-01：整轮只有读取动作时推一把，避免"只看不做"耗尽轮数
        action_ok = any(o["tool"] in ACTION_TOOLS and o["ok"] for o in outcomes)
        only_read = bool(outcomes) and all(o["tool"] in READ_ONLY_TOOLS for o in outcomes)
        if only_read and not action_ok and nudges < 1 and round_no < 2:
            nudges += 1
            trace.add_step(conn, run_id, phase="plan", kind="progress_nudge",
                           payload={"round": round_no, "message": "本轮只有读取动作，未产生管理动作"})
            history.append({
                "role": "system",
                "content": "本轮只有读取动作，没有产生任何管理动作。请立即执行 create_task / ask_user / request_human_review，"
                           "或说明为什么无法继续；不要再次检索同一主题。",
            })
        # A0-FULL-P1-04：respond 成功后不再进入下一轮，避免"工具轮 + 纯文本轮"重复答复
        if responded:
            break
        # 整轮都被拒绝或工具失败时停止收费循环；可修正的参数错误允许模型再试一次
        correctable = {validators.INVALID_DUE, validators.MISSING_REQUIRED_DATA, "TOOL_CHOICE_INVALID"}
        if outcomes and not any(o['ok'] for o in outcomes) and not any(o.get('code') in correctable for o in outcomes):
            break
    if not executed and not responses and not rejections:
        reject([{"code": validators.TOOL_EXECUTION_FAILED, "message": "模型没有返回可执行工具或说明"}])
    # A0-FULL-P1-04：动作成功但模型没给最终答复时，由系统输出确定性收尾（只陈述实际执行的动作）
    if not responses and not question_created and not rejections:
        done = [_TOOL_LABELS.get(e["tool"], e["tool"]) for e in executed
                if e.get("ok") and e["tool"] in ACTION_TOOLS]
        if done:
            responses.append("本轮已完成：" + "、".join(dict.fromkeys(done)) + "。如需调整，请告诉我。")
    # B16：整次运行结束后再核对"声称已执行"，避免 respond 排在同轮 create_task 之前被误判
    for text in claim_texts:
        for item in _unsupported_claims(text, executed):
            reject([item])
    # B17：知识问答没有检索到任何可引用证据时，必须明确判 NO_EVIDENCE，
    # 不能用 ask_user 追问或空回复把问题带过去。
    no_evidence = intent == "knowledge_question" and not evidence
    # 只做了读取、既没给结论也没提问/升级：不能算完成（resume 路径的"查完就完成"）
    # 知识问答无证据属于已确定结论（确定性"资料不足"答复），不再叠加"没有给出结论"的矛盾拒绝
    if (executed and all(e["tool"] in READ_ONLY_TOOLS for e in executed) and not responses
            and not question_created and not no_evidence):
        reject([{"code": validators.POSTCHECK_MISMATCH, "message": "只执行了读取动作，没有给出结论或管理动作"}])
    if no_evidence:
        reject([{"code": validators.NO_EVIDENCE,
                 "message": "知识问答未检索到可引用证据，不能生成结论，也不应改用追问代替"}])
        # 确定性答复：明确告知资料不足，不猜测、不生成健康结论
        if not responses:
            responses.append("现有知识库没有足够资料回答这个问题，我不会猜测；建议咨询医生，或补充资料后再问。")
    # A0-FULL-P1-03：用户明确"只解析、不要修改"时，parse_constraint + respond 即算完成
    parse_only = bool(message) and any(
        cue in message for cue in ("只解析", "仅解析", "只是解析", "不要修改", "不修改", "别改", "不要改")
    ) and any(e.get("ok") and e["tool"] == "parse_constraint" for e in executed)
    if intent in ('event_response', 'negotiate_plan') and not question_created and not parse_only and not any(
        e.get('ok') and e['tool'] in ('create_task', 'update_task', 'request_human_review') for e in executed
    ):
        reject([{"code": validators.POSTCHECK_MISMATCH, "message": "所需业务动作未执行，不能标记完成"}])
    if rejections and not responses:
        responses.append("执行未全部通过核验，请查看拒绝原因；没有足够资料时不生成健康结论。")
    plan = {"intent": intent, "reasoning_summary": ["真实模型通过原生工具调用决策，执行结果已核验"],
            "actions": [{"tool": e['tool']} for e in executed], "tool_rounds": rounds,
            "priority_order": [e['id'] for e in events]}
    return plan, evidence, responses, question_created, executed, rejections


def run_agent(
    conn: sqlite3.Connection,
    patient_id: str,
    *,
    trigger_type: str = "user_request",
    trigger_ref: str | None = None,
    message: str | None = None,
    event_ids: list[str] | None = None,
    llm: llm_module.LLMClient | None = None,
) -> dict[str, Any]:
    """统一异常收口：已创建的 run 绝不能停留在 running。"""
    try:
        return _run_agent_body(conn, patient_id, trigger_type=trigger_type, trigger_ref=trigger_ref,
                               message=message, event_ids=event_ids, llm=llm)
    except Exception as exc:
        row = conn.execute(
            "SELECT id FROM agent_runs WHERE patient_id=? AND status='running' ORDER BY started_at DESC LIMIT 1",
            (patient_id,),
        ).fetchone()
        if row:
            trace.add_step(conn, row["id"], phase="error", kind="exception", status="failed",
                           code=validators.TOOL_EXECUTION_FAILED,
                           payload={"error": f"{type(exc).__name__}: {exc}"})
            trace.finish_run(conn, row["id"], status="failed", error=f"{type(exc).__name__}: {exc}",
                             intent=None)
        raise
