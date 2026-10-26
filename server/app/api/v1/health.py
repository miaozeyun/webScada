"""存活检查（compose healthcheck 依赖，03-接口清单 §2.1）。"""
import time

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.base import get_db

router = APIRouter(tags=["health"])

_START = time.time()


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    try:
        await db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:  # noqa: BLE001
        return JSONResponse(status_code=503, content={"status": "degraded", "db": "error"})
    return JSONResponse(
        status_code=200,
        content={"status": "ok", "version": settings.APP_VERSION, "uptimeSec": int(time.time() - _START), "db": db_status},
    )
