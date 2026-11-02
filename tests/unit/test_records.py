"""F01-F03：患者、记录、导入与隔离。"""
from __future__ import annotations

import pytest

from backend.app.services import patients, records


def _patient(conn, pid="T001"):
    return patients.create_patient(conn, {"id": pid, "name": "测试患者", "age": 55, "duration_years": 5, "goals": ["稳定"]})


def test_add_record_persists_and_reads_back(conn):
    _patient(conn)
    created = records.add_record(conn, "T001", {"kind": "fasting_glucose", "value": 7.4, "recorded_at": "2026-01-01T00:00:00Z"})
    assert created["value"] == 7.4
    assert created["unit"] == "mmol/L"
    listed = records.list_records(conn, "T001")
    assert len(listed) == 1 and listed[0]["id"] == created["id"]


def test_unknown_kind_rejected(conn):
    _patient(conn)
    with pytest.raises(records.RecordValidationError):
        records.add_record(conn, "T001", {"kind": "blood_magic", "value": 1})


def test_value_out_of_range_rejected(conn):
    _patient(conn)
    with pytest.raises(records.RecordValidationError):
        records.add_record(conn, "T001", {"kind": "fasting_glucose", "value": 99})


def test_bp_requires_payload(conn):
    _patient(conn)
    with pytest.raises(records.RecordValidationError):
        records.add_record(conn, "T001", {"kind": "bp", "value": None})


def test_duplicate_record_is_idempotent(conn):
    _patient(conn)
    data = {"kind": "steps", "value": 5000, "recorded_at": "2026-01-01T08:00:00Z"}
    first = records.add_record(conn, "T001", data)
    second = records.add_record(conn, "T001", data)
    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert second["id"] == first["id"]
    assert len(records.list_records(conn, "T001")) == 1


def test_csv_import_partial_failure(conn):
    _patient(conn)
    csv_text = (
        "kind,value,recorded_at\n"
        "fasting_glucose,7.1,2026-01-01T07:00:00Z\n"
        "fasting_glucose,not-a-number,2026-01-02T07:00:00Z\n"
        "unknown_kind,3,2026-01-02T08:00:00Z\n"
        "steps,4200,2026-01-02T09:00:00Z\n"
    )
    summary = records.import_records(conn, "T001", csv_text=csv_text)
    assert summary["imported"] == 2
    assert summary["failed"] == 2
    assert {e["row"] for e in summary["errors"]} == {3, 4}


def test_import_duplicate_rows_skipped(conn):
    _patient(conn)
    rows = [{"kind": "steps", "value": 6000, "recorded_at": "2026-01-03T08:00:00Z"}]
    first = records.import_records(conn, "T001", json_rows=rows)
    second = records.import_records(conn, "T001", json_rows=rows)
    assert first["imported"] == 1
    assert second["imported"] == 0 and second["duplicates"] == 1


def test_patient_isolation(conn):
    _patient(conn, "T001")
    _patient(conn, "T002")
    records.add_record(conn, "T001", {"kind": "steps", "value": 1000, "recorded_at": "2026-01-01T08:00:00Z"})
    records.add_record(conn, "T002", {"kind": "steps", "value": 9000, "recorded_at": "2026-01-01T08:00:00Z"})
    assert records.list_records(conn, "T001")[0]["value"] == 1000
    assert records.list_records(conn, "T002")[0]["value"] == 9000


def test_unknown_patient_rejected(conn):
    with pytest.raises(patients.PatientNotFound):
        records.add_record(conn, "NOPE", {"kind": "steps", "value": 1})
