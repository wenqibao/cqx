"""SQLite 连接、初始化与时间工具。"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from backend.app.config import settings

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
CLOCK_KEY = "clock_offset_seconds"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None = None) -> str:
    dt = dt or utcnow()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else settings().db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False：FastAPI 会把同步依赖（get_conn）与同步路由分别交给
    # 线程池的不同线程执行，连接必然跨线程；每个请求持有独立连接，同一连接上的
    # 使用是"依赖进入 → 路由 → 依赖退出"的串行过程，因此关闭线程绑定是安全的。
    # 这是 C-API-001（并发 GET 触发 ProgrammingError）的修复点。
    conn = sqlite3.connect(path, timeout=30.0, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    # 并发写时等待锁而不是立刻抛 "database is locked"
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA synchronous = NORMAL")
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(sql)
    # 迁移只在版本落后时执行一次，普通连接不重复做破坏性 DDL
    from backend.app.db import migrations

    migrations.migrate(conn)


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


@contextmanager
def db_session(db_path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO app_meta(key, value, updated_at) VALUES(?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, value, iso()),
    )


def clock_offset(conn: sqlite3.Connection) -> int:
    raw = get_meta(conn, CLOCK_KEY, "0") or "0"
    try:
        return int(float(raw))
    except ValueError:
        return 0


def now(conn: sqlite3.Connection | None = None) -> datetime:
    """业务时间 = UTC now + 演示时钟偏移（测试可推进）。"""
    if conn is None:
        return utcnow()
    return utcnow() + timedelta(seconds=clock_offset(conn))


def advance_clock(conn: sqlite3.Connection, seconds: int) -> int:
    total = clock_offset(conn) + int(seconds)
    set_meta(conn, CLOCK_KEY, str(total))
    return total


def reset_clock(conn: sqlite3.Connection) -> None:
    set_meta(conn, CLOCK_KEY, "0")


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def loads(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default
