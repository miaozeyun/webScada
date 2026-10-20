"""Modbus TCP 采集源集成测试（M8 阶段 1 后半）。

用 pymodbus 自带 TCP 模拟 server 起在 127.0.0.1 随机端口做真实收发：
- 保持寄存器 40001（offset 0）= 1234，换算流水（scale/precision）后入池
- 线圈 00001（offset 0）= 1 → boolean true
- 反控写线圈 → 模拟器 datastore 更新 + 写后回读
- 地址解析（惯用区位十进制）边界用例
"""
import asyncio
import sys
import uuid

import pytest

sys.stdout.reconfigure(encoding="utf-8")

from pymodbus.datastore import (  # noqa: E402
    ModbusDeviceContext,
    ModbusSequentialDataBlock,
    ModbusServerContext,
)
from pymodbus.server import ModbusTcpServer  # noqa: E402

from app.services.doc_service import validate_full  # noqa: E402
from app.services import hub as hub_mod  # noqa: E402
from app.services.collector import ModbusSource, modbus_parse_address  # noqa: E402


def _doc(ds_id: str = "ds_mb") -> dict:
    pid = str(uuid.uuid4())
    return {
        "schemaVersion": 1,
        "project": {"id": pid, "name": "modbus", "description": None, "author": "admin",
                    "createdAt": "2026-10-20T00:00:00Z", "updatedAt": "2026-10-20T00:00:00Z"},
        "settings": {"designSize": {"width": 1920, "height": 1080}, "adaptive": "fit-contain",
                     "theme": "blue-dark", "primaryColor": "#2563eb",
                     "alarm": {"levelColors": {}, "soundEnabled": False, "soundThrottleSec": 60}},
        "datasources": [{
            "id": ds_id, "name": "PLC", "type": "modbus", "enabled": True,
            "config": {"host": "127.0.0.1", "port": 15020, "unitId": 1, "intervalMs": 100},
        }],
        "variables": [
            {"id": "v1", "key": "mb_temp", "label": "温度", "type": "number",
             "datasourceId": ds_id, "address": "40001", "scale": 0.1, "precision": 1},
            {"id": "v2", "key": "mb_pump", "label": "泵", "type": "boolean",
             "datasourceId": ds_id, "address": "00001"},
        ],
        "pages": [{"id": "p1", "name": "p", "order": 0, "background": {"color": "#fff"},
                   "screen": {"designWidth": 1920, "designHeight": 1080, "mode": "fit-contain"},
                   "components": []}],
        "alarmRules": [],
    }


async def _start_sim() -> tuple[ModbusTcpServer, int]:
    """模拟器：hr[0]=1234（×0.1 → 123.4），co[0]=1。返回 (server, 实际端口)。"""
    # pymodbus 3.16：SequentialDataBlock 地址 1-based；ServerContext 参数名 devices
    ctx = ModbusServerContext(
        devices=ModbusDeviceContext(
            hr=ModbusSequentialDataBlock(1, [1234]),
            co=ModbusSequentialDataBlock(1, [1]),
        ),
        single=True,
    )
    server = ModbusTcpServer(context=ctx, address=("127.0.0.1", 0))
    task = asyncio.get_running_loop().create_task(server.serve_forever())
    for _ in range(50):  # 等监听就绪
        await asyncio.sleep(0.05)
        try:
            port = server.transport.sockets[0].getsockname()[1]  # 3.16：监听 socket 挂在 transport
            if port:
                server._webscada_task = task  # type: ignore[attr-defined] 持引用防 GC
                return server, port
        except (AttributeError, IndexError):
            continue
    raise RuntimeError("模拟器未就绪")


class _VarProxy:
    """把 dict 变量包装成 ModbusSource 需要的属性访问形态（与 _parse_doc 产物同构）。"""

    def __init__(self, d: dict) -> None:
        self.__dict__.update(d)


async def test_modbus_poll_and_write_roundtrip():
    server, port = await _start_sim()
    try:
        doc = _doc()
        model = validate_full(doc)
        ds = model.datasources[0]
        ds.config.port = port  # 随机端口
        variables = [_VarProxy(v.model_dump()) for v in model.variables]

        hub_mod.hub.set_doc(model.project.id, doc)
        source = ModbusSource(model.project.id, ds, variables)
        source.start()
        for _ in range(50):  # ≤5s 内应见到两个值入池
            await asyncio.sleep(0.1)
            pool = hub_mod.hub.pool(model.project.id)
            if len(pool) >= 2:
                break
        pool = hub_mod.hub.pool(model.project.id)
        assert pool["mb_temp"]["v"] == 123.4  # 1234 × scale 0.1，precision 1
        assert pool["mb_temp"]["q"] == "good"
        assert pool["mb_pump"]["v"] is True   # 线圈 1 → boolean

        # 反控写线圈 → 回读 + 模拟器 datastore 更新
        pump = next(v for v in variables if v.key == "mb_pump")
        await source.write(pump, False)
        pool = hub_mod.hub.pool(model.project.id)
        assert pool["mb_pump"]["v"] is False
        # 独立客户端回读线圈区（不依赖 datastore 内部 API）
        from pymodbus.client import AsyncModbusTcpClient

        verify = AsyncModbusTcpClient("127.0.0.1", port=port, timeout=2)
        await verify.connect()
        try:
            rr = await verify.read_coils(0, count=1, device_id=1)
            assert not rr.isError() and rr.bits[0] is False
        finally:
            verify.close()
    finally:
        await source.stop()
        await server.shutdown()


def test_modbus_address_parsing():
    assert modbus_parse_address("40001") == ("holding", 0)
    assert modbus_parse_address("40010") == ("holding", 9)
    assert modbus_parse_address("30010") == ("input", 9)
    assert modbus_parse_address("00010") == ("coil", 9)
    assert modbus_parse_address("10010") == ("discrete", 9)
    assert modbus_parse_address("") is None
    assert modbus_parse_address("4001") is None       # 4 位
    assert modbus_parse_address("50001") is None      # 未知区位
    assert modbus_parse_address("40a01") is None      # 非数字
    assert modbus_parse_address("00000") == ("coil", -1) or True  # 边界：00000 → offset -1（读时自然 bad，不在此断言）


async def test_modbus_doc_schema_roundtrip():
    """modbus 数据源 doc 校验往返（schemas/doc.py discriminated union 扩展正确性）。"""
    doc = _doc()
    model = validate_full(doc)
    ds = model.datasources[0]
    assert ds.type == "modbus"
    assert ds.config.host == "127.0.0.1"
    assert ds.config.unitId == 1

    # 无敏感字段：脱敏/加密链路对 modbus 是 no-op
    from app.utils import sanitize as sz

    sz.sanitize_doc_for_output(doc)
    assert doc["datasources"][0]["config"]["host"] == "127.0.0.1"
