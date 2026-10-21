"""仿真验证台：多设备 MQTT 网关模拟器（compose sim profile 的 sim-mqtt-gateway 服务）。

模拟 3 台产线设备接入 EMQX 周期上送，供 scripts/seed_demo.py 演示工程的 MQTT 数据源
订阅（topics 建议含 factory/#）。与 sim-modbus 无依赖关系，可单独启用。

主题表（发布周期 1s；payload 统一为 {"v": <值>, "ts": <epoch_ms>}）：

    factory/{dev}/temp   line1/line2/line3 各一：温度正弦 20~85 ℃
                         line1 周期 60s、初相 0 —— 启动后第 15s 到达峰值 85，
                         首轮 60 秒内必然扫过 80（约 8~22s 区间越过 80，约 7s 起
                         越过 75），用于触发 seed 演示工程 line1_temp > 75 的 warn
                         报警演示；line2/line3 周期 90s/120s 错相，读数各不相同
    factory/{dev}/run    line1/line2/line3 各一：0/1 每秒交替（boolean 点位，
                         配合通配地址 factory/+/run 验证）
    factory/line1/press  仅 line1：压力正弦 0.4~0.8 MPa（同 topic 双变量场景）

环境变量：
    MQTT_URL                 缺省 emqx:1883（兼容 emqx:1883 / mqtt://emqx:1883 写法）
    MQTT_USERNAME            缺省取 compose 注入的 EMQX 默认 MQTT 账号
    MQTT_PASSWORD            同上

断线按指数退避重连（1s 起步、每次 ×2、封顶 30s）；每次发布打一行日志 topic=v。
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import time
from urllib.parse import urlparse

import aiomqtt

logging.basicConfig(level=logging.INFO, format="%(asctime)s [sim-gateway] %(levelname)s %(message)s")
log = logging.getLogger("sim-gateway")

DEVICES = ("line1", "line2", "line3")
PUBLISH_PERIOD = 1.0
RECONNECT_MIN = 1.0
RECONNECT_MAX = 30.0

# 各设备温度正弦参数：周期（秒）、初相。line1 保证首轮 60s 内扫过 80（见 docstring）。
_TEMP_PROFILE: dict[str, tuple[float, float]] = {
    "line1": (60.0, 0.0),
    "line2": (90.0, 2.0 * math.pi / 3.0),
    "line3": (120.0, 4.0 * math.pi / 3.0),
}
TEMP_MIN, TEMP_MAX = 20.0, 85.0
PRESS_MIN, PRESS_MAX = 0.4, 0.8
PRESS_PERIOD = 30.0


def _sine(t: float, period: float, phase: float, lo: float, hi: float) -> float:
    """区间 [lo, hi] 内的正弦取值。"""
    mid, amp = (lo + hi) / 2.0, (hi - lo) / 2.0
    return mid + amp * math.sin(2.0 * math.pi * t / period + phase)


def _parse_broker(raw: str) -> tuple[str, int]:
    """MQTT_URL → (host, port)，容忍带/不带 scheme 两种写法。"""
    parsed = urlparse(raw if "://" in raw else f"//{raw}", scheme="mqtt")
    return parsed.hostname or "127.0.0.1", parsed.port or 1883


def _payload(value: int | float) -> str:
    return json.dumps({"v": value, "ts": int(time.time() * 1000)})


async def _publish_round(client: aiomqtt.Client, elapsed: float) -> None:
    """发布一轮（3 设备 temp/run + line1 press），每条一行日志。"""
    for dev in DEVICES:
        period, phase = _TEMP_PROFILE[dev]
        temp = round(_sine(elapsed, period, phase, TEMP_MIN, TEMP_MAX), 1)
        await client.publish(f"factory/{dev}/temp", _payload(temp))
        log.info(f"factory/{dev}/temp v={temp}")
        run = int(elapsed) % 2
        await client.publish(f"factory/{dev}/run", _payload(run))
        log.info(f"factory/{dev}/run v={run}")
        if dev == "line1":
            press = round(_sine(elapsed, PRESS_PERIOD, 0.0, PRESS_MIN, PRESS_MAX), 3)
            await client.publish("factory/line1/press", _payload(press))
            log.info(f"factory/line1/press v={press}")


async def _run() -> None:
    host, port = _parse_broker(os.environ.get("MQTT_URL", "emqx:1883").strip())
    username = os.environ.get("MQTT_USERNAME") or None
    password = os.environ.get("MQTT_PASSWORD") or None
    delay = RECONNECT_MIN
    while True:
        try:
            async with aiomqtt.Client(
                host, port, identifier="sim-mqtt-gateway", username=username, password=password
            ) as client:
                log.info(f"已连接 {host}:{port}，开始周期发布（1s，设备 {list(DEVICES)}）")
                delay = RECONNECT_MIN
                start = time.monotonic()
                next_at = time.monotonic()
                while True:
                    await _publish_round(client, time.monotonic() - start)
                    next_at += PUBLISH_PERIOD
                    await asyncio.sleep(max(0.0, next_at - time.monotonic()))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 —— aiomqtt.MqttError 等一律退避重连
            log.warning(f"连接断开（{type(exc).__name__}: {exc}），{delay:.0f}s 后重连")
        await asyncio.sleep(delay)
        delay = min(delay * 2.0, RECONNECT_MAX)


if __name__ == "__main__":
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        log.info("已退出")
