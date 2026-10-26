"""WS 运行态与数据源测试端点验收（契约 §9 A 包）。

策略（契约 §8 集成说明）：自建 mini FastAPI app + include_router(own_router)，
不依赖 app.main 全量装配；lifespan 内建独立 sqlite 引擎/种子数据，
并把 app.db.base.SessionLocal 指向测试库（ws/datasources 走短会话，不经 get_db）。

覆盖：JWT/分享/非法 token、snapshot 首帧（activeAlarms 截断与降级）、values 合帧抑制、
write→writeAck 全 code（READ_ONLY/FORBIDDEN/VARIABLE_NOT_FOUND/NOT_WRITABLE/WRITE_FAILED/成功回环）、
并发上限 RATE_LIMITED、reload/PROJECT_REMOVED/SHARE_REVOKED/SHARE_EXPIRED、
hub 虚拟变量拓扑（环不死循环）/stale 翻转、datasources/test 凭证注回与角色门槛。
"""
import asyncio
import queue
import sys
import threading
import time
import types
import uuid as uuidlib
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import pytest
from fastapi import APIRouter, FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from app.api.v1 import datasources as datasources_api
from app.api.v1 import ws as ws_api
from app.core.config import settings
from app.core.errors import register_handlers
from app.core.security import create_access_token, hash_password
from app.db import base as db_base
from app.db import models  # noqa: F401  # 注册全部模型
from app.db.base import Base
from app.db.models import Project, ShareLink, User
from app.services import collector as collector_mod
from app.services import hub as hub_mod
from app.services import ws_manager as ws_manager_mod

# ---- 种子数据（每测试经 mini fixture 重建引擎，以下 id 全程固定）----

PID = uuidlib.uuid4()
ADMIN_ID = uuidlib.uuid4()
VIEWER_ID = uuidlib.uuid4()
SHARE_TOKEN = "share-token-abc123"
EXPIRED_SHARE_TOKEN = "share-token-expired"
REVOKED_SHARE_TOKEN = "share-token-revoked"


def seed_doc(project_id: str) -> dict:
    now = "2026-10-20T00:00:00.000Z"
    return {
        "schemaVersion": 1,
        "project": {"id": project_id, "name": "WS 测试工程", "description": None,
                    "author": "admin", "createdAt": now, "updatedAt": now},
        "settings": {
            "designSize": {"width": 1920, "height": 1080},
            "adaptive": "fit-contain", "theme": "blue-dark", "primaryColor": "#2563eb",
            "alarm": {"levelColors": {"info": "#3b82f6", "warn": "#f59e0b", "critical": "#ef4444"},
                      "soundEnabled": True, "soundThrottleSec": 60},
        },
        "datasources": [{
            "id": "ds_mock", "name": "仿真源", "type": "mock", "enabled": True,
            "config": {"defaultIntervalMs": 1000},
        }],
        "variables": [
            {"id": "var_hold", "key": "hold_val", "label": "保持量", "type": "number",
             "datasourceId": "ds_mock", "mock": {"kind": "hold"}, "defaultValue": 42, "writable": True},
            {"id": "var_ro", "key": "ro_val", "label": "只读量", "type": "number",
             "datasourceId": "ds_mock", "mock": {"kind": "hold"}, "defaultValue": 7},
            {"id": "var_virtual", "key": "virtual_val", "label": "虚拟量", "type": "number",
             "datasourceId": "virtual", "expr": "hold_val * 2"},
            {"id": "var_vrow", "key": "vrow_val", "label": "不可写量", "type": "number",
             "datasourceId": "ds_mock", "mock": {"kind": "hold"}, "defaultValue": 1, "writable": False},
        ],
        "pages": [{
            "id": "page_1", "name": "页1", "order": 0, "background": {"color": "#0b1220"},
            "screen": {"designWidth": 1920, "designHeight": 1080, "mode": "fit-contain"},
            "components": [],
        }],
        "alarmRules": [],
    }


def _mini_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        original_session_local = db_base.SessionLocal
        db_base.SessionLocal = factory  # ws/datasources 短会话经模块属性惰性取用

        async with factory() as db:
            admin = User(id=ADMIN_ID, username="admin", password_hash=hash_password("admin12345"), role="admin")
            viewer = User(id=VIEWER_ID, username="viewer", password_hash=hash_password("pw-viewer-123"), role="viewer")
            db.add_all([admin, viewer])
            await db.flush()
            db.add(Project(id=PID, name="WS 测试工程", doc=seed_doc(str(PID)), revision=1, owner_id=ADMIN_ID))
            await db.flush()
            now = datetime.now(timezone.utc)
            db.add_all([
                ShareLink(project_id=PID, token=SHARE_TOKEN, doc_snapshot={}, expires_at=None),
                ShareLink(project_id=PID, token=EXPIRED_SHARE_TOKEN, doc_snapshot={},
                          expires_at=datetime(2020, 1, 1, tzinfo=timezone.utc)),
                ShareLink(project_id=PID, token=REVOKED_SHARE_TOKEN, doc_snapshot={},
                          expires_at=None, revoked_at=now),
            ])
            await db.commit()

        # 运行态单例复位 + 装配（模拟 runtime_boot，但不做全工程扫描）
        hub_mod.hub.reset()
        await collector_mod.collector.reset()
        await ws_manager_mod.manager.reset()
        hub_mod.hub.set_doc(PID, seed_doc(str(PID)))
        await collector_mod.collector.sync(PID, seed_doc(str(PID)))  # mock hold 变量推初始值入池
        await ws_manager_mod.manager.start()
        await asyncio.sleep(0.2)  # 等 coalesce 窗口排空 lifespan 期脏值，测试只看自身动作产生的帧
        yield
        await ws_manager_mod.manager.stop()
        await collector_mod.collector.reset()
        hub_mod.hub.reset()
        db_base.SessionLocal = original_session_local
        await engine.dispose()

    app = FastAPI(lifespan=lifespan)
    register_handlers(app)  # 与生产同错误信封（AppError → {code,message}，401/403 映射）
    api = APIRouter(prefix="/api/v1")  # 与 main.py 同前缀（测试 URL 与生产一致）
    api.include_router(ws_api.router)
    api.include_router(datasources_api.router)
    app.include_router(api)

    # 测试专用：广播原语必须在 app 事件循环内执行（ASGI send 跨线程不安全），
    # 经 HTTP 触达即由 TestClient portal 调度（等价 B/C 包在请求路径内调用的真实形态）
    @app.post("/__test/broadcast")
    async def _broadcast(payload: dict):
        kind = payload.get("kind")
        if kind == "reload":
            await ws_manager_mod.manager.broadcast_reload(str(payload["token"]))
        elif kind == "project_removed":
            await ws_manager_mod.manager.broadcast_project_removed(uuidlib.UUID(payload["project"]))
        elif kind == "alarm_ack":
            await ws_manager_mod.manager.broadcast_alarm_ack(
                PID, int(payload["alarmId"]), int(payload["ackedAt"]), str(payload["ackedBy"]))
        return {"ok": True}

    return app


@pytest.fixture()
def mini():
    with TestClient(_mini_app()) as client:
        yield client


def jwt_token(user_id: uuidlib.UUID) -> str:
    token, _ = create_access_token(str(user_id))
    return token


def ws_url(**params: str) -> str:
    from urllib.parse import urlencode

    return "/api/v1/ws/runtime?" + urlencode(params)


def recv(client_ws, timeout: float = 3.0) -> dict:
    """带超时收帧（starlette WebSocketTestSession 阻塞收，守护线程 + 队列落地超时）。"""
    q: "queue.Queue[dict]" = queue.Queue()

    def _rx() -> None:
        try:
            q.put(client_ws.receive_json())
        except Exception as exc:  # noqa: BLE001
            q.put({"type": "__closed__", "reason": str(exc)})

    threading.Thread(target=_rx, daemon=True).start()
    try:
        return q.get(timeout=timeout)
    except Exception:  # noqa: BLE001
        return {"type": "__timeout__"}


def enter(mini_client, **params: str):
    """open WS 并消费首帧 snapshot，返回会话（供多连接编排）。"""
    ws = mini_client.websocket_connect(ws_url(**params)).__enter__()
    snap = recv(ws)
    assert snap["type"] == "snapshot", snap
    return ws


# ---------------- 鉴权与首帧 ----------------


def test_ws_jwt_snapshot_first_frame(mini):
    now = int(time.time() * 1000)
    hub_mod.hub.ingest(PID, hub_mod.hub.variable(PID, "hold_val"), 42, now)
    with mini.websocket_connect(ws_url(project=str(PID), token=jwt_token(ADMIN_ID))) as ws:
        snap = recv(ws)
        assert snap["type"] == "snapshot"
        assert snap["data"]["hold_val"] == {"v": 42, "q": "good", "t": snap["data"]["hold_val"]["t"]}
        assert snap["activeAlarms"] == []
        assert snap["totalActive"] == 0
        assert snap["truncated"] is False


def test_ws_illegal_token_error_then_close(mini):
    with mini.websocket_connect(ws_url(project=str(PID), token="not.a.jwt")) as ws:
        frame = recv(ws)
        assert frame["type"] == "error"
        assert frame["code"] == "TOKEN_EXPIRED"


def test_ws_missing_token(mini):
    with mini.websocket_connect(ws_url(project=str(PID))) as ws:
        frame = recv(ws)
        assert frame["type"] == "error" and frame["code"] == "TOKEN_EXPIRED"


def test_ws_share_token_snapshot_and_read_only(mini):
    with mini.websocket_connect(ws_url(project=str(PID), token=SHARE_TOKEN)) as ws:
        snap = recv(ws)
        assert snap["type"] == "snapshot"
        # 分享连接值流按 live doc 变量集推送（快照 doc 仅决定渲染）
        assert "hold_val" in snap["data"]
        ws.send_json({"type": "write", "reqId": "w1", "variableKey": "hold_val", "value": 1})
        ack = recv(ws)
        assert ack["type"] == "writeAck" and ack["reqId"] == "w1"
        assert ack["ok"] is False and ack["code"] == "READ_ONLY"


def test_ws_share_expired_and_revoked(mini):
    cases = [(EXPIRED_SHARE_TOKEN, "SHARE_EXPIRED"), (REVOKED_SHARE_TOKEN, "SHARE_REVOKED")]
    for token, code in cases:
        with mini.websocket_connect(ws_url(project=str(PID), token=token)) as ws:
            frame = recv(ws)
            assert frame["type"] == "error" and frame["code"] == code, (token, frame)


def test_ws_project_removed(mini):
    other = uuidlib.uuid4()
    with mini.websocket_connect(ws_url(project=str(other), token=jwt_token(ADMIN_ID))) as ws:
        frame = recv(ws)
        assert frame["type"] == "error" and frame["code"] == "PROJECT_REMOVED"


# ---------------- values 合帧与变化抑制 ----------------


def test_values_coalesce_and_suppression(mini):
    now = int(time.time() * 1000)
    hold = hub_mod.hub.variable(PID, "hold_val")
    ro = hub_mod.hub.variable(PID, "ro_val")
    with mini.websocket_connect(ws_url(project=str(PID), token=jwt_token(ADMIN_ID))) as ws:
        assert recv(ws)["type"] == "snapshot"
        # 100ms 窗口内两个变量变化 → 合并为一帧（虚拟变量 virtual_val 随 hold_val 拓扑传播同帧）
        hub_mod.hub.ingest(PID, hold, 100, now)
        hub_mod.hub.ingest(PID, ro, 200, now)
        frame = recv(ws)
        assert frame["type"] == "values"
        assert set(frame["data"].keys()) == {"hold_val", "ro_val", "virtual_val"}
        assert frame["data"]["virtual_val"]["v"] == 200
        # 变化抑制：相同值再次 ingest 不产生新帧（用随后的 writeAck 帧验证队列次序）
        hub_mod.hub.ingest(PID, hold, 100, now + 1)
        ws.send_json({"type": "write", "reqId": "w-sup", "variableKey": "hold_val", "value": 300})
        next_frame = recv(ws)
        assert next_frame["type"] == "writeAck" and next_frame["reqId"] == "w-sup"
        assert next_frame["ok"] is True
        loop_frame = recv(ws)
        assert loop_frame["type"] == "values" and loop_frame["data"]["hold_val"]["v"] == 300


def test_broadcast_reload_to_share_conns(mini):
    with mini.websocket_connect(ws_url(project=str(PID), token=SHARE_TOKEN)) as ws:
        assert recv(ws)["type"] == "snapshot"
        # C 包 shares refresh 的调用面：该 token 全部连接收 reload
        r = mini.post("/__test/broadcast", json={"kind": "reload", "token": SHARE_TOKEN})
        assert r.status_code == 200
        assert recv(ws) == {"type": "reload"}
        # 其他 token 不收（0.6s 内无帧）
        mini.post("/__test/broadcast", json={"kind": "reload", "token": "another-token"})
        assert recv(ws, timeout=0.6)["type"] == "__timeout__"


def test_broadcast_alarm_ack_to_project(mini):
    with mini.websocket_connect(ws_url(project=str(PID), token=SHARE_TOKEN)) as ws:
        assert recv(ws)["type"] == "snapshot"
        r = mini.post("/__test/broadcast", json={"kind": "alarm_ack", "alarmId": 7, "ackedAt": 123, "ackedBy": "admin"})
        assert r.status_code == 200
        frame = recv(ws)
        assert frame == {"type": "alarmAck", "alarmId": 7, "ackedAt": 123, "ackedBy": "admin"}


def test_broadcast_project_removed(mini):
    with mini.websocket_connect(ws_url(project=str(PID), token=SHARE_TOKEN)) as ws:
        assert recv(ws)["type"] == "snapshot"
        r = mini.post("/__test/broadcast", json={"kind": "project_removed", "project": str(PID)})
        assert r.status_code == 200
        frame = recv(ws)
        assert frame["type"] == "error" and frame["code"] == "PROJECT_REMOVED"


# ---------------- 虚拟变量拓扑 / stale ----------------


def test_virtual_variable_topological_evaluation(mini):
    """hub 虚拟变量拓扑求值：依赖变化 → 虚拟变量随池更新；环配置不死循环。"""
    doc = seed_doc(str(PID))
    doc["variables"].append({"id": "var_a", "key": "loop_a", "label": "环A", "type": "number",
                             "datasourceId": "virtual", "expr": "loop_b + 1"})
    doc["variables"].append({"id": "var_b", "key": "loop_b", "label": "环B", "type": "number",
                             "datasourceId": "virtual", "expr": "loop_a + 1"})
    hub_mod.hub.set_doc(PID, doc)
    try:
        now = int(time.time() * 1000)
        hub_mod.hub.ingest(PID, hub_mod.hub.variable(PID, "hold_val"), 10, now)
        pool = hub_mod.hub.pool(PID)
        assert pool["virtual_val"]["v"] == 20  # hold_val * 2（拓扑传播）
        assert "loop_a" in pool and "loop_b" in pool  # 环上节点按出现序兜底求值，不死循环
    finally:
        hub_mod.hub.set_doc(PID, seed_doc(str(PID)))


def test_virtual_variable_turns_bad_when_dependency_stale(mini):
    """依赖停更时虚拟变量必须转 bad，不能继续用旧值算出「正常值」。"""
    doc = seed_doc(str(PID))
    # sine 会周期性来帧，超时后应判 stale；chain 依赖它，坏值必须继续向下游传导
    doc["variables"].append({"id": "var_sine", "key": "sine_val", "label": "正弦量", "type": "number",
                             "datasourceId": "ds_mock",
                             "mock": {"kind": "sine", "min": 0, "max": 100, "periodMs": 30000}})
    doc["variables"].append({"id": "var_chain", "key": "chain_val", "label": "链式量", "type": "number",
                             "datasourceId": "virtual", "expr": "sine_val + 1"})
    hub_mod.hub.set_doc(PID, doc)
    try:
        now = int(time.time() * 1000)
        hub_mod.hub.ingest(PID, hub_mod.hub.variable(PID, "sine_val"), 10, now)
        pool = hub_mod.hub.pool(PID)
        assert pool["chain_val"]["v"] == 11 and pool["chain_val"]["q"] == "good"
        hub_mod.hub.sweep_stale(PID, now_ms=now + 120_000)
        pool = hub_mod.hub.pool(PID)
        assert pool["sine_val"]["q"] == "stale"
        assert pool["chain_val"]["q"] == "bad"
        # hold 型 mock 是常量语义：不参与 stale 计时，依赖它的虚拟变量也不该被拖坏
        assert pool["hold_val"]["q"] == "good"
        assert pool["virtual_val"]["q"] == "good"
    finally:
        hub_mod.hub.set_doc(PID, seed_doc(str(PID)))


def test_hub_touch_keeps_subscription_value_fresh(mini):
    """订阅型源无数据变化时，连接健康探测应推进新鲜度（OPC UA 用）。"""
    doc = seed_doc(str(PID))
    doc["variables"].append({"id": "var_sine", "key": "sine_val", "label": "正弦量", "type": "number",
                             "datasourceId": "ds_mock",
                             "mock": {"kind": "sine", "min": 0, "max": 100, "periodMs": 30000}})
    hub_mod.hub.set_doc(PID, doc)
    try:
        now = int(time.time() * 1000)
        var = hub_mod.hub.variable(PID, "sine_val")
        hub_mod.hub.ingest(PID, var, 10, now)
        hub_mod.hub.touch(PID, var, now + 60_000)
        hub_mod.hub.sweep_stale(PID, now_ms=now + 100_000)  # 距 touch 40s < 90s 阈值
        assert hub_mod.hub.pool(PID)["sine_val"]["q"] == "good"
    finally:
        hub_mod.hub.set_doc(PID, seed_doc(str(PID)))


def test_hub_stale_flip(mini):
    doc = seed_doc(str(PID))
    doc["variables"].append({"id": "var_sine", "key": "sine_val", "label": "正弦量", "type": "number",
                             "datasourceId": "ds_mock",
                             "mock": {"kind": "sine", "min": 0, "max": 100, "periodMs": 30000}})
    hub_mod.hub.set_doc(PID, doc)
    try:
        now = int(time.time() * 1000)
        hub_mod.hub.ingest(PID, hub_mod.hub.variable(PID, "sine_val"), 1, now)
        flipped = hub_mod.hub.sweep_stale(PID, now_ms=now + 120_000)
        assert flipped >= 1
        entry = hub_mod.hub.pool(PID)["sine_val"]
        assert entry["q"] == "stale" and entry["v"] == 1  # 值保留、质量翻转
        assert hub_mod.hub.pool(PID)["hold_val"]["q"] == "good"  # hold 常量不参与 stale
    finally:
        hub_mod.hub.set_doc(PID, seed_doc(str(PID)))


# ---------------- write → writeAck 全 code ----------------


def test_write_all_codes(mini):
    with mini.websocket_connect(ws_url(project=str(PID), token=jwt_token(VIEWER_ID))) as wsv:
        assert recv(wsv)["type"] == "snapshot"
        wsv.send_json({"type": "write", "reqId": "r1", "variableKey": "hold_val", "value": 1})
        ack = recv(wsv)
        assert ack["ok"] is False and ack["code"] == "FORBIDDEN"

    with mini.websocket_connect(ws_url(project=str(PID), token=jwt_token(ADMIN_ID))) as ws:
        assert recv(ws)["type"] == "snapshot"

        ws.send_json({"type": "write", "reqId": "r2", "variableKey": "nope", "value": 1})
        assert recv(ws)["code"] == "VARIABLE_NOT_FOUND"

        # 虚拟变量不可写
        ws.send_json({"type": "write", "reqId": "r3", "variableKey": "virtual_val", "value": 1})
        assert recv(ws)["code"] == "NOT_WRITABLE"

        # 未开启 writable
        ws.send_json({"type": "write", "reqId": "r4", "variableKey": "vrow_val", "value": 1})
        assert recv(ws)["code"] == "NOT_WRITABLE"

        # 值类型非法
        ws.send_json({"type": "write", "reqId": "r5", "variableKey": "hold_val", "value": {"a": 1}})
        assert recv(ws)["code"] == "WRITE_FAILED"

        # 数据源未运行（enabled=false 无采集任务）→ WRITE_FAILED
        doc = seed_doc(str(PID))
        doc["datasources"].append({"id": "ds_dead", "name": "离线源", "type": "mock", "enabled": False, "config": {}})
        doc["variables"].append({"id": "var_dead", "key": "dead_val", "label": "离线", "type": "number",
                                 "datasourceId": "ds_dead", "mock": {"kind": "hold"}, "writable": True})
        hub_mod.hub.set_doc(PID, doc)
        ws.send_json({"type": "write", "reqId": "r6", "variableKey": "dead_val", "value": 5})
        assert recv(ws)["code"] == "WRITE_FAILED"
        hub_mod.hub.set_doc(PID, seed_doc(str(PID)))

        # 成功：mock 服务端回环（经换算流水入池 → values 帧广播）
        ws.send_json({"type": "write", "reqId": "r7", "variableKey": "hold_val", "value": 55})
        ack = recv(ws)
        assert ack["ok"] is True and ack["reqId"] == "r7"
        values = recv(ws)
        assert values["type"] == "values" and values["data"]["hold_val"]["v"] == 55


# ---------------- 并发上限 ----------------


def test_ws_jwt_per_user_project_limit(mini, monkeypatch):
    monkeypatch.setattr(settings, "JWT_WS_MAX_PER_USER_PROJECT", 1)
    token = jwt_token(ADMIN_ID)
    with mini.websocket_connect(ws_url(project=str(PID), token=token)) as ws1:
        assert recv(ws1)["type"] == "snapshot"
        with mini.websocket_connect(ws_url(project=str(PID), token=token)) as ws2:
            frame = recv(ws2)
            assert frame["type"] == "error" and frame["code"] == "RATE_LIMITED"


def test_ws_share_token_limit(mini, monkeypatch):
    monkeypatch.setattr(settings, "SHARE_MAX_WS_PER_TOKEN", 1)
    with mini.websocket_connect(ws_url(project=str(PID), token=SHARE_TOKEN)) as ws1:
        assert recv(ws1)["type"] == "snapshot"
        with mini.websocket_connect(ws_url(project=str(PID), token=SHARE_TOKEN)) as ws2:
            frame = recv(ws2)
            assert frame["type"] == "error" and frame["code"] == "RATE_LIMITED"


# ---------------- snapshot activeAlarms ----------------


def _fake_alarm_service(rows: list[dict]):
    """构造 alarm_service 假模块：B 包可能已合入（包属性已绑定），须同时替换
    sys.modules 与 app.services 包属性，惰性 `from app.services import alarm_service` 才能命中。"""
    import app.services

    fake = types.ModuleType("app.services.alarm_service")

    async def active_for_snapshot(db, project_id, limit=200):  # noqa: ARG001
        rank = {"critical": 0, "warn": 1, "info": 2}
        ordered = sorted(rows, key=lambda r: rank.get(str(r.get("level")), 3))  # B 契约：先排序后截断
        return ordered[:limit]

    fake.active_for_snapshot = active_for_snapshot
    return fake, app.services


def _install_fake_alarm_service(monkeypatch, rows: list[dict]) -> None:
    fake, pkg = _fake_alarm_service(rows)
    monkeypatch.setitem(sys.modules, "app.services.alarm_service", fake)
    monkeypatch.setattr(pkg, "alarm_service", fake, raising=False)


def test_snapshot_active_alarms_truncation(mini, monkeypatch):
    """snapshot 内嵌 activeAlarms：≤200 截断、critical>warn>info 优先保留、truncated=true。"""
    rows = []
    for i in range(250):
        level = ("info", "warn", "critical")[i % 3]  # info 84 / warn 83 / critical 83
        rows.append({"id": i, "ruleId": f"r{i}", "variableKey": "k", "level": level,
                     "message": "m", "value": "1", "status": "triggered", "triggeredAt": 1000 + i})
    _install_fake_alarm_service(monkeypatch, rows)
    with mini.websocket_connect(ws_url(project=str(PID), token=jwt_token(ADMIN_ID))) as ws:
        snap = recv(ws)
        assert snap["truncated"] is True
        assert len(snap["activeAlarms"]) == 200
        levels = [a["level"] for a in snap["activeAlarms"]]
        assert all(lv == "critical" for lv in levels[:83])
        assert all(lv == "warn" for lv in levels[83:166])
        assert set(levels[166:]) == {"info"}


def test_snapshot_active_alarms_under_limit(mini, monkeypatch):
    rows = [{"id": 1, "ruleId": "r1", "variableKey": "k", "level": "warn",
             "message": "m", "value": "1", "status": "triggered", "triggeredAt": 1000}]
    _install_fake_alarm_service(monkeypatch, rows)
    with mini.websocket_connect(ws_url(project=str(PID), token=jwt_token(ADMIN_ID))) as ws:
        snap = recv(ws)
        assert snap["totalActive"] == 1 and snap["truncated"] is False
        assert snap["activeAlarms"][0]["ruleId"] == "r1"


def test_snapshot_alarm_service_missing_degrades_empty(mini, monkeypatch):
    import app.services

    monkeypatch.setitem(sys.modules, "app.services.alarm_service", None)  # import 即失败
    monkeypatch.delattr(app.services, "alarm_service", raising=False)  # 包属性一并摘除
    with mini.websocket_connect(ws_url(project=str(PID), token=jwt_token(ADMIN_ID))) as ws:
        snap = recv(ws)
        assert snap["activeAlarms"] == [] and snap["truncated"] is False


# ---------------- datasources/test ----------------


def auth(user_id: uuidlib.UUID) -> dict:
    return {"Authorization": f"Bearer {jwt_token(user_id)}"}


def test_datasource_test_mock_ok(mini):
    resp = mini.post("/api/v1/datasources/test", headers=auth(ADMIN_ID), json={"type": "mock", "config": {}})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True and body["type"] == "mock" and "latencyMs" in body


def test_datasource_test_viewer_forbidden(mini):
    resp = mini.post("/api/v1/datasources/test", headers=auth(VIEWER_ID), json={"type": "mock", "config": {}})
    assert resp.status_code == 403
    assert resp.json()["code"] == "FORBIDDEN"


def test_datasource_test_requires_auth(mini):
    resp = mini.post("/api/v1/datasources/test", json={"type": "mock", "config": {}})
    assert resp.status_code == 401


def test_datasource_test_mqtt_unreachable_reports_false(mini):
    """不可达 broker → 200 + ok=false（失败是正常测试结果，不 500、不泄露敏感值）。"""
    resp = mini.post(
        "/api/v1/datasources/test", headers=auth(ADMIN_ID),
        json={"type": "mqtt", "config": {"brokerUrl": "mqtt://127.0.0.1:1", "username": "u"},
              "projectId": str(PID), "datasourceId": "none"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "pw-viewer" not in body["message"]


def test_merge_stored_credentials_unit():
    """凭证注回纯函数：FER1: 密文解密注回；非空明文优先；headers 仅敏感键。"""
    from app.utils.encrypt import encrypt

    cipher_pw = encrypt("Secret@123")  # conftest 注入的随机 DATASOURCE_SECRET
    config: dict = {}
    datasources_api.merge_stored_credentials("mqtt", config, {"password": cipher_pw})
    assert config["password"] == "Secret@123"

    config2 = {"password": "NewPlain"}  # 非空明文按本次值
    datasources_api.merge_stored_credentials("mqtt", config2, {"password": cipher_pw})
    assert config2["password"] == "NewPlain"

    headers_cfg: dict = {}
    datasources_api.merge_stored_credentials(
        "rest", headers_cfg,
        {"headers": {"Authorization": encrypt("Bearer tok"), "Content-Type": "application/json"}},
    )
    assert headers_cfg["headers"]["Authorization"] == "Bearer tok"
    assert "Content-Type" not in headers_cfg["headers"]  # 非敏感键不注回

    # rest 未传 headers 键时整体缺省补齐
    headers_cfg2: dict = {}
    datasources_api.merge_stored_credentials(
        "websocket", headers_cfg2, {"headers": {"X-Api-Token": encrypt("t2")}},
    )
    assert headers_cfg2["headers"]["X-Api-Token"] == "t2"


# ---------------- collector 差量键与并发互斥（R1 修复回归） ----------------


async def test_collector_rebuild_when_variables_change():
    """critical 回归：差量键 = ds config hash + 该源变量集 hash——向既有数据源新增
    变量后必须重建采集任务（旧实现只比 config hash → 新变量永不被采集）。"""
    pid = uuidlib.uuid4()
    c = collector_mod.Collector()
    try:
        await c.sync(pid, seed_doc(str(pid)))
        entry0 = c._projects[pid]["ds_mock"]
        assert [v.id for v in entry0.source.variables] == ["var_hold", "var_ro", "var_vrow"]

        doc = seed_doc(str(pid))
        doc["variables"].append({"id": "var_new", "key": "new_val", "label": "新增量", "type": "number",
                                 "datasourceId": "ds_mock", "mock": {"kind": "hold"}, "defaultValue": 9})
        await c.sync(pid, doc)
        entry1 = c._projects[pid]["ds_mock"]
        assert entry1 is not entry0  # 变量集变化 → 命中差量 → 重建
        assert "var_new" in [v.id for v in entry1.source.variables]

        doc2 = seed_doc(str(pid))
        doc2["variables"].append({"id": "var_new", "key": "new_val", "label": "新增量", "type": "number",
                                  "datasourceId": "ds_mock", "mock": {"kind": "hold"}, "defaultValue": 9})
        doc2["pages"][0]["name"] = "改名不触差量"
        await c.sync(pid, doc2)
        assert c._projects[pid]["ds_mock"] is entry1  # 变量集未变时，与采集无关的变更不重建
    finally:
        await c.reset()


async def test_collector_concurrent_sync_remove_serialized():
    """major 回归：并发 sync/remove 经 per-project 锁全程互斥——不 KeyError
    （KeyError 会被热更新钩子吞掉 → 保存成功但采集不更新）、不泄漏已停任务；
    收束后每个存续 entry 的采集任务存活，remove 收尾后无残留。"""
    pid = uuidlib.uuid4()
    c = collector_mod.Collector()
    try:
        docs = []
        for i in range(6):
            d = seed_doc(str(pid))
            d["datasources"][0]["config"]["defaultIntervalMs"] = 1000 + i  # 每次都命中差量重建
            docs.append(d)
        await asyncio.gather(
            *(c.sync(pid, d) for d in docs),
            c.remove(pid),
            c.sync(pid, docs[-1]),
            return_exceptions=True,
        )
        entries = c._projects.get(pid, {})
        for entry in entries.values():
            assert entry.source._task is not None and not entry.source._task.done()
        await c.remove(pid)
        assert c._projects.get(pid) is None
    finally:
        await c.reset()


# ---------------- WS 发送超时与停滞连接摘除（R1 修复回归） ----------------


class _StalledWS:
    """对端停滞的假连接：send_text 永不完成（发送缓冲写满的真实形态）。"""

    def __init__(self) -> None:
        self.closed: int | None = None

    async def send_text(self, text: str) -> None:  # noqa: ARG002
        await asyncio.sleep(3600)

    async def close(self, code: int = 1000) -> None:
        self.closed = code


class _HealthyWS:
    def __init__(self) -> None:
        self.frames: list[str] = []

    async def send_text(self, text: str) -> None:
        self.frames.append(text)

    async def close(self, code: int = 1000) -> None:
        pass


async def test_send_timeout_drops_stalled_connection():
    """major 回归：send 带 per-conn 超时——停滞连接超时失败并被摘除，
    同工程健康连接照常收帧（旧实现无超时会永久阻塞广播/心跳循环）。"""
    stalled_ws, healthy_ws = _StalledWS(), _HealthyWS()
    mgr = ws_manager_mod.WSManager()
    stalled = ws_manager_mod.Connection(stalled_ws, PID, "jwt", "t1", send_timeout=0.05)
    healthy = ws_manager_mod.Connection(healthy_ws, PID, "jwt", "t2", send_timeout=0.05)
    # 缺省超时取模块常量
    assert ws_manager_mod.Connection(_HealthyWS(), PID, "jwt", "t3").send_timeout == ws_manager_mod.SEND_TIMEOUT_SEC
    await mgr.register(stalled)
    await mgr.register(healthy)
    try:
        t0 = time.monotonic()
        assert await stalled.send_json({"type": "values", "data": {}}) is False  # 超时返回而非永久阻塞
        assert time.monotonic() - t0 < 1.0
        await mgr._broadcast_project(PID, {"type": "values", "data": {"k": {"v": 1}}})
        assert mgr.total_count() == 1  # 停滞连接被摘除
    finally:
        await mgr.stop()
    assert any('"type":"values"' in f for f in healthy_ws.frames)  # 健康连接收到广播帧


async def test_ping_send_failure_unregisters_connection():
    """心跳发送失败（含停滞超时）→ 连接摘除，不随死连接常驻。"""
    mgr = ws_manager_mod.WSManager()
    dead = ws_manager_mod.Connection(_StalledWS(), PID, "jwt", "t1", send_timeout=0.05)
    await mgr.register(dead)
    try:
        assert await dead.send_json({"type": "ping"}) is False
        await mgr.unregister(dead)
        assert mgr.total_count() == 0
    finally:
        await mgr.stop()
