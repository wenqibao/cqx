"""患者、健康记录、状态、事件与知识检索接口（F01-F07、F24）。"""
from __future__ import annotations

import sqlite3
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.app.api.deps import get_conn
from backend.app.automation import triggers
from backend.app.db.connection import iso, now
from backend.app.events.detector import detect_events, list_events
from backend.app.knowledge import search as knowledge_search
from backend.app.knowledge.index import documents, ensure_index
from backend.app.schemas.models import PatientCreate, RecordCreate, RecordImport
from backend.app.services import patients as patient_service
from backend.app.services import records as record_service
from backend.app.services import state as state_service

router = APIRouter()


@router.get("/patients", tags=["patients"], summary="F01 演示患者列表")
def list_patients(conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    items = patient_service.list_patients(conn)
    return {"count": len(items), "items": items}


@router.post("/patients", tags=["patients"], status_code=201, summary="F01/F02 新建演示患者")
def create_patient(payload: PatientCreate, conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    return patient_service.create_patient(conn, payload.model_dump())


@router.get("/patients/{patient_id}", tags=["patients"], summary="F02 患者档案")
def get_patient(patient_id: str, conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    try:
        patient = patient_service.get_patient(conn, patient_id)
    except patient_service.PatientNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {**patient, "profile": patient_service.profile_completeness(patient)}


@router.get("/patients/{patient_id}/state", tags=["state"], summary="F04 状态快照与趋势")
def get_state(patient_id: str, conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    try:
        return state_service.build_state(conn, patient_id)
    except patient_service.PatientNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/patients/{patient_id}/state/history", tags=["state"], summary="F04 历史状态快照")
def state_history(patient_id: str, conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT version, created_at FROM state_snapshots WHERE patient_id=? ORDER BY version DESC LIMIT 20",
        (patient_id,),
    ).fetchall()
    return {"patient_id": patient_id, "snapshots": [dict(r) for r in rows]}


@router.get("/patients/{patient_id}/records", tags=["records"], summary="F03 健康记录列表")
def list_records(
    patient_id: str,
    kind: str | None = None,
    days: int = Query(default=30, ge=1, le=365),
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    since = iso(now(conn) - timedelta(days=days))
    items = record_service.list_records(conn, patient_id, kind=kind, since=since)
    return {"patient_id": patient_id, "count": len(items), "items": items}


@router.post(
    "/patients/{patient_id}/records", tags=["records"], status_code=201, summary="F03/F06 录入记录并自动触发 Agent"
)
def add_record(
    patient_id: str, payload: RecordCreate, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    try:
        record = record_service.add_record(conn, patient_id, payload.model_dump())
    except patient_service.PatientNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except record_service.RecordValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result: dict[str, Any] = {"record": record, "automation": None}
    if payload.trigger_agent and not record.get("duplicate"):
        result["automation"] = triggers.after_records(conn, patient_id, [record], source="record_created")
    return result


@router.post("/patients/{patient_id}/records/import", tags=["records"], summary="F03 CSV/JSON 回放导入")
def import_records(
    patient_id: str, payload: RecordImport, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    if not payload.csv_text and not payload.json_rows:
        raise HTTPException(status_code=422, detail="需要 csv_text 或 json_rows")
    try:
        summary = record_service.import_records(
            conn, patient_id, csv_text=payload.csv_text, json_rows=payload.json_rows, source="csv_import"
        )
    except patient_service.PatientNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if payload.trigger_agent and summary["records"]:
        summary["automation"] = triggers.after_records(conn, patient_id, summary["records"], source="import")
    return summary


@router.get("/patients/{patient_id}/events", tags=["events"], summary="F05 事件列表")
def get_events(
    patient_id: str, status: str | None = None, conn: sqlite3.Connection = Depends(get_conn)
) -> dict[str, Any]:
    items = list_events(conn, patient_id, status=status)
    return {"patient_id": patient_id, "count": len(items), "items": items}


@router.post("/patients/{patient_id}/events/scan", tags=["events"], summary="F05 手动触发事件检测（演示用）")
def scan_events(patient_id: str, conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    return detect_events(conn, patient_id, trigger="manual_scan")


@router.get("/knowledge", tags=["knowledge"], summary="F24 知识包清单")
def knowledge_list(conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    ensure_index(conn)
    docs = documents(conn)
    return {"count": len(docs), "items": docs}


@router.post("/knowledge/reindex", tags=["knowledge"], summary="F24 重建知识索引")
def knowledge_reindex(conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    return ensure_index(conn, force=True)


@router.get("/knowledge/search", tags=["knowledge"], summary="F24 检索并返回可定位出处")
def knowledge_search_endpoint(
    q: str = Query(min_length=1),
    top_k: int = Query(default=4, ge=1, le=10),
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    ensure_index(conn)
    return knowledge_search.search(conn, q, top_k=top_k)
