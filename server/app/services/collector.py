"""采集器（M8 工作包 A）：服务端常驻采集，替代浏览器直连（02 §7.1 修订）。

四类上游源（与前端 sources.ts 同语义）：
- MockSource：sine/ramp/random/square/hold 服务端仿真（公式逐条对齐前端 startMock）
- RestSource：httpx 定时轮询（intervalMs 下限 500；失败 failureBackoffMs）
- UpstreamWsSource：websockets 长连接客户端（subscribeFrame/heartbeatSec/重连退避）
- MqttSource：aiomqtt 订阅（Fernet 解密 config.password 后鉴权；cleanSession/qos 按 doc；
  client id = webscada-{projectId8}-{nanoid8}）

帧缺失/解析失败 → raw=None → hub 换算 q='bad'（02 §2.9 第 1 条）；
帧内路径缺字段 → 同样判 bad；mqtt 变量 address 即订阅 topic，不匹配的变量静默跳过（与前端一致）。
凭证注回：连接前对 FER1: 密文 decrypt；解密失败视为配置错误记日志并按无凭证尝试。
"""
import asyncio
import hashlib
import json
import math
import random as _random
import secrets
import string
import time
import uuid as uuidlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from loguru import logger

from app.core.config import settings
from app.schemas.doc import DataSource, VariableDef
from app.services import convert
from app.services.convert import MISSING
from app.services.modbus_codec import decode_modbus_registers, modbus_word_count

_NANOID_ALPHABET = string.ascii_letters + string.digits


def _nanoid8() -> str:
    return "".join(secrets.choice(_NANOID_ALPHABET) for _ in range(8))


def _now_ms() -> int:
    return int(time.time() * 1000)


def _payload_str(value: Any) -> str:
    """JS String(value) 口径：true→'true'（mqtt publish/rest 模板共用）。"""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _frame_ts(data: Any, ts_path: str | None) -> int:
    """载荷时间戳提取（G26）：数值（>1e11 视为毫秒，否则秒）/ISO 字符串；失败回落当前时间。"""
    if data is not None and ts_path:
        v = convert.get_by_path(data, ts_path)
        if v is not MISSING and v is not None and not isinstance(v, bool):
            try:
                if isinstance(v, (int, float)):
                    return int(v if v > 1e11 else v * 1000)
                s = str(v).strip()
                if s.replace(".", "", 1).isdigit():
                    num = float(s)
                    return int(num if num > 1e11 else num * 1000)
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return int(dt.timestamp() * 1000)
            except (ValueError, OverflowError, OSError):
                pass
    return _now_ms()


def _decrypt_credential(value: str | None) -> str | None:
    """FER1: 密文 → 明文；非密文原样；解密失败记日志按 None（无凭证）。"""
    if not value:
        return None
    if not value.startswith("FER1:"):
        return value
    try:
        from app.utils.encrypt import decrypt

        return decrypt(value)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"数据源凭证解密失败（DATASOURCE_SECRET 已变更？）：{type(exc).__name__}")
        return None


def _decrypt_headers(headers: dict[str, str] | None) -> dict[str, str] | None:
    if not headers:
        return headers
    out: dict[str, str] = {}
    for k, v in headers.items():
        out[k] = _decrypt_credential(v) if isinstance(v, str) else v
    return out


class BaseSource:
    """源基类：单 asyncio task 承载重连/轮询循环；stop 取消。"""

    def __init__(self, project_id: uuidlib.UUID, ds: DataSource, variables: list[VariableDef]) -> None:
        self.project_id = project_id
        self.ds = ds
        self.variables = variables
        self._task: asyncio.Task | None = None

    # -- 生命周期 --

    def start(self) -> None:
        self._task = asyncio.create_task(self._run_wrapper(), name=f"collector-{self.ds.type}-{self.ds.id}")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    async def _run_wrapper(self) -> None:
        from app.services import hub as hub_mod

        self._hub = hub_mod.hub
        try:
            await self.run()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - 源意外退出不拖垮进程（sync 重建可恢复）
            logger.exception(f"采集源异常退出 project={self.project_id} ds={self.ds.id} type={self.ds.type}")

    # -- 子类接口 --

    async def run(self) -> None:
        raise NotImplementedError

    async def write(self, variable: VariableDef, value: Any) -> None:
        raise RuntimeError(f"数据源类型 {self.ds.type} 不支持写入")

    def _ingest(self, variable: VariableDef, raw: Any, ts: int | None = None) -> None:
        self._hub.ingest(self.project_id, variable, raw, ts if ts is not None else _now_ms())

    # -- 重连退避（COLLECTOR_RECONNECT_*；ds 配置优先）--

    def _backoff_range(self) -> tuple[float, float]:
        cfg = getattr(self.ds, "config", None)
        lo = float(getattr(cfg, "reconnectMinMs", None) or settings.COLLECTOR_RECONNECT_MIN_MS)
        hi = float(getattr(cfg, "reconnectMaxMs", None) or settings.COLLECTOR_RECONNECT_MAX_MS)
        return max(lo, 100) / 1000, max(hi, lo) / 1000


# ---------------- mock ----------------


class MockSource(BaseSource):
    """服务端仿真：公式与前端 startMock 逐条一致；hold 仅推一次初始默认值（此后随反控回环）。"""

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        t0 = _now_ms()
        next_due: dict[str, float] = {}
        for var in self.variables:
            spec = var.mock
            if spec is None:
                continue
            if spec.kind == "hold":
                if var.defaultValue is not None:
                    self._ingest(var, var.defaultValue)  # 保持型初始值
                continue
            interval = spec.intervalMs if spec.kind == "random" else max(100, spec.periodMs / 24)
            next_due[var.key] = loop.time() + interval / 1000
        while True:
            now_loop = loop.time()
            for var in self.variables:
                spec = var.mock
                if spec is None or spec.kind == "hold":
                    continue
                due = next_due.get(var.key)
                if due is not None and due <= now_loop:
                    self._ingest(var, self._mock_raw(spec, _now_ms() - t0))
                    interval = spec.intervalMs if spec.kind == "random" else max(100, spec.periodMs / 24)
                    next_due[var.key] = now_loop + interval / 1000
            sleeps = [max(0.01, d - now_loop) for d in next_due.values()]
            await asyncio.sleep(max(min(sleeps) if sleeps else 0.5, 0.01))

    @staticmethod
    def _mock_raw(spec: Any, t: float) -> float:
        if spec.kind == "sine":
            return spec.min + (spec.max - spec.min) * (0.5 + 0.5 * math.sin(2 * math.pi * t / spec.periodMs))
        if spec.kind == "ramp":
            p = (t % spec.periodMs) / spec.periodMs
            if p < 0.5:
                return spec.min + (spec.max - spec.min) * p * 2
            return spec.max - (spec.max - spec.min) * (p - 0.5) * 2
        if spec.kind == "random":
            return spec.min + _random.random() * (spec.max - spec.min)
        if spec.kind == "square":
            p = (t % spec.periodMs) / spec.periodMs
            return spec.onValue if p < (spec.duty if spec.duty is not None else 0.5) else spec.offValue
        return 0.0

    async def write(self, variable: VariableDef, value: Any) -> None:
        # mock 反控本地回环：经完整换算流水入池（与前端 engine.write 同构）
        self._ingest(variable, value)


# ---------------- rest ----------------


class RestSource(BaseSource):
    async def run(self) -> None:
        import httpx

        cfg = self.ds.config
        interval = max(500, cfg.intervalMs) / 1000
        backoff = max(500, cfg.failureBackoffMs or cfg.intervalMs) / 1000
        timeout = (cfg.timeoutMs or 5000) / 1000
        headers = _decrypt_headers(cfg.headers)
        delay = interval
        async with httpx.AsyncClient(timeout=timeout) as client:
            while True:
                started = _now_ms()
                try:
                    resp = await client.request(
                        cfg.method or "GET",
                        cfg.url,
                        headers=headers or None,
                        content=(cfg.body or None) if (cfg.method or "GET") == "POST" else None,
                    )
                    if resp.status_code < 400:
                        try:
                            data = resp.json()
                        except ValueError:
                            data = None
                        ts = _frame_ts(data, cfg.tsPath)
                        for var in self.variables:
                            if data is None:
                                self._ingest(var, None, ts)  # 解析失败=bad
                                continue
                            raw = convert.pick_value(data, var)
                            self._ingest(var, None if raw is MISSING else raw, ts)
                    delay = interval
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.debug(f"rest 轮询失败 project={self.project_id} ds={self.ds.id}：{type(exc).__name__} {exc}")
                    delay = backoff
                elapsed = (_now_ms() - started) / 1000
                await asyncio.sleep(max(delay - elapsed, 0.05))

    async def write(self, variable: VariableDef, value: Any) -> None:
        import httpx

        cfg = self.ds.config
        url = cfg.writeUrl
        if not url:
            raise RuntimeError("该 REST 数据源未配置写端点（writeUrl）")
        body = (
            cfg.writeBodyTemplate.replace("{key}", variable.key).replace("{value}", json.dumps(self._js_value(value)))
            if cfg.writeBodyTemplate
            else json.dumps({variable.key: self._js_value(value)})
        )
        headers = {"Content-Type": "application/json"}
        if cfg.headers:
            headers.update(_decrypt_headers(cfg.headers) or {})
        timeout = (cfg.timeoutMs or 5000) / 1000
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(cfg.writeMethod or "POST", url, headers=headers, content=body)
        if resp.status_code >= 400:
            raise RuntimeError(f"写入失败：HTTP {resp.status_code}")

    @staticmethod
    def _js_value(value: Any) -> Any:
        return value


# ---------------- upstream websocket ----------------


class UpstreamWsSource(BaseSource):
    async def run(self) -> None:
        import websockets

        cfg = self.ds.config
        lo, hi = self._backoff_range()
        delay = lo
        headers = _decrypt_headers(cfg.headers)
        kwargs: dict[str, Any] = {}
        if headers:
            import inspect

            params = inspect.signature(websockets.connect).parameters
            key = "additional_headers" if "additional_headers" in params else "extra_headers"
            kwargs[key] = headers
        while True:
            heartbeat_task: asyncio.Task | None = None
            try:
                async with websockets.connect(cfg.url, open_timeout=settings.COLLECTOR_CONNECT_TIMEOUT_MS / 1000, **kwargs) as upstream:
                    self._upstream = upstream
                    delay = lo
                    if cfg.subscribeFrame:
                        await upstream.send(cfg.subscribeFrame)
                    if cfg.heartbeatSec:
                        heartbeat_task = asyncio.create_task(self._heartbeat(upstream, cfg.heartbeatSec))
                    async for message in upstream:
                        ts = _now_ms()
                        data = self._parse(message)
                        frame_ts = _frame_ts(data, cfg.tsPath)
                        for var in self.variables:
                            if data is None:
                                self._ingest(var, None, ts)  # 解析失败=bad
                                continue
                            raw = convert.pick_value(data, var)
                            self._ingest(var, None if raw is MISSING else raw, frame_ts)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"上游 WS 断开 project={self.project_id} ds={self.ds.id}：{type(exc).__name__} {exc}")
            finally:
                self._upstream = None
                if heartbeat_task is not None:
                    heartbeat_task.cancel()
                    try:
                        await heartbeat_task
                    except (asyncio.CancelledError, Exception):  # noqa: BLE001
                        pass
            await asyncio.sleep(delay)
            delay = min(delay * 2, hi)

    @staticmethod
    async def _heartbeat(upstream: Any, heartbeat_sec: int) -> None:
        while True:
            await asyncio.sleep(heartbeat_sec)
            await upstream.send("{}")

    @staticmethod
    def _parse(message: Any) -> Any:
        if isinstance(message, bytes):
            message = message.decode("utf-8", "replace")
        if isinstance(message, str):
            try:
                return json.loads(message)
            except ValueError:
                return None
        return None

    async def write(self, variable: VariableDef, value: Any) -> None:
        upstream = getattr(self, "_upstream", None)
        if upstream is None:
            raise RuntimeError("上游 WebSocket 未连接，写入失败")
        cfg = self.ds.config
        frame = (
            cfg.writeFrameTemplate.replace("{key}", variable.key).replace("{value}", json.dumps(value))
            if cfg.writeFrameTemplate
            else json.dumps({variable.key: value})
        )
        await upstream.send(frame)


# ---------------- mqtt ----------------


def mqtt_topic_matches(sub: str, topic: str) -> bool:
    """MQTT 订阅规则匹配（变量 address 亦按此口径）：`+` 恰好匹配一层；`#` 仅允许作为
    末段且匹配零或多层（如 factory/# 也匹配 factory 本身）；`#` 非末段属非法模式恒 False；
    两侧先 strip；非通配模式走全等快速路径。"""
    sub = sub.strip()
    topic = topic.strip()
    if "+" not in sub and "#" not in sub:
        return sub == topic
    sub_segs = sub.split("/")
    topic_segs = topic.split("/")
    last = len(sub_segs) - 1
    for i, seg in enumerate(sub_segs):
        if seg == "#":
            return i == last  # 末段吃掉余下全部层（含零层）；非末段=非法模式恒 False
        if i >= len(topic_segs):
            return False  # topic 层数不足
        if seg == "+":
            continue  # 恰好一层，任意值
        if seg != topic_segs[i]:
            return False
    return len(sub_segs) == len(topic_segs)


class MqttSource(BaseSource):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._client: Any = None

    @staticmethod
    def _parse_broker(url: str) -> tuple[str, int, bool]:
        """brokerUrl → (host, port, tls)。mqtt/mqtts 为原生 TCP；ws/wss 取其 host:port（aiomqtt 走 TCP）。"""
        parsed = urlparse(url if "//" in url else f"//{url}", scheme="mqtt")
        scheme = parsed.scheme.lower()
        tls = scheme in ("mqtts", "ssl")
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (8883 if tls else 1883)
        return host, port, tls

    async def run(self) -> None:
        import aiomqtt

        cfg = self.ds.config
        host, port, tls = self._parse_broker(cfg.brokerUrl)
        lo, hi = self._backoff_range()
        delay = lo
        username = _decrypt_credential(cfg.username) if cfg.username else None
        password = _decrypt_credential(cfg.password)
        client_id = f"webscada-{str(self.project_id)[:8]}-{_nanoid8()}"
        while True:
            try:
                kwargs: dict[str, Any] = {
                    "identifier": client_id,
                    "clean_session": cfg.cleanSession if cfg.cleanSession is not None else True,
                }
                if username is not None:
                    kwargs["username"] = username
                if password is not None:
                    kwargs["password"] = password
                if tls:
                    kwargs["tls_params"] = aiomqtt.TLSParameters()
                async with aiomqtt.Client(host, port, **kwargs) as client:
                    self._client = client
                    delay = lo
                    qos = cfg.qos if cfg.qos is not None else 0
                    for topic in cfg.topics:
                        await client.subscribe(topic, qos=qos)
                    logger.info(f"mqtt 已连接 project={self.project_id} ds={self.ds.id} broker={host}:{port}")
                    async for message in client.messages:
                        topic = str(message.topic)
                        self._dispatch(topic, message.payload, cfg.tsPath)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"mqtt 断开 project={self.project_id} ds={self.ds.id}：{type(exc).__name__} {exc}")
            finally:
                self._client = None
            await asyncio.sleep(delay)
            delay = min(delay * 2, hi)

    def _dispatch(self, topic: str, payload: bytes | str, ts_path: str | None) -> None:
        try:
            data = json.loads(payload if isinstance(payload, str) else bytes(payload).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            data = None
        ts = _frame_ts(data, ts_path)
        for var in self.variables:
            # 变量 address 即订阅 topic（支持 +/# 通配，订阅送达的具体 topic 由此匹配）；同 topic 多变量各自经 jsonPath 取值（与前端一致）
            if var.address and not mqtt_topic_matches(var.address, topic):
                continue
            if data is None:
                self._ingest(var, None, ts)  # 解析失败=bad
                continue
            raw = convert.get_by_path(data, var.jsonPath)
            self._ingest(var, None if raw is MISSING else raw, ts)

    async def write(self, variable: VariableDef, value: Any) -> None:
        client = self._client
        if client is None:
            raise RuntimeError("MQTT 未连接，写入失败")
        topic = variable.writeAddress or variable.address
        if not topic:
            raise RuntimeError(f"变量 {variable.key} 未配置写地址（writeAddress/address）")
        cfg = self.ds.config
        await client.publish(topic, _payload_str(value), qos=cfg.writeQos if cfg.writeQos is not None else 0, retain=False)


# ---------------- Collector ----------------


def _config_hash(ds: DataSource) -> str:
    raw = json.dumps(
        {"id": ds.id, "type": ds.type, "enabled": ds.enabled, "config": getattr(ds, "config", None) and ds.config.model_dump(mode="json")},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _vars_hash(variables: list[VariableDef]) -> str:
    """该源变量集规范化 JSON hash（按 id 排序 + sort_keys）：变量增删/修改必改变键。"""
    raw = json.dumps(
        sorted(
            (v.model_dump(mode="json") for v in variables),
            key=lambda d: str(d.get("id")),
        ),
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _entry_hash(ds: DataSource, variables: list[VariableDef]) -> str:
    """采集任务差量键 = ds 配置 hash + 该源变量集 hash。

    只比 ds config hash 会让「向既有数据源新增/修改变量」永不触发重建（新变量不被采集）。
    """
    return f"{_config_hash(ds)}:{_vars_hash(variables)}"


class _Entry:
    def __init__(self, hash_: str, source: BaseSource) -> None:
        self.hash = hash_
        self.source = source

    async def stop(self) -> None:
        await self.source.stop()


# ---------------- modbus（M8 阶段 1 后半；工厂可用阶段一批量读深化） ----------------

# 变量 address 的 Modbus 惯用区位：首字符 4=保持寄存器 3=输入寄存器 0=线圈 1=离散输入（doc.py ModbusConfig 同注释）
_MODBUS_AREAS = {"4": "holding", "3": "input", "0": "coil", "1": "discrete"}

# bit 区（coil/discrete）与寄存器区（holding/input）走不同读方法、上限与解码路径
_MODBUS_BIT_AREAS = frozenset({"coil", "discrete"})

# 单组批量读上限：寄存器区 120 字（Modbus PDU 253 字节 ≈ 125 字，留余量）；bit 区 1000 位
_MODBUS_MAX_REGISTERS = 120
_MODBUS_MAX_BITS = 1000

# 相邻间隙 ≤2 个地址单位仍合并（小空洞多读 2 字换取读次数减半）
_MODBUS_MERGE_GAP = 2


def modbus_parse_address(address: str) -> tuple[str, int] | None:
    """'40010' → ('holding', 9)；'00010' → ('coil', 9)。非 5 位区位十进制返回 None。"""
    s = (address or "").strip()
    if len(s) != 5 or not s.isdigit():
        return None
    area = _MODBUS_AREAS.get(s[0])
    if area is None:
        return None
    return area, int(s) % 10000 - 1  # 惯用地址 1-based → 协议 offset 0-based


@dataclass
class ModbusReadGroup:
    """一次批量读计划：同 (unitId, 区) 内 offset 升序、相邻间隙 ≤2 合并（受单组上限约束）。"""

    unit_id: int
    area: str  # holding / input / coil / discrete
    start: int  # 组首 offset（协议 0-based）
    count: int  # 组跨度：寄存器区=字数、bit 区=位数
    items: list[tuple[VariableDef, int, int]]  # (变量, 绝对 offset, 字宽)；bit 区 width 恒 1


def plan_modbus_reads(variables: list[VariableDef], default_unit_id: int) -> list[ModbusReadGroup]:
    """变量列表 → 批量读组计划（模块级纯函数，便于单测）。

    - 地址解析失败的变量不入组——由 run 每轮标 bad（语义同逐变量读时代）；
    - unitId 解析：var.unitId 缺省回落 default_unit_id（源级 config.unitId）；
    - 按 (unit_id, area) 分组、组内 offset 升序；相邻间隙 ≤ _MODBUS_MERGE_GAP 合并；
    - 单组上限：寄存器区 _MODBUS_MAX_REGISTERS 字 / bit 区 _MODBUS_MAX_BITS 位，超限另起组；
    - 32 位变量占 2 字（modbus_word_count）；bit 区忽略 modbusDataType（值即 bool）。
    """
    buckets: dict[tuple[int, str], list[tuple[int, int, VariableDef]]] = {}
    for var in variables:
        parsed = modbus_parse_address(var.address)
        if parsed is None:
            continue
        area, offset = parsed
        unit_id = var.unitId if var.unitId is not None else default_unit_id
        if area in _MODBUS_BIT_AREAS:
            width = 1  # bit 区忽略 modbusDataType
        else:
            width = modbus_word_count(var.modbusDataType or "int16")
        buckets.setdefault((unit_id, area), []).append((offset, width, var))

    groups: list[ModbusReadGroup] = []
    for (unit_id, area), entries in buckets.items():
        entries.sort(key=lambda e: e[0])
        cap = _MODBUS_MAX_BITS if area in _MODBUS_BIT_AREAS else _MODBUS_MAX_REGISTERS
        cur: ModbusReadGroup | None = None
        for offset, width, var in entries:
            # 并入当前组：与组尾间隙 ≤2 且并后跨度不超上限；否则另起一组
            if (
                cur is not None
                and offset - (cur.start + cur.count) <= _MODBUS_MERGE_GAP
                and offset + width - cur.start <= cap
            ):
                cur.count = offset + width - cur.start
                cur.items.append((var, offset, width))
                continue
            cur = ModbusReadGroup(
                unit_id=unit_id, area=area, start=offset, count=width, items=[(var, offset, width)]
            )
            groups.append(cur)
    # 输出定序（unit → area → start）：测试断言与日志可读
    groups.sort(key=lambda g: (g.unit_id, g.area, g.start))
    return groups


class ModbusSource(BaseSource):
    """Modbus TCP 轮询源（pymodbus 异步客户端）：按组批量读 + 16/32 位解码 + 变量级 unitId。"""

    async def run(self) -> None:
        from pymodbus.client import AsyncModbusTcpClient

        cfg = self.ds.config
        interval = max(cfg.intervalMs, 100) / 1000
        # 地址不变则分组不变（变量增删/修改会整源重建）——组计划与非法地址清单在循环外一次算好
        groups = plan_modbus_reads(self.variables, cfg.unitId)
        bad_vars = [v for v in self.variables if modbus_parse_address(v.address) is None]
        client = AsyncModbusTcpClient(cfg.host, port=cfg.port, timeout=cfg.timeoutMs / 1000)
        try:
            while True:
                started = _now_ms()
                try:
                    if not client.connected:
                        await client.connect()
                    for var in bad_vars:
                        self._ingest(var, None)  # 地址非法 = bad（换算流水保持上一有效值语义）
                    for group in groups:
                        await self._poll_group(client, group)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        f"modbus 轮询失败 project={self.project_id} ds={self.ds.id}：{type(exc).__name__} {exc}"
                    )
                elapsed = (_now_ms() - started) / 1000
                await asyncio.sleep(max(interval - elapsed, 0.05))
        finally:
            client.close()

    async def _poll_group(self, client: Any, group: ModbusReadGroup) -> None:
        """单组一次读 + 组内按变量 offset 切片解码入池；读失败整组标 bad。"""
        if group.area == "holding":
            rr = await client.read_holding_registers(group.start, count=group.count, device_id=group.unit_id)
        elif group.area == "input":
            rr = await client.read_input_registers(group.start, count=group.count, device_id=group.unit_id)
        elif group.area == "coil":
            rr = await client.read_coils(group.start, count=group.count, device_id=group.unit_id)
        else:
            rr = await client.read_discrete_inputs(group.start, count=group.count, device_id=group.unit_id)
        if rr.isError():
            for var, _offset, _width in group.items:
                self._ingest(var, None)
            return
        for var, offset, width in group.items:
            i = offset - group.start  # 绝对 offset → 组内切片起点
            if group.area in _MODBUS_BIT_AREAS:
                self._ingest(var, rr.bits[i])  # bit 区忽略 modbusDataType，值即 bool
                continue
            try:
                words = rr.registers[i : i + width]
                value = decode_modbus_registers(
                    words, var.modbusDataType or "int16", var.modbusByteOrder or "ABCD"
                )
            except ValueError:
                self._ingest(var, None)  # 应答字数不足等解码失败 = 该变量 bad（不拖垮同组其余变量）
                continue
            self._ingest(var, value)

    async def write(self, variable: VariableDef, value: Any) -> None:
        from pymodbus.client import AsyncModbusTcpClient

        parsed = modbus_parse_address(variable.address)
        if parsed is None:
            raise RuntimeError(f"变量 {variable.key} 的 Modbus 地址非法：{variable.address}")
        area, offset = parsed
        if area not in ("coil", "holding"):
            raise RuntimeError("仅线圈(0xxxx)与保持寄存器(4xxxx)支持写入")
        cfg = self.ds.config
        client = AsyncModbusTcpClient(cfg.host, port=cfg.port, timeout=cfg.timeoutMs / 1000)
        try:
            await client.connect()
            if area == "coil":
                rr = await client.write_coil(offset, bool(value), device_id=cfg.unitId)
            else:
                rr = await client.write_register(offset, int(round(float(value))), device_id=cfg.unitId)
            if rr.isError():
                raise RuntimeError(f"Modbus 写入失败（{variable.address}）")
            # 写后回读同址（写确认语义；失败不阻断——下一轮轮询自然刷新）
            self._ingest(variable, bool(value) if area == "coil" else int(round(float(value))))
        finally:
            client.close()


class Collector:
    """采集任务注册表：sync 差量热重建（datasource id + config hash + 变量集 hash），write 反控分发。"""

    def __init__(self) -> None:
        self._projects: dict[uuidlib.UUID, dict[str, _Entry]] = {}
        # per-project 互斥锁：sync/remove 全程持锁（含 stop 的 await），串行化并发保存与删除——
        # 防并发 sync 交错 KeyError（异常被热更新钩子吞掉 → 保存成功但采集不更新）、
        # 防 delete 与在途 sync 竞态泄漏常驻采集任务。锁随工程常驻（体量可忽略）
        self._locks: dict[uuidlib.UUID, asyncio.Lock] = {}

    def _lock_for(self, project_id: uuidlib.UUID) -> asyncio.Lock:
        lock = self._locks.get(project_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[project_id] = lock
        return lock

    def _gauge(self) -> None:
        from app.core import stats

        stats.set_gauge("collector_tasks", float(sum(len(v) for v in self._projects.values())))

    async def sync(self, project_id: uuidlib.UUID, doc: dict) -> None:
        """差量热重建（签名冻结）：PUT/导入/启动共用；校验失败仅记日志（doc 校验链已拦截）。"""
        try:
            model = _parse_doc(doc)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"collector.sync doc 解析失败 project={project_id}：{exc}")
            return

        vars_by_ds: dict[str, list[VariableDef]] = {}
        for var in model.variables:
            vars_by_ds.setdefault(var.datasourceId, []).append(var)

        wanted: dict[str, tuple[DataSource, str]] = {}
        for ds in model.datasources:
            wanted[ds.id] = (ds, _entry_hash(ds, vars_by_ds.get(ds.id, [])))

        async with self._lock_for(project_id):
            entries = self._projects.setdefault(project_id, {})
            for ds_id in list(entries.keys()):
                if ds_id not in wanted or wanted[ds_id][1] != entries[ds_id].hash:
                    entry = entries.pop(ds_id, None)  # 防御性默认值：并发窗口下键可能已被摘除
                    if entry is not None:
                        await entry.stop()

            started = False
            for ds_id, (ds, hash_) in wanted.items():
                if ds_id in entries:
                    continue
                if ds.enabled is False:  # G13：enabled=false 不建采集任务
                    continue
                source = self._make_source(project_id, ds, vars_by_ds.get(ds_id, []))
                entries[ds_id] = _Entry(hash_, source)
                source.start()
                started = True
            if started or entries:
                self._gauge()

    def _make_source(self, project_id: uuidlib.UUID, ds: DataSource, variables: list[VariableDef]) -> BaseSource:
        cls: dict[str, type[BaseSource]] = {
            "mock": MockSource,
            "modbus": ModbusSource,
            "rest": RestSource,
            "websocket": UpstreamWsSource,
            "mqtt": MqttSource,
        }
        return cls[ds.type](project_id, ds, variables)

    async def remove(self, project_id: uuidlib.UUID) -> None:
        async with self._lock_for(project_id):
            entries = self._projects.pop(project_id, None)
            if entries:
                for entry in entries.values():
                    await entry.stop()
        self._gauge()

    async def remove_all(self) -> None:
        for pid in list(self._projects.keys()):
            await self.remove(pid)

    async def write(self, project_id: uuidlib.UUID, variable: VariableDef, value: Any) -> None:
        """反控写分发（签名冻结）；失败抛 RuntimeError → ws.py 转 writeAck(WRITE_FAILED)。"""
        entry = self._projects.get(project_id, {}).get(variable.datasourceId)
        if entry is None:
            raise RuntimeError(f"变量所属数据源 {variable.datasourceId} 未在采集运行（已禁用或未同步）")
        await entry.source.write(variable, value)

    async def reset(self) -> None:
        await self.remove_all()


def _parse_doc(doc: dict):
    """doc dict → Pydantic 模型（独立小函数便于测试打桩）。"""
    from app.schemas.doc import ProjectDoc

    return ProjectDoc.model_validate(doc)


# 进程内单例（runtime_boot 挂 app.state；project_service/ws.py 惰性 import 取用）
collector = Collector()
