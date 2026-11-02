"""F02/F04：状态快照、聚合、趋势与缺失字段。"""
from __future__ import annotations

from datetime import timedelta

from backend.app.db.connection import iso, now
from backend.app.services import patients, records, state


def _mk(conn, pid="S001"):
    return patients.create_patient(
        conn, {"id": pid, "name": "状态患者", "age": 52, "duration_years": 4, "goals": ["稳定血糖"]}
    )


def test_aggregates_and_trend(conn):
    _mk(conn)
    for i, value in enumerate([6.5, 7.0, 8.2]):
        records.add_record(
            conn,
            "S001",
            {"kind": "fasting_glucose", "value": value, "recorded_at": iso(now(conn) - timedelta(days=3 - i))},
        )
    snap = state.build_state(conn, "S001")
    agg = snap["aggregates"]["7d"]["fasting_glucose"]
    assert agg["count"] == 3
    assert agg["mean"] == round((6.5 + 7.0 + 8.2) / 3, 2)
    assert snap["trend"]["fasting_glucose_7d"] == "rising"


def test_missing_medication_field(conn):
    _mk(conn)
    records.add_record(conn, "S001", {"kind": "steps", "value": 5000, "recorded_at": iso(now(conn))})
    snap = state.build_state(conn, "S001")
    assert "medication_taken" in snap["missing_fields"]


def test_snapshot_versions_increment(conn):
    _mk(conn)
    first = state.save_snapshot(conn, "S001")
    second = state.save_snapshot(conn, "S001")
    assert first["snapshot_version"] == 1
    assert second["snapshot_version"] == 2
    latest = state.latest_snapshot(conn, "S001")
    assert latest["snapshot_version"] == 2


def test_state_survives_new_connection(conn, db_path):
    _mk(conn)
    records.add_record(conn, "S001", {"kind": "steps", "value": 7000, "recorded_at": iso(now(conn))})
    state.save_snapshot(conn, "S001")
    conn.close()
    from backend.app.db.connection import connect

    conn2 = connect(db_path)
    try:
        snap = state.build_state(conn2, "S001")
        assert snap["aggregates"]["7d"]["steps"]["count"] == 1
        assert state.latest_snapshot(conn2, "S001") is not None
    finally:
        conn2.close()
