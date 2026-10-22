"""OPC UA 第六数据源测试（工厂可用阶段二 Task 8）。

asyncua 自带 Server 在测试进程内起真实 OPC UA 服务（127.0.0.1 动态端口，
ns=2 建 demo.temp / demo.press / demo.state 三节点）做真集成：
- ① 订阅收值：变量 address=nodeId 字符串 → DataChange → 换算流水入池（scale/precision）
- ② 断线重连后订阅重建（Review Focus #5）：停 Server → 源退避重连 → 同端口重启 Server
  → 断言新值恢复流动（订阅未重建则池值停滞）
- ③ browse 列子节点：POST /datasources/opcua/browse（凭证注回沿 test 端点模式 + operator+ 权限）
- 另：write=set_value 反控、schema 校验（非法 endpointUrl 422 等）、opcua password 脱敏/合并

asyncua 2.1.0 实装口径（与旧文档有偏差，见 docs/经验教训.md 2026-10-22 条目）：
- Server 动态端口：endpoint 写 :0，启动后取 srv.bserver.port
- 停止服务：await srv.stop()（无 shutdown()）
- 订阅回调 datachange_notification(node, val, data) 的 data 为 DataChangeNotif，
  时间戳在 data.monitored_item.Value.SourceTimestamp
"""
import asyncio
import sys
import uuid as uuidlib
from typing import Any

import pytest

sys.stdout.reconfigure(encoding="utf-8")

from asyncua import Client as UaClient, Server as UaServer  # noqa: E402

from app.core.errors import AppError  # noqa: E402
from app.services import hub as hub_mod  # noqa: E402
from app.services.collector import OpcUaSource  # noqa: E402
from app.services.doc_service import validate_full  # noqa: E402

NS_URI = "http://webscada.local/opcua-sim"


def _doc(endpoint: str, ds_id: str = "ds_opcua") -> dict:
    """最小合法 doc：单 opcua 源 + temp(number, scale 0.1) + state(boolean) 两变量。"""
    pid = str(uuidlib.uuid4())
    return {
        "schemaVersion": 1,
        "project": {"id": pid, "name": "opcua", "description": None, "author": "admin",
                    "createdAt": "2026-10-22T00:00:00Z", "updatedAt": "2026-10-22T00:00:00Z"},
        "settings": {"designSize": {"width": 1920, "height": 1080}, "adaptive": "fit-contain",
                     "theme": "blue-dark", "primaryColor": "#2563eb",
                     "alarm": {"levelColors": {}, "soundEnabled": False, "soundThrottleSec": 60}},
        "datasources": [{
            "id": ds_id, "name": "产线 OPC UA", "type": "opcua", "enabled": True,
            # 测试用快退避：断线后尽快重连（重连重建用例时序可控）
            "config": {"endpointUrl": endpoint, "publishIntervalMs": 200,
                       "reconnectMinMs": 100, "reconnectMaxMs": 1000},
        }],
        "variables": [
            {"id": "v_temp", "key": "opc_temp", "label": "温度", "type": "number",
             "datasourceId": ds_id, "address": "ns=2;s=demo.temp", "scale": 0.1, "precision": 1},
            {"id": "v_state", "key": "opc_state", "label": "运行", "type": "boolean",
             "datasourceId": ds_id, "address": "ns=2;s=demo.state"},
        ],
        "pages": [{"id": "p1", "name": "p", "order": 0, "background": {"color": "#fff"},
                   "screen": {"designWidth": 1920, "designHeight": 1080, "mode": "fit-contain"},
                   "components": []}],
        "alarmRules": [],
    }


async def _build_sim(base_temp: float = 20.0, port: int | None = None) -> tuple[UaServer, Any, Any, int]:
    """ns=2 建 demo 三节点（temp/press/state）；temp/state 可写（反控演示）。

    显式字符串 nodeId（ns=2;s=demo.temp）须走 add_variable(nodeid, qname) 两参显式形式
    （int 首参形式生成数字 nodeId，无法与变量 address 对齐）。
    port=None 时先探测一个空闲端口（重启用例需要"同端口重启"：动态 :0 重启必换端口，
    探测-关闭-绑定的小竞态在单测环境可接受）。
    返回 (server, temp 节点, state 节点, 实际端口)。
    """
    if port is None:
        import socket as _socket

        with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
    srv = UaServer()
    await srv.init()
    srv.set_endpoint(f"opc.tcp://127.0.0.1:{port}/webscada/sim/")
    idx = await srv.register_namespace(NS_URI)
    assert idx == 2
    demo = await srv.nodes.objects.add_folder("ns=2;s=demo", "2:demo")
    temp = await demo.add_variable("ns=2;s=demo.temp", "2:temp", base_temp)
    await demo.add_variable("ns=2;s=demo.press", "2:press", 0.75)
    state = await demo.add_variable("ns=2;s=demo.state", "2:state", False)
    await temp.set_writable()
    await state.set_writable()
    await srv.start()
    return srv, temp, state, port


# ---------------- schema 校验 ----------------


def test_opcua_schema_valid_and_defaults():
    doc = _doc("opc.tcp://127.0.0.1:4840/webscada/sim/")
    # 剥掉 _doc 注入的时序覆盖，验证字段缺省值
    doc["datasources"][0]["config"] = {"endpointUrl": "opc.tcp://127.0.0.1:4840/webscada/sim/"}
    model = validate_full(doc)
    ds = model.datasources[0]
    assert ds.type == "opcua"
    cfg = ds.config
    assert cfg.securityMode == "none"
    assert cfg.publishIntervalMs == 1000            # 缺省
    assert cfg.reconnectMinMs == 1000 and cfg.reconnectMaxMs == 30000
    assert cfg.username is None and cfg.password is None
    # 变量 address 即 nodeId 字符串
    assert model.variables[0].address == "ns=2;s=demo.temp"


def test_opcua_schema_rejects_bad_endpoint():
    for bad in ("http://127.0.0.1:4840/x", "opc.http://x", "127.0.0.1:4840", "mqtts://x"):
        doc = _doc("opc.tcp://placeholder/")
        doc["datasources"][0]["config"]["endpointUrl"] = bad
        with pytest.raises(AppError) as ei:
            validate_full(doc)
        assert ei.value.status_code == 422
        assert "endpointUrl" in str(ei.value.extra.get("errors"))


def test_opcua_schema_rejects_small_publish_interval():
    doc = _doc("opc.tcp://127.0.0.1:4840/x/")
    doc["datasources"][0]["config"]["publishIntervalMs"] = 199  # 下限 200
    with pytest.raises(AppError) as ei:
        validate_full(doc)
    assert ei.value.status_code == 422


# ---------------- ① 订阅收值 / write 反控 ----------------


async def _wait_pool(pid, key, expect, timeout=10.0) -> dict:
    """轮询 hub 池直到 var.v == expect（float 按工程值直比）。"""
    for _ in range(int(timeout / 0.1)):
        await asyncio.sleep(0.1)
        entry = hub_mod.hub.pool(pid).get(key)
        if entry is not None and entry.get("v") == expect:
            return entry
    pool = hub_mod.hub.pool(pid)
    raise AssertionError(f"等待 {key}=={expect} 超时，池={pool.get(key)}")


async def test_opcua_subscribe_and_write_roundtrip():
    srv, temp, state, port = await _build_sim(base_temp=20.0)
    source = None
    pid = None
    try:
        doc = _doc(f"opc.tcp://127.0.0.1:{port}/webscada/sim/")
        model = validate_full(doc)
        pid = model.project.id
        hub_mod.hub.set_doc(pid, doc)
        source = OpcUaSource(pid, model.datasources[0], model.variables)
        source.start()

        # 初始值经订阅推送入池：temp=20.0×0.1=2.0（good）；state=False
        e1 = await _wait_pool(model.project.id, "opc_temp", 2.0)
        assert e1["q"] == "good"
        e2 = await _wait_pool(model.project.id, "opc_state", False)
        assert e2["q"] == "good"

        # 服务端值变化 → 订阅推送（41.0×0.1 → 4.1，precision 1）
        await temp.write_value(41.0)
        await _wait_pool(model.project.id, "opc_temp", 4.1)

        # 反控 write=set_value：写 boolean → 服务端节点翻转（独立客户端回读验证）
        var_state = next(v for v in model.variables if v.key == "opc_state")
        await source.write(var_state, True)
        async with UaClient(url=f"opc.tcp://127.0.0.1:{port}/webscada/sim/") as cli:
            assert await cli.get_node("ns=2;s=demo.state").read_value() is True
        # 订阅回环：写后的值也推入池
        await _wait_pool(model.project.id, "opc_state", True)
    finally:
        if source is not None:
            await source.stop()
        if pid is not None:
            hub_mod.hub.remove(pid)
        await srv.stop()


# ---------------- ② 断线重连后订阅重建（Review Focus #5）----------------


async def test_opcua_reconnect_rebuilds_subscriptions():
    srv, temp, state, port = await _build_sim(base_temp=20.0)
    source = None
    pid = None
    try:
        doc = _doc(f"opc.tcp://127.0.0.1:{port}/webscada/sim/")
        model = validate_full(doc)
        pid = model.project.id
        hub_mod.hub.set_doc(pid, doc)
        source = OpcUaSource(pid, model.datasources[0], model.variables)
        source.start()
        await temp.write_value(31.0)
        await _wait_pool(pid, "opc_temp", 3.1)  # 连接正常，值流动

        # ---- 断线：停 Server（源应进入退避重连）----
        await srv.stop()
        await asyncio.sleep(1.6)  # > 健康探测周期 + 退避，确保源已感知断线并至少重试失败一次

        # ---- 恢复：同端口重启 Server（temp 基值 50.0）----
        srv2, temp2, _state2, port2 = await _build_sim(base_temp=50.0, port=port)
        assert port2 == port  # 显式端口重绑：模拟"服务重启后地址不变"
        try:
            # 订阅若未重建：池值将永远停在 3.1（静默停滞——Review Focus #5 要防的缺陷）
            # 先看到重启初值 5.0，再验证后续推送 7.7 仍在流动
            await _wait_pool(pid, "opc_temp", 5.0, timeout=15.0)
            await temp2.write_value(77.0)
            await _wait_pool(pid, "opc_temp", 7.7)
            entry = hub_mod.hub.pool(pid)["opc_temp"]
            assert entry["q"] == "good"  # 重连后质量位恢复 good
        finally:
            await srv2.stop()
    finally:
        if source is not None:
            await source.stop()
        if pid is not None:
            hub_mod.hub.remove(pid)


# ---------------- ③ browse 端点（凭证注回沿 test 端点模式 + 权限）----------------
# 自建 mini app（沿 test_datasources_security.py 头注模式）：不依赖主 app 装配。


def _build_mini_app():
    from fastapi import FastAPI
    from app.core.errors import register_handlers
    from app.api.v1 import datasources

    app = FastAPI()
    register_handlers(app)
    app.include_router(datasources.router, prefix="/api/v1")
    return app


@pytest.fixture
async def browse_env():
    """测试库（库内 doc 存 opcua 源 FER1: 密文）+ mini app + 审计工厂注入。"""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool
    from httpx import ASGITransport, AsyncClient

    from app.db import models  # noqa: F401 注册全部模型
    from app.db.base import Base, get_db
    from app.db.models import Project, User
    from app.core.security import create_access_token, hash_password
    from app.services import audit_service
    from app.utils.encrypt import encrypt

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    pid = uuidlib.uuid4()
    ds_id = "ds_opcua"
    endpoint = "opc.tcp://127.0.0.1:59940/webscada/sim/"
    secret = "opc-pass-9527"
    async with factory() as session:
        admin = User(username="admin", password_hash=hash_password("admin12345"), role="admin")
        viewer = User(username="viewer", password_hash=hash_password("viewer12345"), role="viewer")
        session.add_all([admin, viewer])
        await session.flush()
        session.add(Project(
            id=pid, name="browse 工程", revision=1, owner_id=admin.id,
            doc={
                "schemaVersion": 1,
                "project": {"id": str(pid), "name": "browse 工程"},
                "datasources": [{
                    "id": ds_id, "name": "产线 OPC UA", "type": "opcua", "enabled": True,
                    "config": {"endpointUrl": endpoint, "password": encrypt(secret)},
                }],
                "variables": [], "pages": [], "alarmRules": [],
            },
        ))
        await session.commit()

    prev = audit_service.session_factory
    audit_service.session_factory = factory

    application = _build_mini_app()

    async def _override_get_db():
        async with factory() as session:
            yield session

    application.dependency_overrides[get_db] = _override_get_db
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as c:
        async with factory() as session:
            admin_row = (await session.execute(select(User).where(User.username == "admin"))).scalars().one()
            viewer_row = (await session.execute(select(User).where(User.username == "viewer"))).scalars().one()
        yield {
            "client": c,
            "factory": factory,
            "endpoint": endpoint,
            "pid": str(pid),
            "ds_id": ds_id,
            "secret": secret,
            "admin_h": {"Authorization": f"Bearer {create_access_token(str(admin_row.id))[0]}"},
            "viewer_h": {"Authorization": f"Bearer {create_access_token(str(viewer_row.id))[0]}"},
        }
    application.dependency_overrides.pop(get_db, None)
    audit_service.session_factory = prev
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def test_browse_lists_children_against_live_server():
    """browse 对真实 Server 列子节点：Objects 下含 demo 文件夹；demo 下三节点 nodeId+browseName。"""
    srv, _temp, _state, port = await _build_sim()
    try:
        async with UaClient(url=f"opc.tcp://127.0.0.1:{port}/webscada/sim/") as cli:
            from app.api.v1.datasources import _browse_opcua

            ok, msg, nodes = await _browse_opcua(
                f"opc.tcp://127.0.0.1:{port}/webscada/sim/", None, None, None)
            assert ok, msg
            ids = [n["nodeId"] for n in nodes]
            assert "ns=2;s=demo" in ids
            # 指定 nodeId 深入 demo 文件夹
            ok2, _msg2, nodes2 = await _browse_opcua(
                f"opc.tcp://127.0.0.1:{port}/webscada/sim/", None, None, "ns=2;s=demo")
            assert ok2
            by_id = {n["nodeId"]: n["browseName"] for n in nodes2}
            assert set(by_id) == {"ns=2;s=demo.temp", "ns=2;s=demo.press", "ns=2;s=demo.state"}
            assert by_id["ns=2;s=demo.temp"] == "2:temp"
    finally:
        await srv.stop()


async def test_browse_endpoint_refill_and_rbac(browse_env, monkeypatch):
    """凭证注回沿 test 端点模式：endpointUrl 一致 → FER1 密文解密注入探测；viewer 403；落审计。"""
    from app.api.v1 import datasources
    from app.db.models import AuditLog

    seen: list[dict] = []

    async def _fake_browse(endpoint, username, password, node_id):
        seen.append({"endpoint": endpoint, "username": username, "password": password, "nodeId": node_id})
        return True, "ok", [{"nodeId": "ns=2;s=demo", "browseName": "2:demo"}]

    monkeypatch.setattr(datasources, "_browse_opcua", _fake_browse)

    # viewer 403（operator+ 权限，沿 test 端点）
    resp = await browse_env["client"].post(
        "/api/v1/datasources/opcua/browse", headers=browse_env["viewer_h"],
        json={"endpoint": browse_env["endpoint"]},
    )
    assert resp.status_code == 403

    # 空 password + projectId/datasourceId → 注回库内密文解密
    resp = await browse_env["client"].post(
        "/api/v1/datasources/opcua/browse", headers=browse_env["admin_h"],
        json={"endpoint": browse_env["endpoint"], "projectId": browse_env["pid"],
              "datasourceId": browse_env["ds_id"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["nodes"] == [{"nodeId": "ns=2;s=demo", "browseName": "2:demo"}]
    assert seen[-1]["password"] == browse_env["secret"]  # 探测收到解密明文

    # endpointUrl 不一致 → 不注回 + message 提示重填（防换 URL 窃取凭证，沿终审 #1）
    resp = await browse_env["client"].post(
        "/api/v1/datasources/opcua/browse", headers=browse_env["admin_h"],
        json={"endpoint": "opc.tcp://evil.example.com:4840/x", "projectId": browse_env["pid"],
              "datasourceId": browse_env["ds_id"]},
    )
    assert resp.status_code == 200
    assert "重填凭证" in resp.json()["message"]
    assert seen[-1]["password"] is None  # 未注回

    # 落审计（action=datasource_test 沿 test 端点口径）
    from sqlalchemy import select as _sel

    async with browse_env["factory"]() as session:
        rows = (await session.scalars(_sel(AuditLog))).all()
    assert len(rows) == 2  # viewer 403 不落（沿 test 端点：鉴权失败在门槛抛出，不进探测）
    assert all(r.action == "datasource_test" for r in rows)


async def test_browse_bad_node_id(browse_env):
    """nodeId 不存在 → ok=False + message（不 5xx）。"""
    srv, _t, _s, port = await _build_sim()
    try:
        resp = await browse_env["client"].post(
            "/api/v1/datasources/opcua/browse", headers=browse_env["admin_h"],
            json={"endpoint": f"opc.tcp://127.0.0.1:{port}/webscada/sim/", "nodeId": "ns=9;s=missing"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert body["nodes"] == []
    finally:
        await srv.stop()


# ---------------- 凭证脱敏 / 空值合并（沿 mqtt 口径）----------------


def test_opcua_password_sanitize_and_merge():
    from app.utils import sanitize as sz

    def _doc_with_pw(pw) -> dict:
        doc = _doc("opc.tcp://127.0.0.1:4840/x/")
        doc["datasources"][0]["config"]["password"] = pw
        return doc

    # 出口脱敏为空串
    doc = _doc_with_pw("plain-secret")
    out = sz.sanitize_doc_for_output(doc)
    assert out["datasources"][0]["config"]["password"] == ""
    # 导入一律置空
    doc2 = _doc_with_pw("plain-secret")
    sz.clear_credentials_for_import(doc2)
    assert doc2["datasources"][0]["config"]["password"] == ""
    # PUT 空串=保留库内值 / null=清除
    stored = _doc_with_pw("FER1:xxxx")
    submitted = _doc_with_pw("")
    sz.merge_sensitive_fields(submitted, stored)
    assert submitted["datasources"][0]["config"]["password"] == "FER1:xxxx"
    submitted2 = _doc_with_pw(None)
    sz.merge_sensitive_fields(submitted2, stored)
    assert "password" not in submitted2["datasources"][0]["config"]
