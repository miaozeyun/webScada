"""采集源存活标记：基类 ticker 与子类 WS 心跳不得同名冲突（回归：曾导致 WS 源全量停采）。"""
import asyncio
import inspect
import uuid as uuidlib
from types import SimpleNamespace

from app.services.collector import BaseSource, UpstreamWsSource


class _FakeSource(BaseSource):
    async def run(self) -> None:  # pragma: no cover - 仅用于实例化
        return None


def test_ws_heartbeat_signature_not_shadowed():
    """UpstreamWsSource._heartbeat 是「向上游发心跳帧」的静态方法，基类不得再定义同名方法。"""
    params = inspect.signature(UpstreamWsSource._heartbeat).parameters
    assert "upstream" in params and "heartbeat_sec" in params
    assert hasattr(BaseSource, "_alive_ticker")


async def test_alive_ticker_advances_last_ok():
    src = _FakeSource(uuidlib.uuid4(), SimpleNamespace(id="ds1", type="websocket", config=None), [])
    assert src.state == "starting" and src.last_ok_ms is None
    task = src._alive_ticker(interval_sec=0.01)
    await asyncio.sleep(0.03)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert src.state == "ok"
    assert src.last_ok_ms is not None
