"""historian 测试（B 包，契约 §6.2）：定窗采样 last-write-wins、批量/定时冲刷、保留清理。"""
import asyncio
import time
import uuid as uuidlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.db.models import HistoryValue
from app.services import historian
from app.services.historian import Historian, cleanup_history, get_historian

UTCD = timezone.utc
T0_MS = 1760000000000  # 固定 epoch 毫秒基准


async def rows_of(env) -> list[HistoryValue]:
    async with env.factory() as s:
        return list((await s.execute(select(HistoryValue).order_by(HistoryValue.id))).scalars())


async def wait_rows(env, n: int, what="入库") -> list[HistoryValue]:
    deadline = time.monotonic() + 2.0
    rows: list[HistoryValue] = []
    while time.monotonic() < deadline:
        rows = await rows_of(env)
        if len(rows) >= n:
            return rows
        await asyncio.sleep(0.01)
    raise AssertionError(f"等待超时：{what}（当前 {len(rows)} 行）")


@pytest.fixture
async def env():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield SimpleNamespace(engine=engine, factory=factory)
    await engine.dispose()


@pytest.fixture
def seam(env):
    historian.session_factory = env.factory
    yield
    historian.session_factory = None


def test_singleton():
    assert get_historian() is get_historian()


async def test_push_and_flush_batch_rows(env, seam):
    h = Historian()
    pid = uuidlib.uuid4()
    h.push(pid, "temp", T0_MS, 21.5)
    h.push(pid, "press", T0_MS + 10, True)  # boolean → 1.0
    assert h.pending_count() == 2
    assert await h.flush() == 2
    assert await h.flush() == 0  # 空缓冲幂等
    rows = await rows_of(env)
    assert [(r.variable_key, r.value) for r in rows] == [("temp", 21.5), ("press", 1.0)]
    # 时间口径：SQLite 读回 naive 时按 UTC 墙钟（入库 _to_dt 已统一 UTC）
    ts0 = rows[0].ts.replace(tzinfo=UTCD) if rows[0].ts.tzinfo is None else rows[0].ts
    assert int(ts0.timestamp() * 1000) == T0_MS


async def test_window_last_write_wins(env, seam):
    h = Historian()
    pid = uuidlib.uuid4()
    h.push(pid, "temp", T0_MS, 1.0)
    h.push(pid, "temp", T0_MS + 500, 2.0)
    h.push(pid, "temp", T0_MS + 900, 3.0)  # 同窗口同 key：仅保留最后一个 good 值
    assert h.pending_count() == 1
    assert await h.flush() == 1
    rows = await rows_of(env)
    assert len(rows) == 1 and rows[0].value == 3.0


async def test_window_out_of_order_keeps_newest(env, seam):
    """同一窗口内乱序到达：保留样本时间最大的值，历史时间轴不倒退。"""
    h = Historian()
    pid = uuidlib.uuid4()
    h.push(pid, "temp", T0_MS + 5000, 5.0)
    h.push(pid, "temp", T0_MS + 1000, 1.0)  # 迟到的旧帧
    assert h.pending_count() == 1
    assert await h.flush() == 1
    rows = await rows_of(env)
    assert len(rows) == 1 and rows[0].value == 5.0
    ts0 = rows[0].ts.replace(tzinfo=UTCD) if rows[0].ts.tzinfo is None else rows[0].ts
    assert int(ts0.timestamp() * 1000) == T0_MS + 5000


async def test_push_skips_invalid(env, seam):
    h = Historian()
    h.push("not-a-uuid", "k", T0_MS, 1.0)  # 非法工程 id
    h.push(uuidlib.uuid4(), "k", T0_MS, "str")  # string 值
    h.push(uuidlib.uuid4(), "k", T0_MS, float("nan"))  # NaN
    h.push(uuidlib.uuid4(), "", T0_MS, 1.0)  # 空 key
    assert h.pending_count() == 0


async def test_batch_threshold_auto_flush(env, seam, monkeypatch):
    monkeypatch.setattr(settings, "HISTORY_WRITE_BATCH", 3)
    h = Historian()
    pid = uuidlib.uuid4()
    for i in range(3):
        h.push(pid, f"k{i}", T0_MS + i, float(i))
    # 阈值触发的冲刷为后台任务：显式等它完成再做断言（StaticPool 单连接下避免轮询读写竞态）
    assert h.last_flush_task is not None
    await h.last_flush_task
    rows = await rows_of(env)
    assert len(rows) == 3


async def test_timer_window_flush_and_stop(env, seam, monkeypatch):
    """定窗冲刷 + stop 最终冲刷。

    时序注记：测试库为 StaticPool 单连接（生产为 asyncpg 池），轮询会话与冲刷任务
    并发会交错出「close 回滚清掉他者事务」的测试栈特有竞态——故此处不用轮询，
    以 sleep 越过若干采样窗后一次性读，全程串行。
    """
    monkeypatch.setattr(settings, "HISTORY_SAMPLE_INTERVAL_MS", 30)
    h = Historian()
    await h.start()
    pid = uuidlib.uuid4()
    h.push(pid, "temp", T0_MS, 7.0)
    await asyncio.sleep(0.2)  # 越过 ≥5 个采样窗：定时冲刷已完成且无并发访问
    rows = await rows_of(env)
    assert [r.variable_key for r in rows] == ["temp"] and rows[0].value == 7.0

    # stop 前再压入缓冲：stop 应做最终冲刷（awaited，串行）
    h.push(pid, "temp2", T0_MS + 1, 8.0)
    await h.stop()
    rows = await rows_of(env)
    assert {r.variable_key for r in rows} == {"temp", "temp2"}


async def test_cleanup_history(env, seam):
    """cleanup_history(db) 契约签名：删除超 HISTORY_RETENTION_DAYS 的行。"""
    pid = uuidlib.uuid4()
    now = datetime.now(UTCD)
    async with env.factory() as s:
        s.add_all(
            [
                HistoryValue(project_id=pid, variable_key="old", ts=now - timedelta(days=40), value=1.0),
                HistoryValue(project_id=pid, variable_key="fresh", ts=now - timedelta(days=1), value=2.0),
            ]
        )
        await s.commit()
        assert await cleanup_history(s) == 1
        left = [r.variable_key for r in (await s.execute(select(HistoryValue))).scalars()]
    assert left == ["fresh"]


async def test_cleanup_history_batched(env, seam):
    """分批删除：过期行数超过 batch 时循环多批删净（防止单条大 DELETE 长事务）。"""
    pid = uuidlib.uuid4()
    now = datetime.now(UTCD)
    async with env.factory() as s:
        s.add_all(
            [
                HistoryValue(project_id=pid, variable_key=f"old{i}", ts=now - timedelta(days=40), value=1.0)
                for i in range(5)
            ]
            + [HistoryValue(project_id=pid, variable_key="fresh", ts=now - timedelta(days=1), value=2.0)]
        )
        await s.commit()
        # batch=2：5 行过期分 3 批（2+2+1），最后一批不足 batch 终止
        assert await cleanup_history(s, batch=2) == 5
        left = [r.variable_key for r in (await s.execute(select(HistoryValue))).scalars()]
    assert left == ["fresh"]
