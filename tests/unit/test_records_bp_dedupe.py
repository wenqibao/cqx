"""A-WB-02 回归：血压去重必须区分同分钟内不同的观察值。

缺陷：去重键只含 value 与 payload.text，而血压的 value 为 None，
同分钟 120/80 与 130/85 生成同一个键，被 INSERT OR IGNORE 合并，第二条返回第一条内容。
"""
from __future__ import annotations

import pytest

from backend.app.services import patients, records

TS = "2026-11-05T08:30:10+08:00"
TS2 = "2026-11-05T08:30:40+08:00"


def _patient(conn, pid="BP1"):
    return patients.create_patient(conn, {"id": pid, "name": "血压患者", "age": 60, "duration_years": 5, "goals": ["稳定"]})


def _bp(conn, pid, ts, s, d):
    return records.add_record(conn, pid, {"kind": "bp", "recorded_at": ts, "payload": {"systolic": s, "diastolic": d}})


def test_same_minute_same_bp_is_deduped(conn):
    _patient(conn)
    first = _bp(conn, "BP1", TS, 120, 80)
    second = _bp(conn, "BP1", TS2, 120, 80)
    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert second["id"] == first["id"]
    assert len(records.list_records(conn, "BP1", kind="bp")) == 1


def test_same_minute_different_bp_is_not_deduped(conn):
    _patient(conn)
    first = _bp(conn, "BP1", TS, 120, 80)
    second = _bp(conn, "BP1", TS2, 130, 85)
    assert first["duplicate"] is False
    assert second["duplicate"] is False
    assert second["id"] != first["id"]
    assert second["payload"] == {"systolic": 130, "diastolic": 85}
    items = records.list_records(conn, "BP1", kind="bp")
    assert len(items) == 2
    assert {int(r["payload"]["systolic"]) for r in items} == {120, 130}


def test_bp_numeric_forms_are_normalized(conn):
    """120 / 120.0 / "120" 视为同一观察，不能被当成两条。"""
    _patient(conn)
    first = _bp(conn, "BP1", TS, 120, 80)
    second = _bp(conn, "BP1", TS2, "120.0", "80")
    assert second["duplicate"] is True
    assert second["id"] == first["id"]


def test_same_bp_different_patient_not_deduped(conn):
    _patient(conn, "BP1")
    _patient(conn, "BP2")
    a = _bp(conn, "BP1", TS, 120, 80)
    b = _bp(conn, "BP2", TS, 120, 80)
    assert a["duplicate"] is False and b["duplicate"] is False
    assert records.list_records(conn, "BP1", kind="bp")[0]["value"] is None


def test_legacy_dedupe_key_row_still_matches(conn):
    """升级前写入的行只有旧键；同观察再提交仍应判为重复，而不是插两条。"""
    _patient(conn)
    from backend.app.db.connection import dumps, iso, parse_ts
    from backend.app.util import short_hash

    stored_ts = iso(parse_ts(TS))  # 落库时间已归一为 UTC
    legacy = short_hash(f"BP1|bp|{stored_ts[:16]}|None|")
    conn.execute(
        """INSERT INTO health_records(patient_id,kind,value,unit,recorded_at,source,note,payload,dedupe_key,created_at)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        ("BP1", "bp", None, "mmHg", TS, "manual", None, dumps({"systolic": 120, "diastolic": 80}), legacy, TS),
    )
    again = _bp(conn, "BP1", TS2, 120, 80)
    assert again["duplicate"] is True
    assert len(records.list_records(conn, "BP1", kind="bp")) == 1


def test_symptom_text_still_distinguishes_observations(conn):
    _patient(conn)
    a = records.add_record(conn, "BP1", {"kind": "symptom", "recorded_at": TS, "payload": {"text": "心慌"}})
    b = records.add_record(conn, "BP1", {"kind": "symptom", "recorded_at": TS, "payload": {"text": " 心慌 "}})
    c = records.add_record(conn, "BP1", {"kind": "symptom", "recorded_at": TS, "payload": {"text": "出汗"}})
    assert a["duplicate"] is False
    assert b["duplicate"] is True
    assert c["duplicate"] is False


@pytest.mark.parametrize("kind,value", [("fasting_glucose", 7.2), ("steps", 5000), ("weight", 78.0)])
def test_other_kinds_dedupe_unchanged(conn, kind, value):
    _patient(conn)
    a = records.add_record(conn, "BP1", {"kind": kind, "value": value, "recorded_at": TS})
    b = records.add_record(conn, "BP1", {"kind": kind, "value": float(value), "recorded_at": TS2})
    assert a["duplicate"] is False
    assert b["duplicate"] is True
    c = records.add_record(conn, "BP1", {"kind": kind, "value": float(value) + 1, "recorded_at": TS2})
    assert c["duplicate"] is False


def test_json_import_supports_nested_payload(conn):
    """json_rows 与单条 API 的 payload 结构不同，导入也要按同一观察语义去重。"""
    _patient(conn)
    rows = [
        {"kind": "bp", "recorded_at": TS, "payload": {"systolic": 120, "diastolic": 80}},
        {"kind": "bp", "recorded_at": TS2, "payload": {"systolic": 130, "diastolic": 85}},
        {"kind": "bp", "recorded_at": TS2, "payload": {"systolic": 130, "diastolic": 85}},
    ]
    summary = records.import_records(conn, "BP1", json_rows=rows)
    assert summary["imported"] == 2
    assert summary["duplicates"] == 1
    assert len(records.list_records(conn, "BP1", kind="bp")) == 2
