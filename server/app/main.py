"""FastAPI 应用入口：路由装配、统一错误信封、Loguru 日志接管。"""
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from loguru import logger

from app.api.v1 import alarms, auth, health, projects, shares
from app.core.config import settings
from app.core.errors import register_handlers
from app.utils.encrypt import ensure_key


class InterceptHandler(logging.Handler):
    """标准 logging → Loguru 转发（接管 uvicorn 等第三方日志）。"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = sys._getframe(6), 6
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 启动自检：凭证加密密钥必须合法（fail fast，容器启动期暴露配置错误）
    ensure_key()
    logger.info(f"{settings.APP_NAME} server 启动完成（schemaVersion={settings.CURRENT_SCHEMA_VERSION}）")
    yield
    logger.info("server 关闭")


def create_app() -> FastAPI:
    logging.basicConfig(handlers=[InterceptHandler()], level=logging.INFO, force=True)
    logger.remove()
    logger.add(sys.stderr, level="DEBUG" if settings.DEBUG else "INFO")

    app = FastAPI(title="webScada API", version="0.1.0", lifespan=lifespan)
    register_handlers(app)

    api = APIRouter(prefix="/api/v1")
    api.include_router(health.router)
    api.include_router(auth.router)
    api.include_router(projects.router)
    api.include_router(shares.router)
    api.include_router(alarms.router)
    app.include_router(api)
    return app


app = create_app()
