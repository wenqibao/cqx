"""C-API-001 端到端回归：真实 uvicorn + 并发 HTTP 请求。

TestClient 是串行调用，无法暴露"依赖与路由跑在不同线程池线程"的问题；
必须起真实 ASGI 服务器并同时发多个请求。
"""
from __future__ import annotations

import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture()
def live_server(db_path):
    """在后台线程里跑真实 uvicorn，返回 (base_url, seed_conn)。"""
    import uvicorn

    from backend.app.main import create_app
    from scripts.reset_demo import seed
    from backend.app.db.connection import connect

    conn = connect(db_path)
    seed(conn)
    conn.close()

    port = _free_port()
    app = create_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", lifespan="on")
    server = uvicorn.Server(config)
    # 在非主线程中无法安装信号处理器
    server.install_signal_handlers = lambda: None  # type: ignore[assignment]

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 20
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("uvicorn 未能在 20 秒内启动")
    try:
        yield f"http://127.0.0.1:{port}/api"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_concurrent_reads_return_200(live_server):
    """C 的原始场景：state / tasks / runs 各 3 次并发，9/9 必须 200。"""
    base = live_server
    paths = ["/patients/P001/state", "/patients/P001/tasks", "/patients/P001/runs"] * 3

    def fetch(path: str) -> int:
        with httpx.Client(timeout=30) as client:
            return client.get(base + path).status_code

    with ThreadPoolExecutor(max_workers=9) as pool:
        codes = list(pool.map(fetch, paths))

    assert codes.count(200) == 9, f"并发读失败: {codes}"


def test_concurrent_writes_do_not_lock(live_server):
    """并发写不应出现 database is locked；每条记录都必须真实落库。"""
    base = live_server

    def post(value: float) -> int:
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                base + "/patients/P002/records",
                json={"kind": "fasting_glucose", "value": value, "trigger_agent": False},
            )
            return resp.status_code

    with ThreadPoolExecutor(max_workers=6) as pool:
        codes = list(pool.map(post, [6.1, 6.2, 6.3, 6.4, 6.5, 6.6]))

    assert codes.count(201) == 6, f"并发写失败: {codes}"

    with httpx.Client(timeout=30) as client:
        total = client.get(base + "/patients/P002/records").json()["count"]
    assert total >= 6


def test_error_response_keeps_cors_headers(live_server):
    """兜底 500 也必须带 CORS 头，否则浏览器会把后端错误显示成 CORS 失败。"""
    base = live_server
    with httpx.Client(timeout=30) as client:
        resp = client.get(base + "/runs/RUN-does-not-exist", headers={"Origin": "http://127.0.0.1:5173"})
    # 该路径本身返回 404；这里验证的是"任何非 2xx 也带 CORS 头"
    assert resp.status_code in (404, 500)
    assert resp.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"
def test_unhandled_error_returns_json_with_cors(monkeypatch):
    """兜底处理器必须把 500 变成带 CORS 头的结构化错误（不是空正文）。"""
    from fastapi.testclient import TestClient

    from backend.app.main import create_app
    from backend.app.services import patients as patient_service

    def boom(*args, **kwargs):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(patient_service, "list_patients", boom)
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/patients", headers={"Origin": "http://127.0.0.1:5173"})
    assert resp.status_code == 500
    body = resp.json()
    assert body["detail"] == "internal server error"
    assert body["error"] == "RuntimeError"
    assert resp.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"