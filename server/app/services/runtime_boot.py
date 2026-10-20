"""运行态装配（M8 工作包 A）：main.lifespan 调用，先于 background_jobs（B）。

- 装配 Hub / Collector / WSManager 进程内单例并挂 app.state
- 启动 ws_manager 合帧/心跳循环；启动 stale 扫描（1s 粒度）
- 启动时对全部工程 hub.set_doc + collector.sync（表缺失等启动期缺撼仅告警不阻断）
"""
import asyncio

from fastapi import FastAPI
from loguru import logger
from sqlalchemy import select

from app.services import collector as collector_mod
from app.services import hub as hub_mod
from app.services import ws_manager as ws_manager_mod

_STALE_SWEEP_INTERVAL_SEC = 1.0


async def _sync_all_projects() -> int:
    """启动收口：全部工程重建值池索引与采集任务（lifespan 序：先 A 值流，后 B 清理循环）。"""
    from app.db.base import SessionLocal
    from app.db.models import Project

    count = 0
    async with SessionLocal() as db:
        rows = (await db.execute(select(Project))).scalars().all()
        for project in rows:
            doc = project.doc if isinstance(project.doc, dict) else {}
            hub_mod.hub.set_doc(project.id, doc)
            await collector_mod.collector.sync(project.id, doc)
            count += 1
    return count


async def startup(app: FastAPI) -> None:
    """签名冻结（契约 §6.1）。幂等：重复调用不重复起循环。"""
    app.state.hub = hub_mod.hub
    app.state.collector = collector_mod.collector
    app.state.ws_manager = ws_manager_mod.manager

    # License 骨架（M8 阶段 2）：未配置 = 开源核心全功能；无效/过期仅告警不阻断（监控连续性优先）
    from app.core import license as license_mod
    from app.core import stats

    info, status = license_mod.load_runtime_license()
    app.state.license = info
    app.state.license_status = status
    stats.set_gauge("license_status", {"open-source": 0, "valid": 1, "expired": 2, "invalid": 3}.get(status, -1))
    if status in ("expired", "invalid"):
        logger.warning(f"license {status}——规模上限回落开源核心基线（不影响已有连接与采集）")
    elif status == "valid":
        logger.info(f"license 有效：{info.licensee}（上限收敛 WS≤{license_mod.effective_limits(info)[0]}）")

    await ws_manager_mod.manager.start()
    app.state.stale_task = asyncio.create_task(_stale_loop())

    try:
        count = await _sync_all_projects()
        logger.info(f"runtime_boot 完成：{count} 个工程采集已装配")
    except Exception as exc:  # noqa: BLE001 - 测试环境（无表）/DB 暂不可用不阻断启动
        logger.warning(f"runtime_boot 工程同步降级：{type(exc).__name__} {exc}")


async def shutdown(app: FastAPI) -> None:
    """签名冻结（契约 §6.1）。与 startup 逆序收口。"""
    stale_task = getattr(app.state, "stale_task", None)
    if stale_task is not None:
        stale_task.cancel()
        try:
            await stale_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        app.state.stale_task = None
    await collector_mod.collector.remove_all()
    await ws_manager_mod.manager.stop()


async def _stale_loop() -> None:
    while True:
        await asyncio.sleep(_STALE_SWEEP_INTERVAL_SEC)
        try:
            hub_mod.hub.sweep_stale_all()
        except Exception:  # noqa: BLE001
            logger.exception("stale 扫描异常")
