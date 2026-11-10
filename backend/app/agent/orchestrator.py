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
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

from backend.app.agent import llm as llm_module
from backend.app.agent import tools
from backend.app.audit import trace
from backend.app.config import safety_rules
from backend.app.db.connection import dumps, iso, now, parse_ts
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
决策协议（Real 模式必须遵守）：
- 先读患者实际状态：事件证据、趋势、最近记录、已有任务/问题/复评、缺失字段；
- 优先处理高风险事件；同样的事件在不同患者状态下应选择不同行动；
- 已有 pending 同类任务时，必须优先 update_task 或说明现有任务如何覆盖；禁止重复 create_task；
- 按状态选下一步：缺关键信息→ask_user；已有任务覆盖→update_task；高风险→request_human_review；
  需要随访→schedule_review；信息足够且安全→create_task；无法继续→respond。
- 缺少会影响决策的信息时用 ask_user 提一个具体问题，不要猜测；
- 需要正式复评时用 schedule_review；用户只要求安排复评时，只调用 schedule_review，不要额外建任务；
- 沿用已有复评时明确说明沿用，并核对原计划的复评编号和时间；只有本轮成功调用工具后才说新建或改期。
- 高风险或需专业判断时用 request_human_review；
- 每个动作都要能用工具结果与数据库状态核验；无法继续时用 respond 说明原因。
- 意图为知识问答（knowledge_question）时，只允许 search_knowledge 与 respond：
  不得建任务、发通知、提人工复核或反问；回答必须直接针对患者的问题，不要汇报执行动作。
完成标准（关键）：
- 处理健康事件时必须产生至少一个管理动作：create_task、ask_user 或 request_human_review；
  只调用 search_knowledge / query_history / get_preferences / list_tasks 属于"只看不做"，不算完成。
- search_knowledge 最多调用 2 次；拿到证据后立即行动，不要反复检索同一主题。
- 知识问答检索不到可引用证据时，直接用 respond 说明"没有足够资料"，不要改用 ask_user 追问无关问题。
- 安排复评/随访时必须调用 schedule_review（正式复评记录），不要用 create_task 代替。
- 保存时间偏好时 kind 必须用 preferred_time_window，value 用 24 小时制 HH:MM（如 08:00）；
  不要用 kind=note 记录具体时间。
- respond 的 text 只写自然语言结论；不要把 JSON、plan_id、data_snapshot、actions_taken 等内部字段写进 respond。
- 发送与任务/复核相关的站内提醒时，带上 ref_type 与 ref_id（来自工具返回的 task_id/review_id），避免重复提醒。
- 无法继续时，用 respond 说明原因，或 request_human_review 升级，不要沉默。
请始终以工具调用的方式行动。"""

# 只读工具：不改变业务状态，不能单独构成"处理完成"
READ_ONLY_TOOLS = frozenset({"search_knowledge", "query_history", "get_preferences", "list_tasks"})
ACTION_TOOLS = frozenset({"create_task", "update_task", "complete_task", "ask_user", "request_human_review",
                          "schedule_review", "save_preference", "create_notification"})
# 能让一次管理事件"有业务进展"的动作（ask_user 另行以 waiting 处理）
MANAGEMENT_TOOLS = frozenset({"create_task", "update_task", "schedule_review", "request_human_review"})
MAX_SEARCH_CALLS = 2
# 用户只要求"安排复评"时，不应额外创建任务（v0.3.1）
REVIEW_ONLY_CUES = ("安排一次正式复评", "安排正式复评", "只安排复评", "仅安排复评", "只做复评", "只安排一次复评")
NON_REVIEW_CUES = ("任务", "记录", "提醒", "通知", "建档")


def _is_review_only(message: str | None) -> bool:
    if not message or not any(cue in message for cue in REVIEW_ONLY_CUES):
        return False
    return not any(cue in message for cue in NON_REVIEW_CUES)
# 重复任务被拒后，下一轮强制走复用路径
REUSE_TOOLS = frozenset({"update_task", "respond", "list_tasks"})
# 知识问答只允许检索与回答（B/A-REAL-AUTONOMY-02）
KNOWLEDGE_TOOLS = frozenset({"search_knowledge", "respond"})
_TOOL_LABELS = {
    "create_task": "创建任务", "update_task": "更新任务", "complete_task": "完成任务",
    "save_preference": "保存偏好", "create_notification": "创建站内提醒",
    "schedule_review": "安排复评", "request_human_review": "提交人工复核",
    "parse_constraint": "解析时间约束", "search_knowledge": "检索知识",
    "query_history": "查询历史", "get_preferences": "读取偏好", "list_tasks": "查看任务",
}


EVENT_TASK_HINTS = {
    "GLUCOSE_RISING": ("record_glucose", "confirm_medication", "medication_verification", "review_glucose"),
    "GLUCOSE_VARIABILITY": ("record_glucose", "review_glucose"),
    "HYPOGLYCEMIA_RECORD": ("record_glucose", "confirm_medication"),
    "HYPERGLYCEMIA_RECORD": ("record_glucose", "confirm_medication"),
    "LOW_ACTIVITY": ("record_activity", "record_steps"),
    "WEIGHT_GAIN": ("record_weight", "record_activity"),
    "MEDICATION_MISSED": ("confirm_medication", "medication_verification"),
}


def _covering_tasks(state: dict[str, Any], event: dict[str, Any]) -> list[dict[str, Any]]:
    """找出可能覆盖该事件的待办任务，供模型优先复用。"""
    hints = set(EVENT_TASK_HINTS.get(event.get("code"), ()))
    covering = []
    for task in state.get("open_tasks", []):
        if task.get("event_id") == event.get("id") or task.get("task_type") in hints:
            covering.append({"id": task["id"], "task_type": task["task_type"],
                             "title": task["title"], "due_at": task.get("due_at"),
                             "event_id": task.get("event_id")})
    return covering


def _state_brief(state: dict[str, Any]) -> str:
    patient = state["patient"]
    agg = state["aggregates"]["7d"]
    events = state.get("open_events", [])
    lines = [
        f"当前业务时间（UTC）: {state['generated_at']}；due_at 必须是未来 0~720 小时的带时区 ISO8601 时间",
        f"患者: {patient['id']} {patient['name']}，{patient.get('age')}岁，病程{patient.get('duration_years')}年",
        f"管理目标: {patient.get('goals', [])}；已确认约束: {patient.get('constraints', [])}",
        f"档案完整: {state.get('profile_complete')}；缺失字段: {state['missing_fields']}",
        f"近7天血糖: {agg.get('fasting_glucose')}",
        f"近7天步数: {agg.get('steps')}",
        f"近7天服药: {agg.get('medication_taken')}",
        f"血糖趋势: {state.get('trend')}",
        f"最近记录: {state['latest']}",
        "未处理事件（含证据，决定管理动作时必须逐条考虑）:",
    ]
    if not events:
        lines.append("  （无）")
    for event in events:
        covering = _covering_tasks(state, event)
        lines.append(
            f"  - {event['id']} {event['code']} severity={event['severity']} "
            f"detected_at={event['detected_at']} message={event.get('message')} "
            f"evidence={event.get('evidence_summary')} records={event.get('record_ids')} "
            f"已有可覆盖任务={covering if covering else '无'}"
        )
    lines.extend([
        f"已有待办任务（先判断是否已覆盖，不要重复创建）: {state['open_tasks']}",
        f"待回答问题（不要重复询问同一字段）: {state['pending_questions']}",
        f"最近已答复/过期问题: {state.get('recent_answers', [])}",
        f"已安排的复评（不要重复安排）: {state.get('open_reviews', [])}",
        f"已保存的回答上下文: {state.get('answer_context')}",
        f"有效偏好: {[(p['kind'], p['value']) for p in state['preferences']]}",
        f"单次运行动作额度: {validators.max_actions_per_run()} 个；优先必要管理动作，避免重复读取",
    ])
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
                    conn, run_id, patient_id, llm, state, events, message, intent, trigger_type
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
            # C06：可修正的拒绝若随后被同一工具成功纠正，不再把整次运行判失败
            resolved_indexes = _resolved_rejection_indexes(rejections, executed)
            hard_rejections = [r for i, r in enumerate(rejections) if i not in resolved_indexes]
            warnings = [{**r, "resolved": True} for i, r in enumerate(rejections) if i in resolved_indexes]
            warnings.extend(plan.get("warnings") or [])
            trace.finish_run(
                conn,
                run_id,
                status="failed" if no_evidence_blocked or (hard_rejections and not question_created)
                else _status_for(executed, hard_rejections, question_created),
                plan=plan,
                output={"responses": responses, "rejections": rejections, "warnings": warnings,
                        "actions": executed},
                intent=plan.get("intent"),
            )
            _finalize_events(conn, run_id, events, question_created, executed)
            state_service.save_snapshot(conn, patient_id)
            return _result(conn, run_id, patient_id, plan, evidence, responses, rejections, executed, question_created,
                           warnings=warnings)

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
    ctx = tools.ToolContext(conn, patient_id=patient_id, run_id=run_id, evidence=evidence,
                        event_ids=[e["id"] for e in events])
    for idx, action in enumerate(plan.get("actions", [])):
        if idx in rejected_indexes:
            continue
        result = _execute_action(conn, ctx, run_id, action, executed, rejections)
        if result.get("question_id"):
            question_created = True
        if result.get("text"):
            responses.append(result["text"])

    status = _status_for(executed, rejections, question_created)
    # 契约：未解决的 NO_EVIDENCE 属于失败；兜底回复与拒绝码保留
    if any(r.get("code") == validators.NO_EVIDENCE for r in rejections):
        status = "failed"
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
    step_no = trace.add_step(
        conn,
        run_id,
        phase="observe",
        kind="tool_result",
        tool_name=tool,
        payload={"result": result, "post_check": check},
        status="ok" if ok else "failed",
        code=code,
    )
    entry = {"tool": tool, "args": args, "result": result, "ok": ok, "post_check": check, "step_no": step_no}
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
        # 先按实体相关性过滤，再持久化证据（C-REG-KQ-01 残留）
        hits = knowledge_search.filter_relevant_hits(query, hits)
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


CORRECTABLE_CODES = {
    validators.INVALID_DUE,
    validators.MISSING_REQUIRED_DATA,
    validators.TOOL_EXECUTION_FAILED,
    "TOOL_CHOICE_INVALID",
}


def _resolved_rejection_indexes(rejections: list[dict[str, Any]], executed: list[dict[str, Any]]) -> set[int]:
    """可修正拒绝若随后被同一工具成功纠正，返回其下标。安全类拒绝永不豁免。"""
    resolved: set[int] = set()
    for index, rejection in enumerate(rejections):
        if rejection.get("code") not in CORRECTABLE_CODES:
            continue
        tool = rejection.get("tool")
        if tool and any(entry.get("ok") and entry.get("tool") == tool for entry in executed):
            resolved.add(index)
    return resolved


MISSING_FIELD_LABELS = {
    "medication_taken": "最近的服药执行情况",
    "fasting_glucose": "最近的空腹血糖记录",
    "steps": "最近的活动步数",
    "weight": "最近的体重记录",
}


def _required_fields_for_events(events: list[dict[str, Any]]) -> list[str]:
    from backend.app.config import task_rules

    templates = task_rules().get("templates", {}) or {}
    required: list[str] = []
    for event in events:
        for item in templates.get(event.get("code"), []) or []:
            for field in item.get("required_fields") or []:
                if field not in required:
                    required.append(field)
    return required


def _ensure_missing_info_question(
    conn: sqlite3.Connection,
    *,
    patient_id: str,
    state: dict[str, Any],
    events: list[dict[str, Any]],
    run_id: str,
    executed: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """REAL-A04：缺必要信息且模型没有提问时，兜底创建真实问题（不额外调用模型）。"""
    if not events or any(e.get("tool") == "ask_user" and e.get("ok") for e in executed):
        return None
    waiting = conn.execute(
        "SELECT id FROM questions WHERE patient_id=? AND status='waiting' LIMIT 1", (patient_id,)
    ).fetchone()
    if waiting:
        return None
    required = _required_fields_for_events(events)
    missing = [field for field in required if field in (state.get("missing_fields") or [])]
    if not missing:
        return None
    # A-033-02：事件模板要求的字段缺失时都应先核实，不依赖患者目标里是否出现依从性关键词
    if not missing:
        return None
    field = missing[0]
    args = {
        "patient_id": patient_id,
        "question": f"为了继续处理当前情况，请补充{MISSING_FIELD_LABELS.get(field, field)}。",
        "target_field": field,
        "resume": {"intent": "event_response", "event_ids": [e["id"] for e in events]},
    }
    result = tools.execute(
        tools.ToolContext(conn, patient_id=patient_id, run_id=run_id,
                          event_ids=[e["id"] for e in events]),
        "ask_user", args,
    )
    if not result.get("ok"):
        return None
    trace.add_step(conn, run_id, phase="act", kind="system_question", tool_name="ask_user",
                   payload={"target_field": field, "reason": "模型未提问，系统兜底创建"},
                   status="ok")
    executed.append({"tool": "ask_user", "ok": True, "args": args, "result": result})
    return result


def _verify_task_coverage(
    conn: sqlite3.Connection,
    patient_id: str,
    context: dict[str, Any],
    responses: list[str],
) -> dict[str, Any] | None:
    """核验模型"已有任务覆盖"的说法：任务必须真实、属于当前患者、仍有效且类型匹配。"""
    task_id = context.get("existing_task_id")
    task_type = context.get("task_type")
    if not task_id:
        return None
    row = conn.execute("SELECT * FROM tasks WHERE id=? AND patient_id=?", (task_id, patient_id)).fetchone()
    if not row or row["status"] not in ("pending", "missed"):
        return None
    if task_type and row["task_type"] != task_type:
        return None
    text = " ".join(responses)
    if task_id not in text and row["title"] not in text and "已有任务" not in text and "现有任务" not in text:
        return None
    return {
        "task_id": task_id,
        "task_type": row["task_type"],
        "status": row["status"],
        "title": row["title"],
        "event_id": row["event_id"],
        "response_mentions_task": task_id in text or row["title"] in text,
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
        # 以数据库实际关联为准：update_task 返回不含 event_id，需按 task_id 反查
        if entry.get("tool") == "update_task":
            task_id = (entry.get("result") or {}).get("task_id") or (entry.get("args") or {}).get("task_id")
            if task_id:
                row = conn.execute("SELECT event_id FROM tasks WHERE id=?", (task_id,)).fetchone()
                if row and row["event_id"]:
                    referenced.add(row["event_id"])
        if entry.get("tool") in ("schedule_review", "request_human_review"):
            review_id = (entry.get("result") or {}).get("review_id")
            if review_id:
                row = conn.execute("SELECT event_id FROM reviews WHERE id=?", (review_id,)).fetchone()
                if row and row["event_id"]:
                    referenced.add(row["event_id"])
    # B1-002：不再用"只剩一个事件"推断关联；只有明确关联才关闭
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
    warnings: list[dict[str, Any]] | None = None,
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
        "warnings": warnings or [],
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


def _check_real_reply(text, *, conn, patient_id, intent, evidence, executed, claims_out=None, events=None, run_id=None):
    """自由文本与 respond 工具使用相同安全/证据门。

    "声称已执行"的核对不在执行单个工具时做（B16：respond 可能排在同轮 create_task 之前），
    而是把文本放进 claims_out，等整轮/整次运行的 executed 完整后再统一核对。
    """
    action = {"tool": "respond", "args": {"text": text}, "requires_evidence": intent == "knowledge_question"}
    checked = validators.validate_plan(conn, patient_id=patient_id, plan={"actions": [action]}, evidence=evidence)
    if claims_out is not None:
        claims_out.append(text)
    else:
        checked["rejections"].extend(_unsupported_claims(
            text, executed, conn=conn, patient_id=patient_id,
            event_ids=[e["id"] for e in (events or [])], run_id=run_id,
        ))
    return checked["rejections"]


_EXISTING_REVIEW = re.compile(
    r"(?:沿用|保留|继续执行)(?:既有|现有|原有|原先|原计划|之前|此前)?(?:已)?"
    r"(?:安排(?:好)?的?)?(?:的)?(?:到期|后续)?复评"
    r"|(?:之前|此前|原先|原计划)(?:已)?安排(?:好)?的?(?:到期|后续)?复评"
    r"|(?:已有|既有|现有|原有)的?(?:到期|计划)?复评"
    r"|复评(?:\s*[（(][^）)]{0,60}[）)])?\s*(?:仍)?(?:按|沿用)原计划"
)
_COLLECTIVE_REVIEW = re.compile(r"([两二三四五六七八九2-9])项(?:任务|待办)?(?:都|均)已安排(?:了)?(?:到期)?复评")
_REVIEW_CHANGE = re.compile(
    r"(?:已|已经)(?:为您|又)?(?:新建|新增|追加|重新安排|改期|改到|推迟|提前)[^，,]{0,10}复评"
    r"|(?:本轮|本次|这次)(?:的)?(?:[两二三四五六七八九2-9]项(?:任务|待办)?(?:都|均))?"
    r"(?:又)?(?:已经|已)(?:为您)?安排[^，,]{0,8}复评"
    r"|(?:刚刚|已|已经)安排[^，,]{0,4}(?:新(?:的)?|另一条|另外一条)复评"
    r"|复评(?:安排)?(?:已|已经)(?:调整|改期|改到|推迟|提前|新建|新增|重新安排)"
)
_REVIEW_SCHEDULED = re.compile(r"复评(?:安排|时间)?(?:已|已经)(?:安排|设定|排定|定于)")
_REVIEW_DATE = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?)?")
_REVIEW_CLOCK = re.compile(r"(?<!\d)(\d{1,2})(?::(\d{2})|点(?:(\d{1,2})分)?)")
_REVIEW_OFFSET = re.compile(r"(\d+|[一二两三四五六七八九十])(天|小时)(?:后|之后|以后)")
_REVIEW_IDS = re.compile(r"(?<![A-Za-z0-9_-])(?:REV|EVT|TSK)-[A-Za-z0-9_-]+")
_REVIEW_PATIENT = re.compile(r"患者(?:编号|ID)?[：:\s]*([A-Za-z0-9][A-Za-z0-9_-]*)"
                             r"|(?<![A-Za-z0-9_-])(P\d+)(?![A-Za-z0-9_-])")
_REVIEW_TIME_CHANGE = re.compile(r"^(?:时间)?(?:已|已经)(?:改期到|改到|改为|推迟到|提前到)")
_REVIEW_QUALIFIER = re.compile(
    r"^(?:复评)?(?:时间(?:为|是|在)|定于|日期(?:为|是)|(?:REV|EVT|TSK)-)"
    r"|^(?:今天|明天|大?后天)(?:上午|下午|晚上)?(?:进行|触发|执行|开始|复评|$)"
)
_DIGITS = {digit: value for value, digit in enumerate("零一二三四五六七八九十")} | {"两": 2}


def _split_segments(sentence: str) -> list[str]:
    """按逗号/并接词分段，但不切分括号内的 ID 与日期。"""
    parts: list[str] = []
    buffer: list[str] = []
    depth = 0
    index = 0
    while index < len(sentence):
        char = sentence[index]
        if char in "（(":
            depth += 1
        elif char in "）)":
            depth = max(0, depth - 1)
        if depth == 0:
            if char in "，,":
                parts.append("".join(buffer).strip())
                buffer = []
                index += 1
                continue
            for connector in ("并且", "同时", "并", "又"):
                if sentence.startswith(connector, index) and re.match(
                    r"(?:本轮|本次|刚刚|已)", sentence[index + len(connector):]
                ):
                    parts.append("".join(buffer).strip())
                    buffer = []
                    index += len(connector)
                    break
            else:
                buffer.append(char)
                index += 1
            continue
        buffer.append(char)
        index += 1
    parts.append("".join(buffer).strip())
    return [part for part in parts if part]


def _review_claims(text: str) -> Iterator[tuple[str, bool, int]]:
    for sentence in re.split(r"[。；;！!？?\n]", text):
        segments = _split_segments(sentence)
        for index, part in enumerate(segments):
            if "复评" not in part:
                continue
            collective = _COLLECTIVE_REVIEW.search(part)
            existing = collective or _EXISTING_REVIEW.search(part)
            change = _REVIEW_CHANGE.search(part)
            if not (existing or change or _REVIEW_SCHEDULED.search(part)
                    or "schedule_review" in _claimed_state_changes(part)):
                continue
            end = index + 1
            while end < len(segments) and (_REVIEW_QUALIFIER.match(segments[end])
                                            or _REVIEW_TIME_CHANGE.match(segments[end])):
                change = change or _REVIEW_TIME_CHANGE.match(segments[end])
                end += 1
            count = collective[1] if collective else "1"
            yield "，".join(segments[index:end]), bool(existing and not change), int(count) if count.isdigit() else _DIGITS[count]


def _review_time_matches(statement: str, scheduled: datetime, current: datetime) -> bool:
    """按服务业务时钟核对日期、时分与显式相对时间。"""
    for value in _REVIEW_DATE.findall(statement):
        try:
            stated = parse_ts(value)
        except ValueError:
            return False
        if len(value) == 10:
            if scheduled.date() != stated.date():
                return False
        elif scheduled.replace(second=0, microsecond=0) != stated.replace(
                tzinfo=stated.tzinfo or scheduled.tzinfo, second=0, microsecond=0):
            return False
    remaining = _REVIEW_DATE.sub("", statement)
    for word, days in (("大后天", 3), ("后天", 2), ("明天", 1), ("明日", 1), ("次日", 1), ("今天", 0), ("今日", 0)):
        if word in remaining and scheduled.date() != (current + timedelta(days=days)).date():
            return False
        remaining = remaining.replace(word, "")
    for value, unit in _REVIEW_OFFSET.findall(remaining):
        amount = int(value) if value.isdigit() else _DIGITS[value]
        if unit == "天" and scheduled.date() != (current + timedelta(days=amount)).date():
            return False
        if unit == "小时" and abs((scheduled - current).total_seconds() - amount * 3600) >= 60:
            return False
    for hour, minute, chinese_minute in _REVIEW_CLOCK.findall(remaining):
        hour_value = int(hour)
        if any(word in remaining for word in ("下午", "晚上")) and hour_value < 12:
            hour_value += 12
        if scheduled.hour != hour_value or scheduled.minute != int(minute or chinese_minute or 0):
            return False
    if any(word in remaining for word in ("上午", "早上", "早晨")) and scheduled.hour >= 12:
        return False
    if any(word in remaining for word in ("下午", "晚上")) and scheduled.hour < 12:
        return False
    return not re.search(r"(?:下周|下星期|本周|这周|周[一二三四五六日天]|\d+月\d+日|今早|今晚|明早|明晚)", remaining)


def _verified_review_ids(conn: sqlite3.Connection, patient_id: str, event_ids: list[str],
                         statement: str, count: int, tool_ids: set[str] | None) -> list[str]:
    if any((labelled or shorthand) != patient_id for labelled, shorthand in _REVIEW_PATIENT.findall(statement)):
        return []
    current = now(conn)
    rows = conn.execute(
        "SELECT id, event_id, task_id, scheduled_for FROM reviews "
        "WHERE patient_id=? AND status='scheduled' AND scheduled_for > ?",
        (patient_id, iso(current)),
    ).fetchall()
    ids = set(_REVIEW_IDS.findall(statement))
    id_filters = {
        column: {value for value in ids if value.startswith(prefix)}
        for prefix, column in (("REV-", "id"), ("EVT-", "event_id"), ("TSK-", "task_id"))
    }
    matches = []
    for row in rows:
        if event_ids and row["event_id"] not in event_ids:
            continue
        if tool_ids is not None and row["id"] not in tool_ids:
            continue
        if any(values and row[column] not in values for column, values in id_filters.items()):
            continue
        if _review_time_matches(statement, parse_ts(row["scheduled_for"]), current):
            matches.append(row)
    if ids - {row[key] for row in matches for key in ("id", "event_id", "task_id")}:
        return []
    if count > 1:
        by_task = {row["task_id"]: row["id"] for row in matches if row["task_id"]}
        return list(by_task.values()) if len(by_task) == count else []
    return [matches[0]["id"]] if len(matches) == 1 else []


def _unsupported_claims(text: str, executed: list[dict[str, Any]], *,
                        conn: sqlite3.Connection | None = None, patient_id: str | None = None,
                        event_ids: list[str] | None = None, run_id: str | None = None) -> list[dict[str, Any]]:
    claimed = _claimed_state_changes(text)
    succeeded = {e["tool"] for e in executed if e.get("ok")}
    review_mismatch = False
    if conn is not None and patient_id is not None:
        review_claims = list(_review_claims(text))
        tool_ids = {e["result"]["review_id"] for e in executed
                    if e.get("ok") and e.get("tool") == "schedule_review" and e.get("result", {}).get("review_id")}
        references: set[str] = set()
        for statement, existing, count in review_claims:
            review_ids = _verified_review_ids(conn, patient_id, event_ids or [], statement, count,
                                              None if existing else tool_ids)
            if not review_ids:
                review_mismatch = True
                break
            if existing:
                references.update(review_ids)
        else:
            if review_claims:
                claimed.discard("schedule_review")
                if run_id:
                    for review_id in sorted(references):
                        trace.add_step(conn, run_id, phase="observe", kind="review_reference", tool_name="respond",
                                       payload={"review_id": review_id, "reason": "引用既有复评"}, status="ok")
    unsupported = claimed - succeeded
    if review_mismatch:
        unsupported.add("schedule_review")
    return [
        {"code": validators.POSTCHECK_MISMATCH,
         "message": "复评声明与实际安排不一致" if tool == "schedule_review" and review_mismatch
         else "回答声称的业务变更没有成功工具支持", "tool": tool}
        for tool in sorted(unsupported)
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
    trigger_type: str = "",
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
    force_reuse_task_id: str | None = None
    duplicate_context: dict[str, Any] | None = None
    extra_warnings: list[dict[str, Any]] = []
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
    ctx = tools.ToolContext(conn, patient_id=patient_id, run_id=run_id,
                            event_ids=[e["id"] for e in events])

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
        if accepted_actions:
            remaining = max(0, validators.max_actions_per_run() - len(accepted_actions))
            history.append({"role": "system",
                            "content": f"已执行 {len(accepted_actions)} 个动作，剩余动作额度 {remaining}；"
                                       "优先安排必要的管理动作，避免重复读取；额度用尽时总结未完成事项。"})
        if force_reuse_task_id:
            tool_list = llm_module.tool_schemas(only=REUSE_TOOLS)
        elif intent == "knowledge_question":
            tool_list = llm_module.tool_schemas(only=KNOWLEDGE_TOOLS)
        else:
            tool_list = llm_module.tool_schemas()
        response = llm.plan_actions(system=SYSTEM_PROMPT, user=user, tools=tool_list, extra_messages=history)
        raw = response.raw or {}
        trace.add_step(conn, run_id, phase="plan", kind="llm_response", payload={
            "round": round_no, "response_id": raw.get('id'), "model": raw.get('model'), "usage": raw.get('usage'),
            "tool_calls": [{"id": c.id, "name": c.name, "arguments": c.arguments} for c in response.tool_calls],
        })
        if response.tool_calls:
            # 可审计决策摘要：只用同一响应里的简短理由与工具名，不记录隐藏思维链
            trace.add_step(conn, run_id, phase="plan", kind="decision_rationale", payload={
                "round": round_no,
                "rationale": (response.content or "")[:200],
                "tools": [c.name for c in response.tool_calls],
                "linked_event_ids": [e["id"] for e in events],
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
            # 只要求复评且复评已成功：不再额外建任务（v0.3.1）
            if call.name == "create_task" and _is_review_only(message) and any(
                e.get("ok") and e.get("tool") == "schedule_review" for e in executed
            ):
                guidance = {"ok": False, "code": "TOOL_NOT_ALLOWED",
                            "error": "用户只要求安排复评，复评已创建；无需额外建任务"}
                trace.add_step(conn, run_id, phase="validate", kind="tool_choice", tool_name=call.name,
                               payload=guidance, status="skipped", code="TOOL_NOT_ALLOWED")
                history.append({"role": "tool", "tool_call_id": tool_call_id,
                                "content": json.dumps(guidance, ensure_ascii=False)})
                outcomes.append({"tool": call.name, "ok": False, "code": "TOOL_NOT_ALLOWED"})
                continue
            # 判重前先归一任务类型，别名与规范类型必须命中同一条检查（B-032-02）
            if call.name == "create_task" and isinstance(call.arguments, dict):
                from backend.app.tasks.types import normalize_task_type

                raw_task_type = call.arguments.get("task_type")
                normalized_type = normalize_task_type(raw_task_type)
                if normalized_type:
                    call.arguments["task_type"] = normalized_type
                    call.arguments["_raw_task_type"] = raw_task_type
            # 已有同类待办时禁止重复建任务（A-REAL-AUTONOMY-03）
            if call.name == "create_task" and isinstance(call.arguments, dict):
                # 只按任务类型判重：同事件下不同类型任务可能对应不同管理目标（R09 口径 A）
                existing_task = conn.execute(
                    "SELECT id, title, due_at FROM tasks WHERE patient_id=? AND task_type=? "
                    "AND status IN ('pending','missed') ORDER BY created_at LIMIT 1",
                    (patient_id, str(call.arguments.get("task_type") or "")),
                ).fetchone()
                if existing_task:
                    guidance = {
                        "ok": False,
                        "code": "DUPLICATE_TASK",
                        "error": f"已有同类待办任务 {existing_task['id']}（{existing_task['title']}）；"
                                 "请用 update_task 调整它，或说明现有任务如何覆盖，不要重复创建",
                        "existing_task_id": existing_task["id"],
                    }
                    trace.add_step(conn, run_id, phase="validate", kind="duplicate_task", tool_name=call.name,
                                   payload=guidance, status="skipped", code="DUPLICATE_TASK")
                    history.append({"role": "tool", "tool_call_id": tool_call_id,
                                    "content": json.dumps(guidance, ensure_ascii=False)})
                    outcomes.append({"tool": call.name, "ok": False, "code": "DUPLICATE_TASK"})
                    force_reuse_task_id = existing_task["id"]
                    duplicate_context = {
                        "task_type": str(call.arguments.get("task_type") or ""),
                        "event_id": call.arguments.get("event_id"),
                        "existing_task_id": existing_task["id"],
                    }
                    extra_warnings.append({"code": "DUPLICATE_TASK", "tool": "create_task",
                                           "resolved": False, "existing_task_id": existing_task["id"]})
                    history.append({
                        "role": "system",
                        "content": f"上一轮重复创建被拒绝。下一轮只允许 update_task({existing_task['id']}) "
                                   "调整该任务，或用 respond 说明现有任务如何覆盖；不得再 create_task。",
                    })
                    continue
            # 知识问答只允许检索+回答：其他动作软拒绝并提示直接回答
            if intent == "knowledge_question" and call.name not in KNOWLEDGE_TOOLS:
                guidance = {"ok": False, "code": "TOOL_NOT_ALLOWED",
                            "error": "知识问答只允许 search_knowledge 与 respond；请直接回答患者问题"}
                trace.add_step(conn, run_id, phase="validate", kind="tool_choice", tool_name=call.name,
                               payload=guidance, status="skipped", code="TOOL_NOT_ALLOWED")
                history.append({"role": "tool", "tool_call_id": tool_call_id,
                                "content": json.dumps(guidance, ensure_ascii=False)})
                outcomes.append({"tool": call.name, "ok": False, "code": "TOOL_NOT_ALLOWED"})
                continue
            # REL-01：正式复评必须用 schedule_review，普通任务不能替代（软拒绝，允许下一轮纠正）
            if call.name == "create_task" and isinstance(call.arguments, dict):
                task_type = str(call.arguments.get("task_type") or "").lower()
                title = str(call.arguments.get("title") or "")
                if task_type in {"follow_up_review", "followup_review", "review"}:
                    guidance = {"ok": False, "code": "TOOL_CHOICE_INVALID",
                                "error": "task_type 不能是复评类型；如先建关联任务，请用普通 task_type，再用 schedule_review"}
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
                                               claims_out=claim_texts, events=events, run_id=run_id))
            if errors:
                # 方便定位是哪一轮、第几个工具调用触发的拒绝（B 的轨迹对齐问题）
                for item in errors:
                    item.setdefault("tool", call.name)
                    item["round"] = round_no
                    item["call_index"] = index
                    item["call_id"] = tool_call_id
                    if item.get("code") == validators.TOO_MANY_ACTIONS:
                        item["detail"] = {"executed": len(accepted_actions),
                                          "cap": validators.max_actions_per_run(),
                                          "omitted_tool": call.name}
                        history.append({"role": "system",
                                        "content": "动作额度已满：不要继续新增动作，请总结已完成结果、"
                                                   "未完成事项，并给出人工下一步建议。"})
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
                if result.get("ok") and call.name == "update_task":
                    force_reuse_task_id = None
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
                "content": "本轮只有读取动作，没有产生任何管理动作。请立即执行 create_task / update_task / "
                           "schedule_review / ask_user / request_human_review，或说明为什么无法继续；不要再次检索同一主题。",
            })
        # A0-FULL-P1-04：respond 成功后不再进入下一轮，避免"工具轮 + 纯文本轮"重复答复
        if responded:
            break
        # 整轮都被拒绝或工具失败时停止收费循环；可修正的参数错误允许模型再试一次
        correctable = {validators.INVALID_DUE, validators.MISSING_REQUIRED_DATA, validators.TOOL_EXECUTION_FAILED,
                   "TOOL_CHOICE_INVALID", "TOOL_NOT_ALLOWED", validators.DUPLICATE_TASK,
                   validators.INVALID_TASK_TYPE}
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
    for text in dict.fromkeys(claim_texts):
        errors = _unsupported_claims(text, executed, conn=conn, patient_id=patient_id,
                                     event_ids=[e["id"] for e in events], run_id=run_id)
        review_error = next((item for item in errors if item["tool"] == "schedule_review"), None)
        if review_error:
            responses = [reply for reply in responses if reply != text]
            # respond 的最终核验发生在本轮工具都结束后，保留原文并标记结果未通过。
            check = {"ok": False, "code": review_error["code"], "message": review_error["message"]}
            for entry in executed:
                if entry["tool"] == "respond" and entry["ok"] and entry["result"].get("text") == text:
                    entry.update(ok=False, post_check=check)
                    conn.execute(
                        "UPDATE agent_steps SET status='failed', code=?, payload=? WHERE run_id=? AND step_no=? "
                        "AND run_id IN (SELECT id FROM agent_runs WHERE patient_id=? AND status='running')",
                        (check["code"], dumps({"result": entry["result"], "post_check": check}),
                         run_id, entry["step_no"], patient_id),
                    )
        for item in errors:
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
    # REAL-A04：缺必要信息且模型没问 → 系统兜底创建真实问题，run 进入 waiting_user
    question_result = None if trigger_type == "answer_received" else _ensure_missing_info_question(
        conn, patient_id=patient_id, state=state, events=events,
        run_id=run_id, executed=executed,
    )
    if question_result:
        question_created = True
    business_done = any(e.get("ok") and e["tool"] in MANAGEMENT_TOOLS for e in executed)
    coverage = None
    if not business_done and duplicate_context:
        coverage = _verify_task_coverage(conn, patient_id, duplicate_context, responses)
        if coverage:
            trace.add_step(conn, run_id, phase="observe", kind="task_coverage",
                           payload=coverage, status="ok")
            if coverage.get("event_id") and coverage["event_id"] in {e["id"] for e in events}:
                mark_handled(conn, [coverage["event_id"]], run_id)
                coverage["event_closed"] = True
    # 重复任务告警只有在真实 update_task 或覆盖核验通过后才算已解决
    resolved_tasks = {e["result"].get("task_id") for e in executed
                      if e.get("ok") and e["tool"] == "update_task" and isinstance(e.get("result"), dict)}
    if coverage:
        resolved_tasks.add(coverage.get("task_id"))
    for warning in extra_warnings:
        if warning.get("existing_task_id") in resolved_tasks:
            warning["resolved"] = True
    if intent in ("event_response", "negotiate_plan") and not question_created and not parse_only \
            and not business_done and not coverage:
        reject([{"code": validators.POSTCHECK_MISMATCH, "message": "所需业务动作未执行，不能标记完成"}])
    if rejections and not responses:
        responses.append("执行未全部通过核验，请查看拒绝原因；没有足够资料时不生成健康结论。")
    plan = {"intent": intent, "reasoning_summary": ["真实模型通过原生工具调用决策，执行结果已核验"],
            "actions": [{"tool": e['tool']} for e in executed], "tool_rounds": rounds,
            "warnings": extra_warnings,
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
