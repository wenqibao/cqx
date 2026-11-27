"""比赛视频演示数据包导入程序（VIDEO-DEMO-DATA-PACK-V1）。

只负责把人工设计的患者档案与健康记录通过现有 HTTP API 导入后端，
不生成数据、不运行 Agent、不调用真实模型（mock 模式）。

用法：
  python evaluation/demo_pack/import_demo_pack.py --dry-run
  python evaluation/demo_pack/import_demo_pack.py --apply --confirm VIDEO-DEMO-20261110-V1
  python evaluation/demo_pack/import_demo_pack.py --verify-only
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

PACK_DIR = Path(__file__).resolve().parent
PATIENTS_DIR = PACK_DIR / "patients"
MANIFEST = PACK_DIR / "manifest.json"
BASE_URL = os.environ.get("DEMO_API_BASE", "http://127.0.0.1:8000/api").rstrip("/")
EXPECTED_DB_NAME = "diabetes_agent_video_demo.db"
PACK_VERSION = "VIDEO-DEMO-DATA-PACK-V1"
CONFIRM_TOKEN = "VIDEO-DEMO-20261110-V1"

# 合法记录类型与范围（与 backend/app/services/records.py 的 KIND_SPEC 保持一致）
KIND_SPEC = {
    "fasting_glucose": (2.0, 35.0, True),
    "postprandial_glucose": (2.0, 35.0, True),
    "steps": (0.0, 100000.0, True),
    "weight": (25.0, 300.0, True),
    "medication_taken": (0.0, 1.0, True),
    "symptom": (None, None, False),
    "meal": (None, None, False),
    "bp": (None, None, False),
}


def _iso(hours_ago: float) -> str:
    """hours_ago → 过去的 UTC ISO 时间。"""
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def _load_pack() -> list[dict]:
    files = sorted(PATIENTS_DIR.glob("*.json"))
    data = []
    for f in files:
        with open(f, encoding="utf-8") as fh:
            data.append(json.load(fh))
    return data


def _validate_pack(pack: list[dict]) -> list[str]:
    """dry-run 结构校验，返回错误列表。"""
    errors = []
    ids = set()
    for p in pack:
        patient = p.get("patient", {})
        pid = patient.get("id")
        if not pid:
            errors.append("存在缺少 patient.id 的文件")
            continue
        if pid in ids:
            errors.append(f"患者 ID 重复: {pid}")
        ids.add(pid)
        if not patient.get("is_synthetic"):
            errors.append(f"{pid}: is_synthetic 必须为 true")
        for r in p.get("records", []):
            kind = r.get("kind")
            if kind not in KIND_SPEC:
                errors.append(f"{pid}: 不支持的记录类型 {kind!r}")
                continue
            lo, hi, value_required = KIND_SPEC[kind]
            value = r.get("value")
            expected_failed = r.get("expected_failed", False)  # 预期坏行，不报结构错误
            if value_required and value is None:
                errors.append(f"{pid}: {kind} 需要数值")
            elif value_required and (lo is not None) and not (lo <= value <= hi) and not expected_failed:
                errors.append(f"{pid}: {kind} 值 {value} 超出范围 {lo}-{hi}")
            if kind == "bp":
                pl = r.get("payload") or {}
                if not (pl.get("systolic") and pl.get("diastolic")):
                    errors.append(f"{pid}: bp 需要 payload.systolic/diastolic")
            if kind == "symptom" and not (r.get("payload") or {}).get("text"):
                errors.append(f"{pid}: symptom 需要 payload.text")
            ha = r.get("hours_ago")
            if ha is None or ha < 0:
                errors.append(f"{pid}: hours_ago 必须为非负数")
    return errors


def _preflight() -> dict:
    """执行前安全检查，返回系统状态。"""
    c = httpx.Client(timeout=30, trust_env=False)
    health = c.get(f"{BASE_URL}/health").json()
    mode = c.get(f"{BASE_URL}/system/mode").json()
    db_path = (health.get("database") or {}).get("path", "")
    return {"health": health, "mode": mode, "db_path": db_path, "db_ok": EXPECTED_DB_NAME in db_path}


def _dry_run() -> int:
    pack = _load_pack()
    errors = _validate_pack(pack)
    if errors:
        print("✗ dry-run 校验失败:")
        for e in errors:
            print("  -", e)
        return 1
    total_records = sum(len(p["records"]) for p in pack)
    print(f"✓ dry-run 通过：{len(pack)} 个患者，{total_records} 条记录")
    for p in pack:
        print(f"  {p['patient']['id']}: {len(p['records'])} 条记录, "
              f"预期事件={p.get('expected_event_codes', [])}")
    return 0


def _apply() -> int:
    state = _preflight()
    if not state["db_ok"]:
        print(f"✗ 数据库路径不符合预期（需含 {EXPECTED_DB_NAME}）: {state['db_path']}")
        return 1
    if state["mode"].get("llm_mode") != "mock":
        print(f"✗ 当前模式非 mock（{state['mode'].get('llm_mode')}），拒绝导入以避免调用真实模型")
        return 1

    c = httpx.Client(timeout=120, trust_env=False)
    pack = _load_pack()
    report = {"pack_version": PACK_VERSION, "git_sha": "", "db_path": state["db_path"],
              "patients": {}, "imported_at": datetime.now(timezone.utc).isoformat()}

    for p in pack:
        patient = p["patient"]
        pid = patient["id"]
        # 检查是否已存在
        exists = c.get(f"{BASE_URL}/patients/{pid}").status_code == 200
        if exists:
            print(f"✗ 患者 {pid} 已存在，停止（不覆盖原档案）")
            return 1
        r = c.post(f"{BASE_URL}/patients", json=patient)
        if r.status_code not in (200, 201):
            print(f"✗ 创建患者 {pid} 失败: {r.status_code} {r.text[:200]}")
            return 1

        # 导入记录（json_rows + trigger_agent=false）
        json_rows = []
        for rec in p["records"]:
            row = {"kind": rec["kind"], "value": rec["value"],
                   "recorded_at": _iso(rec["hours_ago"]), "note": rec.get("note", "")}
            if rec.get("payload"):
                row["payload"] = rec["payload"]
            json_rows.append(row)
        rr = c.post(f"{BASE_URL}/patients/{pid}/records/import",
                    json={"json_rows": json_rows, "trigger_agent": False})
        if rr.status_code != 200:
            print(f"✗ 导入记录 {pid} 失败: {rr.status_code} {rr.text[:200]}")
            return 1
        imp = rr.json()
        # 事件检测（不运行 Agent）
        c.post(f"{BASE_URL}/patients/{pid}/events/scan")
        ev = c.get(f"{BASE_URL}/patients/{pid}/events").json()
        report["patients"][pid] = {
            "records": imp.get("records", 0),
            "duplicates": imp.get("duplicates", 0),
            "failed": imp.get("failed", 0),
            "events": [e["code"] for e in ev.get("items", [])],
        }
        print(f"  {pid}: 导入 {imp.get('records', 0)} 条, 去重 {imp.get('duplicates', 0)}, "
              f"失败 {imp.get('failed', 0)}, 事件 {[e['code'] for e in ev.get('items', [])]}")

    out = PACK_DIR.parent.parent / ".tmp" / "demo_pack_import_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n✓ 导入完成，报告: {out}")
    return 0


def _verify_only() -> int:
    c = httpx.Client(timeout=30, trust_env=False)
    pack = _load_pack()
    print("只读核验（不写库）:")
    for p in pack:
        pid = p["patient"]["id"]
        pr = c.get(f"{BASE_URL}/patients/{pid}")
        if pr.status_code != 200:
            print(f"  ✗ {pid}: 患者不存在")
            continue
        pat = pr.json()
        recs = c.get(f"{BASE_URL}/patients/{pid}/records").json()
        runs = c.get(f"{BASE_URL}/patients/{pid}/runs").json()
        ev = c.get(f"{BASE_URL}/patients/{pid}/events").json()
        print(f"  {pid}: 记录 {len(recs.get('items', []))} 条, "
              f"运行 {len(runs.get('items', []))} 个, 事件 {[e['code'] for e in ev.get('items', [])]}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--confirm")
    ap.add_argument("--verify-only", action="store_true")
    args = ap.parse_args()

    if args.dry_run:
        return _dry_run()
    if args.apply:
        if args.confirm != CONFIRM_TOKEN:
            print(f"✗ 需要 --confirm {CONFIRM_TOKEN}")
            return 1
        return _apply()
    if args.verify_only:
        return _verify_only()
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
