"""MockSource 首帧语义：慢周期变量也必须立即出首值（2026-10-29 演示案例踩坑回归）。"""
import asyncio
import uuid

import pytest

from app.schemas.doc import VariableDef
from app.services.collector import MockSource


def _var(**mock) -> VariableDef:
    return VariableDef(
        id="v_mock_1", key="mock_1", label="仿真量", type="number",
        datasourceId="ds_mock",
        mock={"kind": "sine", "min": 0, "max": 100, "periodMs": 1_200_000, **mock},
    )


async def test_slow_period_mock_emits_first_frame_immediately():
    """周期 20min（interval=periodMs/24=50s）也必须在 t=0 先推一帧，否则首屏/虚拟变量级联长时间为 0。"""
    src = MockSource(uuid.uuid4(), None, [_var()])  # type: ignore[arg-type]
    calls: list[float] = []
    src._ingest = lambda _v, raw, _ts=None: calls.append(raw)  # type: ignore[method-assign]

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(src.run(), timeout=0.2)

    assert calls, "首帧未立即推送：慢周期变量会等 periodMs/24 才出值"
    assert 0 <= calls[0] <= 100


async def test_hold_variable_only_pushes_default_once():
    """hold 保持型仍只推 defaultValue，不进入周期采样。"""
    var = VariableDef(
        id="v_hold_1", key="hold_1", label="保持量", type="number",
        datasourceId="ds_mock", defaultValue=42,
        mock={"kind": "hold"},
    )
    src = MockSource(uuid.uuid4(), None, [var])  # type: ignore[arg-type]
    calls: list[float] = []
    src._ingest = lambda _v, raw, _ts=None: calls.append(raw)  # type: ignore[method-assign]

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(src.run(), timeout=0.2)

    assert calls == [42]
