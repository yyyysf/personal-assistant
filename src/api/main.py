"""FastAPI 应用入口。

本地启动：uvicorn src.api.main:app --reload
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from src.api.routes import api_v1, dashboard, learning, news, reading, research, todo, travel
from src.core.config import BASE_DIR, settings
from src.core.db import init_db
from src.core.logging import get_logger, setup_logging
from src.mcp_host.manager import mcp_host
from src.scheduler.runner import shutdown_scheduler, start_scheduler

setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("启动 %s（%s）", settings.app_name, settings.app_env)
    init_db()
    start_scheduler()
    yield
    shutdown_scheduler()
    mcp_host.stop_all()
    logger.info("应用已关闭")


app = FastAPI(
    title=settings.app_name,
    description="私人网页智能助手：科研、学习、阅读、资讯、旅游与任务管理",
    version="0.1.0",
    debug=settings.debug,
    lifespan=lifespan,
)

static_dir = Path(BASE_DIR) / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

app.include_router(dashboard.router)
app.include_router(todo.router)
app.include_router(research.router)
app.include_router(reading.router)
app.include_router(news.router)
app.include_router(learning.router)
app.include_router(travel.router)
app.include_router(api_v1.router, prefix="/api/v1")


@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else "请求处理失败"
    return JSONResponse(
        status_code=exc.status_code,
        content={"ok": False, "message": detail, "data": None},
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", []) if part != "body")
        errors.append(f"{location}: {error.get('msg', '参数不合法')}")
    return JSONResponse(
        status_code=422,
        content={
            "ok": False,
            "message": "参数校验失败：" + "；".join(errors),
            "data": exc.errors(),
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    logger.exception("未处理异常：%s", exc)
    return JSONResponse(
        status_code=500,
        content={
            "ok": False,
            "message": "服务器内部错误，请查看日志定位问题",
            "data": {"detail": str(exc)} if settings.debug else None,
        },
    )
