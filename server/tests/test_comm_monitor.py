"""通讯中断监控（阶段三）：断线出一等报警、恢复清报警、阈值按源类型。"""
import time
import uuid as uuidlib
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.db.models import AlarmRecord
from app.services import alarm_service, comm_monitor as cm


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


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    """报警外发不落网络（本文件只验证报警入库与状态机）。"""
    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr("app.services.notify.send_alarm", _noop)
    monkeypatch.setattr("app.services.notify.send_recovery", _noop)
    cm.comm_monitor.reset()
    yield
    cm.comm_monitor.reset()


def test_timeout_by_source_type():
    assert cm._timeout_ms({"type": "rest", "intervalMs": 1000}) == settings.COMM_TIMEOUT_MIN_MS
    assert cm._timeout_ms({"type": "rest", "intervalMs": 60_000}) == 180_000
    assert cm._timeout_ms({"type": "opcua"}) == settings.COMM_TIMEOUT_OPCUA_MS
    assert cm._timeout_ms({"type": "mqtt"}) == settings.COMM_TIMEOUT_CONN_MS


async def test_down_then_recover(env, monkeypatch):
    pid = uuidlib.uuid4()
    ds_id = "ds_1"
    now = int(time.time() * 1000)
    state = {
        "down": {
            "dsId": ds_id, "name": "1号PLC", "type": "modbus", "state": "error",
            "lastOkMs": now - 60_000, "startedMs": now - 600_000,
            "lastError": "Connection refused", "variableCount": 10, "intervalMs": 1000,
        }
    }
    monkeypatch.setattr(cm, "collector", SimpleNamespace(status_all=lambda: {pid: [state["down"]]}))

    async with env.factory() as db:
        result = await cm.comm_monitor.check_once(db, now_ms=now)
        assert result["triggered"] == 1
        alarm = (await db.execute(select(AlarmRecord))).scalars().one()
        assert alarm.rule_id == f"sys_comm:{ds_id}"
        assert alarm.level == "critical" and alarm.status == "triggered"
        assert "通讯中断" in alarm.message
        assert alarm.variable_key == f"__comm__:{ds_id}"

        # 同一断线周期不重复插行
        result = await cm.comm_monitor.check_once(db, now_ms=now + 5_000)
        assert result["triggered"] == 0
        assert len((await db.execute(select(AlarmRecord))).scalars().all()) == 1

        # 恢复：清报警并计数
        healthy = {**state["down"], "state": "ok", "lastOkMs": now + 10_000, "lastError": None}
        monkeypatch.setattr(cm, "collector", SimpleNamespace(status_all=lambda: {pid: [healthy]}))
        result = await cm.comm_monitor.check_once(db, now_ms=now + 10_000)
        assert result["cleared"] == 1
        await db.refresh(alarm)
        assert alarm.status == "cleared"


async def test_no_alarm_without_variables_or_during_grace(env, monkeypatch):
    pid = uuidlib.uuid4()
    now = int(time.time() * 1000)
    empty = {
        "dsId": "ds_empty", "name": "空源", "type": "modbus", "state": "starting",
        "lastOkMs": None, "startedMs": now, "lastError": None, "variableCount": 0, "intervalMs": 1000,
    }
    monkeypatch.setattr(cm, "collector", SimpleNamespace(status_all=lambda: {pid: [empty]}))
    async with env.factory() as db:
        assert await cm.comm_monitor.check_once(db, now_ms=now) == {"triggered": 0, "cleared": 0}
        assert (await db.execute(select(AlarmRecord))).scalars().all() == []

    grace = {**empty, "dsId": "ds_grace", "variableCount": 5}
    monkeypatch.setattr(cm, "collector", SimpleNamespace(status_all=lambda: {pid: [grace]}))
    async with env.factory() as db:
        assert await cm.comm_monitor.check_once(db, now_ms=now + 5_000) == {"triggered": 0, "cleared": 0}


async def test_source_absent_needs_two_rounds_before_clearing(env, monkeypatch):
    """collector.sync 的 stop() 窗口会让源短暂消失：连续缺席 2 轮才清报警。"""
    pid = uuidlib.uuid4()
    now = int(time.time() * 1000)
    down = {
        "dsId": "ds_1", "name": "PLC", "type": "modbus", "state": "error",
        "lastOkMs": now - 60_000, "startedMs": now - 600_000,
        "lastError": "down", "variableCount": 3, "intervalMs": 1000,
    }
    monkeypatch.setattr(cm, "collector", SimpleNamespace(status_all=lambda: {pid: [down]}))
    async with env.factory() as db:
        await cm.comm_monitor.check_once(db, now_ms=now)
        assert (await db.execute(select(AlarmRecord))).scalars().one().status == "triggered"

        # 第 1 轮缺席：视为 sync 窗口，不清
        monkeypatch.setattr(cm, "collector", SimpleNamespace(status_all=lambda: {}))
        assert await cm.comm_monitor.check_once(db, now_ms=now + 5_000) == {"triggered": 0, "cleared": 0}
        # 第 2 轮仍缺席：确认已删除/禁用，清报警
        assert await cm.comm_monitor.check_once(db, now_ms=now + 10_000) == {"triggered": 0, "cleared": 1}


def test_rule_shape_is_stable():
    rule = cm._rule({"dsId": "d1", "name": "空压机", "type": "mqtt", "lastError": None})
    assert rule["id"] == "sys_comm:d1"
    assert rule["variableKey"] == "__comm__:d1"
    assert rule["level"] == "critical"
    assert "空压机" in rule["message"]
