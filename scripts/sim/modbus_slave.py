"""仿真验证台：Modbus TCP 仿真从站（compose sim profile 的 sim-modbus 服务）。

复用 server 镜像运行（pymodbus 已在 server 依赖内），作为「数据源靶场」供
scripts/seed_demo.py 建立的演示工程端到端验证采集 / 解码 / 上屏链路。

寄存器表（与 seed_demo.py 演示工程变量一一对照；地址为 Modbus 规范地址，括号内
为 0 基协议偏移。表外另预置合法零值区——HR 偏移 0~511、COIL/DI 位 0~15——
避免批量点位验证（如 seed 的 --points 500）被 ILLEGAL_ADDRESS 异常打断）：

    HR 40001~40010 (0~9)     int16   正弦计数：后台协程每 1s 更新
                                     （40001 = 启动秒计数；40002~40010 = 幅值 ±10000、
                                      周期 60s、相位逐点错开的正弦，均按 int16 回绕）
    HR 40101~40102 (100~101) float32 = 23.5，ABCD 字序 → 寄存器字 [0x41BC, 0x0000]
    HR 40103~40104 (102~103) float32 = 88.0，CDAB 字序预置 → 寄存器字 [0x0000, 0x42B0]
                                     （推算：88.0 IEEE 754 大端 = 0x42B00000，ABCD 字序
                                      [hi, lo] = [0x42B0, 0x0000]；CDAB = 字交换 →
                                      [lo, hi] = [0x0000, 0x42B0]，与
                                      server/app/services/modbus_codec.py 的
                                      encode_modbus_registers(88.0, "float32", "CDAB") 一致）
    HR 40111~40112 (110~111) int32 = -123456，ABCD → 寄存器字 [0xFFFE, 0x1DC0]
    COIL 00001     (0)       True
    DI   10001     (0)       False

环境变量：MODBUS_HOST（缺省 0.0.0.0）、MODBUS_PORT（缺省 502）。

版本说明：pyproject 约束 pymodbus>=3.9，镜像安装最新 3.x（当前 3.16）。3.16 起
datastore 旧类（ModbusServerContext / ModbusSequentialDataBlock）已弃用且运行时
写入路径失效，故采用现行 SimDevice/SimData + ModbusTcpServer(...).serve_forever()
+ server.async_setValues API（即 StartAsyncTcpServer 的底层，便于同进程跑后台协程）。
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import os
import signal
import struct
import time

from pymodbus.server import ModbusTcpServer
from pymodbus.simulator import SimData, SimDevice
from pymodbus.simulator.simutils import DataType

logging.basicConfig(level=logging.INFO, format="%(asctime)s [sim-modbus] %(levelname)s %(message)s")
log = logging.getLogger("sim-modbus")
logging.getLogger("pymodbus").setLevel(logging.WARNING)  # pymodbus 自身日志降噪

HOST = os.environ.get("MODBUS_HOST", "0.0.0.0")
PORT = int(os.environ.get("MODBUS_PORT", "502"))
UNIT_ID = 1
UPDATE_INTERVAL = 1.0
COUNTER_REGS = 10          # HR 40001~40010
SINE_AMPLITUDE = 10000     # int16 正弦幅值
SINE_PERIOD = 60.0         # 正弦周期（秒）


def _float32_words(value: float) -> list[int]:
    """float → ABCD 大端寄存器字 [hi, lo]（与 modbus_codec 的 >f 打包一致）。"""
    combined = struct.unpack(">I", struct.pack(">f", value))[0]
    return [combined >> 16, combined & 0xFFFF]


def _int32_words(value: int) -> list[int]:
    """int → ABCD 大端寄存器字 [hi, lo]。"""
    combined = value & 0xFFFFFFFF
    return [combined >> 16, combined & 0xFFFF]


# 常量预置表：HR 偏移 → 寄存器字（docstring 寄存器表的机器可读对照）
_CONSTANT_WORDS: dict[int, list[int]] = {
    100: _float32_words(23.5),         # ABCD：[0x41BC, 0x0000]
    102: _float32_words(88.0)[::-1],   # CDAB 字交换：[0x42B0, 0x0000] → [0x0000, 0x42B0]
    110: _int32_words(-123456),        # ABCD：[0xFFFE, 0x1DC0]
}


def _build_device() -> SimDevice:
    """4 区块独立编址（tuple 形式）：coils / discrete inputs / holding / input。"""
    return SimDevice(
        id=UNIT_ID,
        simdata=(
            [SimData(address=0, count=16, values=False, datatype=DataType.BITS)],      # COIL 00001~00016
            [SimData(address=0, count=16, values=False, datatype=DataType.BITS)],      # DI 10001~10016
            [SimData(address=0, count=512, values=0, datatype=DataType.REGISTERS)],    # HR 40001~40512
            [SimData(address=0, count=16, values=0, datatype=DataType.REGISTERS)],     # IR 30001~（表外，全 0）
        ),
    )


async def _preset_constants(server: ModbusTcpServer) -> None:
    """启动时一次性预置常量区（docstring 表中非动态项）。"""
    for offset, words in _CONSTANT_WORDS.items():
        await server.async_setValues(UNIT_ID, 16, offset, words)
    await server.async_setValues(UNIT_ID, 15, 0, [True])  # COIL 00001 = True
    log.info(
        "常量预置完成：40101=23.5(ABCD [0x41BC,0x0000]) 40103=88.0(CDAB [0x0000,0x42B0]) "
        "40111=-123456(ABCD [0xFFFE,0x1DC0]) COIL00001=True"
    )


async def _update_loop(server: ModbusTcpServer, start: float) -> None:
    """后台协程：每 1s 更新 HR 40001~40010（秒计数 + 相位错开的正弦计数）。

    绝对周期调度（next_at 累加），避免 sleep 误差累积漂移。
    """
    next_at = time.monotonic()
    while True:
        elapsed = time.monotonic() - start
        sec = int(elapsed)
        words = [sec & 0xFFFF]
        for i in range(1, COUNTER_REGS):
            phase = 2.0 * math.pi * (elapsed / SINE_PERIOD + i / COUNTER_REGS)
            words.append(int(SINE_AMPLITUDE * math.sin(phase)) & 0xFFFF)
        await server.async_setValues(UNIT_ID, 16, 0, words)
        if sec % 60 == 0:
            log.info(f"运行中 elapsed={sec}s hr40001={words[0]}")
        next_at += UPDATE_INTERVAL
        await asyncio.sleep(max(0.0, next_at - time.monotonic()))


async def main() -> None:
    server = ModbusTcpServer(_build_device(), address=(HOST, PORT))
    serve_task = asyncio.create_task(server.serve_forever())
    log.info(f"Modbus TCP 仿真从站就绪 {HOST}:{PORT}（unitId={UNIT_ID}，寄存器表见脚本 docstring）")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # Windows 本地运行无 add_signal_handler
            loop.add_signal_handler(sig, stop.set)

    start = time.monotonic()
    update_task = asyncio.create_task(_update_loop(server, start))
    try:
        await _preset_constants(server)
        await stop.wait()
    finally:
        update_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await update_task
        await server.shutdown()
        with contextlib.suppress(Exception):
            await serve_task
        log.info("已退出")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
