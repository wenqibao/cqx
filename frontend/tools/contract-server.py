"""v0.2.1 前端契约验收专用服务。实际 FastAPI/SQLite + 明示脚本模型与一次性故障。

不新增业务端点，不修改后端源码，不访问厂商模型。只允许新的隔离数据库。
python tools/contract-server.py --backend-root <v0.2.1源码目录> --port 8037
"""
import argparse
import json
import os
import sys
import time
from datetime import timedelta
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--backend-root", type=Path, required=True)
parser.add_argument("--port", type=int, default=8037)
args = parser.parse_args()
root = args.backend_root.resolve()
runtime = Path(__file__).resolve().parents[1] / ".runtime/v021"
db = root / "frontend/.runtime/workbench-test.db"
if db.exists():
    raise SystemExit("请使用新的源码快照/隔离库，本脚本不覆盖已有数据")
sys.path.insert(0, str(root))
os.environ.update(DIABETES_DB_PATH=str(db), AGENT_LLM_MODE="mock", AGENT_LLM_API_KEY="",
                  AUTOMATION_ENABLED="0", AUTOMATION_POLL_SECONDS="0", FRONTEND_ORIGIN="http://127.0.0.1:5187")

from backend.app.agent import orchestrator
from backend.app.agent.llm import LLMResponse, ToolCall
from backend.app.automation import triggers
from backend.app.db.connection import connect, iso, now
from backend.app.questioning import service as questions
from backend.app.services import patients
from backend.app.tasks import service as tasks
from scripts.reset_demo import seed

conn = connect(db)
seed(conn)
fixture = {}
for key in ("warning", "record", "preference", "task", "expired", "expiry_race", "slow", "answer"):
    pid = f"CT021-{key}"
    patients.create_patient(conn, {"id": pid, "name": f"契约{key}（虚构）", "age": 55})
    fixture[key] = pid
due = iso(now(conn) + timedelta(days=1))
task, _ = tasks.create_task(conn, fixture["task"], task_type="record_glucose", title="核实记录", due_at=due)
fixture["task_id"] = task["id"]
for key in ("expired", "answer", "expiry_race"):
    q, _ = questions.create_question(conn, fixture[key], question="请核实最近一次是否按时服药？",
                                     target_field="medication_taken", options=["已按时完成", "记不清"],
                                     ttl_hours=-1 if key == "expired" else 1 if key == "expiry_race" else 72)
    fixture[key + "_question"] = q["id"]
# 两个明确前置：打开前已 expired，以及打开时 waiting、提交前才过期。
questions.expire_stale(conn)
first, _ = tasks.create_task(conn, fixture["warning"], task_type="record_glucose", title="核实血糖记录", due_at=due, schedule_review=False)
tasks.create_task(conn, fixture["warning"], task_type="record_activity", title="核实活动记录", due_at=due, schedule_review=False)

class Scripted:
    mode = "real"
    model_name = "contract-scripted-no-provider"

    def __init__(self):
        self.calls = 0

    def plan_actions(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(content="", tool_calls=[ToolCall("schedule_review", {"patient_id": fixture["warning"], "delay_hours": 24}, "c1")], raw={})
        if self.calls == 2:
            return LLMResponse(content="", tool_calls=[ToolCall("schedule_review", {"patient_id": fixture["warning"], "delay_hours": 24, "task_id": first["id"]}, "c2")], raw={})
        return LLMResponse(content="已安排复评。", tool_calls=[], raw={})

result = orchestrator.run_agent(conn, fixture["warning"], trigger_type="user_request", message="安排复评", llm=Scripted())
assert result["status"] == "completed" and result["warnings"], result
fixture["warning_run"] = result["run_id"]
conn.commit()
conn.close()

# 一次失败后恢复实际函数，tick 走真实 outbox 补偿。仅作用于上述专用患者。
def inject_once(name, patient_id, identify):
    original = getattr(triggers, name)
    failed = False
    def wrapped(*values, **kwargs):
        nonlocal failed
        if identify(values) == patient_id and not failed:
            failed = True
            raise RuntimeError("contract-test injected side-effect failure")
        return original(*values, **kwargs)
    setattr(triggers, name, wrapped)

inject_once("after_records", fixture["record"], lambda v: v[1])
inject_once("after_preference_change", fixture["preference"], lambda v: v[1])
inject_once("after_task_completed", fixture["task"], lambda v: v[1]["patient_id"])
original_records = triggers.after_records
def delayed_records(*values, **kwargs):
    if values[1] == fixture["slow"]:
        time.sleep(18)
    return original_records(*values, **kwargs)
triggers.after_records = delayed_records

runtime.mkdir(parents=True, exist_ok=True)
(runtime / "fixtures.json").write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
import uvicorn
uvicorn.run("backend.app.main:app", host="127.0.0.1", port=args.port, access_log=False)
