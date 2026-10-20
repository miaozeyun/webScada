"""数据源连通性测试（M8 工作包 A，契约 §4.5）。

POST /api/v1/datasources/test（operator/admin）：
- 凭证注回：携带 projectId+datasourceId 且敏感字段空/缺省时，用库内 FER1: 密文解密后测试
  （与 PUT 空值保留合并同语义：编辑器持脱敏 doc 也能测试已存凭证的源）；非空明文按本次值。
- 注回前提（M8 终审 #1）：本次连接地址（mqtt=brokerUrl / rest·websocket=url）与库内 stored_config
  一致；不一致不注回（防 operator 换 URL 借注回静默窃取任意工程凭证），响应 message 提示重填凭证。
- 审计：每次测试落 audit(action=datasource_test)；日志脱敏：敏感字段不落日志；结果不落库。
- 限流：REST_DATASOURCE_TEST_PER_MIN（core/rate_limit 中间件消费）。
"""
import copy
import time
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.errors import AppError
from app.db.base import get_db
from app.db.models import User
from app.utils.sanitize import SENSITIVE_HEADER_RE

router = APIRouter(tags=["datasources"])

_PROBE_TIMEOUT_SEC = 5.0


class DatasourceTestBody(BaseModel):
    type: Literal["mqtt", "websocket", "rest", "mock", "modbus"]
    config: dict[str, Any] = Field(default_factory=dict)
    projectId: str | None = None
    datasourceId: str | None = None


def _config_endpoint(ds_type: str, config: dict) -> str:
    """注回一致性校验用的连接地址：mqtt 取 brokerUrl，其余（rest/websocket/mock）取 url；均去首尾空白。"""
    key = "brokerUrl" if ds_type == "mqtt" else "url"
    return str((config or {}).get(key) or "").strip()


def merge_stored_credentials(ds_type: str, config: dict, stored_config: dict) -> dict:
    """凭证注回（纯函数，就地修改并返回 config；契约 §4.5）。

    - mqtt：config.password 空/缺省 → 取库内值（FER1: 解密；非密文原样）
    - rest/websocket：config.headers 敏感键（sanitize 同一正则口径）空/缺省 → 库内值解密
    - 非空明文按本次值（用户正在换凭证的场景优先）
    """
    if ds_type == "mqtt":
        if not config.get("password"):
            stored_pw = (stored_config or {}).get("password")
            if stored_pw:
                config["password"] = _decrypt_or_raw(str(stored_pw))
    elif ds_type in ("rest", "websocket"):
        stored_headers = (stored_config or {}).get("headers")
        if isinstance(stored_headers, dict):
            headers = config.get("headers")
            if not isinstance(headers, dict):
                headers = {}
                config["headers"] = headers
            for key, value in stored_headers.items():
                if not SENSITIVE_HEADER_RE.search(str(key)):
                    continue
                if not headers.get(key):
                    headers[key] = _decrypt_or_raw(str(value))
    return config


def _decrypt_or_raw(value: str) -> str:
    if not value.startswith("FER1:"):
        return value
    try:
        from app.utils.encrypt import decrypt

        return decrypt(value)
    except Exception as exc:  # noqa: BLE001 - 密钥变更等：按原样尝试并记日志（不泄露内容）
        logger.warning(f"datasources/test 凭证注回解密失败：{type(exc).__name__}")
        return value


async def _load_stored_config(db: AsyncSession, project_id: str, datasource_id: str) -> dict | None:
    """库内 doc 中该数据源的 config（含 FER1: 密文）；工程/源不存在返回 None。"""
    import uuid as uuidlib

    from app.db.models import Project

    try:
        pid = uuidlib.UUID(project_id)
    except ValueError:
        raise AppError("NOT_FOUND", "工程不存在", 404) from None
    project = await db.get(Project, pid)
    if project is None:
        raise AppError("NOT_FOUND", "工程不存在", 404)
    doc = project.doc if isinstance(project.doc, dict) else {}
    for ds in doc.get("datasources") or []:
        if isinstance(ds, dict) and ds.get("id") == datasource_id:
            cfg = ds.get("config")
            return cfg if isinstance(cfg, dict) else None
    return None


async def _probe_mqtt(config: dict) -> tuple[bool, str]:
    import asyncio

    import aiomqtt

    parsed = urlparse_cfg(config.get("brokerUrl", ""))
    host, port, tls = parsed
    kwargs: dict[str, Any] = {}
    if config.get("username"):
        kwargs["username"] = str(config["username"])
    if config.get("password"):
        kwargs["password"] = str(config["password"])
    if tls:
        kwargs["tls_params"] = aiomqtt.TLSParameters()

    def _connect() -> Any:
        return aiomqtt.Client(host, port, identifier=f"webscada-test-{time.time_ns()}", **kwargs)

    try:
        client = _connect()
        try:
            await asyncio.wait_for(client.connect(), timeout=_PROBE_TIMEOUT_SEC)
        finally:
            await client.disconnect()
        return True, f"已连接 {host}:{port}"
    except Exception as exc:  # noqa: BLE001 - 连接失败是正常测试结果
        return False, f"连接失败：{exc}"


def urlparse_cfg(broker_url: str) -> tuple[str, int, bool]:
    from urllib.parse import urlparse

    parsed = urlparse(broker_url if "//" in broker_url else f"//{broker_url}", scheme="mqtt")
    scheme = parsed.scheme.lower()
    tls = scheme in ("mqtts", "ssl")
    return parsed.hostname or "127.0.0.1", parsed.port or (8883 if tls else 1883), tls


async def _probe_websocket(config: dict) -> tuple[bool, str]:
    import inspect

    import websockets

    url = str(config.get("url", ""))
    headers = {k: str(v) for k, v in (config.get("headers") or {}).items()}
    kwargs: dict[str, Any] = {}
    if headers:
        params = inspect.signature(websockets.connect).parameters
        kwargs["additional_headers" if "additional_headers" in params else "extra_headers"] = headers
    try:
        ws = await websockets.connect(url, open_timeout=_PROBE_TIMEOUT_SEC, **kwargs)
        await ws.close()
        return True, f"已连接 {url}"
    except Exception as exc:  # noqa: BLE001
        return False, f"连接失败：{exc}"


async def _probe_rest(config: dict) -> tuple[bool, str]:
    import httpx

    url = str(config.get("url", ""))
    method = str(config.get("method") or "GET").upper()
    headers = {k: str(v) for k, v in (config.get("headers") or {}).items()} or None
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_SEC) as client:
            resp = await client.request(
                method, url, headers=headers,
                content=(config.get("body") or None) if method == "POST" else None,
            )
        ok = resp.status_code < 400  # 与前端 resp.ok 同口径（2xx 通）
        return ok, f"HTTP {resp.status_code}（{url}）"
    except Exception as exc:  # noqa: BLE001
        return False, f"请求失败：{exc}"


async def _probe_modbus(config: dict) -> tuple[bool, str]:
    """Modbus TCP 连通性：建连 + 读 1 个保持寄存器（offset 0）验证 UnitId 响应。"""
    from pymodbus.client import AsyncModbusTcpClient

    host = str(config.get("host", ""))
    port = int(config.get("port") or 502)
    unit = int(config.get("unitId") or 1)
    client = AsyncModbusTcpClient(host, port=port, timeout=_PROBE_TIMEOUT_SEC)
    try:
        await client.connect()
        if not client.connected:
            return False, f"无法连接 {host}:{port}"
        rr = await client.read_holding_registers(0, count=1, device_id=unit)
        if rr.isError():
            return False, f"UnitId={unit} 无响应或读失败"
        return True, f"连接成功 {host}:{port} UnitId={unit}"
    except Exception as exc:  # noqa: BLE001
        return False, f"连接失败：{exc}"
    finally:
        client.close()


@router.post("/datasources/test")
async def test_datasource(
    body: DatasourceTestBody,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    # 角色门槛：operator/admin（viewer 403；C 包 require_operator 合入后可替换为依赖）
    if user.role not in ("operator", "admin"):
        raise AppError("FORBIDDEN", "viewer 角色不允许执行连通性测试", 403)

    config = copy.deepcopy(body.config)
    refilled = False
    url_mismatch = False
    # 凭证注回：编辑器脱敏 doc（敏感字段空串）+ projectId/datasourceId → 库内密文解密补齐
    # 终审 #1：注回前校验本次连接地址与库内 stored_config 一致——地址不一致不注回，
    # 关闭"operator 换 URL 借注回静默窃取任意工程凭证"的通道（唯一明文出口）。
    if body.projectId and body.datasourceId:
        stored = await _load_stored_config(db, body.projectId, body.datasourceId)
        if stored is not None:
            if _config_endpoint(body.type, config) == _config_endpoint(body.type, stored):
                config = merge_stored_credentials(body.type, config, stored)
                refilled = True
            else:
                url_mismatch = True

    started = time.perf_counter()
    if body.type == "mock":
        ok, message = True, "mock 数据源在服务端本地生成，无需连接"
    elif body.type == "mqtt":
        ok, message = await _probe_mqtt(config)
    elif body.type == "websocket":
        ok, message = await _probe_websocket(config)
    elif body.type == "modbus":
        ok, message = await _probe_modbus(config)
    else:
        ok, message = await _probe_rest(config)
    latency_ms = int((time.perf_counter() - started) * 1000)

    if url_mismatch:
        message += "；连接地址与已保存数据源不一致，未注回已存凭证，请重填凭证"

    # 日志脱敏：只记类型与结果，不记 config 内容
    logger.info(f"datasources/test type={body.type} ok={ok} latencyMs={latency_ms} user={user.username}")
    # 审计（C 包 audit_service；未合入时打桩降级——惰性 import 跨包规约 §6.4）；
    # detail 只含元数据，不含 config/凭证内容
    try:
        from app.services import audit_service

        await audit_service.audit(
            request, user, "datasource_test", target_type="datasource", target_id=body.datasourceId,
            detail={"type": body.type, "ok": ok, "latencyMs": latency_ms, "refilled": refilled,
                    "urlMatched": not url_mismatch, "projectId": body.projectId},
        )
    except ImportError:
        logger.info("audit_service 未合入（C 包），datasource_test 审计跳过（打桩降级）")
    return {"ok": ok, "type": body.type, "latencyMs": latency_ms, "message": message}
