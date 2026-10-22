"""报警单行状态机测试（B 包，契约 §6.2/§4.1）：自建 mini app，不依赖 app.main 装配。

覆盖：trigger 幂等不插新行、ack 幂等/迟到补确认、clear 保留 ack 字段、sweep_on_startup、
保留清理（retention + 单工程行数上限）、REST 列表过滤/分页、REST ack（403/404/审计/广播打桩）、
废弃别名（GET 同实现 / POST 旧上报映射）。
"""
import asyncio
import sys
import time
import types
import uuid as uuidlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.errors import register_handlers
from app.core.security import hash_password
from app.api.deps import get_current_user
from app.db.base import Base, get_db
from app.db.models import AlarmRecord, AuditLog, Project, User
from app.services import alarm_service
from app.services import audit_service as audit_mod

UTCD = timezone.utc


def _naive(dt: datetime) -> datetime:
    """SQLite 读回 naive（UTC 墙钟），断言口径统一去 tzinfo。"""
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def _at(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTCD)


async def wait_for(cond, timeout: float = 2.0, what: str = "条件"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"等待超时：{what}")


async def make_user(factory, username="admin", role="admin") -> User:
    async with factory() as s:
        u = User(username=username, password_hash=hash_password("pw12345678"), role=role)
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u


async def make_project(factory, owner_id) -> Project:
    async with factory() as s:
        p = Project(id=uuidlib.uuid4(), name="P1", description=None, doc={}, revision=1, owner_id=owner_id)
        s.add(p)
        await s.commit()
        await s.refresh(p)
        return p


async def count_rows(factory, project_id=None) -> int:
    async with factory() as s:
        q = select(AlarmRecord)
        if project_id is not None:
            q = q.where(AlarmRecord.project_id == project_id)
        return len((await s.execute(q)).scalars().all())


SNAP = {"id": "alm_1", "variableKey": "temp_01", "level": "warn", "message": "温度超高"}


# ---------------- 基座 fixtures（每文件自包含 mini app，契约 §8 集成说明） ----------------

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
def audit_seam(env):
    """audit_service 会话缝指向测试库（C 包提供 monkeypatch 点）。"""
    audit_mod.session_factory = env.factory
    yield
    audit_mod.session_factory = None


_MISS = object()


class _FakeWSManager:
    """ws_manager 打桩（A 未合入时的降级路径验证 + 事件外发断言）。"""

    def __init__(self):
        self.alarm, self.clear, self.ack = [], [], []

    async def broadcast_alarm(self, project_id, alarm):
        self.alarm.append((project_id, alarm))

    async def broadcast_alarm_clear(self, project_id, alarm_id, cleared_at):
        self.clear.append((project_id, alarm_id, cleared_at))

    async def broadcast_alarm_ack(self, project_id, alarm_id, acked_at, acked_by):
        self.ack.append((project_id, alarm_id, acked_at, acked_by))


@pytest.fixture
def fake_ws():
    import app.services as pkg

    fake = _FakeWSManager()
    prev_mod = sys.modules.get("app.services.ws_manager", _MISS)
    prev_attr = getattr(pkg, "ws_manager", _MISS)
    sys.modules["app.services.ws_manager"] = fake
    pkg.ws_manager = fake  # from app.services import ws_manager 属性命中优先
    yield fake
    if prev_mod is _MISS:
        sys.modules.pop("app.services.ws_manager", None)
    else:
        sys.modules["app.services.ws_manager"] = prev_mod
    if prev_attr is _MISS:
        if getattr(pkg, "ws_manager", None) is fake:
            delattr(pkg, "ws_manager")
    else:
        pkg.ws_manager = prev_attr


@pytest.fixture(autouse=True)
def _stub_notify(monkeypatch):
    """notify.send_alarm 打桩（本文件聚焦状态机，外发链路由 test_notify.py 覆盖）。

    阶段二起 send_alarm 会派生并发任务读工程 doc 解析渠道——测试未注入
    notify.session_factory 时落到模块级 SessionLocal（跨 pytest 事件循环的
    StaticPool 连接），其异步扰动会让本文件共享单连接上的 commit/refresh
    交错出 InvalidRequestError（曾致 clear 用例随机挂）。打桩后状态机时序
    与 M8 行为一致。
    """
    from app.services import notify as notify_mod

    async def _noop(rec, rule=None):
        return None

    monkeypatch.setattr(notify_mod, "send_alarm", _noop)


# ---------------- 状态机核心语义（服务层直测） ----------------

async def test_trigger_idempotent_no_new_row(env):
    pid = (await make_project(env.factory, (await make_user(env.factory)).id)).id
    async with env.factory() as db:
        id1 = await alarm_service.trigger(db, pid, SNAP, "95.0", _at(1000))
        id2 = await alarm_service.trigger(db, pid, SNAP, "96.0", _at(2000))
    assert id1 == id2
    assert await count_rows(env.factory, pid) == 1


async def test_trigger_new_row_after_clear(env):
    pid = (await make_project(env.factory, (await make_user(env.factory)).id)).id
    async with env.factory() as db:
        id1 = await alarm_service.trigger(db, pid, SNAP, "95.0", _at(1000))
        assert await alarm_service.clear(db, pid, "alm_1", _at(2000)) == id1
        id2 = await alarm_service.trigger(db, pid, SNAP, "95.0", _at(3000))
    assert id2 != id1
    assert await count_rows(env.factory, pid) == 2


async def test_clear_idempotent_and_keeps_ack_fields(env):
    pid = (await make_project(env.factory, (await make_user(env.factory)).id)).id
    op = await make_user(env.factory, "op", role="operator")
    async with env.factory() as db:
        aid = await alarm_service.trigger(db, pid, SNAP, "95.0", _at(1000))
        await alarm_service.ack(db, pid, aid, op, "已派单")
        cleared_id = await alarm_service.clear(db, pid, "alm_1", _at(3000))
        assert cleared_id == aid
        # 幂等：再 clear 无未恢复行 → None
        assert await alarm_service.clear(db, pid, "alm_1", _at(4000)) is None
        rec = await db.get(AlarmRecord, aid)
    assert rec.status == "cleared"
    assert _naive(rec.cleared_at) == _naive(_at(3000))
    assert rec.acked_note == "已派单" and rec.acked_by == op.id  # ack 字段保留


async def test_ack_flow_idempotent_and_late_ack(env):
    pid = (await make_project(env.factory, (await make_user(env.factory)).id)).id
    op = await make_user(env.factory, "op", role="operator")
    async with env.factory() as db:
        aid = await alarm_service.trigger(db, pid, SNAP, "95.0", _at(1000))
        rec = await alarm_service.ack(db, pid, aid, op, "处理中")
        assert rec.status == "acked" and rec.acked_note == "处理中"
        at1 = _naive(rec.acked_at)
        # 幂等：重复 ack 返回当前态（note 不被覆盖）
        rec2 = await alarm_service.ack(db, pid, aid, op, "改口")
        assert rec2.status == "acked" and rec2.acked_note == "处理中"
        assert _naive(rec2.acked_at) == at1
        # 恢复后迟到补确认：status 保持 cleared，ack 字段不变（已确认过）
        await alarm_service.clear(db, pid, "alm_1", _at(5000))
        rec3 = await alarm_service.ack(db, pid, aid, op, "补")
        assert rec3.status == "cleared" and rec3.acked_note == "处理中"


async def test_ack_unknown_or_cross_project_404(env):
    u = await make_user(env.factory)
    p1 = await make_project(env.factory, u.id)
    p2 = await make_project(env.factory, u.id)
    async with env.factory() as db:
        aid = await alarm_service.trigger(db, p1.id, SNAP, "95.0", _at(1000))
        from app.core.errors import AppError
        with pytest.raises(AppError) as ei:
            await alarm_service.ack(db, p2.id, aid, u, None)  # 跨工程
        assert ei.value.status_code == 404
        with pytest.raises(AppError) as ei2:
            await alarm_service.ack(db, p1.id, 999999, u, None)
        assert ei2.value.status_code == 404


async def test_ack_stale_read_not_overwrite_concurrent_clear(env):
    """竞态回归：ack 读出 triggered 后引擎 clear 先落库 → ack 的条件 UPDATE 不命中，
    不得把 cleared 覆写回 acked（读出态过期时 db.get 命中身份映射旧快照）；
    重读当前行走迟到补确认（status 保持 cleared）；后续同规则触发插新行不被幂等早退吞掉。"""
    pid = (await make_project(env.factory, (await make_user(env.factory)).id)).id
    op = await make_user(env.factory, "op", role="operator")
    async with env.factory() as db:
        aid = await alarm_service.trigger(db, pid, SNAP, "95.0", _at(1000))
        # db 身份映射留有 status=triggered 的读出快照（expire_on_commit=False 不失效），
        # 恰好复现「读」与「写」之间被并发 clear 插入的竞态窗口
        async with env.factory() as s2:
            await alarm_service.clear(s2, pid, "alm_1", _at(2000))
        rec = await alarm_service.ack(db, pid, aid, op, "迟到确认")
        assert rec.status == "cleared"  # 关键：不覆写回 acked
        assert rec.acked_note == "迟到确认" and rec.acked_at is not None
        assert _naive(rec.cleared_at) == _naive(_at(2000))  # clear 时刻保留
        # 旧行已 cleared → 同规则再触发必须插新行（修复前滞留 acked 会被幂等早退静默吞掉）
        aid2 = await alarm_service.trigger(db, pid, SNAP, "96.0", _at(3000))
        assert aid2 != aid
    assert await count_rows(env.factory, pid) == 2


async def test_clear_conditional_update_not_resurrect_conflict(env):
    """clear 条件 UPDATE 回归：clear 之后再 clear（行已不在活动态）rowcount=0 →
    幂等返回 None 且不重复外发；acked 行仍在活动态 → 可被正常 clear（ack 字段保留）。"""
    pid = (await make_project(env.factory, (await make_user(env.factory)).id)).id
    op = await make_user(env.factory, "op", role="operator")
    async with env.factory() as db:
        aid = await alarm_service.trigger(db, pid, SNAP, "95.0", _at(1000))
        await alarm_service.ack(db, pid, aid, op, "处理中")
        assert await alarm_service.clear(db, pid, "alm_1", _at(2000)) == aid
        # 幂等：行已 cleared，条件 UPDATE 不命中 → None 不动作
        assert await alarm_service.clear(db, pid, "alm_1", _at(3000)) is None
        rec = await db.get(AlarmRecord, aid)
    assert rec.status == "cleared" and rec.acked_note == "处理中"  # ack 字段保留


async def test_sweep_on_startup(env):
    u = await make_user(env.factory)
    pid = (await make_project(env.factory, u.id)).id
    async with env.factory() as db:
        await alarm_service.trigger(db, pid, SNAP, "1", _at(1000))
        await alarm_service.trigger(db, pid, {"id": "alm_2", "variableKey": "k", "level": "info", "message": "m"}, "2", _at(1000))
        assert await alarm_service.sweep_on_startup(db) == 2
        assert await alarm_service.sweep_on_startup(db) == 0  # 幂等
        left = (await db.execute(select(AlarmRecord))).scalars().all()
    assert all(r.status == "cleared" and r.cleared_at is not None for r in left)


async def test_cleanup_expired_keeps_active(env, monkeypatch):
    monkeypatch.setattr(settings, "ALARM_RETENTION_DAYS", 1)
    u = await make_user(env.factory)
    pid = (await make_project(env.factory, u.id)).id
    old = datetime.now(UTCD) - timedelta(days=5)
    async with env.factory() as db:
        a_old = await alarm_service.trigger(db, pid, SNAP, "1", old)
        await alarm_service.clear(db, pid, "alm_1", old)
        await alarm_service.trigger(db, pid, {"id": "alm_2", "variableKey": "k", "level": "warn", "message": "m"}, "2", old)
        deleted = await alarm_service.cleanup_expired(db)
    assert deleted == 1  # 只清旧 cleared；旧 triggered 不清理
    async with env.factory() as s:
        left = {r.rule_id: r.status for r in (await s.execute(select(AlarmRecord))).scalars()}
    assert left == {"alm_2": "triggered"}
    assert (await count_rows(env.factory, pid)) == 1


async def test_cleanup_per_project_cap(env, monkeypatch):
    monkeypatch.setattr(settings, "ALARM_MAX_ROWS_PER_PROJECT", 3)
    monkeypatch.setattr(settings, "ALARM_RETENTION_DAYS", 3650)  # 隔离 retention 分支，单测行数上限逻辑
    u = await make_user(env.factory)
    pid = (await make_project(env.factory, u.id)).id
    old = datetime.now(UTCD) - timedelta(days=40)
    async with env.factory() as db:
        # 5 条 cleared（旧→新 c1..c5）+ 1 条 triggered（最老；活动不清理）
        for i in range(5):
            await alarm_service.trigger(db, pid, {**SNAP, "id": f"c{i}"}, str(i), old + timedelta(minutes=i))
            await alarm_service.clear(db, pid, f"c{i}", old + timedelta(minutes=i, seconds=30))
        await alarm_service.trigger(db, pid, {**SNAP, "id": "t0"}, "x", old - timedelta(minutes=1))
        deleted = await alarm_service.cleanup_expired(db)
    assert deleted == 2  # c0/c1 被截断（保留最新 3 行；t0 活动保留）
    async with env.factory() as s:
        left = sorted(r.rule_id for r in (await s.execute(select(AlarmRecord))).scalars())
    assert left == ["c2", "c3", "c4", "t0"]


async def test_active_for_snapshot_level_priority(env):
    u = await make_user(env.factory)
    pid = (await make_project(env.factory, u.id)).id
    async with env.factory() as db:
        await alarm_service.trigger(db, pid, {**SNAP, "id": "i1", "level": "info", "message": "i"}, "1", _at(1000))
        await alarm_service.trigger(db, pid, {**SNAP, "id": "c1", "level": "critical", "message": "c"}, "2", _at(2000))
        await alarm_service.trigger(db, pid, {**SNAP, "id": "w1", "level": "warn", "message": "w"}, "3", _at(3000))
        items = await alarm_service.active_for_snapshot(db, pid, limit=2)
    assert [i["ruleId"] for i in items] == ["c1", "w1"]  # critical > warn > info
    assert items[0]["status"] == "triggered" and isinstance(items[0]["triggeredAt"], int)


# ---------------- REST API（mini app） ----------------

def make_app():
    from fastapi import FastAPI
    from app.api.v1 import alarms as alarms_api

    app = FastAPI()
    register_handlers(app)
    app.include_router(alarms_api.router, prefix="/api/v1")
    return app


@pytest.fixture
async def api(env, audit_seam):
    app = make_app()

    async def _override():
        async with env.factory() as s:
            yield s

    app.dependency_overrides[get_db] = _override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield SimpleNamespace(client=c, app=app)


async def seed_list_rows(env, pid):
    async with env.factory() as s:
        s.add_all(
            [
                AlarmRecord(project_id=pid, rule_id="r1", variable_key="temp_01", level="warn",
                            message="m1", value="1", status="triggered",
                            triggered_at=datetime(2026, 1, 1, 8, 0, tzinfo=UTCD)),
                AlarmRecord(project_id=pid, rule_id="r2", variable_key="temp_02", level="critical",
                            message="m2", value="2", status="acked",
                            triggered_at=datetime(2026, 1, 2, 8, 0, tzinfo=UTCD)),
                AlarmRecord(project_id=pid, rule_id="r3", variable_key="press_01", level="info",
                            message="m3", value="3", status="cleared",
                            triggered_at=datetime(2026, 1, 3, 8, 0, tzinfo=UTCD),
                            cleared_at=datetime(2026, 1, 3, 9, 0, tzinfo=UTCD)),
            ]
        )
        await s.commit()


async def test_list_envelope_and_default_filters_untreated(api, env):
    u = await make_user(env.factory)
    pid = (await make_project(env.factory, u.id)).id
    await seed_list_rows(env, pid)
    api.app.dependency_overrides[get_current_user] = lambda: u
    resp = await api.client.get(f"/api/v1/projects/{pid}/alarms")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2 and body["page"] == 1 and body["size"] == 50
    assert [i["ruleId"] for i in body["items"]] == ["r2", "r1"]  # triggered_at 倒序
    assert body["items"][1]["ackedAt"] is None and body["items"][0]["ackedNote"] is None


async def test_list_filters_status_level_prefix_and_range(api, env):
    u = await make_user(env.factory)
    pid = (await make_project(env.factory, u.id)).id
    await seed_list_rows(env, pid)
    api.app.dependency_overrides[get_current_user] = lambda: u
    c = api.client

    r = await c.get(f"/api/v1/projects/{pid}/alarms", params={"status": "cleared"})
    assert [i["ruleId"] for i in r.json()["items"]] == ["r3"]
    assert r.json()["items"][0]["clearedAt"] is not None

    r = await c.get(f"/api/v1/projects/{pid}/alarms", params={"status": "triggered,acked,cleared", "level": "critical"})
    assert [i["ruleId"] for i in r.json()["items"]] == ["r2"]

    r = await c.get(f"/api/v1/projects/{pid}/alarms", params={"status": "triggered,acked,cleared", "variableKey": "temp"})
    assert sorted(i["ruleId"] for i in r.json()["items"]) == ["r1", "r2"]  # 前缀匹配

    r = await c.get(f"/api/v1/projects/{pid}/alarms", params={
        "status": "triggered,acked,cleared", "from": "2026-01-02T00:00:00Z", "to": "2026-01-02T23:59:59Z"})
    assert [i["ruleId"] for i in r.json()["items"]] == ["r2"]

    r = await c.get(f"/api/v1/projects/{pid}/alarms", params={
        "status": "triggered,acked,cleared", "page": 2, "size": 2})
    assert r.json()["total"] == 3 and [i["ruleId"] for i in r.json()["items"]] == ["r1"]  # 倒序第 3 条

    r = await c.get(f"/api/v1/projects/{pid}/alarms", params={"status": "bogus"})
    assert r.status_code == 422
    r = await c.get(f"/api/v1/projects/{pid}/alarms", params={"level": "fatal"})
    assert r.status_code == 422

    r = await c.get(f"/api/v1/projects/{uuidlib.uuid4()}/alarms")
    assert r.status_code == 404


async def test_rest_ack_success_idempotent_403_and_audit(api, env, fake_ws):
    u = await make_user(env.factory)
    op = await make_user(env.factory, "op1", role="operator")
    viewer = await make_user(env.factory, "viewer1", role="viewer")
    pid = (await make_project(env.factory, u.id)).id
    async with env.factory() as s:
        aid = await alarm_service.trigger(s, pid, SNAP, "95.0", _at(1000))

    # viewer 403
    api.app.dependency_overrides[get_current_user] = lambda: viewer
    r = await api.client.post(f"/api/v1/projects/{pid}/alarms/{aid}/ack", json={"note": "x"})
    assert r.status_code == 403 and r.json()["code"] == "FORBIDDEN"

    # operator 成功 → 200 状态机出参 + alarmAck 广播 + 审计 alarm_ack
    api.app.dependency_overrides[get_current_user] = lambda: op
    r = await api.client.post(f"/api/v1/projects/{pid}/alarms/{aid}/ack", json={"note": "已派单"})
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == aid and body["status"] == "acked" and body["ackedNote"] == "已派单"
    assert body["ackedBy"] == str(op.id)
    await wait_for(lambda: fake_ws.ack, what="alarmAck 广播")
    assert fake_ws.ack[0][1] == aid and fake_ws.ack[0][3] == "op1"

    # 幂等重复 ack：返回当前态，不再广播（审计为操作留痕口径：每次成功 POST 各落一条）
    r2 = await api.client.post(f"/api/v1/projects/{pid}/alarms/{aid}/ack", json={})
    assert r2.status_code == 200 and r2.json()["status"] == "acked"
    assert len(fake_ws.ack) == 1

    async with env.factory() as s:
        logs = (await s.execute(select(AuditLog).where(AuditLog.action == "alarm_ack"))).scalars().all()
    assert len(logs) == 2  # 首次 + 幂等重复各一条（403 未鉴权不落审计）
    assert all(log.username == "op1" and log.target_id == str(aid) for log in logs)

    r = await api.client.post(f"/api/v1/projects/{pid}/alarms/424242/ack", json={})
    assert r.status_code == 404


async def test_rest_ack_note_over_256_422(api, env):
    u = await make_user(env.factory)
    pid = (await make_project(env.factory, u.id)).id
    api.app.dependency_overrides[get_current_user] = lambda: u
    r = await api.client.post(f"/api/v1/projects/{pid}/alarms/1/ack", json={"note": "x" * 257})
    assert r.status_code == 422


async def test_deprecated_alias_and_legacy_report(api, env, fake_ws):
    u = await make_user(env.factory)
    pid = (await make_project(env.factory, u.id)).id
    api.app.dependency_overrides[get_current_user] = lambda: u
    c = api.client

    # GET 别名与 /alarms 同实现（信封口径）
    await seed_list_rows(env, pid)
    r = await c.get(f"/api/v1/projects/{pid}/alarm-records", params={"status": "triggered,acked"})
    assert r.status_code == 200 and r.json()["total"] == 2

    # 旧前端上报：active → trigger（201），recovered → clear
    r = await c.post(f"/api/v1/projects/{pid}/alarm-records", json={
        "ruleId": "alm_9", "variableKey": "k1", "level": "warn", "message": "旧上报", "value": "7", "status": "active"})
    assert r.status_code == 201
    await wait_for(lambda: fake_ws.alarm, what="alarm 帧广播")
    rows = await count_rows(env.factory, pid)
    assert rows == 4
    async with env.factory() as s:
        rec = (await s.execute(select(AlarmRecord).where(AlarmRecord.rule_id == "alm_9"))).scalars().one()
        assert rec.status == "triggered" and rec.value == "7"
    r = await c.post(f"/api/v1/projects/{pid}/alarm-records", json={
        "ruleId": "alm_9", "variableKey": "k1", "level": "warn", "message": "旧上报", "value": "6", "status": "recovered"})
    assert r.status_code == 201
    await wait_for(lambda: fake_ws.clear, what="alarmClear 帧广播")
    async with env.factory() as s:
        rec = (await s.execute(select(AlarmRecord).where(AlarmRecord.rule_id == "alm_9"))).scalars().one()
        assert rec.status == "cleared" and rec.cleared_at is not None
    assert await count_rows(env.factory, pid) == 4  # 单行状态机：恢复不另插新行
