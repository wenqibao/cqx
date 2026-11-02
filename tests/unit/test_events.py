"""F05 事件检测与去重。"""
from __future__ import annotations

from datetime import timedelta

from backend.app.db.connection import iso, now
from backend.app.events.detector import detect_events
from backend.app.services import patients, records


def _mk(conn, pid="E001"):
    patients.create_patient(conn, {"id": pid, "name": "事件患者", "age": 60, "duration_years": 6, "goals": ["稳定"]})
    return pid


def _rec(conn, pid, kind, value, hours_ago, payload=None):
    return records.add_record(
        conn,
        pid,
        {
            "kind": kind,
            "value": value,
            "recorded_at": iso(now(conn) - timedelta(hours=hours_ago)),
            "payload": payload or {},
        },
    )


def test_glucose_rising_detected(conn):
    pid = _mk(conn)
    for i, value in enumerate([7.0, 7.4, 7.9, 8.4, 9.1]):
        _rec(conn, pid, "fasting_glucose", value, 24 * (5 - i))
    result = detect_events(conn, pid)
    codes = [e["code"] for e in result["created"]]
    assert "GLUCOSE_RISING" in codes
    event = next(e for e in result["created"] if e["code"] == "GLUCOSE_RISING")
    assert event["evidence"]["delta"] >= 1.5


def test_low_activity_detected(conn):
    pid = _mk(conn)
    _rec(conn, pid, "steps", 2400, 40)
    _rec(conn, pid, "steps", 2100, 16)
    codes = [e["code"] for e in detect_events(conn, pid)["created"]]
    assert "LOW_ACTIVITY" in codes


def test_medication_nonadherence_detected(conn):
    pid = _mk(conn)
    _rec(conn, pid, "medication_taken", 0, 30)
    _rec(conn, pid, "medication_taken", 0, 10)
    codes = [e["code"] for e in detect_events(conn, pid)["created"]]
    assert "MEDICATION_NONADHERENCE" in codes


def test_hypoglycemia_is_high_severity(conn):
    pid = _mk(conn)
    _rec(conn, pid, "fasting_glucose", 3.4, 5)
    events = detect_events(conn, pid)["created"]
    hypo = next(e for e in events if e["code"] == "HYPOGLYCEMIA_RECORD")
    assert hypo["severity"] == "high"


def test_repeat_scan_same_hour_is_idempotent(conn):
    pid = _mk(conn)
    _rec(conn, pid, "fasting_glucose", 3.4, 5)
    first = detect_events(conn, pid)["created"]
    second = detect_events(conn, pid)["created"]
    assert len(first) >= 1
    assert second == []
    total = conn.execute("SELECT COUNT(*) AS c FROM events WHERE patient_id=?", (pid,)).fetchone()["c"]
    assert total == len(first)


def test_no_data_no_event(conn):
    pid = _mk(conn)
    assert detect_events(conn, pid)["created"] == []
