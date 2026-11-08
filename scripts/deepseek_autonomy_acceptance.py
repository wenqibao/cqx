"""A-REAL 自主管理真实验收（R07-R11，独立库与账本，fail-closed）。

用法（B 在批准预算后执行，A 本地不运行真实模型）：
  1) 以独立库启动真实模式服务：
     $env:DIABETES_DB_PATH="data/runtime/deepseek_autonomy.db"
     $env:AGENT_LLM_MODE="real"; $env:AGENT_LLM_BASE_URL=...; $env:AGENT_LLM_API_KEY=...
     python -m cli.main serve --port 8011
  2) python scripts/deepseek_autonomy_acceptance.py prepare
  3) 逐个执行（每次触发只允许一次）：
     python scripts/deepseek_autonomy_acceptance.py run R07
     ...
  4) python scripts/deepseek_autonomy_acceptance.py collect R07

预算：业务触发 5 次、HTTP 16 次；账本落盘，不得清空或重置报告绕过。
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import sqlite3
import subprocess
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE = "http://127.0.0.1:8011/api"
REPORT = ROOT / "evaluation/reports"
FIXTURES = ROOT / ".tmp/deepseek-autonomy-fixtures.json"
LEDGER = ROOT / ".tmp/deepseek-autonomy-ledger.json"
DB_PATH = ROOT / "data/runtime/deepseek_autonomy.db"
CASES = ["R07", "R08", "R09", "R10", "R11"]
MAX_TRIGGERS = 5
MAX_HTTP = 16

MESSAGES = {
    "R07": "我的血糖最近在上升，请安排一次正式复评，并说明依据。",
    "R08": "请核实我最近的服药情况，如果已经有相关任务就沿用，不要重复创建。",
    "R09": "我的记录有缺项，请按我现有的任务帮我处理，不要重复建任务。",
    "R10": "请核实我的健康记录缺项，缺失的信息先问我，不要猜测。",
    "R11": "我最近头晕、出冷汗，测了血糖很低，请尽快处理。",
}


def _ledger() -> dict:
    if LEDGER.exists():
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    return {"triggers": [], "http": 0}


def _save_ledger(data: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def request(method: str, path: str, body=None, *, count: bool = False) -> dict:
    ledger = _ledger()
    if count:
        if ledger["http"] >= MAX_HTTP:
            raise SystemExit(f"HTTP 预算已用尽（{MAX_HTTP}），拒绝继续请求")
        ledger["http"] += 1
        _save_ledger(ledger)
    with httpx.Client(timeout=180, trust_env=False) as client:
        response = client.request(method, BASE + path, json=body)
    return {"method": method, "path": path, "status": response.status_code, "body": response.json()}


def dump(name: str, data) -> None:
    REPORT.mkdir(parents=True, exist_ok=True)
    path = REPORT / name
    assert not path.exists(), f"报告已存在，禁止覆盖：{path}"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT).decode().strip()


def prepare() -> None:
    from backend.app.config import settings
    from backend.app.db.connection import connect, iso, now
    from backend.app.events.detector import detect_events
    from backend.app.tasks.service import create_task

    cfg = settings()
    assert Path(cfg.db_path).resolve() == DB_PATH.resolve(), f"请使用独立验收库：{DB_PATH}"
    assert not FIXTURES.exists(), "已准备，禁止重建"
    health = request("GET", "/health")
    assert health["body"]["database"]["path"] == str(DB_PATH.resolve())

    fixture = {"prepared_at": iso(), "patients": {}, "setup": "API 合成患者 + 真实 service，不伪造状态"}
    for case in CASES:
        pid = "AUTO-" + case
        created = request("POST", "/patients", {
            "id": pid, "name": f"自主验收 {case}（虚构）", "age": 55, "duration_years": 6,
            "goals": ["稳定血糖", "规律记录"], "is_synthetic": True,
        })
        assert created["status"] == 201, created
        fixture["patients"][case] = pid
        values = {"R07": [7.0, 7.8, 8.6, 9.4], "R08": [7.2, 8.0], "R09": [7.4, 8.2], "R10": [7.1], "R11": [7.0]}[case]
        for index, value in enumerate(values):
            payload = {"kind": "fasting_glucose", "value": value,
                       "recorded_at": iso(now() - dt.timedelta(hours=24 * (len(values) - index))),
                       "trigger_agent": False}
            assert request("POST", f"/patients/{pid}/records", payload)["status"] == 201
        if case != "R10":
            assert request("POST", f"/patients/{pid}/records",
                           {"kind": "steps", "value": 6000, "trigger_agent": False})["status"] == 201
        if case in ("R08", "R09"):
            assert request("POST", f"/patients/{pid}/records",
                           {"kind": "medication_taken", "value": 1, "trigger_agent": False})["status"] == 201
    # R11：低血糖记录触发高风险事件
    assert request("POST", f"/patients/{fixture['patients']['R11']}/records",
                   {"kind": "fasting_glucose", "value": 3.1, "trigger_agent": False})["status"] == 201

    conn = connect(DB_PATH)
    try:
        p08 = fixture["patients"]["R08"]
        task08, _ = create_task(conn, p08, task_type="confirm_medication", title="核实近3天服药",
                                due_at=iso(now() + dt.timedelta(hours=20)), schedule_review=False)
        fixture["task_R08"] = task08["id"]
        # R09：为已有任务建立事件关联，用于"覆盖说明"路径
        p09 = fixture["patients"]["R09"]
        detect_events(conn, p09)
        event = conn.execute("SELECT id FROM events WHERE patient_id=? AND status='open' LIMIT 1", (p09,)).fetchone()
        task09, _ = create_task(conn, p09, task_type="confirm_medication", title="核实服药",
                                event_id=event["id"] if event else None,
                                due_at=iso(now() + dt.timedelta(hours=20)), schedule_review=False)
        fixture["task_R09"] = task09["id"]

        preview = sqlite3.connect(ROOT / ".tmp/autonomy-event-preview.db")
        preview.row_factory = sqlite3.Row
        conn.backup(preview)
        preview_events = {}
        for case in CASES:
            detected = detect_events(preview, fixture["patients"][case])
            preview_events[case] = [e["code"] for e in detected["created"]]
        preview.close()
        fixture["event_preview"] = preview_events
    finally:
        conn.close()

    FIXTURES.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
    env = {
        "git_sha": _git("rev-parse", "HEAD"), "branch": _git("branch", "--show-current"),
        "python": sys.version, "os": platform.platform(), "db": str(DB_PATH),
        "mode": cfg.llm_mode, "model": cfg.llm_model,
        "safety_sha256": hashlib.sha256((ROOT / "config/safety_rules.yaml").read_bytes()).hexdigest(),
        "health": health, "system_mode": request("GET", "/system/mode"),
        "fixtures": fixture,
    }
    dump("autonomy_environment.json", env)
    print(json.dumps({"prepared": True, "event_preview": fixture["event_preview"]}, ensure_ascii=False))


def run(case: str) -> None:
    assert case in CASES, f"未知场景 {case}"
    output = REPORT / f"autonomy_{case}_response.json"
    assert not output.exists(), "该场景已执行，禁止重复收费测试"
    ledger = _ledger()
    assert case not in ledger["triggers"], "账本显示该场景已触发"
    fixtures = json.loads(FIXTURES.read_text(encoding="utf-8"))
    mode = request("GET", "/system/mode", count=True)["body"]
    assert str(mode.get("mode", "")).lower() == "real", f"当前不是 real 模式：{mode}"
    assert mode.get("model"), "未报告真实模型名称"
    response = request("POST", f"/patients/{fixtures['patients'][case]}/agent/runs",
                       {"message": MESSAGES[case]}, count=True)
    ledger = _ledger()
    ledger["triggers"].append(case)
    ledger.setdefault("runs", {})[case] = response["body"].get("run_id")
    _save_ledger(ledger)
    dump(output.name, {"mode": mode, "response": response})
    print(json.dumps({"scenario": case, "http_status": response["status"],
                      "run_id": response["body"].get("run_id"), "status": response["body"].get("status")},
                     ensure_ascii=False))
    collect(case)


def collect(case: str) -> None:
    from backend.app.config import settings
    from backend.app.db.connection import connect

    fixtures = json.loads(FIXTURES.read_text(encoding="utf-8"))
    pid = fixtures["patients"][case]
    conn = connect(settings().db_path)
    try:
        objects = {
            table: [dict(row) for row in conn.execute(
                f"SELECT * FROM {table} WHERE {'id' if table == 'patients' else 'patient_id'}=?", (pid,)
            ).fetchall()]
            for table in ["patients", "health_records", "tasks", "questions", "reviews",
                          "agent_runs", "evidence_items", "audit_log", "state_snapshots"]
        }
    finally:
        conn.close()
    runs = request("GET", f"/patients/{pid}/runs", count=True)
    details = [request("GET", "/runs/" + item["id"], count=True)["body"] for item in runs["body"]["items"]]
    snapshot = {
        "scenario": case, "patient_id": pid, "database": objects, "traces": details,
        "tasks": request("GET", f"/patients/{pid}/tasks", count=True),
        "questions": request("GET", f"/patients/{pid}/questions", count=True),
        "reviews": request("GET", f"/patients/{pid}/reviews", count=True),
        "state": request("GET", f"/patients/{pid}/state", count=True),
        "audit": request("GET", "/system/audit", count=True),
        "expectations": {
            "R07": "schedule_review 成功，reviews 有 scheduled 记录，无多余任务",
            "R08": "不新增任务；已有任务被 update_task 调整或说明覆盖",
            "R09": "覆盖说明可核验：任务存在、属于该患者、状态 pending/missed",
            "R10": "ask_user 创建 waiting 问题，未猜测写入",
            "R11": "request_human_review 创建 HUMAN_REVIEW / pending_human",
        }[case],
    }
    dump(f"autonomy_{case}_snapshot.json", snapshot)
    print(json.dumps({"scenario": case, "tasks": len(objects["tasks"]),
                      "questions": len(objects["questions"]), "reviews": len(objects["reviews"])},
                     ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "run", "collect"])
    parser.add_argument("scenario", nargs="?")
    args = parser.parse_args()
    if args.action == "prepare":
        prepare()
    elif args.action == "run":
        run(args.scenario)
    else:
        collect(args.scenario)
