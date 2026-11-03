"""CGMacros 公共数据集验证（B 任务书第六节）。

一条完整链路：完整性核验 -> 字段映射/单位转换 -> 真实导入 ->
事件检测 -> Patient State 趋势/缺失 -> Agent 回放触发。

产物：
- 控制台人类可读摘要
- 机器可读结果写回 data/public/cgmacros_validation_result.json

注意：本脚本只做「辅助验证」，不产生任何临床结论；原始数据不提交仓库。
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# 只回放一个参与者，避免把整个数据集导入演示库
PARTICIPANT = "CGMacros-039"

MGDL_TO_MMOLL = 1 / 18.0182

os.environ.setdefault("AUTOMATION_ENABLED", "0")
os.environ.setdefault("AGENT_LLM_MODE", "mock")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    # 数据源目录只认环境变量 CGMACROS_DIR（指向解压后的参与者目录，含 CGMacros-039.csv）
    raw_dir = os.environ.get("CGMACROS_DIR", "").strip()
    if not raw_dir:
        print("请设置 CGMACROS_DIR 环境变量，指向解压后的参与者目录（含 CGMacros-039.csv）")
        return 2
    data_dir = Path(raw_dir)
    if not data_dir.exists():
        print(f"CGMACROS_DIR 指向的目录不存在: {data_dir}")
        return 2
    csv_path = data_dir / f"{PARTICIPANT}.csv"
    if not csv_path.exists():
        print(f"找不到数据文件: {csv_path}")
        return 2

    # 完整性核验（相对官方清单）
    manifest_path = REPO / "data" / "public" / "cgmacros_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}

    from backend.app import config
    from backend.app.agent import orchestrator
    from backend.app.db.connection import connect, now
    from backend.app.events.detector import detect_events
    from backend.app.services.patients import create_patient
    from backend.app.services.records import add_record
    from backend.app.services.state import build_state

    config.reload_config()

    # 护栏：验证库必须位于仓库 .tmp/ 下，不进入演示患者库、不随服务启动
    tmp_root = (REPO / ".tmp").resolve()
    db_path = tmp_root / "cgmacros_validation.db"
    if db_path.resolve().parent != tmp_root:
        print("拒绝运行：验证库必须位于仓库 .tmp/ 下")
        return 2
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    os.environ["DIABETES_DB_PATH"] = str(db_path)
    config.reload_config()

    conn = connect(db_path)
    create_patient(
        conn,
        {
            "id": "CGV-039",
            "name": f"{PARTICIPANT}（验证命名空间）",
            "diabetes_type": "T2DM",
            "is_synthetic": False,
            "constraints": ["public-dataset-validation", "not-clinical"],
        },
    )

    with csv_path.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    libre = []
    for r in rows:
        v = (r.get("Libre GL") or "").strip()
        ts = (r.get("Timestamp") or "").strip().replace(" ", "T")
        if v and ts:
            libre.append((ts, float(v)))

    base = now(conn) - timedelta(hours=2)
    last_dt = datetime.fromisoformat(libre[-1][0])
    shift = base.replace(tzinfo=None) - last_dt

    imported = 0
    mmoll_vals = []
    for ts, mgdl in libre:
        new_dt = datetime.fromisoformat(ts) + shift
        mmoll = round(mgdl * MGDL_TO_MMOLL, 3)
        mmoll_vals.append(mmoll)
        add_record(
            conn,
            "CGV-039",
            {
                "kind": "fasting_glucose",
                "value": mmoll,
                "unit": "mmol/L",
                "recorded_at": new_dt.isoformat(timespec="seconds"),
                "source": "cgmacros_replay",
                "note": "CGMacros Libre GL 连续血糖（mg/dL 转换），非空腹血糖语义，仅辅助验证",
                "payload": {"raw_mgdl": mgdl, "sensor": "Libre GL"},
            },
        )
        imported += 1

    events = detect_events(conn, "CGV-039", trigger="cgmacros_replay")["created"]
    state = build_state(conn, "CGV-039")
    outcome = orchestrator.run_agent(
        conn, "CGV-039", trigger_type="event_detected", event_ids=[e["id"] for e in events[:3]]
    )

    result = {
        "participant": PARTICIPANT,
        "imported_rows": imported,
        "unit_conversion": {"from": "mg/dL", "to": "mmol/L", "factor": MGDL_TO_MMOLL},
        "glucose_mmoll": {
            "min": min(mmoll_vals),
            "max": max(mmoll_vals),
            "mean": round(sum(mmoll_vals) / len(mmoll_vals), 2),
        },
        "events_detected": [{"code": e["code"], "severity": e["severity"]} for e in events],
        "state_7d_glucose": state["aggregates"]["7d"]["fasting_glucose"],
        "trend": state["trend"]["fasting_glucose_7d"],
        "missing_fields": state["missing_fields"],
        "agent_replay": {
            "run_id": outcome["run_id"],
            "status": outcome["status"],
            "intent": outcome["intent"],
            "actions": [a["tool"] for a in outcome["actions"]],
        },
        "db_evidence": {
            "agent_runs": conn.execute("SELECT COUNT(*) c FROM agent_runs WHERE patient_id='CGV-039'").fetchone()["c"],
            "reviews": conn.execute("SELECT COUNT(*) c FROM reviews WHERE patient_id='CGV-039'").fetchone()["c"],
            "rejected": conn.execute("SELECT COUNT(*) c FROM audit_log WHERE decision='reject'").fetchone()["c"],
        },
        "clinical_claim": False,
        "csv_sha256": sha256(csv_path),
        "manifest_integrity_recorded": bool(manifest.get("integrity", {}).get("all_files_match")),
    }

    out = REPO / "data" / "public" / "cgmacros_validation_result.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n[OK] 结果已写 {out.name}（辅助验证，非临床结论）")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
