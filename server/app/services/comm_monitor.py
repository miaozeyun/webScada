"""通讯中断监控（阶段三）：把「设备断线」提升为一等报警。

为什么不靠变量 stale：stale 是单点视角且 OPC UA 订阅无变化时帧不再到达，
无法区分「值没变」与「设备没了」。这里以采集源的健康状态为准：

- 每个采集源维护 state/last_ok_ms（collector.BaseSource，连接/收发/心跳推进）
- 静默超过阈值 → alarm_service.trigger 一条系统报警（rule_id=sys_comm:<dsId>，
  level=critical，variable_key=__comm__:<dsId>）
- 恢复 → alarm_service.clear 同一 rule_id，触发恢复通知
- 阈值：轮询源 3×采集周期（下限 15s）；OPC UA 30s；MQTT/WS 长连接 90s
  （长连接由心跳/健康探测推进 last_ok_ms，空闲不等于断线）

阈值刻意偏保守：宁可晚 30 秒报，也不要因为值不变而误报。
"""
import time
import uuid as uuidlib
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import stats
from app.core.config import settings
from app.services import alarm_service
from app.services.collector import collector

_DOWN_RULE_PREFIX = "sys_comm:"
_COMM_VAR_PREFIX = "__comm__:"


def _timeout_ms(st: dict) -> int:
    """单源静默阈值（毫秒）。"""
    ds_type = st.get("type")
    interval = st.get("intervalMs")
    if ds_type in ("rest", "modbus", "mock"):
        return max(settings.COMM_TIMEOUT_MIN_MS, 3 * int(interval or 1000))
    if ds_type == "opcua":
        return max(settings.COMM_TIMEOUT_MIN_MS, settings.COMM_TIMEOUT_OPCUA_MS)
    heartbeat = st.get("heartbeatSec")
    if ds_type == "websocket" and heartbeat:
        return max(settings.COMM_TIMEOUT_CONN_MS, 3 * int(heartbeat) * 1000)
    return settings.COMM_TIMEOUT_CONN_MS


def _rule(st: dict) -> dict:
    ds_id = str(st.get("dsId") or "")
    name = str(st.get("name") or ds_id)
    ds_type = str(st.get("type") or "?")
    detail = str(st.get("lastError") or "无响应")[:160]
    return {
        "id": f"{_DOWN_RULE_PREFIX}{ds_id}",
        "name": f"通讯中断：{name}",
        "variableKey": f"{_COMM_VAR_PREFIX}{ds_id}",
        "level": "critical",
        "message": f"设备通讯中断：{name}（{ds_type}），{detail}",
    }


class CommMonitor:
    """进程内断线集合（触发/恢复各一次；重启后由当前健康态重新收敛）。"""

    def __init__(self) -> None:
        self._down: set[tuple[str, str]] = set()
        # 源在快照中连续缺席的轮数：collector.sync 的 stop() await 窗口会让源短暂消失，
        # 只缺席 1 轮不能判「已删除」，否则一次配置保存会产生「恢复+中断」成对假通知
        self._missing: dict[tuple[str, str], int] = {}

    def reset(self) -> None:
        self._down.clear()
        self._missing.clear()

    def down_count(self) -> int:
        return len(self._down)

    async def check_once(self, db: AsyncSession, now_ms: int | None = None) -> dict:
        """扫描一轮采集源健康态：返回 {triggered, cleared}。"""
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        now_dt = datetime.fromtimestamp(now / 1000, tz=timezone.utc)
        snapshot = collector.status_all()
        seen: set[tuple[str, str]] = set()
        triggered = 0
        cleared = 0

        for pid, items in snapshot.items():
            for st in items:
                key = (str(pid), str(st.get("dsId") or ""))
                seen.add(key)
                last_ok = st.get("lastOkMs") or st.get("startedMs") or now
                # 没有点位的数据源不产生新报警；但若已有活动报警，必须走恢复分支清掉，
                # 否则「断线报警后把变量全删了」会永久悬挂一条 critical。
                down = int(st.get("variableCount") or 0) > 0 and (now - int(last_ok)) > _timeout_ms(st)
                rule_id = f"{_DOWN_RULE_PREFIX}{st.get('dsId')}"
                try:
                    if down and key not in self._down:
                        # 先写库成功、再记内存态：trigger 抛异常时下一轮仍会重试，
                        # 不会因为「内存里已标记断线」而静默丢掉整段报警。
                        result = await alarm_service.trigger(db, pid, _rule(st), None, now_dt)
                        if result is not None:
                            self._down.add(key)
                            triggered += 1
                            logger.warning(
                                "通讯中断报警：project={} ds={} type={} 静默 {}ms error={}",
                                pid, st.get("dsId"), st.get("type"), now - int(last_ok), st.get("lastError"),
                            )
                    elif not down and key in self._down:
                        result = await alarm_service.clear(db, pid, rule_id, now_dt)
                        self._down.discard(key)
                        if result is not None:
                            cleared += 1
                            logger.info("通讯恢复：project={} ds={}", pid, st.get("dsId"))
                except Exception as exc:  # noqa: BLE001 - 单源故障不影响其余源扫描
                    logger.warning(
                        "通讯监控处理失败（下轮重试）project={} ds={}：{}",
                        pid, st.get("dsId"), exc,
                    )

        # 数据源被删除/禁用后不再上报：连续缺席 2 轮才清遗留活动报警，防 sync 窗口误判
        for key in list(self._down):
            if key in seen:
                self._missing.pop(key, None)
                continue
            self._missing[key] = self._missing.get(key, 0) + 1
            if self._missing[key] < 2:
                continue
            try:
                pid = uuidlib.UUID(key[0])
            except ValueError:
                self._down.discard(key)
                self._missing.pop(key, None)
                continue
            try:
                result = await alarm_service.clear(db, pid, f"{_DOWN_RULE_PREFIX}{key[1]}", now_dt)
            except Exception as exc:  # noqa: BLE001 - 清失败保留状态，下轮重试
                logger.warning("通讯报警清除失败（下轮重试）project={} ds={}：{}", key[0], key[1], exc)
                continue
            self._down.discard(key)
            self._missing.pop(key, None)
            if result is not None:
                cleared += 1

        stats.set_gauge("collector_down_sources", float(len(self._down)))
        return {"triggered": triggered, "cleared": cleared}


comm_monitor = CommMonitor()
