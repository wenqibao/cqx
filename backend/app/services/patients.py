"""F01 演示患者管理 + F02 基础健康档案。"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from backend.app.db.connection import dumps, iso, loads, now
from backend.app.util import new_id


class PatientNotFound(LookupError):
    def __init__(self, patient_id: str) -> None:
        super().__init__(f"患者不存在: {patient_id}")
        self.patient_id = patient_id


def _row_to_patient(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "age": row["age"],
        "sex": row["sex"],
        "diabetes_type": row["diabetes_type"],
        "duration_years": row["duration_years"],
        "complications": loads(row["complications"], []),
        "goals": loads(row["goals"], []),
        "constraints": loads(row["constraints"], []),
        "baseline": loads(row["baseline"], {}),
        "is_synthetic": bool(row["is_synthetic"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_patient(conn: sqlite3.Connection, data: dict[str, Any]) -> dict[str, Any]:
    pid = data.get("id") or new_id("patient")
    ts = iso(now(conn))
    conn.execute(
        """INSERT INTO patients(id,name,age,sex,diabetes_type,duration_years,complications,
                goals,constraints,baseline,is_synthetic,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            pid,
            data.get("name", pid),
            data.get("age"),
            data.get("sex"),
            data.get("diabetes_type", "T2DM"),
            data.get("duration_years"),
            dumps(data.get("complications", [])),
            dumps(data.get("goals", [])),
            dumps(data.get("constraints", [])),
            dumps(data.get("baseline", {})),
            1,  # DATA-SYN-01：演示系统只允许合成患者，忽略调用方传入的 false
            ts,
            ts,
        ),
    )
    return get_patient(conn, pid)


def upsert_patient(conn: sqlite3.Connection, data: dict[str, Any]) -> dict[str, Any]:
    pid = data["id"]
    existing = get_patient_or_none(conn, pid)
    if existing is None:
        return create_patient(conn, data)
    merged = {**existing, **{k: v for k, v in data.items() if v is not None}}
    conn.execute(
        """UPDATE patients SET name=?, age=?, sex=?, duration_years=?, complications=?, goals=?,
               constraints=?, baseline=?, updated_at=? WHERE id=?""",
        (
            merged.get("name"),
            merged.get("age"),
            merged.get("sex"),
            merged.get("duration_years"),
            dumps(merged.get("complications", [])),
            dumps(merged.get("goals", [])),
            dumps(merged.get("constraints", [])),
            dumps(merged.get("baseline", {})),
            iso(now(conn)),
            pid,
        ),
    )
    return get_patient(conn, pid)


def get_patient_or_none(conn: sqlite3.Connection, patient_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM patients WHERE id = ?", (patient_id,)).fetchone()
    return _row_to_patient(row) if row else None


def get_patient(conn: sqlite3.Connection, patient_id: str) -> dict[str, Any]:
    patient = get_patient_or_none(conn, patient_id)
    if patient is None:
        raise PatientNotFound(patient_id)
    return patient


def list_patients(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM patients ORDER BY id").fetchall()
    return [_row_to_patient(r) for r in rows]


def profile_completeness(patient: dict[str, Any]) -> dict[str, Any]:
    """F02：基础档案完整性检查，缺失字段会进入 F21 主动询问队列。"""
    required = ["age", "duration_years", "goals"]
    missing = []
    for field in required:
        value = patient.get(field)
        if value in (None, "", [], {}):
            missing.append(field)
    return {"complete": not missing, "missing": missing}
