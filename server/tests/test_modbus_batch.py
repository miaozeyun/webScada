"""ModbusSource 批量读分组 + 32 位解码 + 变量级 unitId 测试（工厂可用阶段一 Task 4）。

三层验证：
- plan_modbus_reads 纯函数：连续/小间隙合并、单组 120 字上限、不跨 unit/区合并、非法地址跳过；
- run 循环（FakeClient 桩替 pymodbus 客户端，monkeypatch pymodbus.client.AsyncModbusTcpClient）：
  按组一次读、组内按 offset 切片解码、变量级 unitId 覆盖源级、非法地址每轮标 bad。
  run 测试模式：intervalMs=60s → asyncio.wait_for(0.5s) 超时内恰跑一轮（首轮立即执行、随后长睡被取消）。
- write（Task 5）：float32 按 dataType 编码走 write_registers 双字、int16 仍 write_register 单值、
  coil 写 bool 不变；unitId 解析与读路径一致（变量级优先回落源级）。
"""
import asyncio
import sys
import uuid
from typing import Any

import pytest

sys.stdout.reconfigure(encoding="utf-8")

from app.schemas.doc import ModbusConfig, ModbusDataSource, VariableDef  # noqa: E402
from app.services.collector import ModbusSource, plan_modbus_reads  # noqa: E402


# ---------------- 构造辅助 ----------------


def _var(key: str, address: str, *, vtype: str = "number", **kwargs: Any) -> VariableDef:
    """最小合法变量（datasourceId 固定 ds_mb；modbus 三字段经 kwargs 透传）。"""
    return VariableDef(
        id=f"var_{key}", key=key, label=key, type=vtype, datasourceId="ds_mb", address=address, **kwargs
    )


def _ds(**cfg_kwargs: Any) -> ModbusDataSource:
    """modbus 数据源（intervalMs=60000：run 测试 0.5s 超时窗口内恰一轮）。"""
    cfg: dict[str, Any] = {"host": "127.0.0.1", "port": 502, "unitId": 1, "intervalMs": 60000}
    cfg.update(cfg_kwargs)
    return ModbusDataSource(id="ds_mb", name="PLC", type="modbus", enabled=True, config=ModbusConfig(**cfg))


class _ReadResult:
    """读应答桩：携带 .registers / .bits，isError() 恒 False。"""

    def __init__(self, *, registers: list[int] | None = None, bits: list[bool] | None = None) -> None:
        self.registers = registers or []
        self.bits = bits or []

    def isError(self) -> bool:
        return False


class FakeClient:
    """pymodbus 客户端桩：无参构造（run 内以 host/port/timeout 构造，全部吞掉）。

    寄存器/线圈状态与读调用记录存类级容器——run 在协程内部自建客户端实例，
    测试经类属性预置状态、读取调用记录（每个用例先 _reset_fake 清场）。
    """

    calls: list[tuple[Any, ...]] = []          # (method, offset, count, device_id)
    registers: dict[int, int] = {}             # offset → word
    bits: dict[int, bool] = {}                 # offset → bit
    connected: bool = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.connected = True

    async def connect(self) -> None:
        self.connected = True

    def close(self) -> None:
        pass

    async def read_holding_registers(self, offset: int, count: int = 1, device_id: int = 1) -> _ReadResult:
        self.calls.append(("read_holding_registers", offset, count, device_id))
        return _ReadResult(registers=[self.registers.get(offset + i, 0) for i in range(count)])

    async def read_input_registers(self, offset: int, count: int = 1, device_id: int = 1) -> _ReadResult:
        self.calls.append(("read_input_registers", offset, count, device_id))
        return _ReadResult(registers=[self.registers.get(offset + i, 0) for i in range(count)])

    async def read_coils(self, offset: int, count: int = 1, device_id: int = 1) -> _ReadResult:
        self.calls.append(("read_coils", offset, count, device_id))
        return _ReadResult(bits=[self.bits.get(offset + i, False) for i in range(count)])

    async def read_discrete_inputs(self, offset: int, count: int = 1, device_id: int = 1) -> _ReadResult:
        self.calls.append(("read_discrete_inputs", offset, count, device_id))
        return _ReadResult(bits=[self.bits.get(offset + i, False) for i in range(count)])

    # -- 写桩（Task 5）：记录 (method, offset, value/values, device_id)，isError 恒 False --

    async def write_coil(self, offset: int, value: bool, device_id: int = 1) -> _ReadResult:
        self.calls.append(("write_coil", offset, bool(value), device_id))
        return _ReadResult(bits=[bool(value)])

    async def write_register(self, offset: int, value: int, device_id: int = 1) -> _ReadResult:
        self.calls.append(("write_register", offset, value, device_id))
        return _ReadResult(registers=[value])

    async def write_registers(self, offset: int, values: list[int], device_id: int = 1) -> _ReadResult:
        self.calls.append(("write_registers", offset, list(values), device_id))
        return _ReadResult(registers=list(values))


def _reset_fake(registers: dict[int, int] | None = None, bits: dict[int, bool] | None = None) -> None:
    """清场并预置寄存器/线圈状态。"""
    FakeClient.calls.clear()
    FakeClient.registers = registers or {}
    FakeClient.bits = bits or {}


async def _run_one_round(monkeypatch: pytest.MonkeyPatch, source: ModbusSource) -> dict[str, Any]:
    """monkeypatch _ingest 收集 (key, raw)，跑 run 至 0.5s 超时（恰一轮），返回 key → raw。"""
    ingested: list[tuple[str, Any]] = []
    monkeypatch.setattr(source, "_ingest", lambda var, raw, ts=None: ingested.append((var.key, raw)))
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(source.run(), timeout=0.5)
    return dict(ingested)


# ---------------- plan_modbus_reads 纯函数 ----------------


def test_plan_merges_contiguous_and_small_gaps():
    # 40001/40002/40004 → offset 0/1/3：间隙 0、2 均 ≤2 → 1 组 count=4（含小空洞）
    groups = plan_modbus_reads([_var("a", "40001"), _var("b", "40002"), _var("c", "40004")], 1)
    assert len(groups) == 1
    g = groups[0]
    assert (g.unit_id, g.area, g.start, g.count) == (1, "holding", 0, 4)
    assert [(v.key, off, w) for v, off, w in g.items] == [("a", 0, 1), ("b", 1, 1), ("c", 3, 1)]


def test_plan_respects_120_register_cap():
    # 500 个连续 int16（40001~40500）→ 4 组 120 字 + 1 组 20 字 = 5 组
    vars_ = [_var(f"v{i:03d}", str(40001 + i)) for i in range(500)]
    groups = plan_modbus_reads(vars_, 1)
    assert len(groups) == 5
    assert max(g.count for g in groups) == 120
    assert sum(g.count for g in groups) == 500
    assert [g.start for g in groups] == [0, 120, 240, 360, 480]
    assert groups[-1].count == 20


def test_plan_not_merge_across_unit_or_area():
    # unitId 不同 → 2 组（变量级 unitId 覆盖源级缺省）
    groups = plan_modbus_reads([_var("u1", "40001"), _var("u2", "40002", unitId=2)], 1)
    assert len(groups) == 2
    assert {(g.unit_id, g.start) for g in groups} == {(1, 0), (2, 1)}
    # holding / input 同 offset 也各成一组（area 不同不合并）
    groups2 = plan_modbus_reads([_var("h", "40001"), _var("i", "30001")], 1)
    assert len(groups2) == 2
    assert {g.area for g in groups2} == {"holding", "input"}


def test_plan_skips_invalid_address():
    groups = plan_modbus_reads([_var("ok", "40001"), _var("bad", "abc")], 1)
    assert len(groups) == 1
    assert [v.key for v, _, _ in groups[0].items] == ["ok"]  # 非法地址不入组


# ---------------- run 循环（FakeClient） ----------------


async def test_run_reads_group_once(monkeypatch):
    _reset_fake({0: 11, 1: 22, 2: 33})
    monkeypatch.setattr("pymodbus.client.AsyncModbusTcpClient", FakeClient)
    source = ModbusSource(uuid.uuid4(), _ds(), [_var("a", "40001"), _var("b", "40002"), _var("c", "40003")])
    ingested = await _run_one_round(monkeypatch, source)
    # 3 个连续变量 → read_holding_registers 恰 1 次（一轮内），count=3
    assert FakeClient.calls == [("read_holding_registers", 0, 3, 1)]
    assert ingested == {"a": 11, "b": 22, "c": 33}


async def test_run_slices_group_words_per_var(monkeypatch):
    # 同组 int16@40101（offset 100，1 字）+ float32@40102（offset 101，占 101~102）：
    # 组 start=100 count=3 一次读回，按 offset 切片——float 解得 100.0（0x42C8,0x0000 / ABCD）
    _reset_fake({100: 1234, 101: 0x42C8, 102: 0x0000})
    monkeypatch.setattr("pymodbus.client.AsyncModbusTcpClient", FakeClient)
    source = ModbusSource(
        uuid.uuid4(), _ds(), [_var("i16", "40101"), _var("f32", "40102", modbusDataType="float32")]
    )
    ingested = await _run_one_round(monkeypatch, source)
    assert FakeClient.calls == [("read_holding_registers", 100, 3, 1)]
    assert ingested == {"i16": 1234, "f32": 100.0}


async def test_run_var_level_unit_id(monkeypatch):
    _reset_fake({0: 7})
    monkeypatch.setattr("pymodbus.client.AsyncModbusTcpClient", FakeClient)
    source = ModbusSource(uuid.uuid4(), _ds(unitId=1), [_var("plc2", "40001", unitId=2)])
    ingested = await _run_one_round(monkeypatch, source)
    assert ingested == {"plc2": 7}
    assert FakeClient.calls == [("read_holding_registers", 0, 1, 2)]  # 变量级 unitId=2 覆盖源级 1


async def test_run_marks_bad_for_invalid_address(monkeypatch):
    _reset_fake({0: 5})
    monkeypatch.setattr("pymodbus.client.AsyncModbusTcpClient", FakeClient)
    source = ModbusSource(uuid.uuid4(), _ds(), [_var("bad", "abc"), _var("ok", "40001")])
    ingested = await _run_one_round(monkeypatch, source)
    assert ingested == {"bad": None, "ok": 5}  # 非法地址每轮标 bad，合法变量正常入池


# ---------------- write（多寄存器编码，Task 5） ----------------


def _patch_ingest(monkeypatch: pytest.MonkeyPatch, source: ModbusSource) -> list[tuple[str, Any]]:
    """monkeypatch 实例 _ingest 收集 (key, raw)——write 不经 run，须替掉 _hub 依赖。"""
    ingested: list[tuple[str, Any]] = []
    monkeypatch.setattr(source, "_ingest", lambda var, raw, ts=None: ingested.append((var.key, raw)))
    return ingested


async def test_write_float32_encodes_two_registers(monkeypatch):
    # float32 100.0 @40101（offset 100）→ write_registers(100, [0x42C8, 0x0000], device_id=1)
    _reset_fake()
    monkeypatch.setattr("pymodbus.client.AsyncModbusTcpClient", FakeClient)
    source = ModbusSource(uuid.uuid4(), _ds(), [_var("f32", "40101", modbusDataType="float32")])
    ingested = _patch_ingest(monkeypatch, source)
    await source.write(source.variables[0], 100.0)
    assert FakeClient.calls == [("write_registers", 100, [0x42C8, 0x0000], 1)]
    assert ingested == [("f32", 100.0)]  # 写后本地回环 _ingest 写入值


async def test_write_int16_single_register_with_var_unit_id(monkeypatch):
    # int16（缺省 dataType）仍走 write_register 单值；变量级 unitId=2 覆盖源级 1
    _reset_fake()
    monkeypatch.setattr("pymodbus.client.AsyncModbusTcpClient", FakeClient)
    source = ModbusSource(uuid.uuid4(), _ds(unitId=1), [_var("i16", "40005", unitId=2)])
    ingested = _patch_ingest(monkeypatch, source)
    await source.write(source.variables[0], 123)
    assert FakeClient.calls == [("write_register", 4, 123, 2)]
    assert ingested == [("i16", 123)]


async def test_write_coil_bool_unchanged(monkeypatch):
    # coil 区写 bool 走 write_coil，语义不变（unitId 回落源级 1）
    _reset_fake()
    monkeypatch.setattr("pymodbus.client.AsyncModbusTcpClient", FakeClient)
    source = ModbusSource(uuid.uuid4(), _ds(), [_var("c1", "00003", vtype="boolean")])
    ingested = _patch_ingest(monkeypatch, source)
    await source.write(source.variables[0], True)
    assert FakeClient.calls == [("write_coil", 2, True, 1)]
    assert ingested == [("c1", True)]
