"""加载随仓库交付的患者体验数据，并启动本机 API。"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="启动糖衡智管患者体验环境")
    parser.add_argument("--db", type=Path, default=ROOT / "data/runtime/patient-experience.db")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--automation", action="store_true", help="启用后台到期调度，可能触发配置的模型")
    args = parser.parse_args()
    os.environ["DIABETES_DB_PATH"] = str(args.db.resolve())
    os.environ["AUTOMATION_ENABLED"] = "1" if args.automation else "0"
    os.environ.setdefault("FRONTEND_ORIGIN", "http://127.0.0.1:5180")

    from scripts.patient_experience_pack import restore

    try:
        result = restore(args.db)
    except (ValueError, OSError) as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        return 1
    print(f"患者数据：{result['status']}；数据库：{args.db.resolve()}", flush=True)
    import uvicorn

    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
