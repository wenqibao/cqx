"""F08 Agent 自主决策 + F10 工具执行 + F14 轨迹。

单 Agent 架构：感知状态 → 识别事件/意图 → 检索证据 → 生成计划 → 安全与自检 →
执行工具 → 执行后核对 → 记录轨迹 → 更新状态与事件。

mock 模式下计划由 planning.planner 的确定性规则产生；real 模式下由模型通过原生
tool calling 产生。两种模式都会把 llm_mode 写入 agent_runs，禁止混淆。
"""
from __future__ import annotations

import json
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
请始终以 JSON 计划或工具调用的方式行动。"""


def _state_brief(state: dict[str, Any]) -> str:
    patient = state["patient"]
    agg = state["aggregates"]["7d"]
    lines = [
        f"患者: {patient['id']} {patient['name']}，{patient.get('age')}岁，病程{patient.get('duration_years')}年",
        f"近7天空腹血糖: {agg.get('fasting_glucose')}",
        f"近7天步数: {agg.get('steps')}",
        f"缺失字段: {state['missing_fields']}",
        f"未处理事件: {[e['code'] for e in state['open_events']]}",
        f"待办任务: {[t['title'] for t in state['open_tasks']]}",
        f"有效偏好: {[(p['kind'], p['value']) for p in state['preferences']]}",
    ]
    return "\n".join(lines)


def run_agent(
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
    events = [get_event(conn, eid) for eid in (event_ids or []) if get_event(conn, eid)]
    if not events:
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
            plan, evidence, responses, question_created, executed, rejections = _run_real_llm(
                conn, run_id, patient_id, llm, state, events, message
            )
            trace.finish_run(
                conn,
                run_id,
                status=_status_for(executed, rejections, question_created),
                plan=plan,
                output={"responses": responses, "rejections": rejections, "actions": executed},
                intent=plan.get("intent"),
            )
            _finalize_events(conn, run_id, events, question_created, executed)
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
    if not events or question_created:
        return
    handled_ok = any(e.get("ok") for e in executed)
    if handled_ok:
        mark_handled(conn, [e["id"] for e in events], run_id)


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


def _run_real_llm(
    conn: sqlite3.Connection,
    run_id: str,
    patient_id: str,
    llm: llm_module.LLMClient,
    state: dict[str, Any],
    events: list[dict[str, Any]],
    message: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str], bool, list[dict[str, Any]], list[dict[str, Any]]]:
    """real 模式：模型通过原生 tool calling 决策，安全门与自检仍然由本系统强制。"""
    evidence: list[dict[str, Any]] = []
    executed: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    responses: list[str] = []
    question_created = False
    user = "\n".join(
        [
            _state_brief(state),
            f"触发类型: {'事件' if events else '患者请求'}",
            f"待处理事件: {[{'id': e['id'], 'code': e['code'], 'severity': e['severity']} for e in events]}",
            f"患者输入: {message or '（无）'}",
            "请调用工具处理；只处理必要的动作，缺信息就提问。",
        ]
    )
    ctx = tools.ToolContext(conn, patient_id=patient_id, run_id=run_id)
    calls: list[dict[str, Any]] = []
    content = ""
    history: list[dict[str, Any]] = []
    for round_no in range(3):
        trace.add_step(
            conn, run_id, phase="plan", kind="decision", payload={"round": round_no, "mode": "real_llm"}
        )
        response = llm.plan_actions(
            system=SYSTEM_PROMPT,
            user=user,
            tools=llm_module.tool_schemas(),
            extra_messages=history,
        )
        content = response.content or content
        if not response.tool_calls:
            break
        assistant_call = {
            "role": "assistant",
            "content": response.content or "",
            "tool_calls": [
                {
                    "id": c.id or f"call_{i}",
                    "type": "function",
                    "function": {"name": c.name, "arguments": json.dumps(c.arguments, ensure_ascii=False)},
                }
                for i, c in enumerate(response.tool_calls)
            ],
        }
        history.append(assistant_call)
        tool_messages = []
        for idx, call in enumerate(response.tool_calls):
            action = {"tool": call.name, "args": call.arguments, "requires_evidence": False, "reason": "模型决策"}
            single = validators.validate_plan(
                conn, patient_id=patient_id, plan={"actions": [action]}, state=state, evidence=evidence
            )
            if not single["ok"]:
                rejections.extend(single["rejections"])
                for rej in single["rejections"]:
                    trace.add_step(
                        conn,
                        run_id,
                        phase="validate",
                        kind="rejection",
                        tool_name=call.name,
                        payload={"rejection": rej},
                        status="rejected",
                        code=rej["code"],
                    )
                payload = {"ok": False, "error": "rejected by safety gate", "code": single["rejections"][0]["code"]}
                history.append(
                    {"role": "tool", "tool_call_id": call.id or f"call_{idx}", "content": json.dumps(payload, ensure_ascii=False)}
                )
                tool_messages.append({"tool": call.name, "ok": False, "error": payload["error"]})
                continue
            if call.name == "search_knowledge":
                result = tools.execute(ctx, call.name, call.arguments)
                hits = (result.get("hits") or []) if result.get("ok") else []
                if hits:
                    evidence = knowledge_search.record_evidence(
                        conn, patient_id=patient_id, run_id=run_id, hits=hits, query=call.arguments.get("query", "")
                    )
                executed.append({"tool": call.name, "ok": result.get("ok"), "result": result})
                history.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id or f"call_{idx}",
                        "content": json.dumps({"ok": result.get("ok"), "hits": len(hits)}, ensure_ascii=False),
                    }
                )
                tool_messages.append({"tool": call.name, "ok": result.get("ok"), "hits": len(hits)})
                continue
            result = _execute_action(conn, ctx, run_id, action, executed, rejections)
            if result.get("question_id"):
                question_created = True
            if result.get("text"):
                responses.append(result["text"])
            history.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id or f"call_{idx}",
                    "content": json.dumps(
                        {k: v for k, v in result.items() if k in ("ok", "task_id", "created", "review_id", "question_id", "status", "error")},
                        ensure_ascii=False,
                    ),
                }
            )
            tool_messages.append({"tool": call.name, "ok": result.get("ok"), "result": result})
        calls.append({"round": round_no, "messages": tool_messages})
    if content:
        responses.append(content)
    plan = {
        "intent": "real_llm",
        "reasoning_summary": ["由真实模型通过 tool calling 决策"],
        "actions": [{"tool": e["tool"]} for e in executed],
        "tool_rounds": calls,
    }
    return plan, evidence, responses, question_created, executed, rejections
