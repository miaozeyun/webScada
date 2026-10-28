"""仿真验证台：上游 WebSocket 推流服务（数据源类型 websocket 的假接口）。

用途：验证工程里「WebSocket」数据源（UpstreamWsSource，server/app/services/collector.py）
的连接/解析/断线重连，而不需要真实设备网关。注意它模拟的是**上游**：服务端 collector 主动
连过来订阅；浏览器侧看到的 /api/v1/ws/runtime 仍由服务端生成，与本脚本无关。

帧格式（每秒一帧，字段与 mqtt_gateway.py 的语义保持一致，可直接对照）：

    {
      "ts": 1730000000000,
      "line1": {"temp": 62.4, "press": 0.62, "run": 1},
      "line2": {"temp": 41.2, "press": 0.51, "run": 0},
      "line3": {"temp": 78.9, "press": 0.73, "run": 1}
    }

    temp  ：正弦 20~85 ℃，line1/2/3 周期 60/90/120s 错相（line1 首轮必扫过 80，
            可触发 seed 演示工程的 line1_temp > 75 报警）
    press ：正弦 0.4~0.8 MPa，周期 45s
    run   ：0/1 每秒交替（boolean 点位）

变量配置示例（地址=第一层键，jsonPath=第二层）：
    address="line1"  jsonPath="temp"
也可把值平铺到根上（address="line1_temp"），jsonPath 留空。

启动：
    server/.venv/Scripts/python scripts/sim/ws_feed.py          # Windows
    server/.venv/bin/python scripts/sim/ws_feed.py              # Linux/macOS
    （websockets 是 server 依赖，宿主机全局 Python 可能没装）

数据源 URL 填法（关键）：
    server 裸跑在宿主机            ws://127.0.0.1:8765
    server 在 compose 容器内       ws://host.docker.internal:8765
    server 在不支持上面别名的环境    ws://<宿主机局域网 IP>:8765

环境变量：
    WS_FEED_HOST  缺省 0.0.0.0
    WS_FEED_PORT  缺省 8765
    WS_FEED_PERIOD_MS  缺省 1000
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import time
from typing import Any

import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s [sim-ws-feed] %(levelname)s %(message)s")
log = logging.getLogger("sim-ws-feed")

HOST = os.environ.get("WS_FEED_HOST", "0.0.0.0")
PORT = int(os.environ.get("WS_FEED_PORT", "8765"))
PERIOD = max(0.1, int(os.environ.get("WS_FEED_PERIOD_MS", "1000")) / 1000)

DEVICES = ("line1", "line2", "line3")
# 周期（秒）、初相弧度；与 mqtt_gateway.py 的温度剖面一致
_TEMP_PROFILE: dict[str, tuple[float, float]] = {
    "line1": (60.0, 0.0),
    "line2": (90.0, 2.0 * math.pi / 3.0),
    "line3": (120.0, 4.0 * math.pi / 3.0),
}
TEMP_MIN, TEMP_MAX = 20.0, 85.0
PRESS_MIN, PRESS_MAX, PRESS_PERIOD = 0.4, 0.8, 45.0

_clients: set[Any] = set()
_started = time.monotonic()


def build_frame(elapsed: float) -> dict[str, Any]:
    frame: dict[str, Any] = {"ts": int(time.time() * 1000)}
    for idx, dev in enumerate(DEVICES):
        period, phase = _TEMP_PROFILE[dev]
        angle = 2.0 * math.pi * elapsed / period + phase
        temp = TEMP_MIN + (TEMP_MAX - TEMP_MIN) * (0.5 + 0.5 * math.sin(angle))
        press = PRESS_MIN + (PRESS_MAX - PRESS_MIN) * (0.5 + 0.5 * math.sin(2.0 * math.pi * elapsed / PRESS_PERIOD))
        frame[dev] = {
            "temp": round(temp, 2),
            "press": round(press, 3),
            "run": int(elapsed) % 2,  # 每秒交替的 0/1 点位
        }
    return frame


async def _broadcast_loop() -> None:
    while True:
        await asyncio.sleep(PERIOD)
        if not _clients:
            continue
        payload = json.dumps(build_frame(time.monotonic() - _started), ensure_ascii=False)
        # gather 容错：单个连接发送失败不影响其他连接
        results = await asyncio.gather(*(c.send(payload) for c in list(_clients)), return_exceptions=True)
        for client, result in zip(list(_clients), results):
            if isinstance(result, Exception):
                _clients.discard(client)


async def _handler(websocket: Any, *_args: Any) -> None:
    peer = getattr(websocket, "remote_address", None)
    _clients.add(websocket)
    log.info("上游连接建立 %s（当前 %d 个）", peer, len(_clients))
    try:
        # 首帧立即推一次，避免 collector 连上后等一个周期才有值
        await websocket.send(json.dumps(build_frame(time.monotonic() - _started), ensure_ascii=False))
        async for message in websocket:
            # 订阅帧/心跳帧（"{}"）一律忽略；需要回执时在此扩展
            log.debug("收到客户端帧：%s", message)
    except Exception:  # noqa: BLE001 - 客户端断开按正常关闭处理
        pass
    finally:
        _clients.discard(websocket)
        log.info("上游连接关闭 %s（当前 %d 个）", peer, len(_clients))


async def main() -> None:
    # 广播循环与 serve 同生命周期；handler 兼容 websockets 12+ 单参签名
    async with websockets.serve(_handler, HOST, PORT):
        log.info("上游 WS 推流已启动 ws://%s:%d（%.1fs/帧），等待 collector 连接", HOST, PORT, PERIOD)
        await _broadcast_loop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("已停止")
