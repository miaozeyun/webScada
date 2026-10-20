"""FastAPI 应用入口：路由装配、统一错误信封、Loguru 日志接管、限流与 CORS、生命周期。

M8 服务端闭环（契约：docs/implementation/server-closed-loop-plan.md）：
- 新增路由装配：ws(A) / datasources(A) / history(B) / users(C) / audit(C) / metrics(共享)
- 自研限流中间件（core/rate_limit，消费 G16 死参数）
- CORS 默认收紧：同源部署不放开，仅 CORS_ORIGINS 白名单非空时启用
- lifespan：安全自检（ensure_key + settings.validate_runtime）→ runtime_boot（A：采集/hub/ws）
  → background_jobs（B：historian 清理 / 报警保留清理 / 启动收口）

【集成中间态声明】ws/datasources/history/users/audit、services/runtime_boot、
services/background_jobs 由六个工作包并行交付；在全部包合入前本模块 import 失败、
服务不可启动——这是预期状态，集成顺序见契约文档 §9。
"""
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.api.v1 import alarms, audit, auth, datasources, health, history, metrics, projects, shares, users, ws
from app.core.config import settings
from app.core.errors import register_handlers
from app.core.rate_limit import RateLimitMiddleware
from app.services import background_jobs, runtime_boot
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
async def lifespan(app: FastAPI):
    # 启动自检：凭证加密密钥必须合法 + JWT_SECRET 非弱值（fail fast，容器启动期暴露配置错误）
    ensure_key()
    settings.validate_runtime()
    logger.info(f"{settings.APP_NAME} server 启动完成（schemaVersion={settings.CURRENT_SCHEMA_VERSION}）")
    # 采集/WS（工作包 A）先起值流，后台任务（工作包 B）随后挂载清理循环
    await runtime_boot.startup(app)
    await background_jobs.startup(app)
    yield
    await background_jobs.shutdown(app)
    await runtime_boot.shutdown(app)
    logger.info("server 关闭")


def create_app() -> FastAPI:
    logging.basicConfig(handlers=[InterceptHandler()], level=logging.INFO, force=True)
    logger.remove()
    logger.add(sys.stderr, level="DEBUG" if settings.DEBUG else "INFO")

    app = FastAPI(title="webScada API", version="0.2.0", lifespan=lifespan)
    register_handlers(app)

    # CORS 收紧（M8）：同源部署（nginx 统一入口）默认零 CORS；跨域部署显式白名单
    origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
        )

    api = APIRouter(prefix="/api/v1")
    api.include_router(health.router)
    api.include_router(auth.router)
    api.include_router(projects.router)
    api.include_router(shares.router)
    api.include_router(datasources.router)   # A：连通性测试（凭证注回）
    api.include_router(ws.router)            # A：/ws/runtime 服务端推送
    api.include_router(alarms.router)        # B：报警列表/ack（状态机）
    api.include_router(history.router)       # B：历史区间查询
    api.include_router(users.router)         # C：用户 CRUD（admin）
    api.include_router(audit.router)         # C：审计查询（admin）
    app.include_router(api)
    app.include_router(metrics.router)       # /metrics 根路径（Prometheus 惯例）

    # 公开面限流（登录 / 分享文档 / 连通性测试）；纯 ASGI，WS 透传
    app.add_middleware(RateLimitMiddleware)
    return app


app = create_app()
