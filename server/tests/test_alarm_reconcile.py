"""报警生命周期收口测试（2026-10-26 评审修复）。

覆盖：
- 保存 doc 后按规则集合差集清除残留活动报警（删除/停用规则）；
- sys_comm: 系统报警不被误清；
- 人工清除 force_clear 幂等；
- 质量非 good 时（stale/bad）该变量的活动工艺报警自动收口，恢复 good 后可再次触发。
"""
import asyncio
import sys
import time
import uuid as uuidlib
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import AlarmRecord, Project, User
from app.services import alarm_service

UTCD = timezone.utc


def _at(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTCD)


async def wait_for(cond, timeout: float = 2.0, what: str = "条件"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"等待超时：{what}")


class _FakeWSManager:
    def __init__(self):
        self.clear: list[tuple] = []

    async def broadcast_alarm(self, project_id, alarm):  # noqa: ARG002
        return None

    async def broadcast_alarm_clear(self, project_id, alarm_id, cleared_at):
        self.clear.append((project_id, alarm_id, cleared_at))

    async def broadcast_alarm_ack(self, project_id, alarm_id, acked_at, acked_by):  # noqa: ARG002
        return None


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
def fake_ws(monkeypatch):
    import app.services as pkg

    fake = _FakeWSManager()
    prev_mod = sys.modules.get("app.services.ws_manager")
    sys.modules["app.services.ws_manager"] = fake
    pkg.ws_manager = fake
    yield fake
    if prev_mod is None:
        sys.modules.pop("app.services.ws_manager", None)
    else:
        sys.modules["app.services.ws_manager"] = prev_mod
    if getattr(pkg, "ws_manager", None) is fake:
        delattr(pkg, "ws_manager")


@pytest.fixture(autouse=True)
def _stub_notify(monkeypatch):
    from app.services import notify as notify_mod

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(notify_mod, "send_alarm", _noop)
    monkeypatch.setattr(notify_mod, "send_recovery", _noop)


async def _project(factory) -> Project:
    async with factory() as s:
        u = User(username=f"u{uuidlib.uuid4().hex[:8]}", password_hash="x", role="admin")
        s.add(u)
        await s.commit()
        await s.refresh(u)
        p = Project(id=uuidlib.uuid4(), name="P1", doc={}, revision=1, owner_id=u.id)
        s.add(p)
        await s.commit()
        await s.refresh(p)
        return p


SNAP_A = {"id": "a_t", "variableKey": "temp", "level": "critical", "message": "温度超限"}
SNAP_B = {"id": "a_f", "variableKey": "freq", "level": "warn", "message": "频率偏低"}


async def test_reconcile_clears_removed_rule_and_keeps_live(env, fake_ws):
    p = await _project(env.factory)
    async with env.factory() as db:
        keep = await alarm_service.trigger(db, p.id, SNAP_A, "72.0", _at(1000))
        gone = await alarm_service.trigger(db, p.id, SNAP_B, "49.0", _at(1100))
    # 新 doc 只保留 a_t（a_f 被删除）
    doc = {"alarmRules": [{"id": "a_t", "enabled": True}, {"id": "a_f", "enabled": False}]}
    async with env.factory() as db:
        cleared = await alarm_service.reconcile_rules(db, p.id, doc)
    assert cleared == [gone]
    async with env.factory() as db:
        keep_rec = await db.get(AlarmRecord, keep)
        gone_rec = await db.get(AlarmRecord, gone)
    assert keep_rec.status == "triggered"
    assert gone_rec.status == "cleared"
    await wait_for(lambda: len(fake_ws.clear) == 1, what="alarmClear 广播")


async def test_reconcile_never_touches_sys_comm(env):
    p = await _project(env.factory)
    async with env.factory() as db:
        comm = await alarm_service.trigger(
            db,
            p.id,
            {"id": "sys_comm:ds1", "variableKey": "__comm__:ds1", "level": "critical", "message": "通讯中断"},
            None,
            _at(1000),
        )
    async with env.factory() as db:
        cleared = await alarm_service.reconcile_rules(db, p.id, {"alarmRules": []})
    assert cleared == []
    async with env.factory() as db:
        rec = await db.get(AlarmRecord, comm)
    assert rec.status == "triggered"


async def test_force_clear_idempotent(env, fake_ws):
    p = await _project(env.factory)
    async with env.factory() as db:
        aid = await alarm_service.trigger(db, p.id, SNAP_A, "80.0", _at(1000))
    async with env.factory() as db:
        rec = await alarm_service.force_clear(db, p.id, aid, _at(2000))
        assert rec.status == "cleared"
    async with env.factory() as db:
        rec2 = await alarm_service.force_clear(db, p.id, aid, _at(3000))
        assert rec2.status == "cleared"
        assert rec2.cleared_at is not None
    await wait_for(lambda: len(fake_ws.clear) == 1, what="仅广播一次")


async def _statuses(factory, pid):
    async with factory() as db:
        rows = (await db.execute(select(AlarmRecord).where(AlarmRecord.project_id == pid))).scalars().all()
        return sorted(r.status for r in rows)


async def test_bad_quality_clears_active_alarm_and_allows_retrigger(env, fake_ws, monkeypatch):
    from app.services import rules_engine

    engine = rules_engine.RulesEngine()
    monkeypatch.setattr(rules_engine, "session_factory", env.factory)
    p = await _project(env.factory)
    doc = {
        "variables": [{"id": "v_t", "key": "temp", "label": "温度", "precision": 1}],
        "alarmRules": [
            {"id": "a_t", "variableId": "v_t", "op": ">", "threshold": 70, "level": "critical", "enabled": True}
        ],
    }
    assert engine.sync(p.id, doc) == 1

    ts = int(time.time() * 1000)
    engine.on_value(p.id, {"id": "v_t"}, 80.0, "good", ts)
    for _ in range(200):
        if await _statuses(env.factory, p.id) == ["triggered"]:
            break
        await asyncio.sleep(0.01)
    assert await _statuses(env.factory, p.id) == ["triggered"]

    # 质量转 stale → 活动报警收口
    engine.on_value(p.id, {"id": "v_t"}, 80.0, "stale", ts + 1000)
    for _ in range(200):
        if await _statuses(env.factory, p.id) == ["cleared"]:
            break
        await asyncio.sleep(0.01)
    assert await _statuses(env.factory, p.id) == ["cleared"]

    # 重复 stale 帧不重复动作（去重）
    engine.on_value(p.id, {"id": "v_t"}, 80.0, "stale", ts + 2000)

    # 恢复 good 且条件仍满足 → 重新触发（新行）
    engine.on_value(p.id, {"id": "v_t"}, 81.0, "good", ts + 3000)
    for _ in range(200):
        if await _statuses(env.factory, p.id) == ["cleared", "triggered"]:
            break
        await asyncio.sleep(0.01)
    assert await _statuses(env.factory, p.id) == ["cleared", "triggered"]
    engine.remove(p.id)
