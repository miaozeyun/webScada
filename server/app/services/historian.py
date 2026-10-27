"""历史采样入库（M8，契约 §6.2）：定窗采样 + 批量落库 + 保留清理。

- 窗口内同 (project_id, variable_key) 仅保留最后一个 good 值（last-write-wins，§1 定窗采样口径）
- 缓冲 ≥ HISTORY_WRITE_BATCH 条立即冲刷，否则按 HISTORY_SAMPLE_INTERVAL_MS 定窗冲刷
- flush 失败仅告警并丢弃本批（历史为尽力而为语义，不阻塞值流；下个窗口继续采样）
- cleanup_history 消费 HISTORY_RETENTION_DAYS（background_jobs 启动 + 每 24h 各一次）

会话工厂注入点（与 audit_service 同款测试缝）：模块属性 session_factory。
"""
import asyncio
import math
import uuid
from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import HistoryValue

session_factory = None


def _get_session_factory():
    if session_factory is not None:
        return session_factory
    from app.db.base import SessionLocal  # 惰性：避免导入期连库副作用

    return SessionLocal


def _to_number(value) -> float | None:
    """boolean→1/0（03 §2.10 点口径）；有限数值→float；string/NaN/Inf 跳过。"""
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        f = float(value)
        return f if math.isfinite(f) else None
    return None


def _to_dt(ts) -> datetime:
    """epoch 毫秒（≥1e11，hub/WS 口径）/ epoch 秒 / datetime → UTC datetime。"""
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    n = float(ts)
    sec = n / 1000.0 if n >= 1e11 else n
    return datetime.fromtimestamp(sec, tz=timezone.utc)


def _norm_pid(project_id) -> uuid.UUID | None:
    if isinstance(project_id, uuid.UUID):
        return project_id
    try:
        return uuid.UUID(str(project_id))
    except ValueError:
        return None


class Historian:
    """定窗采样缓冲器（进程内单例，get_historian 取用）。"""

    def __init__(self) -> None:
        # (pid,key) -> 行：同窗口按【样本时间最大】保留，而非按到达顺序（乱序/重发不倒退）
        self._pending: dict[tuple[str, str], dict] = {}
        self._task: asyncio.Task | None = None
        self._stopping = False
        self._bg_tasks: set[asyncio.Task] = set()
        # 最近一次阈值触发的冲刷任务（测试/集成可 await 它做确定性同步）
        self.last_flush_task: asyncio.Task | None = None

    def push(self, project_id, key, ts, value) -> None:
        """值监听适配入口（同步；契约签名 push(project_id,key,ts,value)）。

        仅数值入库（boolean→1/0）；非 UUID 工程 id / 非法值静默跳过。
        """
        num = _to_number(value)
        if num is None:
            return
        pid = _norm_pid(project_id)
        if pid is None or not key:
            return
        try:
            ts_dt = _to_dt(ts)
        except (TypeError, ValueError, OSError, OverflowError):
            return
        pending_key = (str(pid), str(key))
        prev = self._pending.get(pending_key)
        if prev is not None and ts_dt < prev["ts"]:
            # 乱序旧帧：保留窗口内较新的样本，避免历史时间轴倒退
            return
        self._pending[pending_key] = {
            "project_id": pid,
            "variable_key": str(key),
            "ts": ts_dt,
            "value": num,
        }
        if len(self._pending) >= settings.HISTORY_WRITE_BATCH:
            self.last_flush_task = self._spawn(self.flush())

    def pending_count(self) -> int:
        return len(self._pending)

    async def flush(self) -> int:
        """当前窗口缓冲批量入库，返回落库行数（无缓冲/失败返回 0）。

        - 实现注记：用 ORM add_all + commit（与 alarm_service 派发路径同款），不用
          core executemany——Python 3.14 + SQLAlchemy 2.1 组合下，create_task 派发协程内
          的 executemany 存在静默丢写现象（直 await 正常；见交付 deviations）。
        - 失败/取消回填：入库失败（含 stop 取消打断 commit）把本批回填缓冲，下窗重试不丢数。
        """
        if not self._pending:
            return 0
        rows = list(self._pending.values())
        self._pending.clear()
        try:
            async with _get_session_factory()() as db:
                db.add_all(HistoryValue(**row) for row in rows)
                await db.commit()
            return len(rows)
        except asyncio.CancelledError:
            self._restore(rows)
            raise
        except Exception as exc:
            self._restore(rows)
            logger.warning("historian 批量入库失败，{} 行留待下窗重试：{}", len(rows), exc)
            return 0

    def _restore(self, rows: list[dict]) -> None:
        """失败回填（last-write-wins 键去重；先清后写语义保持不变）。"""
        for row in reversed(rows):
            self._pending.setdefault((str(row["project_id"]), row["variable_key"]), row)

    async def start(self, app=None) -> None:
        """定窗冲刷循环（幂等；lifespan 调用）。"""
        if self._task is not None and not self._task.done():
            return
        self._stopping = False
        self._task = asyncio.create_task(self._loop())

    async def stop(self, app=None) -> None:
        """停止循环并最终冲刷（关闭逆序：background_jobs.shutdown 调用）。

        flush 的失败/取消回填保证：取消打断在途 commit 时数据回填缓冲，由本方法的
        最终冲刷补写，关闭路径不丢采样点。
        """
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        try:
            await self.flush()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("historian 关闭冲刷失败：{}", exc)

    async def _loop(self) -> None:
        interval = max(settings.HISTORY_SAMPLE_INTERVAL_MS / 1000.0, 0.05)
        while not self._stopping:
            await asyncio.sleep(interval)
            try:
                await self.flush()
            except Exception as exc:  # 循环永续，单次失败不终止
                logger.warning("historian 定窗冲刷异常：{}", exc)

    def _spawn(self, coro) -> asyncio.Task | None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return None
        task = loop.create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return task


_historian = Historian()


def get_historian() -> Historian:
    return _historian


async def cleanup_history(db: AsyncSession, batch: int = 5000) -> int:
    """保留清理（契约 §6.2）：删除 ts 早于 HISTORY_RETENTION_DAYS 的行，返回删除条数。

    分批删除（id 子查询按 ts 索引取一批）：过期行可达数十万，单条大 DELETE
    长事务持锁并放大 WAL，批量提交让清理与读写并发平滑。"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.HISTORY_RETENTION_DAYS)
    total = 0
    while True:
        res = await db.execute(
            delete(HistoryValue)
            .where(
                HistoryValue.id.in_(
                    select(HistoryValue.id)
                    .where(HistoryValue.ts < cutoff)
                    .order_by(HistoryValue.ts)
                    .limit(batch)
                )
            )
            .execution_options(synchronize_session=False)
        )
        await db.commit()
        n = res.rowcount or 0
        total += n
        if n < batch:
            return total
