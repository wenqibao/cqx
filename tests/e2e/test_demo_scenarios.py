"""端到端：直接回放 evaluation/scenarios 下的场景（与 B 的场景文件同源）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.run_scenarios import SCENARIO_DIR, run_scenario

SCENARIOS = sorted(SCENARIO_DIR.glob("*.json"))


def test_scenarios_exist():
    assert len(SCENARIOS) >= 5, "至少要有 5 个固定合成场景"


@pytest.mark.parametrize("path", SCENARIOS, ids=[p.stem for p in SCENARIOS])
def test_scenario_passes(path: Path, workdir):
    db = workdir / f"{path.stem}.db"
    result = run_scenario(path, db)
    assert result["passed"], json.dumps(result["errors"], ensure_ascii=False)
    assert result["llm_mode"] in ("mock", "real")


def test_demo_patients_are_all_synthetic(seeded):
    rows = seeded.execute("SELECT id, is_synthetic FROM patients").fetchall()
    assert rows
    assert all(r["is_synthetic"] == 1 for r in rows)
    ids = {r["id"] for r in rows}
    assert {"P001", "P002", "P003"} <= ids
