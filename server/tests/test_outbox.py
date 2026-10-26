"""通知补发队列（阶段三）：失败入队、到期补发、指数退避、死信、去重。"""
import uuid as uuidlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import NotificationOutbox
from app.services import notify

UTCD = timezone.utc


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
def seam(env, monkeypatch):
    monkeypatch.setattr(notify, "session_factory", env.factory)
    notify.reset_notify_state()
    yield
    notify.reset_notify_state()


def make_rec(rule_id: str = "r1"):
    return SimpleNamespace(
        id=17,
        project_id=uuidlib.uuid4(),
        rule_id=rule_id,
        variable_key="temp",
        level="critical",
        message="温度超高",
        value="100",
        status="triggered",
        triggered_at=datetime(2026, 1, 1, tzinfo=UTCD),
    )


async def rows(env):
    async with env.factory() as s:
        return list((await s.execute(select(NotificationOutbox))).scalars())


async def test_failed_channel_enqueues_once(env, monkeypatch):
    async def channels(_pid):
        return [{"kind": "webhook", "url": "https://example.com/hook", "minLevel": "warn"}]

    async def fail(_channel, _rec, _rule):
        return False, "boom"

    monkeypatch.setattr(notify, "get_project_channels", channels)
    monkeypatch.setattr(notify, "_dispatch_channel", fail)

    rec = make_rec()
    await notify.send_alarm(rec, {"id": "r1", "name": "温度超高"})
    await notify.send_alarm(rec, {"id": "r1", "name": "温度超高"})  # 同 alarm+渠道去重

    got = await rows(env)
    assert len(got) == 1
    assert got[0].status == "pending" and got[0].attempts == 0
    assert got[0].channel_kind == "webhook"
    assert got[0].payload_json["rec"]["rule_id"] == "r1"
    # URL 内嵌 access_token，落库必须加密（K11）
    assert got[0].channel_json["url"].startswith("FER1:")


async def test_process_outbox_marks_sent(env, monkeypatch):
    sent_urls: list[str] = []

    async def channels(_pid):
        return [{"kind": "webhook", "url": "https://example.com/hook", "minLevel": "warn"}]

    async def fail(_channel, _rec, _rule):
        return False, "boom"

    async def ok(channel, _rec, _rule):
        sent_urls.append(channel["url"])
        return True, None

    monkeypatch.setattr(notify, "get_project_channels", channels)
    monkeypatch.setattr(notify, "_dispatch_channel", fail)
    await notify.send_alarm(make_rec(), {"id": "r1"})

    async with env.factory() as s:
        await s.execute(update(NotificationOutbox).values(next_at=datetime.now(UTCD) - timedelta(seconds=1)))
        await s.commit()

    monkeypatch.setattr(notify, "_dispatch_channel", ok)
    assert await notify.process_outbox() == 1
    got = await rows(env)
    assert got[0].status == "sent" and got[0].sent_at is not None
    assert sent_urls == ["https://example.com/hook"]  # 补发时解密还原


async def test_process_outbox_retries_then_dead(env, monkeypatch):
    async def channels(_pid):
        return [{"kind": "webhook", "url": "https://example.com/hook", "minLevel": "warn"}]

    async def fail(_channel, _rec, _rule):
        return False, "boom"

    monkeypatch.setattr(notify, "get_project_channels", channels)
    monkeypatch.setattr(notify, "_dispatch_channel", fail)
    await notify.send_alarm(make_rec(), {"id": "r1"})

    for _ in range(8):
        async with env.factory() as s:
            await s.execute(update(NotificationOutbox).values(next_at=datetime.now(UTCD) - timedelta(seconds=1)))
            await s.commit()
        await notify.process_outbox()

    got = await rows(env)
    assert got[0].status == "dead" and got[0].attempts == 8
    assert got[0].last_error


async def test_cleanup_outbox_keeps_pending(env, monkeypatch):
    from app.services import notify as notify_mod

    now = datetime.now(UTCD)
    pid = uuidlib.uuid4()
    async with env.factory() as s:
        s.add_all([
            NotificationOutbox(project_id=pid, alarm_id=1, event="trigger", channel_kind="webhook",
                               channel_json={}, payload_json={}, status="sent",
                               next_at=now, attempts=1, sent_at=now - timedelta(days=10)),
            NotificationOutbox(project_id=pid, alarm_id=2, event="trigger", channel_kind="webhook",
                               channel_json={}, payload_json={}, status="dead",
                               next_at=now, attempts=8, created_at=now - timedelta(days=40)),
            NotificationOutbox(project_id=pid, alarm_id=3, event="trigger", channel_kind="webhook",
                               channel_json={}, payload_json={}, status="pending",
                               next_at=now, attempts=0, created_at=now - timedelta(days=40)),
        ])
        await s.commit()
        assert await notify_mod.cleanup_outbox(s) == 2
    got = await rows(env)
    assert len(got) == 1 and got[0].status == "pending"


async def test_recovery_bypasses_trigger_throttle(env, monkeypatch):
    sent: list[str] = []

    async def channels(_pid):
        return [{"kind": "webhook", "url": "https://example.com/hook", "minLevel": "warn"}]

    async def ok(_channel, rec, _rule):
        sent.append(getattr(rec, "status", ""))
        return True, None

    monkeypatch.setattr(notify, "get_project_channels", channels)
    monkeypatch.setattr(notify, "_dispatch_channel", ok)

    rec = make_rec()
    await notify.send_alarm(rec, {"id": "r1"})
    await notify.send_alarm(rec, {"id": "r1"})  # 节流窗口内：不再发
    recovered = SimpleNamespace(**{**rec.__dict__, "status": "cleared"})
    await notify.send_recovery(recovered)

    assert sent == ["triggered", "cleared"]
