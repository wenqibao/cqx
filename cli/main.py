"""F17 CLI 命令行客户端：与 HTTP API 共用同一套业务逻辑与数据库。

用法示例：
    python -m cli.main --help
    python -m cli.main version
    python -m cli.main patient list
    python -m cli.main record add P001 fasting_glucose 9.1
    python -m cli.main run P001 --message "为什么需要连续记录血糖"
    python -m cli.main trace RUN-xxxx
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app import __version__  # noqa: E402
from backend.app.db.connection import advance_clock, clock_offset, connect, iso, now, reset_clock  # noqa: E402


def _print(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _connect():
    return connect()


# ---------------------------------------------------------------- patient / state
def cmd_patient(args: argparse.Namespace) -> int:
    from backend.app.services import patients as svc

    conn = _connect()
    try:
        if args.action == "list":
            _print({"count": len(svc.list_patients(conn)), "items": svc.list_patients(conn)})
        elif args.action == "show":
            patient = svc.get_patient(conn, args.patient_id)
            _print({**patient, "profile": svc.profile_completeness(patient)})
        elif args.action == "state":
            from backend.app.services import state as state_svc

            _print(state_svc.build_state(conn, args.patient_id))
    finally:
        conn.close()
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    from backend.app.services import records as svc
    from backend.app.automation import triggers

    conn = _connect()
    try:
        if args.action == "list":
            items = svc.list_records(conn, args.patient_id, kind=args.kind)
            _print({"count": len(items), "items": items})
        elif args.action == "add":
            payload = {
                "kind": args.kind,
                "value": args.value,
                "recorded_at": args.at,
                "note": args.note,
                "payload": json.loads(args.payload) if args.payload else {},
            }
            record = svc.add_record(conn, args.patient_id, payload)
            result = {"record": record}
            if args.trigger and not record.get("duplicate"):
                result["automation"] = triggers.after_records(conn, args.patient_id, [record])
            _print(result)
        elif args.action == "import":
            text = Path(args.file).read_text(encoding="utf-8")
            if args.file.lower().endswith(".json"):
                rows = json.loads(text)
                summary = svc.import_records(conn, args.patient_id, json_rows=rows, source="json_import")
            else:
                summary = svc.import_records(conn, args.patient_id, csv_text=text, source="csv_import")
            if args.trigger and summary["records"]:
                summary["automation"] = triggers.after_records(conn, args.patient_id, summary["records"])
            _print(summary)
    finally:
        conn.close()
    return 0


def cmd_event(args: argparse.Namespace) -> int:
    from backend.app.events.detector import detect_events, list_events

    conn = _connect()
    try:
        if args.action == "list":
            _print({"items": list_events(conn, args.patient_id, status=args.status)})
        else:
            _print(detect_events(conn, args.patient_id, trigger="cli_scan"))
    finally:
        conn.close()
    return 0


# ---------------------------------------------------------------- agent
def cmd_run(args: argparse.Namespace) -> int:
    from backend.app.agent.orchestrator import run_agent

    conn = _connect()
    try:
        result = run_agent(
            conn,
            args.patient_id,
            trigger_type=args.trigger_type,
            message=args.message,
            event_ids=args.event or None,
        )
        _print(result)
        print(f"\n[run_id] {result['run_id']}  [status] {result['status']}  [llm_mode] {result['llm_mode']}")
    finally:
        conn.close()
    return 0


def cmd_trace(args: argparse.Namespace) -> int:
    from backend.app.audit.trace import trace

    conn = _connect()
    try:
        _print(trace(conn, args.run_id))
    finally:
        conn.close()
    return 0


def cmd_tasks(args: argparse.Namespace) -> int:
    from backend.app.tasks import service as svc
    from backend.app.automation import triggers

    conn = _connect()
    try:
        if args.action == "list":
            _print({"items": svc.list_tasks(conn, args.patient_id, status=args.status)})
        elif args.action == "complete":
            task = svc.complete_task(conn, args.task_id, changed_by="patient")
            _print({"task": task, **triggers.after_task_completed(conn, task)})
        elif args.action == "reschedule":
            task = svc.reschedule_task(conn, args.task_id, due_at=args.due_at, reason=args.reason)
            _print({"task": task, "versions": svc.versions(conn, args.task_id)})
        elif args.action == "show":
            _print({"task": svc.get_task(conn, args.task_id), "versions": svc.versions(conn, args.task_id)})
    finally:
        conn.close()
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    from backend.app.questioning import service as svc
    from backend.app.automation import triggers

    conn = _connect()
    try:
        if args.action == "list":
            _print({"items": svc.list_questions(conn, args.patient_id, status=args.status or None)})
        else:
            question = svc.answer_question(conn, args.question_id, answer_text=args.text)
            _print({"question": question, "resume": triggers.after_answer(conn, question)})
    finally:
        conn.close()
    return 0


def cmd_prefs(args: argparse.Namespace) -> int:
    from backend.app.memory import preferences as svc
    from backend.app.automation import triggers

    conn = _connect()
    try:
        if args.action == "list":
            _print({"items": svc.list_preferences(conn, args.patient_id, include_history=args.history)})
        elif args.action == "set":
            pref = svc.set_preference(conn, args.patient_id, kind=args.kind, value=args.value)
            _print({"preference": pref, "applied": triggers.after_preference_change(conn, args.patient_id)})
        else:
            _print(svc.clear_preference(conn, args.patient_id, args.kind))
    finally:
        conn.close()
    return 0


def cmd_knowledge(args: argparse.Namespace) -> int:
    from backend.app.knowledge import search as svc
    from backend.app.knowledge.index import documents, ensure_index

    conn = _connect()
    try:
        if args.action == "list":
            ensure_index(conn)
            _print({"items": documents(conn)})
        else:
            ensure_index(conn)
            _print(svc.search(conn, args.query, top_k=args.top_k))
    finally:
        conn.close()
    return 0


def cmd_reviews(args: argparse.Namespace) -> int:
    from backend.app.reviews import service as svc
    from backend.app.automation import scheduler

    conn = _connect()
    try:
        if args.action == "list":
            _print({"items": svc.list_reviews(conn, args.patient_id, status=args.status)})
        elif args.action == "evaluate":
            _print(svc.evaluate_review(conn, args.review_id))
        elif args.action == "resolve":
            _print(svc.resolve_human_review(conn, args.review_id, decision=args.decision, note=args.note or ""))
        else:
            _print(scheduler.tick(conn))
    finally:
        conn.close()
    return 0


def cmd_notify(args: argparse.Namespace) -> int:
    from backend.app.services import notifications as svc

    conn = _connect()
    try:
        if args.action == "list":
            _print({"items": svc.list_notifications(conn, args.patient_id, status=args.status)})
        else:
            _print(svc.mark_read(conn, args.notification_id))
    finally:
        conn.close()
    return 0


def cmd_automation(args: argparse.Namespace) -> int:
    from backend.app.automation import scheduler

    conn = _connect()
    try:
        if args.action == "tick":
            if args.advance:
                advance_clock(conn, args.advance)
            result = scheduler.tick(conn)
            result["clock_offset_seconds"] = clock_offset(conn)
            result["now"] = iso(now(conn))
            _print(result)
        else:
            rows = conn.execute(
                "SELECT * FROM automation_jobs ORDER BY run_at DESC LIMIT ?", (args.limit,)
            ).fetchall()
            _print({"items": [dict(r) for r in rows]})
    finally:
        conn.close()
    return 0


def cmd_clock(args: argparse.Namespace) -> int:
    conn = _connect()
    try:
        if args.reset:
            reset_clock(conn)
            _print({"clock_offset_seconds": 0, "now": iso(now(conn))})
        else:
            _print(
                {
                    "clock_offset_seconds": advance_clock(conn, args.advance),
                    "now": iso(now(conn)),
                }
            )
    finally:
        conn.close()
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    from scripts.reset_demo import seed

    conn = _connect()
    try:
        if args.action == "reset":
            _print(seed(conn, keep=False))
        else:
            _print(seed(conn, keep=True))
    finally:
        conn.close()
    return 0


def cmd_health(args: argparse.Namespace) -> int:
    from backend.app.config import settings
    from backend.app.services import patients as svc

    conn = _connect()
    try:
        db_ok = conn.execute("SELECT 1").fetchone() is not None
        mode = settings().llm_mode
        try:
            from backend.app.agent.llm import get_llm

            mode = get_llm().mode
        except Exception as exc:
            mode = f"{mode}_misconfigured: {exc}"
        _print(
            {
                "status": "ok" if db_ok else "degraded",
                "version": __version__,
                "db": str(settings().db_path),
                "llm_mode": mode,
                "patients": len(svc.list_patients(conn)),
            }
        )
    finally:
        conn.close()
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("backend.app.main:app", host=args.host, port=args.port, reload=False)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="diabetes-agent",
        description="糖衡智管 Agent CLI（演示作品，不提供诊断或用药建议）",
    )
    parser.add_argument("--version", action="version", version=f"diabetes-agent {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("version", help="显示版本").set_defaults(func=lambda a: (print(__version__), 0)[1])
    sub.add_parser("health", help="健康检查（数据库 + 模式）").set_defaults(func=cmd_health)

    p_patient = sub.add_parser("patient", help="患者与状态")
    p_patient.add_argument("action", choices=["list", "show", "state"])
    p_patient.add_argument("patient_id", nargs="?")
    p_patient.set_defaults(func=cmd_patient)

    p_record = sub.add_parser("record", help="健康记录")
    p_record.add_argument("action", choices=["list", "add", "import"])
    p_record.add_argument("patient_id")
    p_record.add_argument("kind", nargs="?")
    p_record.add_argument("value", nargs="?", type=float)
    p_record.add_argument("--at", help="记录时间 ISO8601")
    p_record.add_argument("--note")
    p_record.add_argument("--payload", help="JSON 字符串")
    p_record.add_argument("--file", help="CSV/JSON 文件路径")
    p_record.add_argument("--no-trigger", dest="trigger", action="store_false", help="不自动触发 Agent")
    p_record.set_defaults(func=cmd_record, trigger=True)

    p_event = sub.add_parser("event", help="健康事件")
    p_event.add_argument("action", choices=["list", "scan"])
    p_event.add_argument("patient_id")
    p_event.add_argument("--status")
    p_event.set_defaults(func=cmd_event)

    p_run = sub.add_parser("run", help="运行 Agent")
    p_run.add_argument("patient_id")
    p_run.add_argument("--message", help="患者输入")
    p_run.add_argument("--event", action="append", help="只处理指定事件 ID")
    p_run.add_argument("--trigger-type", default="user_request")
    p_run.set_defaults(func=cmd_run)

    p_trace = sub.add_parser("trace", help="查看运行轨迹")
    p_trace.add_argument("run_id")
    p_trace.set_defaults(func=cmd_trace)

    p_tasks = sub.add_parser("task", help="任务")
    p_tasks.add_argument("action", choices=["list", "show", "complete", "reschedule"])
    p_tasks.add_argument("patient_id", nargs="?")
    p_tasks.add_argument("task_id", nargs="?")
    p_tasks.add_argument("--status")
    p_tasks.add_argument("--due-at")
    p_tasks.add_argument("--reason", default="患者申请调整时间")
    p_tasks.set_defaults(func=cmd_tasks)

    p_ask = sub.add_parser("ask", help="主动询问")
    p_ask.add_argument("action", choices=["list", "answer"])
    p_ask.add_argument("patient_id", nargs="?")
    p_ask.add_argument("question_id", nargs="?")
    p_ask.add_argument("--text")
    p_ask.add_argument("--status")
    p_ask.set_defaults(func=cmd_ask)

    p_pref = sub.add_parser("pref", help="长期偏好")
    p_pref.add_argument("action", choices=["list", "set", "clear"])
    p_pref.add_argument("patient_id")
    p_pref.add_argument("--kind")
    p_pref.add_argument("--value")
    p_pref.add_argument("--history", action="store_true")
    p_pref.set_defaults(func=cmd_prefs)

    p_kn = sub.add_parser("knowledge", help="知识检索")
    p_kn.add_argument("action", choices=["list", "search"])
    p_kn.add_argument("query", nargs="?")
    p_kn.add_argument("--top-k", type=int, default=4)
    p_kn.set_defaults(func=cmd_knowledge)

    p_rev = sub.add_parser("review", help="复评")
    p_rev.add_argument("action", choices=["list", "evaluate", "resolve", "tick"])
    p_rev.add_argument("patient_id", nargs="?")
    p_rev.add_argument("review_id", nargs="?")
    p_rev.add_argument("--status")
    p_rev.add_argument("--decision", default="已电话随访")
    p_rev.add_argument("--note")
    p_rev.set_defaults(func=cmd_reviews)

    p_ntf = sub.add_parser("notify", help="站内提醒")
    p_ntf.add_argument("action", choices=["list", "read"])
    p_ntf.add_argument("patient_id", nargs="?")
    p_ntf.add_argument("notification_id", nargs="?")
    p_ntf.add_argument("--status")
    p_ntf.set_defaults(func=cmd_notify)

    p_auto = sub.add_parser("automation", help="自动调度")
    p_auto.add_argument("action", choices=["tick", "jobs"])
    p_auto.add_argument("--advance", type=int, default=0, help="先推进演示时钟（秒）")
    p_auto.add_argument("--limit", type=int, default=20)
    p_auto.set_defaults(func=cmd_automation)

    p_clock = sub.add_parser("clock", help="演示时钟")
    p_clock.add_argument("--advance", type=int, default=0)
    p_clock.add_argument("--reset", action="store_true")
    p_clock.set_defaults(func=cmd_clock)

    p_demo = sub.add_parser("demo", help="演示数据")
    p_demo.add_argument("action", choices=["reset", "seed"])
    p_demo.set_defaults(func=cmd_demo)

    p_serve = sub.add_parser("serve", help="启动 HTTP API")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
