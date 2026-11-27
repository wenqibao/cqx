"""在已有视频演示库中补充周承安的步数缺失复评。"""

from __future__ import annotations

import argparse
from contextlib import closing
from datetime import timedelta
import json
from pathlib import Path
import sqlite3

from backend.app.db.connection import connect, iso, now, transaction
from backend.app.reviews import service as reviews
from backend.app.services.state import build_state
from backend.app.tasks import service as tasks

PATIENT_ID = "VDEMO-104"
PATIENT_NAMES = {"周承安", "视频演示病例04（虚构）"}
CASE = "zhou-missing-steps-review"


def add_review(db: Path) -> dict:
    db = db.resolve(strict=True)
    with closing(sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)) as source:
        patient = source.execute(
            "SELECT name, is_synthetic FROM patients WHERE id=?", (PATIENT_ID,)
        ).fetchone()
        if not patient or patient[0] not in PATIENT_NAMES or patient[1] != 1:
            raise ValueError("目标库缺少数据包中的合成患者 VDEMO-104。")
        if source.execute("SELECT 1 FROM patients WHERE is_synthetic IS NOT 1 LIMIT 1").fetchone():
            raise ValueError("目标库必须仅包含合成患者。")

    with closing(connect(db)) as conn, transaction(conn):
        current_reviews = reviews.list_reviews(conn, PATIENT_ID)
        for task in tasks.list_tasks(conn, PATIENT_ID):
            if task["meta"].get("demo_case") == CASE:
                existing = next(
                    (
                        review for review in current_reviews
                        if review["task_id"] == task["id"] and review["branch"] == "MISSING_DATA"
                    ),
                    None,
                )
                if existing is None:
                    raise ValueError("找到演示任务，但缺少对应的缺失数据复评。")
                return existing
        if "steps" not in build_state(conn, PATIENT_ID)["missing_fields"]:
            raise ValueError("VDEMO-104 已有近期步数记录，无法复现步数缺失。")

        task, _ = tasks.create_task(
            conn,
            PATIENT_ID,
            task_type="record_activity",
            title="补充近期活动步数",
            description="复评需要近期步数记录，请补录已有数据。",
            due_at=iso(now(conn) + timedelta(days=1)),
            required_fields=["steps"],
            meta={"demo_case": CASE},
            merge=False,
            schedule_review=False,
        )
        scheduled = reviews.schedule_review(
            conn, PATIENT_ID, task_id=task["id"], reason="核对活动记录是否齐备"
        )
        result = reviews.evaluate_review(conn, scheduled["id"], closer="staff_demo")
        if result["branch"] != "MISSING_DATA" or result["detail"]["missing_required_fields"] != ["steps"]:
            raise ValueError("未得到步数缺失复评，变更已回滚。")
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="已有合成视频演示库路径")
    args = parser.parse_args()
    try:
        result = add_review(args.db)
    except (OSError, sqlite3.Error, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
