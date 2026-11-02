"""Agent 运行、轨迹、任务、提问、复评接口（F08-F14、F21、F23）。"""
from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.app.agent import orchestrator
from backend.app.api.deps import get_conn
from backend.app.audit import trace
from backend.app.automation import triggers
from backend.app.questioning import service as questioning
from backend.app.reviews import service as reviews
from backend.app.schemas.models import (
    AgentRunRequest,
    AnswerRequest,
    ReviewResolveRequest,
    TaskCompleteRequest,
    TaskRescheduleRequest,
)
from backend.app.services import patients as patient_service
from backend.app.tasks import service as tasks

router = APIRouter()


@router.post("/patients/{patient_id}/agent/runs", tags=["agent"], summary="F08 运行 Agent（患者请求/事件）")
def run_agent(
    patient_id: str, payload: AgentRunRequest, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    try:
        patient_service.get_patient(conn, patient_id)
    except patient_service.PatientNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        return orchestrator.run_agent(
            conn,
            patient_id,
            trigger_type=payload.trigger_type,
            trigger_ref=None,
            message=payload.message,
            event_ids=payload.event_ids,
        )
    except Exception as exc:  # 模型/工具异常必须显式返回，不能假装成功
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc


@router.get("/patients/{patient_id}/runs", tags=["agent"], summary="F14 运行列表")
def list_runs(patient_id: str, conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    items = trace.list_runs(conn, patient_id)
    return {"patient_id": patient_id, "count": len(items), "items": items}


@router.get("/runs/{run_id}", tags=["agent"], summary="F14 运行轨迹（run_id 可复现）")
def get_trace(run_id: str, conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    try:
        return trace.trace(conn, run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/patients/{patient_id}/tasks", tags=["tasks"], summary="F11 任务列表")
def list_tasks(
    patient_id: str,
    status: str | None = None,
    task_type: str | None = None,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    items = tasks.list_tasks(conn, patient_id, status=status, task_type=task_type)
    return {"patient_id": patient_id, "count": len(items), "items": items}


@router.get("/tasks/{task_id}", tags=["tasks"], summary="F11 任务详情")
def get_task(task_id: str, conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    task = tasks.get_task(conn, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    return {"task": task, "versions": tasks.versions(conn, task_id)}


@router.post("/tasks/{task_id}/complete", tags=["tasks"], summary="F12 完成任务并触发复评")
def complete_task(
    task_id: str, payload: TaskCompleteRequest, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    try:
        task = tasks.complete_task(conn, task_id, changed_by=payload.changed_by, note=payload.note)
    except tasks.TaskError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result = triggers.after_task_completed(conn, task, changed_by=payload.changed_by)
    if payload.run_agent:
        result["run"] = orchestrator.run_agent(
            conn, task["patient_id"], trigger_type="task_completed", trigger_ref=task_id
        )
    return {**result, "task": tasks.get_task(conn, task_id)}


@router.post("/tasks/{task_id}/reschedule", tags=["tasks"], summary="F23 调整任务时间（保留版本）")
def reschedule_task(
    task_id: str, payload: TaskRescheduleRequest, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    try:
        task = tasks.reschedule_task(
            conn,
            task_id,
            due_at=payload.due_at,
            reason=payload.reason,
            changed_by=payload.changed_by,
        )
    except (tasks.TaskError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"task": task, "versions": tasks.versions(conn, task_id)}


@router.get("/tasks/{task_id}/versions", tags=["tasks"], summary="F23 计划版本历史")
def task_versions(task_id: str, conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    return {"task_id": task_id, "versions": tasks.versions(conn, task_id)}


@router.get("/patients/{patient_id}/questions", tags=["questions"], summary="F21 待答复问题")
def list_questions(
    patient_id: str, status: str | None = None, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    items = questioning.list_questions(conn, patient_id, status=status)
    return {"patient_id": patient_id, "count": len(items), "items": items}


@router.post("/questions/{question_id}/answer", tags=["questions"], summary="F21 回答并恢复执行")
def answer_question(
    question_id: str, payload: AnswerRequest, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    text = payload.answer_text or payload.option
    try:
        question = questioning.answer_question(
            conn, question_id, answer_text=text, answer_value=payload.answer_value
        )
    except questioning.QuestionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result: dict[str, Any] = {"question": question, "resume": None}
    if payload.trigger_agent:
        result["resume"] = triggers.after_answer(conn, question)
    return result


@router.get("/patients/{patient_id}/reviews", tags=["reviews"], summary="F12 复评列表")
def list_reviews(
    patient_id: str, status: str | None = None, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    items = reviews.list_reviews(conn, patient_id, status=status)
    return {"patient_id": patient_id, "count": len(items), "items": items}


@router.post("/reviews/{review_id}/resolve", tags=["reviews"], summary="F13 人工复核结案")
def resolve_review(
    review_id: str, payload: ReviewResolveRequest, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    try:
        return reviews.resolve_human_review(conn, review_id, decision=payload.decision, note=payload.note)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/patients/{patient_id}/notifications", tags=["notifications"], summary="F16 站内提醒")
def list_notifications(
    patient_id: str,
    status: str | None = Query(default=None),
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    from backend.app.services import notifications as notification_service

    items = notification_service.list_notifications(conn, patient_id, status=status)
    return {"patient_id": patient_id, "count": len(items), "items": items}


@router.post("/notifications/{notification_id}/read", tags=["notifications"], summary="F16 标记已读")
def read_notification(notification_id: str, conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    from backend.app.services import notifications as notification_service

    item = notification_service.mark_read(conn, notification_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"提醒不存在: {notification_id}")
    return item
