"""后台任务装配（M8，契约 §6.2）：启动收口 + 保留清理 + hub 值监听挂载 + 每 24h 清理循环。

lifespan 顺序（main.py 骨架冻结）：runtime_boot.startup（A）→ background_jobs.startup（B），
关闭逆序。A 未合入时本模块降级运行：启动收口与清理照常，hub 监听不挂载并告警，不阻断启动。

挂载内容（契约 §6.2）：hub.add_value_listener(rules_engine) + hub.add_value_listener(historian 适配)。
"""
import asyncio

from loguru import logger

from app.services import alarm_service, historian, rules_engine
from app.services.historian import get_historian

_daily_task: asyncio.Task | None = None


def _locate_hub(app):
    """定位 A 包 hub 实例：优先 app.state.hub，其次 hub 模块级单例/工厂（命名协调点）。"""
    hub = getattr(app.state, "hub", None) if app is not None else None
    if hub is not None:
        return hub
    try:
        from app.services import hub as hub_mod  # 惰性：跨包（A），未合入时 ImportError
    except ImportError:
        return None
    for attr in ("hub", "HUB"):
        cand = getattr(hub_mod, attr, None)
        if cand is not None:
            return cand
    factory = getattr(hub_mod, "get_hub", None)
    if callable(factory):
        try:
            return factory()
        except Exception:
            return None
    return None


def _historian_listener(project_id, variable, value, q, ts) -> None:
    """hub 值监听 → historian.push 适配（契约监听器签名；q!=good 不采样）。"""
    if q != "good":
        return
    if isinstance(variable, dict):
        key = variable.get("key")
    else:
        key = getattr(variable, "key", None)
    if key:
        get_historian().push(project_id, key, ts, value)


async def run_maintenance(initial: bool = False) -> None:
    """启动/每日维护：sweep 收口（仅启动）→ 两类保留清理 → alarms_active gauge 校准。"""
    from app.db.base import SessionLocal  # 惰性：测试可整体替换

    try:
        async with SessionLocal() as db:
            swept = await alarm_service.sweep_on_startup(db) if initial else 0
            alarm_deleted = await alarm_service.cleanup_expired(db)
            hist_deleted = await historian.cleanup_history(db)
            active = await alarm_service.count_active(db)
            alarm_service.set_active_hint(active)
        logger.info(
            "后台维护完成：启动收口 {} 条；报警清理 {} 条；历史清理 {} 条；当前活动报警 {}",
            swept, alarm_deleted, hist_deleted, active,
        )
    except Exception as exc:
        logger.warning("后台维护失败（不阻断启动）：{}", exc)


async def _attach_listeners(app) -> None:
    hub = _locate_hub(app)
    if hub is None:
        logger.warning("未找到 hub 实例（工作包 A 未合入或未挂载 app.state.hub），"
                       "报警引擎与历史采样本次启动不挂载（打桩降级）")
        return
    try:
        engine = rules_engine.get_engine()
        loaded = await engine.reload_all()  # 启动预载全部工程规则（值事件前规则就绪）
        if not engine.attach(hub):
            logger.warning("hub 缺少 add_value_listener，报警引擎未挂载")
            return
        hub.add_value_listener(_historian_listener)
        logger.info("报警引擎（{} 条规则）与历史采样已挂载到 hub", loaded)
    except Exception as exc:
        logger.warning("挂载 hub 监听失败（打桩降级）：{}", exc)


async def _daily_loop() -> None:
    while True:
        await asyncio.sleep(24 * 3600)
        await run_maintenance(initial=False)


async def startup(app) -> None:
    """lifespan 启动（契约 §6.2）：先收口清理，再挂监听，启动 historian 定窗冲刷，最后起 24h 循环。"""
    await run_maintenance(initial=True)
    await _attach_listeners(app)
    await get_historian().start(app)  # push 缓冲的定时落库循环（不启动则仅 500 条批量阈值兜底）
    global _daily_task
    _daily_task = asyncio.create_task(_daily_loop())


async def shutdown(app) -> None:
    """lifespan 关闭（逆序）：停 24h 循环 → historian 最终冲刷。"""
    global _daily_task
    if _daily_task is not None:
        _daily_task.cancel()
        try:
            await _daily_task
        except asyncio.CancelledError:
            pass
        _daily_task = None
    await get_historian().stop(app)
