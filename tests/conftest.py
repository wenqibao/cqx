"""测试基座：每个测试用独立临时数据库，禁用后台线程，保证可复现。

注意：不使用 pytest 的 tmp_path（它会创建/清理临时目录，在部分受限环境下会失败），
改为在仓库 .tmp/ 下创建唯一工作目录。
"""
from __future__ import annotations

import os
import shutil
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor"
for path in (str(ROOT), str(VENDOR)):
    if path not in sys.path:
        sys.path.insert(0, path)


@pytest.fixture()
def workdir():
    base = ROOT / ".tmp" / f"t-{uuid.uuid4().hex[:8]}"
    base.mkdir(parents=True, exist_ok=True)
    yield base
    shutil.rmtree(base, ignore_errors=True)


@pytest.fixture()
def db_path(workdir, monkeypatch):
    path = workdir / "test.db"
    monkeypatch.setenv("DIABETES_DB_PATH", str(path))
    monkeypatch.setenv("AUTOMATION_ENABLED", "0")
    monkeypatch.setenv("AGENT_LLM_MODE", "mock")
    from backend.app import config

    config.reload_config()
    yield path
    config.reload_config()


@pytest.fixture()
def conn(db_path):
    from backend.app.db.connection import connect

    connection = connect(db_path)
    yield connection
    connection.close()


@pytest.fixture()
def seeded(conn):
    from scripts.reset_demo import seed

    seed(conn)
    return conn


@pytest.fixture()
def client(db_path):
    from fastapi.testclient import TestClient

    from backend.app.main import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c
