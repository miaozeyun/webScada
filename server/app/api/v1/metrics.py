"""/metrics 基础可观测端点（M8 共享骨架，根路径、无 /api/v1 前缀）。

- 输出 core.stats 注册表的 Prometheus 文本格式（进程内，无第三方依赖）
- METRICS_TOKEN 非空时要求 Bearer 或 ?token= 匹配；空 = 免鉴权（部署基线：仅内网可达）
- 禁改清单：本文件为共享骨架，实施 agent 不得修改；埋点统一走 core.stats.inc/set_gauge
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from app.core import stats
from app.core.config import settings

router = APIRouter(tags=["metrics"])


def _check_token(request: Request) -> None:
    token = settings.METRICS_TOKEN
    if not token:
        return
    supplied = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not supplied:
        supplied = request.query_params.get("token", "")
    if supplied != token:
        raise HTTPException(status_code=401, detail="metrics token 不匹配")


@router.get("/metrics")
async def metrics(_ok: None = Depends(_check_token)) -> Response:
    return Response(
        content=stats.render(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
