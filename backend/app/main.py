"""FastAPI 应用入口（F15/F18 的后端）。

启动：
    uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app import __version__
from backend.app.api import routes_agent, routes_ops, routes_patients
from backend.app.config import settings
from backend.app.db.connection import connect, iso, now

DESCRIPTION = """糖衡智管 - 单 Agent 稳定期 2 型糖尿病健康管理演示系统。

- 本系统是参赛演示作品，不是医疗器械软件，不提供诊断、处方或用药调整。
- 所有患者均为合成虚构病例（is_synthetic=true）。
- 运行模式（mock/real）在每个 Agent 运行记录中如实标注 llm_mode。
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = connect()
    try:
        from backend.app.knowledge.index import ensure_index

        ensure_index(conn)
    finally:
        conn.close()
    loop = None
    poll = settings().automation_poll_seconds
    if poll > 0 and os.environ.get("AUTOMATION_ENABLED", "1") != "0":
        from backend.app.automation.scheduler import AutomationLoop

        loop = AutomationLoop(str(settings().db_path), interval=poll)
        loop.start()
    app.state.automation_loop = loop
    yield
    if loop is not None:
        loop.stop()


def create_app() -> FastAPI:
    app = FastAPI(
        title="糖衡智管 Agent API",
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
    )
    allowed_origins = [settings().frontend_origin, "http://localhost:5173", "http://127.0.0.1:5173"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 兜底 500 处理器：Starlette 的 ServerErrorMiddleware 位于 CORS 之外，
    # 未捕获异常返回的 500 不带 CORS 头，浏览器会显示成"CORS 失败"（C-API-001 的次生现象）。
    # 这里显式回填该请求来源的 CORS 头，并返回结构化错误而不是空正文。
    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        headers: dict[str, str] = {}
        origin = request.headers.get("origin")
        if origin and origin in allowed_origins:
            headers["Access-Control-Allow-Origin"] = origin
            headers["Vary"] = "Origin"
            headers["Access-Control-Allow-Credentials"] = "true"
        return JSONResponse(
            status_code=500,
            content={"detail": "internal server error", "error": type(exc).__name__, "path": request.url.path},
            headers=headers,
        )

    @app.get("/api/health", tags=["system"], summary="真实健康检查（含数据库与模式）")
    def health() -> dict[str, Any]:
        db_ok = False
        db_error = None
        runtime_mode = settings().llm_mode
        try:
            conn = connect()
            try:
                conn.execute("SELECT 1").fetchone()
                db_ok = True
                from backend.app.agent.llm import get_llm

                try:
                    runtime_mode = get_llm().mode
                except Exception:
                    runtime_mode = f"{settings().llm_mode}_misconfigured"
            finally:
                conn.close()
        except Exception as exc:  # pragma: no cover - 数据库不可用
            db_error = str(exc)
        return {
            "status": "ok" if db_ok else "degraded",
            "service": "diabetes-agent",
            "version": __version__,
            "time": iso(now()),
            "database": {"ok": db_ok, "path": str(settings().db_path), "error": db_error},
            "llm_mode": runtime_mode,
            "disclaimer": "演示作品，不提供诊断或用药建议；患者均为合成虚构数据。",
        }

    @app.get("/api/version", tags=["system"], summary="版本信息")
    def version() -> dict[str, Any]:
        return {"name": "diabetes-agent", "version": __version__}

    app.include_router(routes_patients.router, prefix="/api")
    app.include_router(routes_agent.router, prefix="/api")
    app.include_router(routes_ops.router, prefix="/api")
    return app


app = create_app()
