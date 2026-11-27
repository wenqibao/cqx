"""体验包恢复必须保留真实历史、拒绝覆盖，并且不触发模型。"""
from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path

import pytest

from scripts.patient_experience_pack import DEFAULT_PACK, digest, export_pack, read_pack, restore, verify


def write_pack(path: Path, pack: dict) -> Path:
    pack["counts"] = {k: len(v) for k, v in pack["tables"].items()}
    pack["sha256"] = digest(pack["tables"])
    path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
    return path


def test_restore_all_history_and_references(workdir, monkeypatch):
    import httpx

    def forbid_network(*args, **kwargs):
        pytest.fail("数据恢复不得发起厂商请求")

    monkeypatch.setattr(httpx.Client, "send", forbid_network)
    target = workdir / "experience.db"
    result = restore(target)
    assert result["counts"]["patients"] == 14
    assert result["counts"]["health_records"] == 73
    assert result["counts"]["agent_runs"] == 20
    assert verify(target)["status"] == "verified"
    conn = sqlite3.connect(target)
    try:
        assert conn.execute("SELECT COUNT(*) FROM patients WHERE is_synthetic<>1").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM agent_runs WHERE llm_mode='real'").fetchone()[0] == 20
        assert conn.execute("SELECT COUNT(*) FROM agent_runs WHERE status='failed'").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM knowledge_docs").fetchone()[0] == 4
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()


def test_repeat_restore_preserves_experience_progress(workdir):
    target = workdir / "experience.db"
    restore(target)
    conn = sqlite3.connect(target)
    conn.execute("UPDATE tasks SET title='体验中修改的任务' WHERE id='TSK-e71baf9ba198'")
    conn.commit()
    conn.close()
    assert restore(target)["status"] == "already_imported"
    conn = sqlite3.connect(target)
    assert conn.execute("SELECT title FROM tasks WHERE id='TSK-e71baf9ba198'").fetchone()[0] == "体验中修改的任务"
    conn.close()


def test_existing_database_is_not_overwritten(workdir):
    target = workdir / "existing.db"
    conn = sqlite3.connect(target)
    conn.execute("CREATE TABLE personal_work (value TEXT)")
    conn.execute("INSERT INTO personal_work VALUES ('keep')")
    conn.commit()
    conn.close()
    before = target.read_bytes()
    with pytest.raises(FileExistsError):
        restore(target)
    assert target.read_bytes() == before


@pytest.mark.parametrize("defect", ["checksum", "schema", "patient_flag", "unknown_table", "foreign_key"])
def test_invalid_pack_never_publishes_partial_database(workdir, defect):
    pack = copy.deepcopy(read_pack())
    if defect == "schema":
        pack["schema_version"] = 999
    elif defect == "patient_flag":
        pack["tables"]["patients"][0]["is_synthetic"] = 0
    elif defect == "unknown_table":
        pack["tables"]["unrecognized_table"] = []
    elif defect == "foreign_key":
        pack["tables"]["agent_steps"][0]["run_id"] = "RUN-NOT-IN-PACK"
    path = write_pack(workdir / "invalid.json", pack)
    if defect == "checksum":
        pack["sha256"] = "broken"
        path.write_text(json.dumps(pack), encoding="utf-8")
    target = workdir / "should-not-exist.db"
    with pytest.raises((ValueError, sqlite3.IntegrityError)):
        restore(target, path)
    assert not target.exists()
    assert list(workdir.glob("*.import-*")) == []


def test_readonly_export_roundtrip(workdir):
    target = workdir / "experience.db"
    restore(target)
    before = target.read_bytes()
    path = workdir / "roundtrip.json"
    result = export_pack(target, path)
    assert result["sha256"] == read_pack(DEFAULT_PACK)["sha256"]
    assert target.read_bytes() == before


def test_fresh_package_can_be_browsed_through_real_api(db_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.app.main import create_app

    restore(db_path)
    monkeypatch.setenv("AUTOMATION_ENABLED", "0")
    with TestClient(create_app()) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        assert client.get("/api/patients").json()["count"] == 14
        for patient in read_pack()["tables"]["patients"]:
            pid = patient["id"]
            for endpoint in ("state", "records", "tasks", "questions", "reviews", "runs"):
                assert client.get(f"/api/patients/{pid}/{endpoint}").status_code == 200
        plan = client.get("/api/runs/RUN-e38cff4a521a").json()
        assert plan["summary"]["plan_changes"][0]["version_after"] == 4
        recovered = client.get("/api/runs/RUN-3af69abaa5e6").json()
        assert recovered["summary"]["completed"]
        assert client.get("/api/system/audit").json()["forbidden_executed"] == 0
