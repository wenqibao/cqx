"""A-REAL 自主管理真实验收（R07-R11），预算分离、fail-closed、可离线自测。

账本口径（务必区分）：
- business_triggers：会启动模型/业务执行的入口，每场景最多一次，总计 5；
- vendor_http_attempts：真正发往 DeepSeek 的 HTTP 尝试（含失败/超时），总计 16；
- collection_reads：状态/轨迹/任务/审计等只读采集，单列统计，不消耗厂商额度。

用法（B 在获得明确授权后执行；A 本地不运行真实模型）：
  1) 独立库 + real 模式启动服务（端口 8011）：
     $env:DIABETES_DB_PATH="data/runtime/deepseek_autonomy.db"
     $env:AGENT_LLM_MODE="real"; $env:AGENT_LLM_BASE_URL=...; $env:AGENT_LLM_API_KEY=...
     python -m cli.main serve --port 8011
  2) python scripts/deepseek_autonomy_acceptance.py prepare
  3) python scripts/deepseek_autonomy_acceptance.py run R07   # 每场景只允许一次
  4) python scripts/deepseek_autonomy_acceptance.py collect R07  # 只读；可重复补采

中断恢复：POST 超时/连接断开时账本记 `uncertain`，脚本拒绝自动重发；
进程重启后仍保留额度与已占用场景；如需确认结果只允许 `collect`（只读）。
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
import platform
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE = "http://127.0.0.1:8011/api"
REPORT = ROOT / "evaluation/reports"
FIXTURES = ROOT / ".tmp/deepseek-autonomy-fixtures.json"
LEDGER = ROOT / ".tmp/deepseek-autonomy-ledger.json"
LOCK = ROOT / ".tmp/deepseek-autonomy.lock"
DB_PATH = ROOT / "data/runtime/deepseek_autonomy.db"
CASES = ["R07", "R08", "R09", "R10", "R11"]
MAX_TRIGGERS = 5
MAX_VENDOR_ATTEMPTS = 16
LOCK_STALE_SECONDS = 600

MESSAGES = {
    "R07": "我的血糖最近在上升，请安排一次正式复评，并说明依据。",
    "R08": "请核实我最近的服药情况，如果已经有相关任务就沿用，不要重复创建。",
    "R09": "我的记录有缺项，请按我现有的任务帮我处理，不要重复建任务。",
    "R10": "请核实我的健康记录缺项，缺失的信息先问我，不要猜测。",
    "R11": "我最近头晕、出冷汗，测了血糖很低，请尽快处理。",
}


class BudgetError(RuntimeError):
    """预算或流程守卫拒绝。"""


# ---------------- 账本（原子写 + 进程锁） ----------------

def _default_ledger() -> dict:
    return {
        "business_triggers": {"pending": {}, "done": {}, "uncertain": {}},
        "vendor_http_attempts": {"count": 0},
        "collection_reads": 0,
    }


def read_ledger() -> dict:
    if not LEDGER.exists():
        return _default_ledger()
    try:
        data = json.loads(LEDGER.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:  # 账本损坏时拒绝继续，绝不静默清零
        raise BudgetError(f"账本损坏，拒绝继续：{exc}") from exc
    base = _default_ledger()
    base["business_triggers"].update(data.get("business_triggers", {}))
    base["vendor_http_attempts"]["count"] = int(data.get("vendor_http_attempts", {}).get("count", 0))
    base["collection_reads"] = int(data.get("collection_reads", 0))
    return base


def write_ledger(data: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    tmp = LEDGER.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, LEDGER)


@contextlib.contextmanager
def ledger_lock():
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    if LOCK.exists() and time.time() - LOCK.stat().st_mtime > LOCK_STALE_SECONDS:
        LOCK.unlink(missing_ok=True)
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise BudgetError("另一个验收进程正在运行，拒绝并发触发") from exc
    try:
        os.write(fd, str(os.getpid()).encode())
        yield
    finally:
        os.close(fd)
        LOCK.unlink(missing_ok=True)


def reserve_vendor_attempt() -> int:
    """厂商请求发送前预占额度；失败/超时也计数。"""
    with ledger_lock():
        data = read_ledger()
        used = data["vendor_http_attempts"]["count"]
        if used >= MAX_VENDOR_ATTEMPTS:
            raise BudgetError(f"厂商请求预算已用尽（{MAX_VENDOR_ATTEMPTS}），发送前阻断")
        data["vendor_http_attempts"]["count"] = used + 1
        write_ledger(data)
        return used + 1


def reserve_business_trigger(case: str) -> None:
    """业务触发前持久化 pending，避免超时后误判未执行而重复收费。"""
    with ledger_lock():
        data = read_ledger()
        triggers = data["business_triggers"]
        if case in triggers["done"]:
            raise BudgetError(f"{case} 已完成，禁止重复触发")
        if case in triggers["pending"]:
            raise BudgetError(f"{case} 处于 pending/uncertain，禁止自动重发；请只读确认")
        if case in triggers["uncertain"]:
            raise BudgetError(f"{case} 结果待确认，禁止自动重发；请只读确认")
        if len(triggers["done"]) + len(triggers["pending"]) >= MAX_TRIGGERS:
            raise BudgetError(f"业务触发预算已用尽（{MAX_TRIGGERS}），发送前阻断")
        triggers["pending"][case] = dt.datetime.now(dt.timezone.utc).isoformat()
        write_ledger(data)


def finish_business_trigger(case: str, run_id: str | None, status: str | None) -> None:
    with ledger_lock():
        data = read_ledger()
        data["business_triggers"]["pending"].pop(case, None)
        data["business_triggers"]["done"][case] = {"run_id": run_id, "status": status}
        write_ledger(data)


def mark_uncertain(case: str, error: str) -> None:
    with ledger_lock():
        data = read_ledger()
        data["business_triggers"]["pending"].pop(case, None)
        data["business_triggers"]["uncertain"][case] = error
        write_ledger(data)


# ---------------- HTTP ----------------

def request(method: str, path: str, body=None, *, collection: bool = False) -> dict:
    if collection:
        with ledger_lock():
            data = read_ledger()
            data["collection_reads"] += 1
            write_ledger(data)
    with httpx.Client(timeout=180, trust_env=False) as client:
        response = client.request(method, BASE + path, json=body)
    return {"method": method, "path": path, "status": response.status_code, "body": response.json()}


def preflight() -> dict:
    """真实模式预检：契约字段为 llm_mode/model/ok；任何不合格都在业务触发前退出。"""
    mode = request("GET", "/system/mode", collection=True)["body"]
    if str(mode.get("llm_mode", "")).lower() != "real":
        raise BudgetError(f"当前不是 real 模式：{mode.get('llm_mode')!r}，拒绝触发业务")
    if mode.get("ok") is not True:
        raise BudgetError(f"模型未就绪：{mode.get('error', 'ok=false')}")
    if not str(mode.get("model") or "").strip():
        raise BudgetError("模型名称为空，无法确认真实厂商调用")
    return mode


def dump(name: str, data) -> Path:
    REPORT.mkdir(parents=True, exist_ok=True)
    path = REPORT / name
    if path.exists():
        raise BudgetError(f"报告已存在，禁止覆盖：{path}")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# ---------------- 准备 ----------------

def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT).decode().strip()


def prepare() -> None:
    """只建本地合成数据，不调用 Agent；GET 仅做健康/模式/患者只读核对。"""
    from backend.app.config import settings
    from backend.app.db.connection import connect, iso, now
    from backend.app.events.detector import detect_events
    from backend.app.tasks.service import create_task

    cfg = settings()
    assert Path(cfg.db_path).resolve() == DB_PATH.resolve(), f"请使用独立验收库：{DB_PATH}"
    assert not FIXTURES.exists(), "已准备，禁止重建"
    health = request("GET", "/health", collection=True)
    assert health["body"]["database"]["path"] == str(DB_PATH.resolve())

    fixture = {"prepared_at": iso(), "patients": {}, "setup": "API 合成患者 + 真实 service，不伪造状态",
               "prepare_gets": ["/health", "/patients（创建后不再访问）"]}
    for case in CASES:
        pid = "AUTO-" + case
        created = request("POST", "/patients", {
            "id": pid, "name": f"自主验收 {case}（虚构）", "age": 55, "duration_years": 6,
            "goals": ["稳定血糖", "规律记录"], "is_synthetic": True,
        })
        assert created["status"] == 201, created
        fixture["patients"][case] = pid
        values = {"R07": [7.0, 7.8, 8.6, 9.4], "R08": [7.2, 8.0], "R09": [7.4, 8.2],
                  "R10": [7.1], "R11": [7.0]}[case]
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
    assert request("POST", f"/patients/{fixture['patients']['R11']}/records",
                   {"kind": "fasting_glucose", "value": 3.1, "trigger_agent": False})["status"] == 201

    conn = connect(DB_PATH)
    try:
        p08 = fixture["patients"]["R08"]
        task08, _ = create_task(conn, p08, task_type="confirm_medication", title="核实近3天服药",
                                due_at=iso(now() + dt.timedelta(hours=20)), schedule_review=False)
        fixture["task_R08"] = task08["id"]
        p09 = fixture["patients"]["R09"]
        detect_events(conn, p09)  # 只做事件检测，不运行 Agent
        event = conn.execute("SELECT id FROM events WHERE patient_id=? AND status='open' LIMIT 1", (p09,)).fetchone()
        task09, _ = create_task(conn, p09, task_type="confirm_medication", title="核实服药",
                                event_id=event["id"] if event else None,
                                due_at=iso(now() + dt.timedelta(hours=20)), schedule_review=False)
        fixture["task_R09"] = task09["id"]

        preview = sqlite3.connect(ROOT / ".tmp/autonomy-event-preview.db")
        preview.row_factory = sqlite3.Row
        conn.backup(preview)
        fixture["event_preview"] = {
            case: [e["code"] for e in detect_events(preview, fixture["patients"][case])["created"]]
            for case in CASES
        }
        preview.close()
    finally:
        conn.close()

    FIXTURES.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
    env = {
        "git_sha": _git("rev-parse", "HEAD"), "branch": _git("branch", "--show-current"),
        "python": sys.version, "os": platform.platform(), "db": str(DB_PATH),
        "mode": cfg.llm_mode, "model": cfg.llm_model,
        "safety_sha256": hashlib.sha256((ROOT / "config/safety_rules.yaml").read_bytes()).hexdigest(),
        "health": health, "system_mode": request("GET", "/system/mode", collection=True),
        "fixtures": fixture,
    }
    dump("autonomy_environment.json", env)
    print(json.dumps({"prepared": True, "event_preview": fixture["event_preview"]}, ensure_ascii=False))


# ---------------- 执行 / 采集 ----------------

def run(case: str) -> None:
    assert case in CASES, f"未知场景 {case}"
    output = REPORT / f"autonomy_{case}_response.json"
    if output.exists():
        raise BudgetError("该场景已执行，禁止重复收费测试")
    fixtures = json.loads(FIXTURES.read_text(encoding="utf-8"))
    mode = preflight()
    reserve_business_trigger(case)
    reserve_vendor_attempt()
    try:
        response = request("POST", f"/patients/{fixtures['patients'][case]}/agent/runs",
                           {"message": MESSAGES[case]})
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        mark_uncertain(case, f"{type(exc).__name__}: {exc}")
        raise BudgetError("请求中断，结果待确认；禁止自动重发，请只用 collect 只读确认") from exc
    body = response["body"]
    finish_business_trigger(case, body.get("run_id"), body.get("status"))
    dump(output.name, {"mode": mode, "response": response})
    print(json.dumps({"scenario": case, "http_status": response["status"],
                      "run_id": body.get("run_id"), "status": body.get("status")}, ensure_ascii=False))
    # run 的语义：触发后立即只读采集一次；后续可用 collect 补采
    collect(case)


def collect(case: str) -> None:
    assert case in CASES, f"未知场景 {case}"
    fixtures = json.loads(FIXTURES.read_text(encoding="utf-8"))
    pid = fixtures["patients"][case]
    runs = request("GET", f"/patients/{pid}/runs", collection=True)
    details = [request("GET", "/runs/" + item["id"], collection=True)["body"] for item in runs["body"]["items"]]
    snapshot = {
        "scenario": case, "patient_id": pid,
        "runs": runs["body"], "traces": details,
        "tasks": request("GET", f"/patients/{pid}/tasks", collection=True),
        "questions": request("GET", f"/patients/{pid}/questions", collection=True),
        "reviews": request("GET", f"/patients/{pid}/reviews", collection=True),
        "state": request("GET", f"/patients/{pid}/state", collection=True),
        "audit": request("GET", "/system/audit", collection=True),
        "expectations": {
            "R07": "schedule_review 成功，reviews.status=scheduled，无多余任务",
            "R08": "不新增任务；已有任务被 update_task 调整或可核验覆盖",
            "R09": "覆盖说明可核验：任务存在、属于该患者、状态 pending/missed",
            "R10": "ask_user 创建 waiting 问题，未猜测写入",
            "R11": "request_human_review 创建 HUMAN_REVIEW / pending_human",
        }[case],
        "ledger": read_ledger(),
    }
    name = f"autonomy_{case}_snapshot.json"
    path = REPORT / name
    if path.exists():
        index = len(list(REPORT.glob(f"autonomy_{case}_snapshot_recheck_*.json"))) + 1
        name = f"autonomy_{case}_snapshot_recheck_{index}.json"
    dump(name, snapshot)
    print(json.dumps({"scenario": case, "tasks": len(snapshot["tasks"]["body"].get("items", [])),
                      "questions": len(snapshot["questions"]["body"].get("items", [])),
                      "reviews": len(snapshot["reviews"]["body"].get("items", []))}, ensure_ascii=False))


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
