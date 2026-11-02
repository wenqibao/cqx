# -*- coding: utf-8 -*-
"""场景回放与预期比对（F19/F20 的执行入口；场景与预期由成员 B 维护）。

用法：
    python scripts/run_scenarios.py                 # 跑 evaluation/scenarios/ 下全部场景
    python scripts/run_scenarios.py S01 S03         # 只跑指定场景
    python scripts/run_scenarios.py --report out.json

场景文件格式见 evaluation/README.md。脚本会在独立临时数据库中执行，不污染演示库。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from datetime import timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
VENDOR = ROOT / "vendor"
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

from backend.app.agent.orchestrator import run_agent  # noqa: E402
from backend.app.db.connection import advance_clock, connect, iso, now  # noqa: E402
from backend.app.knowledge.index import ensure_index  # noqa: E402
from backend.app.questioning import service as questioning  # noqa: E402
from backend.app.reviews import service as reviews  # noqa: E402
from backend.app.automation import scheduler, triggers  # noqa: E402
from backend.app.services import patients, records, state  # noqa: E402
from backend.app.tasks import service as tasks  # noqa: E402

SCENARIO_DIR = ROOT / "evaluation" / "scenarios"
REPORT_DIR = ROOT / "evaluation" / "reports"


def _hours_ago(conn, hours: float) -> str:
    return iso(now(conn) - timedelta(hours=float(hours)))


def _apply_step(conn, ctx: dict, step: dict) -> dict[str, Any]:
    action = step["action"]
    out: dict[str, Any] = {"action": action}
    if action == "patient":
        patients.create_patient(conn, step["data"])
        out["patient_id"] = step["data"]["id"]
    elif action == "record":
        record = records.add_record(
            conn,
            ctx["patient_id"],
            {
                "kind": step["kind"],
                "value": step.get("value"),
                "recorded_at": _hours_ago(conn, step.get("hours_ago", 0)),
                "payload": step.get("payload") or {},
                "source": "scenario",
            },
        )
        out["record"] = record
        if step.get("trigger", True) and not record.get("duplicate"):
            out["automation"] = triggers.after_records(conn, ctx["patient_id"], [record], source="scenario")
    elif action == "run_agent":
        out["run"] = run_agent(
            conn, ctx["patient_id"], trigger_type=step.get("trigger_type", "user_request"), message=step.get("message")
        )
    elif action == "answer":
        waiting = questioning.list_questions(conn, ctx["patient_id"], status="waiting")
        if not waiting:
            raise AssertionError("没有等待中的问题可回答")
        question = waiting[0]
        answered = questioning.answer_question(conn, question["id"], answer_text=step.get("text", ""))
        out["question"] = answered
        if step.get("resume", True):
            out["resume"] = triggers.after_answer(conn, answered)
    elif action == "complete_task":
        items = tasks.list_tasks(conn, ctx["patient_id"], status="pending")
        target = None
        if step.get("task_type"):
            target = next((t for t in items if t["task_type"] == step["task_type"]), None)
        else:
            target = items[0] if items else None
        if target is None:
            raise AssertionError("没有可完成的任务")
        done = tasks.complete_task(conn, target["id"], changed_by="patient")
        out["task"] = done
        out["reviews"] = triggers.after_task_completed(conn, done)
    elif action == "tick":
        if step.get("advance_seconds"):
            advance_clock(conn, int(step["advance_seconds"]))
        out["tick"] = scheduler.tick(conn)
    elif action == "state":
        out["state"] = state.build_state(conn, ctx["patient_id"])
    else:
        raise AssertionError(f"未知动作: {action}")
    return out


def _get_path(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if isinstance(cur, list):
            cur = cur[int(part)]
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _check(conn, ctx: dict, expect: dict[str, Any], last: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    run = last.get("run")
    if run is None and last.get("automation"):
        runs = last["automation"].get("runs") or []
        run = runs[-1] if runs else None
    if run is None and last.get("resume"):
        run = last["resume"].get("run")
    for key, expected in expect.items():
        if key == "tasks_min":
            count = conn.execute(
                "SELECT COUNT(*) c FROM tasks WHERE patient_id=?", (ctx["patient_id"],)
            ).fetchone()["c"]
            if count < int(expected):
                errors.append(f"任务数 {count} < 期望 {expected}")
        elif key == "events_include":
            codes = {
                r["code"]
                for r in conn.execute("SELECT code FROM events WHERE patient_id=?", (ctx["patient_id"],)).fetchall()
            }
            for code in expected:
                if code not in codes:
                    errors.append(f"缺少事件 {code}（实际 {sorted(codes)}）")
        elif key == "review_branches_include":
            branches = {
                r["branch"]
                for r in conn.execute(
                    "SELECT branch FROM reviews WHERE patient_id=?", (ctx["patient_id"],)
                ).fetchall()
            }
            for branch in expected:
                if branch not in branches:
                    errors.append(f"缺少复评分支 {branch}（实际 {sorted(branches)}）")
        elif key == "rejections_include":
            codes = [r["code"] for r in (last.get("run") or {}).get("rejections", [])]
            for code in expected:
                if code not in codes:
                    errors.append(f"缺少拒绝码 {code}（实际 {codes}）")
        elif key == "waiting_questions_min":
            count = conn.execute(
                "SELECT COUNT(*) c FROM questions WHERE patient_id=? AND status='waiting'",
                (ctx["patient_id"],),
            ).fetchone()["c"]
            if count < int(expected):
                errors.append(f"待答复问题 {count} < 期望 {expected}")
        elif key.startswith("run."):
            actual = _get_path(run or {}, key[4:])
            if actual != expected:
                errors.append(f"{key} 实际={actual!r} 期望={expected!r}")
        else:
            actual = _get_path(last, key)
            if actual != expected:
                errors.append(f"{key} 实际={actual!r} 期望={expected!r}")
    return errors


def run_scenario(path: Path, db_path: Path) -> dict[str, Any]:
    scenario = json.loads(path.read_text(encoding="utf-8"))
    started = time.time()
    result: dict[str, Any] = {
        "id": scenario["id"],
        "title": scenario.get("title", ""),
        "features": scenario.get("features", []),
        "passed": False,
        "errors": [],
        "steps": [],
        "llm_mode": "unknown",
        "runs": 0,
        "tasks": 0,
    }
    conn = connect(db_path)
    try:
        ensure_index(conn)
        ctx: dict[str, Any] = {"patient_id": None}
        last: dict[str, Any] = {}
        for index, step in enumerate(scenario.get("steps", [])):
            if step["action"] == "patient":
                ctx["patient_id"] = step["data"]["id"]
            out = _apply_step(conn, ctx, step)
            last = out
            ctx["patient_id"] = ctx["patient_id"] or out.get("patient_id")
            entry = {"step": index, "action": step["action"], "ok": True}
            if "run" in out:
                entry["run_id"] = out["run"]["run_id"]
                entry["status"] = out["run"]["status"]
                entry["intent"] = out["run"]["intent"]
            result["steps"].append(entry)
            if step.get("expect"):
                errors = _check(conn, ctx, step["expect"], out)
                if errors:
                    result["errors"].extend(f"step {index}: {e}" for e in errors)
        # 禁止动作断言：任何 reject 记录都算失败（除非场景显式允许）
        reject_count = conn.execute(
            "SELECT COUNT(*) c FROM audit_log WHERE decision='reject' AND patient_id=?", (ctx["patient_id"],)
        ).fetchone()["c"]
        allowed = scenario.get("allow_rejections", False)
        if reject_count and not allowed:
            result["errors"].append(f"出现 {reject_count} 次被拒绝的动作（场景未允许）")
        result["passed"] = not result["errors"]
        result["llm_mode"] = (
            conn.execute("SELECT llm_mode FROM agent_runs LIMIT 1").fetchone()["llm_mode"]
            if conn.execute("SELECT COUNT(*) c FROM agent_runs").fetchone()["c"]
            else "mock"
        )
        result["runs"] = conn.execute("SELECT COUNT(*) c FROM agent_runs").fetchone()["c"]
        result["tasks"] = conn.execute(
            "SELECT COUNT(*) c FROM tasks WHERE patient_id=?", (ctx["patient_id"],)
        ).fetchone()["c"]
    except Exception as exc:  # 场景执行失败要写清楚，不能吞掉
        result["errors"].append(f"{type(exc).__name__}: {exc}")
        result["traceback"] = traceback.format_exc()
    finally:
        conn.close()
    result["duration_ms"] = int((time.time() - started) * 1000)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="糖衡智管场景回放")
    parser.add_argument("ids", nargs="*", help="只运行指定场景 ID")
    parser.add_argument("--report", default=None, help="报告输出路径")
    parser.add_argument("--db", default=None, help="使用指定数据库（默认临时库）")
    args = parser.parse_args(argv)

    workdir = ROOT / ".tmp" / f"scenarios-{int(time.time())}"
    workdir.mkdir(parents=True, exist_ok=True)
    db_path = Path(args.db) if args.db else workdir / "scenario.db"
    files = sorted(SCENARIO_DIR.glob("*.json"))
    if args.ids:
        files = [f for f in files if f.stem.split("-")[0] in args.ids or f.stem in args.ids]
    if not files:
        print("没有找到场景文件")
        return 2

    results = []
    for path in files:
        outcome = run_scenario(path, db_path)
        results.append(outcome)
        status = "PASS" if outcome["passed"] else "FAIL"
        print(f"[{status}] {outcome['id']} {outcome['title']} ({outcome['duration_ms']}ms) mode={outcome['llm_mode']}")
        for err in outcome["errors"]:
            print(f"       - {err}")

    passed = sum(1 for r in results if r["passed"])
    summary = {
        "at": iso(now()),
        "llm_mode": results[0]["llm_mode"] if results else "unknown",
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "results": results,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = Path(args.report) if args.report else REPORT_DIR / f"scenario-report-{int(time.time())}.json"
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n合计 {len(results)} 个场景，通过 {passed}，失败 {len(results) - passed}")
    print(f"报告: {report_path}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
