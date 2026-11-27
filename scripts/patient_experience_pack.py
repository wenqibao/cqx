"""导出、恢复和核对患者体验数据；不运行 Agent、不覆盖已有数据库。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_PACK = ROOT / "data" / "patient_experience_pack" / "snapshot.json"
TABLES = (
    "patients", "health_records", "state_snapshots", "events", "agent_runs",
    "agent_steps", "tasks", "task_versions", "questions", "reviews",
    "preferences", "evidence_items", "notifications", "automation_jobs",
    "automation_outbox", "audit_log",
)
MARKER = "patient_experience_pack_sha256"


def digest(tables: dict[str, Any]) -> str:
    raw = json.dumps(tables, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def table_rows(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    # 表名只来自固定白名单，不执行数据包提供的 SQL。
    return {name: [dict(row) for row in conn.execute(f'SELECT * FROM "{name}" ORDER BY id')]
            for name in TABLES}


def validate(pack: dict[str, Any]) -> None:
    from backend.app.db.migrations import SCHEMA_VERSION

    if pack.get("format") != "patient-experience-pack-v1" or pack.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("数据包格式或结构版本不兼容")
    tables = pack.get("tables", {})
    if set(tables) != set(TABLES) or any(not isinstance(v, list) for v in tables.values()):
        raise ValueError("数据表清单不完整或包含未知表")
    if pack.get("sha256") != digest(tables):
        raise ValueError("数据包校验和不一致")
    if pack.get("counts") != {k: len(v) for k, v in tables.items()}:
        raise ValueError("数据包数量清单不一致")
    patients = tables["patients"]
    if not patients or any(p.get("is_synthetic") != 1 for p in patients):
        raise ValueError("患者属性不符合项目数据边界")
    patient_ids = {p["id"] for p in patients}
    for rows in tables.values():
        for row in rows:
            if not isinstance(row, dict) or any(not isinstance(v, (str, int, float, type(None))) for v in row.values()):
                raise ValueError("数据行必须使用数据库标量值")
            if row.get("patient_id") and row["patient_id"] not in patient_ids:
                raise ValueError("数据行引用了包外患者")


def read_pack(path: Path = DEFAULT_PACK) -> dict[str, Any]:
    pack = json.loads(path.read_text(encoding="utf-8"))
    validate(pack)
    return pack


def export_pack(source: Path, output: Path = DEFAULT_PACK) -> dict[str, Any]:
    from backend.app.db.migrations import SCHEMA_VERSION

    conn = readonly(source)
    try:
        conn.execute("BEGIN")  # 同一次只读事务取得一致快照，兼容运行中的 WAL 库。
        version = conn.execute("SELECT value FROM app_meta WHERE key='schema_version'").fetchone()
        if version is None or int(version[0]) != SCHEMA_VERSION:
            raise ValueError("来源库结构版本不兼容")
        if conn.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("来源库外键检查失败")
        tables = table_rows(conn)
    finally:
        conn.close()
    pack = {
        "format": "patient-experience-pack-v1", "schema_version": SCHEMA_VERSION,
        "backend_tag": "v0.3.7", "backend_commit": "40aa6bf4eebb2f7c18cb2bcbee92db5c82820ed2",
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "counts": {name: len(rows) for name, rows in tables.items()},
        "sha256": digest(tables), "tables": tables,
    }
    validate(pack)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {k: v for k, v in pack.items() if k != "tables"}


def restore(target: Path, pack_path: Path = DEFAULT_PACK) -> dict[str, Any]:
    pack = read_pack(pack_path)
    target = target.resolve()
    if target.exists():
        conn = readonly(target)
        try:
            try:
                row = conn.execute("SELECT value FROM app_meta WHERE key=?", (MARKER,)).fetchone()
            except sqlite3.DatabaseError:
                row = None
            if row and row[0] == pack["sha256"]:
                return {"status": "already_imported", "database": str(target),
                        "message": "保留当前体验进度，不重置数据"}
        finally:
            conn.close()
        raise FileExistsError("目标数据库已存在，未修改；请使用新的 --db 路径")

    from backend.app.db.connection import connect, set_meta, transaction
    from backend.app.knowledge.index import ensure_index

    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=target.name + ".import-", suffix=".tmp", dir=target.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    conn = None
    try:
        conn = connect(temporary)
        with transaction(conn):
            # 知识索引从当前检出的 knowledge/ 重建，不携带其他机器的运行配置。
            ensure_index(conn)
            for name in TABLES:
                columns = [r["name"] for r in conn.execute(f'PRAGMA table_info("{name}")')]
                rows = pack["tables"][name]
                if any(set(row) != set(columns) for row in rows):
                    raise ValueError(f"{name} 字段与冻结版本不一致")
                names = ",".join(f'"{c}"' for c in columns)
                placeholders = ",".join("?" for _ in columns)
                conn.executemany(f'INSERT INTO "{name}" ({names}) VALUES ({placeholders})',
                                 [[row[c] for c in columns] for row in rows])
            if conn.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("恢复后的外键检查失败")
            missing = conn.execute(
                "SELECT COUNT(*) FROM evidence_items e LEFT JOIN knowledge_chunks k ON k.id=e.chunk_id "
                "WHERE k.id IS NULL OR k.doc_id<>e.doc_id"
            ).fetchone()[0]
            if missing:
                raise ValueError("知识引用与当前知识包不一致")
            set_meta(conn, MARKER, pack["sha256"])
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
        conn = None
        # 在同目录发布完整文件，目标已存在时硬链接会失败，不覆盖并发创建的数据。
        os.link(temporary, target)
    finally:
        if conn is not None:
            conn.close()
        for suffix in ("", "-wal", "-shm"):
            Path(str(temporary) + suffix).unlink(missing_ok=True)
    return {"status": "imported", "database": str(target), "counts": pack["counts"], "sha256": pack["sha256"]}


def verify(target: Path, pack_path: Path = DEFAULT_PACK) -> dict[str, Any]:
    pack = read_pack(pack_path)
    conn = readonly(target)
    try:
        actual = table_rows(conn)
        same = digest(actual) == pack["sha256"]
        foreign_keys_ok = not conn.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        conn.close()
    if not same or not foreign_keys_ok:
        raise ValueError("数据库已与初始数据包不同；已有体验操作不会被自动覆盖")
    return {"status": "verified", "counts": {k: len(v) for k, v in actual.items()}, "sha256": pack["sha256"]}


def main() -> int:
    parser = argparse.ArgumentParser(description="患者体验数据包导出、恢复与核对")
    parser.add_argument("action", choices=("export", "restore", "verify"))
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--db", type=Path, required=True, help="明确指定来源库或新的目标库")
    args = parser.parse_args()
    try:
        result = {"export": export_pack, "restore": restore, "verify": verify}[args.action](args.db, args.pack)
    except (ValueError, OSError, sqlite3.DatabaseError) as exc:
        print(f"失败：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
