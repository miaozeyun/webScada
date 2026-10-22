"""仿真验证台：OPC UA 模拟服务（compose sim profile 的 sim-opcua 服务）。

复用 server 镜像运行（asyncua 已在 server 依赖内），作为「数据源靶场」供演示工程
端到端验证 OPC UA 采集 / 订阅推送 / browse / 反控链路。

节点表（ns=2 = http://webscada.local/sim，与 seed_demo/测试 fixture 一一对照）：

    ns=2;s=demo.temp    Float   周期正弦 20~90（周期 60s，1s 更新一次；可写，写后恢复自动变化）
    ns=2;s=demo.press   Float   恒 0.75（静态常量）
    ns=2;s=demo.state   Bool    缺省 False（可写：反控演示，写值经订阅推回）

变量 address 即 nodeId 字符串（如 ns=2;s=demo.temp）；browse 缺省根为 Objects(i=85)，
下钻 Objects → demo 文件夹可见三节点。

环境变量：OPCUA_ENDPOINT（缺省 opc.tcp://0.0.0.0:4840/webscada/sim/）。

版本说明：pyproject 约束 asyncua>=2.0（实装 2.1.0）。2.x 与旧文档 API 的偏差
（Server 无 shutdown 用 stop、动态端口取 bserver.port、订阅回调 data 为 DataChangeNotif）
按实装编写，详见 docs/经验教训.md 2026-10-22 条目。
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import os
import signal
import sys
import time

from asyncua import Server

logging.basicConfig(level=logging.INFO, format="%(asctime)s [sim-opcua] %(levelname)s %(message)s")
log = logging.getLogger("sim-opcua")

ENDPOINT = os.environ.get("OPCUA_ENDPOINT", "opc.tcp://0.0.0.0:4840/webscada/sim/")
NS_URI = "http://webscada.local/sim"
UPDATE_INTERVAL = 1.0     # temp 更新周期（秒）
SINE_MIN, SINE_MAX = 20.0, 90.0
SINE_PERIOD = 60.0


async def main() -> None:
    srv = Server()
    await srv.init()
    srv.set_endpoint(ENDPOINT)
    idx = await srv.register_namespace(NS_URI)

    # 显式字符串 nodeId：add_variable(nodeid, qualified_name) 两参显式形式
    # （int 首参形式生成数字 nodeId，无法与变量 address="ns=2;s=..." 对齐）
    demo = await srv.nodes.objects.add_folder(f"ns={idx};s=demo", f"{idx}:demo")
    temp = await demo.add_variable(f"ns={idx};s=demo.temp", f"{idx}:temp", SINE_MIN)
    press = await demo.add_variable(f"ns={idx};s=demo.press", f"{idx}:press", 0.75)
    state = await demo.add_variable(f"ns={idx};s=demo.state", f"{idx}:state", False)
    await temp.set_writable()   # 反控演示：temp/state 可写
    await state.set_writable()
    _ = press

    await srv.start()
    host, port = srv.bserver.hostname, srv.bserver.port
    log.info(
        f"OPC UA 仿真服务就绪 {host}:{port}（ns={idx}={NS_URI}，节点表：demo.temp/demo.press/demo.state，"
        f"temp 周期正弦 {SINE_MIN}~{SINE_MAX}）"
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # Windows 本地运行无 add_signal_handler
            loop.add_signal_handler(sig, stop.set)

    async def _update_loop(start: float) -> None:
        """temp 周期正弦（绝对周期调度，防 sleep 误差累积）。"""
        next_at = time.monotonic()
        while True:
            elapsed = time.monotonic() - start
            p = 0.5 + 0.5 * math.sin(2.0 * math.pi * elapsed / SINE_PERIOD)
            await temp.write_value(SINE_MIN + (SINE_MAX - SINE_MIN) * p)
            next_at += UPDATE_INTERVAL
            await asyncio.sleep(max(0.0, next_at - time.monotonic()))

    update_task = asyncio.create_task(_update_loop(time.monotonic()))
    try:
        await stop.wait()
    finally:
        update_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await update_task
        await srv.stop()
        log.info("已退出")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
