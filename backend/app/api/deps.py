"""FastAPI 依赖：每个请求一个 SQLite 连接（WAL，串行写）。"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator

from fastapi import HTTPException

from backend.app.db.connection import connect
from backend.app.services.patients import PatientNotFound


def get_conn() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def not_found(exc: Exception) -> HTTPException:
    if isinstance(exc, PatientNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=404, detail=str(exc))
