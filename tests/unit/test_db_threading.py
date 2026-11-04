"""C-API-001 回归：连接必须是线程安全的。

FastAPI 会把同步依赖与同步路由分派到线程池的不同线程，SQLite 连接因此必然跨线程。
本测试直接在"另一个线程"里使用连接，复现最初的 `ProgrammingError`。
"""
from __future__ import annotations

import threading

from backend.app.db.connection import connect


def test_connection_usable_from_other_thread(conn):
    errors: list[BaseException] = []

    def use_from_worker() -> None:
        try:
            row = conn.execute("SELECT 1 AS ok").fetchone()
            assert row["ok"] == 1
        except BaseException as exc:  # 记录后由主线程断言，避免线程内断言丢失
            errors.append(exc)

    worker = threading.Thread(target=use_from_worker)
    worker.start()
    worker.join(timeout=10)
    assert not worker.is_alive()
    assert not errors, f"跨线程使用连接失败: {errors[0]!r}"


def test_pragmas_applied(db_path):
    conn = connect(db_path)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert int(conn.execute("PRAGMA busy_timeout").fetchone()[0]) == 30000
        assert int(conn.execute("PRAGMA foreign_keys").fetchone()[0]) == 1
    finally:
        conn.close()


def test_two_connections_can_be_used_concurrently(db_path):
    """不同请求各自持有一个连接；并发读写不应互相报错。"""
    first = connect(db_path)
    second = connect(db_path)
    errors: list[BaseException] = []

    def worker(conn, marker: str) -> None:
        try:
            for _ in range(20):
                conn.execute("SELECT ?", (marker,)).fetchone()
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(first, "a")),
        threading.Thread(target=worker, args=(second, "b")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    first.close()
    second.close()
    assert not errors, f"并发使用独立连接失败: {errors[0]!r}"
