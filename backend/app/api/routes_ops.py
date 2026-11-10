"""偏好、调度、时钟与演示运维接口（F16/F25/F07 + 演示重置）。"""
from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from backend.app.api.deps import get_conn
from backend.app.automation import scheduler, triggers
from backend.app.db.connection import advance_clock, clock_offset, iso, now, reset_clock
from backend.app.memory import preferences
from backend.app.schemas.models import ClockRequest, PreferenceCreate, TickRequest
from backend.app.safety import gate, validators
from backend.app.services import patients as patient_service

router = APIRouter()


@router.get("/patients/{patient_id}/preferences", tags=["preferences"], summary="F25 有效偏好")
def list_preferences(
    patient_id: str, include_history: bool = False, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    from backend.app.services import patients as patient_service

    patient_service.get_patient(conn, patient_id)
    items = preferences.list_preferences(conn, patient_id, include_history=include_history)
    return {"patient_id": patient_id, "count": len(items), "items": items}


@router.post("/patients/{patient_id}/preferences", tags=["preferences"], summary="F25 保存偏好（覆盖旧值）")
def create_preference(
    patient_id: str, payload: PreferenceCreate, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    from backend.app.automation import outbox
    from backend.app.services import patients as patient_service

    patient_service.get_patient(conn, patient_id)
    try:
        pref = preferences.set_preference(
            conn, patient_id, kind=payload.kind, value=payload.value, source=payload.source
        )
    except preferences.PreferenceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    outbox_id = outbox.enqueue(conn, "after_preference", patient_id, {})
    try:
        applied = outbox.process(conn, outbox_id)
    except Exception as exc:
        return {"preference": pref, "applied_to_tasks": [], "partial_success": True,
                "outbox_id": outbox_id, "error": f"{type(exc).__name__}: {exc}"}
    return {"preference": pref, "applied_to_tasks": applied["updated"]}


@router.delete("/patients/{patient_id}/preferences/{kind}", tags=["preferences"], summary="F25 清除偏好")
def clear_preference(patient_id: str, kind: str, conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    return preferences.clear_preference(conn, patient_id, kind)


@router.post("/automation/tick", tags=["automation"], summary="F07 推进时钟并执行到期作业")
def automation_tick(payload: TickRequest, conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    if payload.advance_seconds:
        advance_clock(conn, payload.advance_seconds)
    result = scheduler.tick(conn, limit=payload.limit)
    result["clock_offset_seconds"] = clock_offset(conn)
    result["now"] = iso(now(conn))
    return result


@router.get("/automation/jobs", tags=["automation"], summary="F07 调度作业列表")
def list_jobs(
    status: str | None = None, limit: int = 50, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    sql = "SELECT * FROM automation_jobs"
    args: list[Any] = []
    if status:
        sql += " WHERE status=?"
        args.append(status)
    sql += " ORDER BY run_at LIMIT ?"
    args.append(limit)
    return {"items": [dict(r) for r in conn.execute(sql, args).fetchall()]}


@router.post("/automation/clock", tags=["automation"], summary="F07 演示时钟（测试可复现）")
def set_clock(payload: ClockRequest, conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    if payload.reset:
        reset_clock(conn)
    offset = advance_clock(conn, payload.advance_seconds) if payload.advance_seconds else clock_offset(conn)
    return {"clock_offset_seconds": offset, "now": iso(now(conn))}


@router.get("/system/audit", tags=["system"], summary="F13/F14 安全与审计日志")
def audit_log(limit: int = 100, conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    rows = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    blocked = conn.execute("SELECT COUNT(*) AS c FROM audit_log WHERE decision='reject'").fetchone()["c"]
    checked = conn.execute("SELECT COUNT(*) AS c FROM agent_steps WHERE kind='tool_result'").fetchone()["c"]
    return {
        "items": [dict(r) for r in rows],
        # 实际执行：成功工具调用中出现越权工具/动作文本的次数（不是拒绝条数）
        "forbidden_executed": gate.forbidden_action_count(conn),
        # 被拦截次数：随拦截增加，不得当作"已执行"
        "blocked_total": int(blocked),
        # 计数覆盖的成功工具结果条数，便于交叉核查不是固定返回 0
        "checked_tool_results": int(checked),
        "rejection_codes": validators.ALL_CODES,
    }


@router.get("/system/vendor-budget", tags=["system"], summary="厂商请求预算状态（只读）")
def vendor_budget_status() -> dict[str, Any]:
    from backend.app.agent import vendor_budget

    try:
        return {"ok": True, **vendor_budget.snapshot()}
    except vendor_budget.VendorBudgetError as exc:
        return {"ok": False, "enabled": vendor_budget.ledger_path() is not None, "error": str(exc)}


@router.get("/system/mode", tags=["system"], summary="当前运行模式（mock / real）")
def system_mode() -> dict[str, Any]:
    from backend.app.agent.llm import get_llm
    from backend.app.config import settings

    try:
        llm = get_llm()
        return {"llm_mode": llm.mode, "model": llm.model_name, "ok": True}
    except Exception as exc:
        return {"llm_mode": settings().llm_mode, "ok": False, "error": str(exc)}


@router.post("/admin/reset", tags=["admin"], summary="演示重置（仅本地演示使用）")
def reset_demo(seed: bool = True, conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    tables = [
        "agent_steps",
        "agent_runs",
        "evidence_items",
        "task_versions",
        "reviews",
        "questions",
        "tasks",
        "events",
        "notifications",
        "automation_jobs",
        "preferences",
        "state_snapshots",
        "health_records",
        "idempotency_keys",
        "audit_log",
        "patients",
    ]
    for table in tables:
        conn.execute(f"DELETE FROM {table}")
    reset_clock(conn)
    summary: dict[str, Any] = {"cleared": tables}
    if seed:
        from scripts.reset_demo import seed as seed_demo

        summary["seed"] = seed_demo(conn)
    return summary
