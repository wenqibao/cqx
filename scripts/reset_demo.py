# -*- coding: utf-8 -*-
"""演示数据重置：重建数据库、写入 3 个虚构患者与近 7 天记录、建立知识索引。

用法：
    python scripts/reset_demo.py            # 重置并写入演示数据
    python scripts/reset_demo.py --keep     # 只补建缺失患者，不动已有数据
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.config import DEMO_DIR, settings  # noqa: E402
from backend.app.db.connection import connect, iso, now  # noqa: E402
from backend.app.knowledge.index import ensure_index  # noqa: E402
from backend.app.services.patients import create_patient, get_patient_or_none  # noqa: E402
from backend.app.services.records import add_record  # noqa: E402


def seed(conn, keep: bool = False) -> dict:
    seeded = []
    for path in sorted(DEMO_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        patient = payload["patient"]
        if keep and get_patient_or_none(conn, patient["id"]):
            seeded.append({"patient": patient["id"], "skipped": True})
            continue
        if not get_patient_or_none(conn, patient["id"]):
            create_patient(conn, patient)
        base = now(conn)
        count = 0
        for record in payload.get("records", []):
            offset = record.get("recorded_at_offset_hours", 0)
            data = {
                "kind": record["kind"],
                "value": record.get("value"),
                "recorded_at": iso(base + timedelta(hours=offset)),
                "source": "demo",
                "payload": record.get("payload") or {},
                "note": record.get("note"),
            }
            created = add_record(conn, patient["id"], data)
            count += 0 if created.get("duplicate") else 1
        seeded.append({"patient": patient["id"], "records": count, "skipped": False})
    index = ensure_index(conn, force=True)
    return {"db": str(settings().db_path), "patients": seeded, "knowledge": index}


def main() -> int:
    parser = argparse.ArgumentParser(description="重置糖衡智管演示数据")
    parser.add_argument("--keep", action="store_true", help="保留现有数据，只补建缺失患者")
    args = parser.parse_args()

    db_path = settings().db_path
    if not args.keep and db_path.exists():
        for suffix in ("", "-wal", "-shm"):
            f = Path(str(db_path) + suffix)
            if f.exists():
                f.unlink()
    conn = connect(db_path)
    try:
        summary = seed(conn, keep=args.keep)
    finally:
        conn.close()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
